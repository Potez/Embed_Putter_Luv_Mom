import type { RoomEvent } from "@roomsense/shared";
import { db } from "./fb.ts";
import { alertCycle, loadState, noteBackfill, noteLightFail, startListeners, cache } from "./alerts.ts";
import { aggregateRange, aggregateRecent, computeBookingResults } from "./aggregate.ts";

const every = (ms: number, name: string, fn: () => Promise<void>) => {
  let running = false;
  const tick = async () => {
    if (running) return;
    running = true;
    try { await fn(); } catch (e) { console.error(`[${name}]`, e); } finally { running = false; }
  };
  setTimeout(tick, 3000);
  setInterval(tick, ms);
};

await loadState();
startListeners();

// Watch gateway events that need a reaction (only new ones).
const startSec = Math.floor(Date.now() / 1000);
const watchedRooms = new Set<string>();
db.ref("room_list").on("child_added", (room) => {
  const roomId = room.key!;
  if (watchedRooms.has(roomId)) return;
  watchedRooms.add(roomId);
  db.ref(`rooms/${roomId}/events`).orderByChild("ts").startAt(startSec).on("child_added", async (s) => {
    const e = s.val() as RoomEvent & { count?: number; from?: number; to?: number };
    if (e.type === "light_fail") noteLightFail(roomId, e.ts);
    if (e.type === "backfill") {
      await noteBackfill(roomId, e.count ?? 0, e.from, e.to);
      if (e.from && e.to) await aggregateRange(roomId, e.from, e.to);
    }
  });
});

every(10_000, "alerts", () => alertCycle());
every(60_000, "bookings", () => computeBookingResults());
every(60_000, "stats", () => aggregateRecent());

await db.ref("worker/heartbeat_ms").set(Date.now());
setInterval(() => db.ref("worker/heartbeat_ms").set(Date.now()), 30_000);

console.log(`[worker] running — telegram:${!!process.env.TELEGRAM_BOT_TOKEN} email:${!!process.env.SMTP_USER}`);
setTimeout(() => console.log(`[worker] watching ${Object.keys(cache.meta).length} rooms`), 3000);
