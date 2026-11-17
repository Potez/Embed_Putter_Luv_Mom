# RoomSense — ESP-NOW protocol (v1)

สำหรับ **Pat (Node)**, **Flame (ESP32-CAM)** และ **Jeen (Gateway)**.
Source of truth คือ [`shared/packets.h`](shared/packets.h) — ให้ `#include` ไฟล์นี้ตรงๆ ห้าม copy struct ไปเขียนเอง

## 1. Packet

ทุก struct เป็น `__attribute__((packed))`, little-endian, **ไบต์แรก = `packet_type`**. ขนาดถูกตรวจด้วย `static_assert`

### NodePacket — `packet_type = 1`, **17 bytes**, ส่งทุก **500 ms (2 Hz)**

| offset | field | type | ความหมาย |
|---:|---|---|---|
| 0 | `packet_type` | uint8 | `PKT_NODE` = 1 |
| 1 | `node_id` | uint8 | 1 = node-A, 2 = node-B … |
| 2 | `node_seq` | uint32 | +1 ต่อ packet **ใหม่** (retry ใช้ seq เดิม), เริ่มใหม่หลังรีบูตได้ |
| 6 | `node_ts` | uint32 | Unix seconds จาก NTP, `0` = ยังไม่ sync |
| 10 | `door_do` | uint8 | **active-low**: `0` = E18-D80NK เจอวัตถุ **อย่างน้อย 1 ครั้งใน 500 ms ที่ผ่านมา** (ต้อง latch!) |
| 11 | `pir` | uint8 | `1` = มีการเคลื่อนไหว |
| 12 | `people_ir` | int16 | จำนวนคนจากการนับที่ประตู, `-1` = ไม่รองรับ |
| 14 | `sound_raw` | uint16 | KY-037 ADC 0–4095 (แนะนำ: ค่าสูงสุดใน 500 ms) |
| 16 | `flame_do` | uint8 | **active-low**: `0` = เจอไฟ |

### CamPacket — `packet_type = 2`, **12 bytes**, ส่ง **ทุกครั้งที่นับได้ (~3 Hz)**

| offset | field | type | ความหมาย |
|---:|---|---|---|
| 0 | `packet_type` | uint8 | `PKT_CAM` = 2 |
| 1 | `cam_id` | uint8 | 1 = cam-A |
| 2 | `seq` | uint32 | +1 ต่อ packet ใหม่ |
| 6 | `ts` | uint32 | Unix seconds (NTP), `0` = ยังไม่ sync |
| 10 | `person_count` | int8 | จำนวนคน, `-1` = นับไม่ได้ (ห้ามส่ง 0 แทน — โมเดลแยก "ไม่มีข้อมูล" กับ "0 คน") |
| 11 | `ai_conf` | uint8 | 0–100 (gateway แปลงเป็น 0–1 ตอนขึ้น cloud) |

### AckPacket — `packet_type = 3`, **7 bytes**, gateway → ผู้ส่ง

| offset | field | type | ความหมาย |
|---:|---|---|---|
| 0 | `packet_type` | uint8 | `PKT_ACK` = 3 |
| 1 | `src_type` | uint8 | ชนิด packet ที่ ACK (1 หรือ 2) |
| 2 | `src_id` | uint8 | `node_id` / `cam_id` |
| 3 | `seq` | uint32 | seq ที่ได้รับ |

## 2. ความถี่และ timeout ที่ gateway ใช้

| ค่า | เท่าไร | ผลถ้าไม่ส่ง |
|---|---|---|
| Node | 2 Hz | ถ้าเงียบ > 2 s → gateway ถือว่า `door_do = 1` (ไม่มีวัตถุ), ค่าของ node ใน reading = `null` |
| CAM | ~3 Hz | ถ้าเงียบ > 2 s → `person_count = -1` (โมเดลเห็นเป็น "กล้องไม่ส่ง") |
| Node offline | 60 s | `devices/node-A/health.online = false` → แจ้งเตือน Telegram |

## 3. ACK / retry (E4)

1. ส่ง packet → รอ `AckPacket` ที่ `src_type`, `src_id`, `seq` ตรงกัน **300 ms**
2. ไม่ได้ ACK → ส่งซ้ำ **seq เดิม** ได้สูงสุด **3 ครั้ง** แล้วทิ้ง ไปส่ง packet ถัดไป (seq + 1)
3. Gateway ACK ทุก packet รวมทั้งตัวซ้ำ (กรณี ACK หาย) แต่ประมวลผลเฉพาะ seq ใหม่
4. Gateway นับ: `rx` (ได้รับไม่ซ้ำ), `lost` (seq ที่ข้าม), `dup` (retry), `seq_resets` (seq ย้อนกลับ = ผู้ส่งรีบูต — seq < 16 หรือย้อน > 64)
   → **PDR = rx / (rx + lost)** อยู่ใน `devices/node-A/health.pdr`
5. ตัวอย่างโค้ดฝั่งผู้ส่ง: [`mock_sender/src/main.cpp`](mock_sender/src/main.cpp) ฟังก์ชัน `sendReliable()`

## 4. Wi-Fi channel + การจับคู่ MAC

ESP-NOW ส่งได้เฉพาะ **channel เดียวกัน** และ gateway ต้องต่อ Wi-Fi (channel ถูกกำหนดโดย router/hotspot)

1. Flash gateway → เปิด Serial Monitor 115200 → จะเห็น
   ```
   Gateway MAC (give to Pat & Flame): 24:6F:28:AA:BB:CC
   Wi-Fi channel (ESP-NOW senders MUST use this): 6
   ```
2. ฝั่ง node / CAM:
   - **ทางที่ง่ายที่สุด:** ต่อ Wi-Fi hotspot ตัวเดียวกับ gateway (`WiFi.begin`) → channel ตรงอัตโนมัติ และได้ NTP สำหรับ `node_ts`
   - หรือไม่ต่อ Wi-Fi: `WiFi.mode(WIFI_STA); esp_wifi_set_channel(<ch>, WIFI_SECOND_CHAN_NONE);` (ts จะเป็น 0)
   - `WiFi.setSleep(false)` ทั้งสองฝั่ง
3. add peer เป็น MAC ของ gateway (`channel = 0`, `ifidx = WIFI_IF_STA`, `encrypt = false`)
4. Gateway **add peer ผู้ส่งอัตโนมัติ** จาก MAC ของ packet แรก — ไม่ต้องบอก MAC ของ node/CAM ให้ gateway
5. ถ้าเปลี่ยน hotspot แล้ว channel เปลี่ยน → gateway print channel ใหม่ตอน reconnect; ฝั่งที่ fix channel ต้องแก้ตาม

## 5. Firebase paths ที่ gateway เขียน (ตาม `firebase-schema.md` v0.1)

| path | method | เมื่อไร |
|---|---|---|
| `rooms/{roomId}/live` | PUT | ทุก window 10 s (reading ล่าสุด) |
| `rooms/{roomId}/readings/{ts}` | PUT | ทุก window 10 s + ทันทีเมื่อ flame เป็น true; backfill ใช้ key `ts` เดิม (`buffered: true`) |
| `rooms/{roomId}/events/{pushId}` | POST | `enter` `exit` `light_on` `light_off` `light_fail` `manual` `reboot` `reconnect` `backfill` |
| `devices/gw-1/health` | PATCH | ทุก 30 s |
| `devices/node-A/health` | PATCH | ทุก 30 s (gateway เขียนแทน node) |
| `devices/{gw-1,node-A}/health/last_outage` | PUT | หลังเน็ตกลับมาและส่ง buffer หมด |
| `control/{roomId}` | GET | poll ทุก 3 s |
| `control/{roomId}/done_ms` | PUT `{".sv":"timestamp"}` | หลังทำคำสั่ง |

Reading:
```json
{ "room_id":"room-A", "ts":1733650002, "node_ts":1733650001, "server_ts":{".sv":"timestamp"},
  "people_ai":2, "ai_conf":0.87, "people_ir":2, "pir":true, "light_on":true, "ldr":812,
  "temp_c":26.4, "humidity":58, "sound_db":52, "flame":false, "node_seq":1042, "buffered":false }
```
`people_ai`/`ai_conf` = `null` ถ้า CAM เงียบหรือส่ง -1; ค่าจาก node = `null` ถ้า node เงียบ > 2 s
