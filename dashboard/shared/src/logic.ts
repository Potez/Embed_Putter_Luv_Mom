import type { Booking, Reading } from "./types.ts";

export const DEFAULTS = {
  OFFLINE_SEC: 60,
  NO_SHOW_GRACE_MIN: 15,
  UNDERUSE_RATIO: 0.5,
  UNDERUSE_MIN: 15,
  TEMP_HIGH_C: 30,
  NOISE_HIGH_DB: 70,
  NOISE_MIN: 5,
  LIGHT_EMPTY_MIN: 10,      // light still on with nobody for this long -> light_fail
  DEDUPE_MIN: 10,
  FIRE_RENOTIFY_MIN: 1,
};
export type Thresholds = typeof DEFAULTS;

/** Device timestamps may be seconds (spec) or ms; normalise to ms. */
export const toMs = (t: number | undefined | null): number =>
  !t ? 0 : t < 1e12 ? t * 1000 : t;

/** AI count is primary; IR in/out count is the fallback. */
export function peopleOf(r: Reading | null | undefined): number {
  if (!r) return 0;
  return Math.max(0, r.people_ai ?? r.people_ir ?? 0);
}

export function isOccupied(r: Reading | null | undefined): boolean {
  return !!r && (peopleOf(r) > 0 || r.pir === true);
}

export function isOffline(r: Reading | null | undefined, nowMs: number, offlineSec = DEFAULTS.OFFLINE_SEC) {
  return !r || nowMs - toMs(r.ts) > offlineSec * 1000;
}

export type SoundLevel = "quiet" | "talk" | "loud";
export function soundLevel(db: number | undefined): SoundLevel | null {
  if (db === undefined || db === null) return null;
  return db < 45 ? "quiet" : db < 65 ? "talk" : "loud";
}

export function activeBooking<T extends Booking>(bookings: T[], roomId: string, nowMs: number): T | undefined {
  return bookings.find((b) => b.room_id === roomId && b.start_ms <= nowMs && b.end_ms > nowMs);
}

export function nextBooking<T extends Booking>(bookings: T[], roomId: string, nowMs: number): T | undefined {
  return bookings
    .filter((b) => b.room_id === roomId && b.start_ms > nowMs)
    .sort((a, b) => a.start_ms - b.start_ms)[0];
}

export type RoomStatus = "fire" | "offline" | "no_show" | "underused" | "in_use" | "free";

/**
 * Instantaneous status for a room card. (Alerts additionally require the
 * condition to persist — see rules.ts — so a card may show "underused"
 * a little before the alert fires.)
 */
export function roomStatus(
  live: Reading | null | undefined,
  booking: Booking | undefined,
  nowMs: number,
  t: Thresholds = DEFAULTS,
): RoomStatus {
  if (live?.flame) return "fire";
  if (isOffline(live, nowMs, t.OFFLINE_SEC)) return "offline";
  const occ = isOccupied(live);
  if (booking) {
    const sinceStartMin = (nowMs - booking.start_ms) / 60000;
    if (!occ && sinceStartMin >= t.NO_SHOW_GRACE_MIN) return "no_show";
    if (occ && sinceStartMin >= t.UNDERUSE_MIN && peopleOf(live) < t.UNDERUSE_RATIO * booking.expected)
      return "underused";
  }
  return occ ? "in_use" : "free";
}

// ---------- Metrics (System Health) ----------

/** Packet delivery rate from node_seq values (handles node reboots: seq going backwards starts a new run). */
export function packetDelivery(seqs: number[]): { received: number; expected: number; pdr: number | null } {
  if (seqs.length === 0) return { received: 0, expected: 0, pdr: null };
  let expected = 0;
  const seen = new Set<string>();
  let run = 0, runMin = seqs[0], runMax = seqs[0], prev = seqs[0];
  const closeRun = () => { expected += runMax - runMin + 1; };
  for (const s of seqs) {
    if (s < prev - 5) { closeRun(); run++; runMin = s; runMax = s; } // reboot / reset
    runMin = Math.min(runMin, s);
    runMax = Math.max(runMax, s);
    seen.add(`${run}:${s}`);
    prev = s;
  }
  closeRun();
  return { received: seen.size, expected, pdr: expected ? seen.size / expected : null };
}

export function stats(values: number[]): { mean: number; min: number; max: number; n: number } | null {
  const v = values.filter((x) => Number.isFinite(x));
  if (!v.length) return null;
  return { mean: v.reduce((a, b) => a + b, 0) / v.length, min: Math.min(...v), max: Math.max(...v), n: v.length };
}

/** sensor -> cloud latency per reading, ms (needs node_ts and server_ts). */
export function sensorToCloudMs(r: Reading): number | null {
  if (!r.node_ts || !r.server_ts) return null;
  const d = r.server_ts - toMs(r.node_ts);
  return d >= 0 && d < 10 * 60_000 ? d : null; // ignore clock garbage
}

export function hourKey(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}`;
}
