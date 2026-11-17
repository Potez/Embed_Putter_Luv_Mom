# RoomSense Gateway (ESP32-WROOM) — Jeen

รับ ESP-NOW จาก node (Pat) + ESP32-CAM (Flame) → ทำนาย `power_on` ด้วย RandomForest ของ Flame ทุก 10 s
→ กดสวิตช์ไฟด้วย servo และยืนยันด้วย LDR → ส่งขึ้น Firebase Realtime Database (HTTPS + TLS verify)

```
[Node 2 Hz]──ESP-NOW+ACK──┐
[CAM ~3 Hz]──ESP-NOW+ACK──┤
                          ▼
 espnowTask ─► sensorTask (500 ms row → RoomSensePredictor → 10 s window) ─► actuatorTask (servo + LDR)
                          │ Reading                                          │ events
                          ▼                                                  ▼
                   ring buffer (200) ──────────────► cloudTask (core 0) ─► Firebase RTDB
```

| task | core/prio | หน้าที่ |
|---|---|---|
| `espnowTask` | 1 / 4 | callback copy ลง queue → แยกประเภท → seq หาย/ซ้ำ/reset → ACK → state ล่าสุด, event enter/exit |
| `sensorTask` | 1 / 3 | ทุก 500 ms สร้างแถวดิบ `person_count, digital_do, analog_2_raw` → predictor; ครบ 20 แถว → closed loop + Reading |
| `actuatorTask` | 1 / 2 | กด servo → รอ 2 s → อ่าน LDR → กดซ้ำ 1 ครั้ง → `light_fail`; ปุ่ม STOP (ISR) |
| `cloudTask` | 0 / 1 | sign-in, readings/live, events, health, control poll, backfill, backoff |

ทุก task ลงทะเบียน task watchdog (60 s) และคุยกันผ่าน Queue / Mutex เท่านั้น

## 1. ตั้งค่า

```bash
cd firmware/gateway
cp src/secrets.example.h src/secrets.h      # secrets.h ถูก .gitignore แล้ว ห้าม commit (ไม่มีไฟล์นี้ = build #error)
```
แก้ `src/secrets.h`: `WIFI_SSID`, `WIFI_PASS`, `FIREBASE_API_KEY`, `FIREBASE_DB_HOST` (ไม่มี `https://`),
`FIREBASE_EMAIL`, `FIREBASE_PASSWORD` (user ที่ `roles/gateway/{uid} = true`)

ค่าอื่นอยู่ใน `src/config.h` (ขา, ROOM_ID, threshold, เวลา)

## 2. Build / flash

```bash
pio run                        # build
pio run -t upload -t monitor   # flash + serial 115200
```
ตอนบูตจะเห็น:
```
  Gateway MAC (give to Pat & Flame): 24:6F:28:AA:BB:CC
  Wi-Fi channel (ESP-NOW senders MUST use this): 6
  Model: RoomSensePredictor (RandomForest 50x d6, Flame)      ← หรือ FALLBACK ถ้าหา header ไม่เจอ
```

## 3. ทดสอบแบบ MOCK (ไม่ต่อวงจร)

`MOCK_SENSORS 1` (ค่าเริ่มต้น): DHT11/LDR สุ่ม, **LED บนบอร์ด (GPIO2) = ไฟห้อง** — ทุกครั้งที่ "servo กด" ไฟจำลองจะสลับ
และ LDR จำลองอ่านตามนั้น closed loop จึงทำงานครบ

1. Flash gateway → จด MAC + channel
2. แก้ `firmware/mock_sender/src/config.h`: `GATEWAY_MAC`, `WIFI_CHANNEL` (หรือ `cp src/secrets.example.h src/secrets.h` ใน mock_sender แล้วใส่ `MOCK_WIFI_SSID`/`MOCK_WIFI_PASS` ให้ต่อ hotspot เดียวกัน → ได้ NTP ด้วย; **ห้ามใส่รหัสใน config.h**)
3. Flash mock_sender ลง ESP32 ตัวที่ 2: `cd ../mock_sender && pio run -t upload -t monitor`
4. คาดว่าจะเห็น (รอบจำลอง ~4 นาที: ว่าง → 1 → 2 → 4 → 3 → 1 → ว่าง):
   - gateway: `[window N] ... -> power_on=1 ... want_light=1` → `[act] light ON confirmed by LDR (latency xxxx ms)` → LED ติด
   - หลังคนออก ~30–40 s → `light OFF` → LED ดับ
   - ทุก ~2 นาที flame 10 s → `!!! FLAME` + reading ทันที + ไฟถูกปิด
   - Firebase console: `rooms/room-A/live` เปลี่ยนทุก 10 s, `events` มี `reboot`, `enter`, `exit`, `light_on`, `light_off`
   - mock: `delivery=100.0%` / gateway `devices/node-A/health.pdr`
5. ปุ่ม STOP (GPIO27 → GND): กด 1 ครั้ง = หยุด servo + ปิด auto (event `manual` by `stop_button`), กดอีกครั้ง = เปิด auto
6. Dashboard ส่ง `control/room-A = {cmd:"light_on", by:"cho", ts_ms:...}` → ภายใน 3 s มี `done_ms` และ auto ถูกพัก 10 นาที; หลัง LDR ยืนยันจะมี event `light_on` ที่มี `by` (dashboard เขียน event `manual` เอง, gateway เขียน `manual` เฉพาะ `servo_stop` — เหมือน `worker/src/sim.ts`)

## 4. ทดสอบ backfill (E4)

1. รัน gateway + mock ให้ส่งขึ้น cloud ปกติ
2. **ปิด hotspot 1 นาที** → serial: `[wifi] DISCONNECTED - buffering readings`, `buffer_depth` เพิ่ม ~6 แถว/นาที
3. **เปิด hotspot** → `[wifi] RECONNECTED` → `reading ... uploaded [buffered]` × N → `outage over: backfilled N readings`
4. ตรวจใน Firebase:
   - `rooms/room-A/readings/{ts}` ช่วงที่หลุดมีครบ และ `buffered: true`
   - `events`: `reconnect` และ `backfill {count, from, to}`
   - `devices/gw-1/health/last_outage {from, to, backfilled}` และ `reconnects` +1
   - ส่งซ้ำไม่เบิ้ล: key = `ts` เดิม (PUT ทับ)
5. Buffer เก็บ 200 readings (= 33 นาที) ถ้าเกินจะทิ้งอันเก่าสุด

## 5. เปลี่ยนเป็นเซนเซอร์จริง

1. `src/config.h`: `#define MOCK_SENSORS 0` (หรือ `build_flags = -DMOCK_SENSORS=0`)
2. ต่อสาย:

| อุปกรณ์ | ขา ESP32 | หมายเหตุ |
|---|---|---|
| DHT11 DATA | GPIO4 | pull-up 10k (module มีให้แล้ว) |
| KY-018 LDR S | GPIO34 | ADC1 เท่านั้น (ADC2 ใช้ไม่ได้ตอน Wi-Fi เปิด) |
| Servo signal | GPIO18 | **ไฟเลี้ยง servo 5 V แยก**, GND ร่วมกับ ESP32 |
| ปุ่ม STOP | GPIO27 ↔ GND | INPUT_PULLUP, interrupt FALLING |

3. Calibrate LDR: ดู `ldr` ใน reading ตอนไฟปิด/เปิด → ตั้ง `LDR_ON_THRESHOLD` ตรงกลาง; ถ้าสว่างแล้วค่าลด ให้ `LDR_INVERT 1`
4. ปรับ `SERVO_PRESS_ANGLE` / `SERVO_REST_ANGLE` ให้กดสวิตช์พอดี (servo attach เฉพาะตอนกด แล้ว detach, ห่างกัน ≥ 3 s)

## 6. วัด metrics

| metric | วิธีวัด | ที่มา |
|---|---|---|
| **latency node → cloud** | `server_ts − node_ts × 1000` (ms) ของแต่ละ reading (เฉพาะ `buffered:false`) | `rooms/room-A/readings` — node และ gateway ต้อง sync NTP; รวมเวลารอ window 10 s ด้วย ถ้าอยากได้เฉพาะ transport ใช้ `server_ts − ts × 1000` |
| **latency คนเข้า → ไฟติด** | `latency_ms` ใน event `light_on` = จากแถวแรกที่ `person_count > 0` หลังห้องว่าง ถึงตอน LDR ยืนยัน | `rooms/room-A/events` — รวมเวลารอครบ window (≤10 s) + servo + รอ 2 s |
| **packet delivery rate** | `pdr = rx / (rx + lost)` จาก seq, แยก `dup`, `seq_resets` | `devices/node-A/health`, CAM: `devices/gw-1/health.cam_pdr`; ฝั่งผู้ส่ง: สถิติ mock_sender |
| **uptime** | `uptime_s`, `reboots` (NVS), `reconnects`, event `reboot` (detail = reset reason) | `devices/gw-1/health` |

ตัวอย่างดึงค่า (Firebase REST):
```bash
curl "https://<db>/rooms/room-A/readings.json?orderBy=\"\$key\"&limitToLast=360&auth=<token>" > readings.json
python3 -c "import json;d=json.load(open('readings.json'));l=[r['server_ts']-r['node_ts']*1000 for r in d.values() if r.get('node_ts') and not r.get('buffered')];print(len(l),min(l),sum(l)/len(l),max(l))"
```

## 7. Predictor (Flame)

- `platformio.ini` อ้าง `../../Roomsense_dataset/src/predictor_class/RoomSensePredictor` (ไม่ copy, ไม่แก้ไฟล์ Flame)
  และตั้ง `-DREQUIRE_PREDICTOR=1` → ถ้าหา `RoomSensePredictor.h` ไม่เจอ build จะ `#error` (ไม่ fallback เงียบๆ)
- API จริง: `int update(int people_ai, int door_ir, int gray)` เรียกทุก 500 ms, `windows` เพิ่มเมื่อปิด window 10 s,
  `x[12]` = feature ล่าสุด (พิมพ์ใน Serial ทุก window) — glue อยู่ที่ `src/predictor_glue.cpp`
- ป้อนเฉพาะ `person_count` (-1 ถ้ากล้องเงียบ > 2 s), `digital_do` (E18), `gray = 0` — **ไม่ป้อน LDR / DHT11** (LDR = leakage)
- `alarm = flame` เป็น hard rule นอกโมเดล: `want_light = power_on && !alarm && !stop_latched && !manual_override`
- reading มี `status`: `power_on ? "in_use" : "vacant"` (ตาม RoomSensePredictor.ino; dashboard คำนวณสถานะละเอียดเองจาก bookings)
