// Booking outcomes + hourly stats for the Reports page.
import {
  hourKey, isOccupied, peopleOf, toMs, DEFAULTS,
  type Booking, type BookingResult, type HourStat, type Reading,
} from "@roomsense/shared";
import { db } from "./fb.ts";
import { cache } from "./alerts.ts";

async function readingsBetween(roomId: string, fromMs: number, toMs_: number): Promise<Reading[]> {
  const s = await db.ref(`rooms/${roomId}/readings`)
    .orderByKey()
    .startAt(String(Math.floor(fromMs / 1000)))
    .endAt(String(Math.floor(toMs_ / 1000)))
    .get();
  return Object.values((s.val() ?? {}) as Record<string, Reading>);
}

export function bookingResult(b: Booking, readings: Reading[], now = Date.now()): BookingResult {
  const counts = readings.map(peopleOf);
  const peak = counts.length ? Math.max(...counts) : 0;
  const avg = counts.length ? counts.reduce((a, c) => a + c, 0) / counts.length : 0;
  const graceEnd = b.start_ms + DEFAULTS.NO_SHOW_GRACE_MIN * 60_000;
  const showedUp = readings.some((r) => toMs(r.ts) <= graceEnd && isOccupied(r));
  return {
    peak,
    avg: Math.round(avg * 100) / 100,
    util_pct: Math.round((avg / Math.max(1, b.expected)) * 100),
    no_show: !showedUp,
    computed_ms: now,
  };
}

export async function computeBookingResults(now = Date.now()) {
  for (const [id, b] of Object.entries(cache.bookings)) {
    if (b.result || b.end_ms > now) continue;
    const readings = await readingsBetween(b.room_id, b.start_ms, b.end_ms);
    const result = bookingResult(b, readings, now);
    await db.ref(`bookings/${id}/result`).set(result);
    console.log(`[booking] ${id} ${b.room_id} peak=${result.peak} util=${result.util_pct}% no_show=${result.no_show}`);
  }
}

export function hourStat(hourMs: number, readings: Reading[]): HourStat {
  const ts = readings.map((r) => toMs(r.ts)).sort((a, b) => a - b);
  const gaps = ts.slice(1).map((t, i) => (t - ts[i]) / 1000).filter((g) => g > 0 && g < 300).sort((a, b) => a - b);
  return {
    hour_ms: hourMs,
    samples: readings.length,
    occupied: readings.filter(isOccupied).length,
    people_sum: readings.reduce((a, r) => a + peopleOf(r), 0),
    light_empty: readings.filter((r) => r.light_on && !isOccupied(r)).length,
    sample_sec: gaps.length ? gaps[Math.floor(gaps.length / 2)] : 5,
  };
}

export async function aggregateHour(roomId: string, anyMsInHour: number) {
  const d = new Date(anyMsInHour);
  d.setMinutes(0, 0, 0);
  const start = d.getTime();
  const readings = await readingsBetween(roomId, start, start + 3_600_000 - 1);
  if (!readings.length) return;
  await db.ref(`stats/${roomId}/hourly/${hourKey(start)}`).set(hourStat(start, readings));
}

/** Recompute the current and previous hour for every room (idempotent). */
export async function aggregateRecent(now = Date.now()) {
  for (const roomId of Object.keys(cache.meta)) {
    await aggregateHour(roomId, now);
    await aggregateHour(roomId, now - 3_600_000);
  }
}

/** After a buffer flush, re-aggregate every hour the backfilled data touched. */
export async function aggregateRange(roomId: string, fromSec: number, toSec: number) {
  for (let t = toMs(fromSec); t <= toMs(toSec) + 3_600_000; t += 3_600_000) await aggregateHour(roomId, t);
}
