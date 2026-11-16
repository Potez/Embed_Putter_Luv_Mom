import {
  activeConditions, conditions, CHANNELS, DEFAULTS, toMs,
  type Alert, type Booking, type Condition, type DeviceHealth, type Reading, type RoomMeta, type Snapshot,
} from "@roomsense/shared";
import { db } from "./fb.ts";
import { formatAlert, sendEmail, sendTelegram } from "./notify.ts";

// ---- live caches fed by RTDB listeners ----
export const cache = {
  meta: {} as Record<string, RoomMeta>,
  live: {} as Record<string, Reading>,
  devices: {} as Record<string, DeviceHealth>,
  bookings: {} as Record<string, Booking>,
  lightFail: {} as Record<string, number>,
};

export function startListeners() {
  // Never listen on rooms/ itself: it contains every raw reading.
  const liveSubs = new Set<string>();
  db.ref("room_list").on("value", (s) => {
    cache.meta = (s.val() ?? {}) as Record<string, RoomMeta>;
    for (const id of Object.keys(cache.meta)) {
      if (liveSubs.has(id)) continue;
      liveSubs.add(id);
      db.ref(`rooms/${id}/live`).on("value", (l) => {
        if (l.exists()) cache.live[id] = l.val() as Reading;
        else delete cache.live[id];
      });
    }
  });
  db.ref("devices").on("value", (s) => {
    const v = (s.val() ?? {}) as Record<string, { health?: DeviceHealth }>;
    cache.devices = Object.fromEntries(Object.entries(v).filter(([, d]) => d.health).map(([k, d]) => [k, d.health!]));
  });
  const dayAgo = Date.now() - 86_400_000;
  db.ref("bookings").orderByChild("end_ms").startAt(dayAgo).on("value", (s) => {
    cache.bookings = (s.val() ?? {}) as Record<string, Booking>;
  });
}

/** Called for every light_fail event the gateway writes (see index.ts). */
export function noteLightFail(roomId: string, tsSec: number) {
  cache.lightFail[roomId] = Math.max(cache.lightFail[roomId] ?? 0, toMs(tsSec));
}

// ---- engine state ----
const since: Record<string, number> = {};      // key -> first seen true (ms)
const open: Record<string, string> = {};       // key -> alertId
const openRoom: Record<string, string | null> = {}; // key -> room_id
let lastNotified: Record<string, number> = {};  // key -> ms (persisted, survives restart)

export async function loadState() {
  lastNotified = (await db.ref("worker/last_notified").get()).val() ?? {};
  const openSnap = await db.ref("alerts").orderByChild("created_ms").startAt(Date.now() - 2 * 86_400_000).get();
  openSnap.forEach((c) => {
    const a = c.val() as Alert;
    if (!a.resolved_ms) { open[a.key] = c.key!; openRoom[a.key] = a.room_id; }
  });
}

const safeKey = (k: string) => k.replace(/[.#$/[\]]/g, "_");

function snapshot(now: number): Snapshot {
  return {
    nowMs: now,
    rooms: Object.entries(cache.meta).map(([id, m]) => ({ id, name: m.name, live: cache.live[id] ?? null })),
    devices: Object.entries(cache.devices).map(([id, d]) => ({ id, kind: d.kind, room_id: d.room_id, last_seen: d.last_seen })),
    bookings: Object.entries(cache.bookings).map(([id, b]) => ({ ...b, id })),
    since,
    lightFailEvents: cache.lightFail,
  };
}

async function raise(c: Condition, now: number) {
  const ref = db.ref("alerts").push();
  const alert: Alert = {
    key: c.key, type: c.type, severity: c.severity, room_id: c.roomId,
    message: c.message, created_ms: now, channels: ["web"],
    ...(c.value ? { value: c.value } : {}),
  };
  open[c.key] = ref.key!;
  openRoom[c.key] = c.roomId;
  await ref.set(alert);
  await notify(ref.key!, alert, now);
}

async function notify(id: string, alert: Alert, now: number) {
  const k = safeKey(alert.key);
  const minGap = (alert.type === "fire" ? DEFAULTS.FIRE_RENOTIFY_MIN : DEFAULTS.DEDUPE_MIN) * 60_000;
  if (lastNotified[k] && now - lastNotified[k] < minGap) return; // dedupe: max once / 10 min
  const want = CHANNELS[alert.type];
  if (!want.length) return;
  lastNotified[k] = now;
  await db.ref(`worker/last_notified/${k}`).set(now);

  const text = formatAlert(alert, alert.room_id ? cache.meta[alert.room_id]?.name : undefined);
  const sent: string[] = ["web"];
  if (want.includes("telegram") && (await sendTelegram(text))) sent.push("telegram");
  if (want.includes("email") && (await sendEmail(`[RoomSense] ${alert.message}`, text))) sent.push("email");
  await db.ref(`alerts/${id}/channels`).set(sent);
  console.log(`[alert] ${alert.type} ${alert.room_id ?? ""} -> ${sent.join(",")}`);
}

export async function alertCycle(now = Date.now()) {
  const snap = snapshot(now);

  // maintain hold timers from *raw* conditions
  const raw = new Set(conditions(snap).map((c) => c.key));
  for (const k of raw) since[k] ??= now;
  for (const k of Object.keys(since)) if (!raw.has(k)) delete since[k];

  const active = activeConditions(snap);
  const activeKeys = new Set(active.map((c) => c.key));

  for (const c of active) {
    if (!open[c.key]) await raise(c, now);
    else if (c.type === "fire") {
      // fire keeps re-notifying (every FIRE_RENOTIFY_MIN) while active
      const a = (await db.ref(`alerts/${open[c.key]}`).get()).val() as Alert | null;
      if (a) await notify(open[c.key], a, now);
    }
  }

  // rooms with stale data: their other alerts are unknown, not resolved — keep them open
  const blind = new Set(
    Object.entries(cache.meta).map(([id]) => id)
      .filter((id) => !cache.live[id] || now - toMs(cache.live[id].ts) > DEFAULTS.OFFLINE_SEC * 1000),
  );
  for (const [key, id] of Object.entries(open)) {
    if (activeKeys.has(key)) continue;
    const room = openRoom[key];
    if (room && blind.has(room) && !key.startsWith("offline:")) continue;
    delete open[key];
    delete openRoom[key];
    await db.ref(`alerts/${id}/resolved_ms`).set(now);
    if (key.startsWith("offline:")) {
      const what = key.slice("offline:".length).replace(/^room:/, "");
      await db.ref("alerts").push({
        key: `recovered:${what}:${now}`, type: "recovered", severity: "info",
        room_id: key.startsWith("offline:room:") ? what : null,
        message: `🟢 ${what} กลับมาออนไลน์แล้ว`, created_ms: now, resolved_ms: now, channels: ["web"],
      } satisfies Alert);
    }
  }
}

/** Gateway reports a store-and-forward flush (E4) -> info alert on the web. */
export async function noteBackfill(roomId: string | null, count: number, fromSec?: number, toSec?: number) {
  const now = Date.now();
  const range = fromSec && toSec
    ? ` (${new Date(toMs(fromSec)).toLocaleTimeString("th-TH")}–${new Date(toMs(toSec)).toLocaleTimeString("th-TH")})`
    : "";
  await db.ref("alerts").push({
    key: `backfill:${roomId}:${now}`, type: "recovered", severity: "info", room_id: roomId,
    message: `🟢 ส่งข้อมูลย้อนหลังจาก buffer แล้ว ${count} รายการ${range}`,
    value: `${count} readings`, created_ms: now, resolved_ms: now, channels: ["web"],
  } satisfies Alert);
}
