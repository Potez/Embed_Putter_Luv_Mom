// Firebase Realtime Database schema (see docs/firebase-schema.md).
// Times: device `ts` fields are Unix SECONDS (as in the spec); everything the
// dashboard/worker writes uses Unix MILLISECONDS and is suffixed `_ms`.

/** gateway -> cloud. Written to rooms/{roomId}/live (PUT) and rooms/{roomId}/readings/{ts} (PUT). */
export interface Reading {
  room_id: string;
  ts: number;               // gateway time, seconds
  node_ts?: number;         // node time, seconds (for sensor->cloud latency)
  server_ts?: number;       // ms, set by Firebase: {".sv":"timestamp"}
  people_ai?: number | null;
  ai_conf?: number | null;  // 0..1
  people_ir?: number | null;
  pir?: boolean;
  light_on?: boolean;
  ldr?: number;
  temp_c?: number;
  humidity?: number;
  sound_db?: number;
  flame?: boolean;
  status?: string;          // optional hint from gateway; dashboard derives its own
  node_seq?: number;
  buffered?: boolean;
}

export interface RoomMeta {
  name: string;
  capacity: number;
  order?: number;
}

export type EventType =
  | "enter" | "exit" | "light_on" | "light_off" | "light_fail"
  | "manual" | "reboot" | "reconnect" | "backfill";

/** rooms/{roomId}/events/{pushId} */
export interface RoomEvent {
  ts: number;               // seconds
  type: EventType;
  detail?: string;
  by?: string;              // who pressed a manual control
  latency_ms?: number;      // e.g. person detected -> light confirmed on
}

/** control/{roomId} — dashboard writes, gateway listens and clears/acks */
export interface ControlCommand {
  cmd: "light_on" | "light_off" | "servo_stop";
  by: string;
  ts_ms: number;
  done_ms?: number;         // gateway sets when executed
}

/** bookings/{bookingId} */
export interface Booking {
  room_id: string;
  booked_by: string;
  title?: string;
  expected: number;
  start_ms: number;
  end_ms: number;
  created_by?: string;
  created_ms?: number;
  result?: BookingResult;   // written by worker after the booking ends
}

export interface BookingResult {
  peak: number;
  avg: number;              // avg people across the booking
  util_pct: number;         // avg / expected * 100
  no_show: boolean;
  computed_ms: number;
}

export type Severity = "critical" | "high" | "medium" | "low" | "info";

/** alerts/{alertId} */
export interface Alert {
  key: string;              // dedupe key, e.g. "no_show:-Nbk123"
  type: AlertType;
  severity: Severity;
  room_id: string | null;
  message: string;
  value?: string;           // measured value, human readable
  created_ms: number;
  resolved_ms?: number;
  ack_by?: string;
  ack_ms?: number;
  channels?: string[];      // where it was sent: web, telegram, email
}

export type AlertType =
  | "fire" | "no_show" | "underused" | "light_fail" | "offline"
  | "temp_high" | "noise_high" | "recovered";

/** devices/{deviceId}/health — gateway writes raw, worker adds derived metrics */
export interface DeviceHealth {
  kind: "gateway" | "node";
  room_id?: string;
  online?: boolean;
  rssi?: number;
  uptime_s?: number;
  heap_free?: number;
  last_seen?: number;       // seconds
  reboots?: number;
  reconnects?: number;
  buffer_depth?: number;
  last_outage?: { from: number; to: number; backfilled: number }; // seconds
}

/** stats/{roomId}/hourly/{YYYYMMDDHH} — worker aggregates for Reports */
export interface HourStat {
  hour_ms: number;
  samples: number;
  occupied: number;         // samples with someone present
  people_sum: number;
  light_empty: number;      // samples with light on and nobody present
  sample_sec: number;       // median spacing between samples (to convert counts to time)
}
