// Gateway simulator — writes exactly what the real ESP32-S3 gateway should write.
// Jeen: use this as the reference for paths/payloads (see docs/firebase-schema.md).
//
//   npm run sim                 normal scenario
//   npm run sim -- --fire       room-A flame sensor trips after 30 s
//   npm run sim -- --outage     room-B goes offline for 90 s, then flushes its buffer
//
// Scenario (repeats every 10 min):
//   room-A: 4 people for ~4 min, then 1 person (underused vs 5 booked), then empty
//   room-B: booked but nobody comes (no-show), lights stuck on (light_fail)
import { ServerValue } from "firebase-admin/database";
import type { ControlCommand, Reading, RoomEvent } from "@roomsense/shared";
import { db } from "./fb.ts";

const FIRE = process.argv.includes("--fire");
const OUTAGE = process.argv.includes("--outage");
const ROOMS = ["room-A", "room-B"] as const;
type RoomId = (typeof ROOMS)[number];

const t0 = Date.now();
const nowSec = () => Math.floor(Date.now() / 1000);
const jitter = (n: number) => (Math.random() - 0.5) * n;
const state: Record<RoomId, { seq: number; ir: number; light: boolean; override?: boolean; temp: number }> = {
  "room-A": { seq: 0, ir: 0, light: false, temp: 25.5 },
  "room-B": { seq: 0, ir: 0, light: true, temp: 26.2 },
};
const buffer: { roomId: RoomId; r: Reading }[] = [];
let outageUntil = 0;

function people(roomId: RoomId, phase: number): number {
  if (roomId === "room-B") return 0;
  return phase < 30 ? 0 : phase < 270 ? 4 : phase < 480 ? 1 : 0;
}

const event = (roomId: string, e: RoomEvent) => db.ref(`rooms/${roomId}/events`).push(e);

async function tick() {
  const phase = Math.floor((Date.now() - t0) / 1000) % 600;
  const elapsed = (Date.now() - t0) / 1000;

  for (const roomId of ROOMS) {
    const s = state[roomId];
    const n = people(roomId, phase);

    // IR in/out events
    if (n > s.ir) for (let i = s.ir; i < n; i++) await event(roomId, { ts: nowSec(), type: "enter" });
    if (n < s.ir) for (let i = n; i < s.ir; i++) await event(roomId, { ts: nowSec(), type: "exit" });
    s.ir = n;

    // closed-loop light control (room-B is "stuck on" to demo light_fail)
    if (roomId === "room-A" && s.override === undefined) {
      const want = n > 0;
      if (want !== s.light) {
        s.light = want;
        await event(roomId, { ts: nowSec(), type: want ? "light_on" : "light_off", latency_ms: Math.round(900 + Math.random() * 600) });
      }
    }

    s.temp += n > 0 ? 0.01 : -0.005;
    const r: Reading = {
      room_id: roomId,
      ts: nowSec(),
      node_ts: nowSec(),
      people_ai: n,
      ai_conf: n ? +(0.8 + Math.random() * 0.15).toFixed(2) : +(0.9 + Math.random() * 0.08).toFixed(2),
      people_ir: n,
      pir: n > 0,
      light_on: s.light,
      ldr: Math.round(s.light ? 800 + jitter(40) : 120 + jitter(20)),
      temp_c: +(s.temp + jitter(0.2)).toFixed(1),
      humidity: Math.round(58 + jitter(4)),
      sound_db: Math.round(n > 0 ? 50 + n * 3 + jitter(6) : 36 + jitter(4)),
      flame: FIRE && roomId === "room-A" && elapsed > 30,
      node_seq: ++s.seq,
      buffered: false,
    };
    // simulate ~1% ESP-NOW packet loss (seq gap) for the PDR metric
    if (Math.random() < 0.01) continue;

    if (roomId === "room-B" && Date.now() < outageUntil) {
      buffer.push({ roomId, r: { ...r, buffered: true } });
      continue;
    }
    // flush buffer after outage (E4 store-and-forward)
    if (roomId === "room-B" && buffer.length) {
      const items = buffer.splice(0);
      const upd: Record<string, unknown> = {};
      for (const b of items) upd[`rooms/${b.roomId}/readings/${b.r.ts}`] = { ...b.r, server_ts: ServerValue.TIMESTAMP };
      await db.ref().update(upd);
      await db.ref(`rooms/${roomId}/events`).push({
        ts: nowSec(), type: "backfill", count: items.length, from: items[0].r.ts, to: items[items.length - 1].r.ts,
      });
      await db.ref("devices/node-B/health/last_outage").set({ from: items[0].r.ts, to: items[items.length - 1].r.ts, backfilled: items.length });
      console.log(`[sim] flushed ${items.length} buffered readings for ${roomId}`);
    }

    const withServerTs = { ...r, server_ts: ServerValue.TIMESTAMP };
    await db.ref().update({
      [`rooms/${roomId}/live`]: withServerTs,
      [`rooms/${roomId}/readings/${r.ts}`]: withServerTs,
      [`devices/node-${roomId.slice(-1)}/health`]: {
        kind: "node", room_id: roomId, online: true, rssi: Math.round(-55 + jitter(10)),
        uptime_s: Math.floor(elapsed), heap_free: 180_000 + Math.round(jitter(4000)), last_seen: r.ts,
        reboots: 0, reconnects: 0,
      },
    });
  }

  await db.ref("devices/gw-1/health").update({
    kind: "gateway", online: true, rssi: Math.round(-60 + jitter(8)), uptime_s: Math.floor(elapsed),
    heap_free: 4_100_000 + Math.round(jitter(50_000)), last_seen: nowSec(), buffer_depth: buffer.length,
    reboots: 0, reconnects: 0,
  });
}

// Gateway side of manual control: listen on control/{room}, execute, ack.
for (const roomId of ROOMS) {
  db.ref(`control/${roomId}`).on("value", async (snap) => {
    const c = snap.val() as ControlCommand | null;
    if (!c || c.done_ms) return;
    const s = state[roomId];
    if (c.cmd === "servo_stop") s.override = s.light;
    else { s.light = c.cmd === "light_on"; s.override = s.light; }
    await event(roomId, { ts: nowSec(), type: c.cmd === "servo_stop" ? "manual" : c.cmd, detail: `manual: ${c.cmd}`, by: c.by });
    await db.ref(`control/${roomId}/done_ms`).set(Date.now());
    console.log(`[sim] ${roomId} executed ${c.cmd} from ${c.by}`);
  });
}

if (OUTAGE) {
  setTimeout(() => { outageUntil = Date.now() + 90_000; console.log("[sim] room-B outage for 90 s"); }, 20_000);
}

console.log(`[sim] gateway simulator running${FIRE ? " (fire in 30 s)" : ""}${OUTAGE ? " (outage at 20 s)" : ""}`);
setInterval(() => tick().catch((e) => console.error("[sim]", e.message)), 5000);
