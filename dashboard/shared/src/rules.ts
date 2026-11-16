// Pure alert rules: snapshot in -> currently-active conditions out.
// The worker tracks how long each condition has been true ("since") and
// handles dedupe / notification channels.

import type { AlertType, Booking, Reading, Severity } from "./types.ts";
import { DEFAULTS, type Thresholds, isOccupied, isOffline, peopleOf, toMs, activeBooking } from "./logic.ts";

export interface RoomInput {
  id: string;
  name: string;
  live: Reading | null;
}

export interface DeviceInput {
  id: string;
  kind: "gateway" | "node";
  room_id?: string;
  last_seen?: number; // seconds
}

export interface Snapshot {
  nowMs: number;
  rooms: RoomInput[];
  devices: DeviceInput[];
  bookings: (Booking & { id: string })[];
  /** ms timestamp when a condition key first became true (maintained by caller) */
  since: Record<string, number>;
  /** ms of the most recent `light_fail` event per room (from gateway) */
  lightFailEvents?: Record<string, number>;
}

export interface Condition {
  key: string;
  type: AlertType;
  severity: Severity;
  roomId: string | null;
  message: string;
  value?: string;
  /** must have been true for this long before it counts (ms) */
  holdMs: number;
}

/** Which channels each alert type goes to (spec §3). Web always. */
export const CHANNELS: Record<AlertType, ("telegram" | "email")[]> = {
  fire: ["telegram", "email"],
  no_show: ["telegram"],
  underused: [],
  light_fail: ["telegram"],
  offline: ["telegram"],
  temp_high: [],
  noise_high: [],
  recovered: [],
};

export function conditions(s: Snapshot, t: Thresholds = DEFAULTS): Condition[] {
  const out: Condition[] = [];
  const now = s.nowMs;
  const min = 60_000;
  const devOffline = (d: DeviceInput) => !d.last_seen || now - toMs(d.last_seen) > t.OFFLINE_SEC * 1000;

  for (const d of s.devices) {
    if (devOffline(d)) {
      out.push({
        key: `offline:${d.id}`, type: "offline", severity: "high", roomId: null, holdMs: 0,
        message: `${d.kind === "gateway" ? "Gateway" : "Node"} ${d.id} ไม่ส่งข้อมูลเกิน ${t.OFFLINE_SEC} วินาที`,
        value: d.last_seen ? `เห็นล่าสุด ${new Date(toMs(d.last_seen)).toLocaleTimeString("th-TH")}` : "ไม่เคยเห็น",
      });
    }
  }

  for (const room of s.rooms) {
    const r = room.live;

    if (r?.flame) {
      out.push({ key: `fire:${room.id}`, type: "fire", severity: "critical", roomId: room.id, holdMs: 0,
        message: `🔥 ตรวจพบไฟใน ${room.name}`, value: "Flame sensor = ON" });
    }

    if (isOffline(r, now, t.OFFLINE_SEC)) {
      // one outage = one alert: skip if this room's node is already reported offline
      if (!s.devices.some((d) => d.room_id === room.id && devOffline(d))) out.push({ key: `offline:room:${room.id}`, type: "offline", severity: "high", roomId: room.id, holdMs: 0,
        message: `${room.name} ไม่มีข้อมูลเกิน ${t.OFFLINE_SEC} วินาที`,
        value: r ? `ข้อมูลล่าสุด ${new Date(toMs(r.ts)).toLocaleTimeString("th-TH")}` : "ไม่เคยมีข้อมูล" });
      continue; // stale data -> skip the rest
    }
    const live = r!;
    const occ = isOccupied(live);
    const people = peopleOf(live);
    const b = activeBooking(s.bookings, room.id, now);

    if (b) {
      if (!occ && now - b.start_ms >= t.NO_SHOW_GRACE_MIN * min) {
        out.push({ key: `no_show:${b.id}`, type: "no_show", severity: "high", roomId: room.id, holdMs: 0,
          message: `No-show: ${room.name} จองโดย ${b.booked_by} เลยเวลาเริ่ม ${t.NO_SHOW_GRACE_MIN} นาทีแล้วไม่มีคน`,
          value: `0 / ${b.expected} คน` });
      }
      if (occ && people < t.UNDERUSE_RATIO * b.expected) {
        out.push({ key: `underused:${b.id}`, type: "underused", severity: "medium", roomId: room.id,
          holdMs: t.UNDERUSE_MIN * min,
          message: `${room.name} ใช้ไม่คุ้ม: คนจริงน้อยกว่า ${Math.round(t.UNDERUSE_RATIO * 100)}% ของที่จองเกิน ${t.UNDERUSE_MIN} นาที`,
          value: `${people} / ${b.expected} คน` });
      }
    }

    if (live.light_on && !occ) {
      out.push({ key: `light_fail:${room.id}`, type: "light_fail", severity: "medium", roomId: room.id,
        holdMs: t.LIGHT_EMPTY_MIN * min,
        message: `${room.name} ไฟยังเปิดอยู่ทั้งที่ไม่มีคนเกิน ${t.LIGHT_EMPTY_MIN} นาที (ไฟไม่ดับ?)`,
        value: `LDR ${live.ldr ?? "-"}` });
    }
    const lf = s.lightFailEvents?.[room.id];
    if (lf && now - lf < t.DEDUPE_MIN * min) {
      out.push({ key: `light_fail_evt:${room.id}`, type: "light_fail", severity: "medium", roomId: room.id, holdMs: 0,
        message: `${room.name} servo กดแล้วแต่ LDR ไม่เปลี่ยน (ลองซ้ำแล้ว)`, value: `LDR ${live.ldr ?? "-"}` });
    }

    if (live.temp_c !== undefined && live.temp_c > t.TEMP_HIGH_C) {
      out.push({ key: `temp_high:${room.id}`, type: "temp_high", severity: "low", roomId: room.id, holdMs: 0,
        message: `${room.name} อุณหภูมิสูงผิดปกติ`, value: `${live.temp_c.toFixed(1)} °C` });
    }

    if (live.sound_db !== undefined && live.sound_db > t.NOISE_HIGH_DB) {
      out.push({ key: `noise_high:${room.id}`, type: "noise_high", severity: "low", roomId: room.id,
        holdMs: t.NOISE_MIN * min,
        message: `${room.name} เสียงดังเกินเกณฑ์นานกว่า ${t.NOISE_MIN} นาที`, value: `${Math.round(live.sound_db)} dB` });
    }
  }
  return out;
}

/** Apply hold times using the caller's `since` map. */
export function activeConditions(s: Snapshot, t: Thresholds = DEFAULTS): Condition[] {
  return conditions(s, t).filter((c) => {
    if (c.holdMs === 0) return true;
    const since = s.since[c.key];
    return since !== undefined && s.nowMs - since >= c.holdMs;
  });
}
