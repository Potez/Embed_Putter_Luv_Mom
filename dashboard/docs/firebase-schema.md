# RoomSense — Firebase data contract (v0.1)

For **Jeen (Gateway/Cloud)** and **Cho (Dashboard)**. Firebase **Realtime Database**.
`worker/src/sim.ts` is a working reference implementation of everything the gateway must write.

> Why RTDB (not Firestore): the ESP32 can write with one plain HTTPS `PUT`, and
> the dashboard gets real-time listeners. `ts` from devices = Unix **seconds**
> (as in the spec); values written by the dashboard/worker end in `_ms`.

## Tree

```
room_list/{roomId}               { name, capacity, order }            ← staff (seed)
rooms/{roomId}/live              Reading (latest)                      ← gateway PUT
rooms/{roomId}/readings/{ts}     Reading (raw, every sample — M5)      ← gateway PUT
rooms/{roomId}/events/{pushId}   { ts, type, detail?, by?, latency_ms? } ← gateway POST
devices/{deviceId}/health        DeviceHealth                          ← gateway PUT/PATCH
control/{roomId}                 { cmd, by, ts_ms, done_ms? }          ← dashboard writes, gateway executes + sets done_ms
bookings/{bookingId}             { room_id, booked_by, title?, expected, start_ms, end_ms, result? }
alerts/{alertId}                 written by worker; staff may set ack_by / ack_ms
stats/{roomId}/hourly/{YYYYMMDDHH}  worker aggregates for Reports
roles/gateway/{uid}: true        which Firebase Auth account is the gateway
```

`roomId` = `room-A`, `room-B`, … Adding a room = add `room_list/{id}` + a node. The dashboard renders one card per entry (Scalability).

## Reading (gateway → cloud) — same as spec §4, plus 2 optional fields

```json
{
  "room_id": "room-A",
  "ts": 1733650002,
  "node_ts": 1733650001,
  "server_ts": { ".sv": "timestamp" },
  "people_ai": 2, "ai_conf": 0.87, "people_ir": 2, "pir": true,
  "light_on": true, "ldr": 812, "temp_c": 26.4, "humidity": 58,
  "sound_db": 52, "flame": false, "status": "in_use",
  "node_seq": 1042, "buffered": false
}
```
- `node_ts` (node clock, seconds) + `server_ts` (Firebase fills it in) → **sensor→cloud latency** on the Health page. Both clocks need NTP.
- `node_seq` → **packet delivery rate** (gaps = lost packets; seq resetting after reboot is handled).
- Write the same object to **both** `rooms/{id}/live` and `rooms/{id}/readings/{ts}`. Keying readings by `ts` makes buffered replays idempotent: re-sending the same reading overwrites, never duplicates (E4).
- `status` is optional; the dashboard derives the status itself (it needs the bookings).

## Events

`type` ∈ `enter` `exit` `light_on` `light_off` `light_fail` `manual` `reboot` `reconnect` `backfill`
- `light_on` → include `latency_ms` (person detected → LDR confirms light). Shown as "คนเข้า → ไฟติด".
- `light_fail` → servo pressed, LDR didn't change after the retry. Worker sends Telegram.
- `backfill` → after flushing the buffer: `{ "ts", "type": "backfill", "count": 18, "from": <ts>, "to": <ts> }`.
  The worker posts a "sent buffered data" notice and recomputes the hourly report stats.

## Device health

```json
devices/gw-1/health  { "kind": "gateway", "online": true, "rssi": -61, "uptime_s": 3600,
                       "heap_free": 4100000, "last_seen": 1733650002, "reboots": 0,
                       "reconnects": 1, "buffer_depth": 0 }
devices/node-A/health { "kind": "node", "room_id": "room-A", ... same fields ... }
devices/node-B/health/last_outage { "from": <ts>, "to": <ts>, "backfilled": 18 }
```
No update for 60 s → offline alert (Telegram). The gateway may write node health on the nodes' behalf.

## Manual control (dashboard → gateway)

Gateway listens to `control/{roomId}` (RTDB REST streaming: `GET …/control.json` with
`Accept: text/event-stream`, or poll every 2–5 s). On a new command without `done_ms`:
execute (`light_on` / `light_off` / `servo_stop`) and `PUT control/{roomId}/done_ms = {".sv":"timestamp"}`.
The dashboard shows "⏳ waiting for gateway" until then.

## Gateway authentication (ESP32)

1. In the Firebase console, create user `gateway@…` (Email/Password) and set `roles/gateway/{thatUid} = true`.
2. On boot (and every ~55 min), sign in:
   `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<WEB_API_KEY>`
   body `{"email":"…","password":"…","returnSecureToken":true}` → `idToken`
3. Write: `PUT https://<db>.firebasedatabase.app/rooms/room-A/live.json?auth=<idToken>`
4. Keep the gateway password in a `secrets.h` that is git-ignored.

The security rules (`database.rules.json`) only allow this account to write sensor data;
staff accounts cannot forge readings or alerts (verified against the emulator).
