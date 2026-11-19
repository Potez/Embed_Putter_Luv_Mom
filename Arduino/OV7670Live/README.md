# OV7670Live — camera stream + on-board person detection

OV7670 (18-pin, no FIFO) on a 30-pin ESP32 DevKit (WROOM, no PSRAM). Tested on real hardware 2026-11-19.

- **ESP32:** streams frames over USB and runs `PersonDetector` (TFLite Micro person model) in a background task, about 5 s per check.
- **Laptop:** `tools/camera_viewer/live.py` shows the live view at http://localhost:8765, with YOLOv8n boxes and the board's verdict.

## Wiring

| OV7670 | ESP32 | | OV7670 | ESP32 |
|---|---|---|---|---|
| 3.3V | 3V3 | | GND | GND (next to 3V3) |
| SCL | D22 | | SDA | D21 |
| VS | D34 | | HS | D35 |
| PCLK | D33 | | MCLK | D32 |
| D7 | D27 | | D6 | D26 |
| D5 | D25 | | D4 | D23 |
| D3 | D19 | | D2 | D18 |
| D1 | VN (39) | | D0 | VP (36) |
| **RST** | **D14** | | **PWNN** | **GND (left, by VIN)** |

No external pull-ups needed. Never connect the camera to VIN (5V).

## Build & flash

1. Arduino IDE → Boards Manager → **esp32 by Espressif = 2.0.17** (3.x / 4.x will not work: their camera I2C driver NACKs this sensor).
2. Library Manager → **TensorFlowLite_ESP32 1.0.0**.
3. Board: *ESP32 Dev Module*. Open `OV7670Live.ino`, upload.

CLI equivalent:
```sh
arduino-cli core install esp32:esp32@2.0.17
arduino-cli lib install TensorFlowLite_ESP32@1.0.0
arduino-cli compile --fqbn esp32:esp32:esp32 Arduino/OV7670Live
arduino-cli upload -p /dev/cu.usbserial-0001 --fqbn esp32:esp32:esp32 Arduino/OV7670Live
```

## Live viewer (macOS / Linux)

```sh
cd tools/camera_viewer
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
OV7670_PORT=/dev/cu.usbserial-0001 .venv/bin/python live.py   # open http://localhost:8765
```
Close Arduino Serial Monitor first, because only one program can use the port.

## Using `PersonDetector` in your own code

```cpp
#include "PersonDetector.h"
PersonDetector detector(0.6f);          // threshold
detector.begin();                       // call FIRST in setup(): needs a contiguous 81KB block
Detection d = detector.detect(fb->buf, fb->len);
if (d.isPerson) { /* d.person, d.noPerson, d.ms */ }
```
It answers "person / no person" only. There are no boxes and no count; YOLO is far too big for this board.

## Known quirks (why the code looks the way it does)

- **Short frames:** the ESP32 misses 1 byte per 320-byte line, so frames are 319-byte lines (~159×108) instead of 160×120. The stock camera driver drops every such frame. `src/cam/` is esp32-camera @ `f0bb429` (Apache-2.0) with the FB-SIZE check in `cam_hal.c` removed. `PersonDetector` and `live.py` realign the lines.
- **Rotation:** the image is rotated 90° because of how the camera is mounted. The code rotates it back.
- **Memory:** allocate in this order: model arena → frame copy → camera. Any other order fails, because the heap fragments.
- **Serial protocol (921600 baud):** send `s`, and the board replies `FRAME <len> <w> <h>\n<raw RGB565>\nDET <person> <none> <isPerson> <ms> <count>\n`.

Model: TensorFlow Lite Micro person_detection (MobileNet v1, 96×96 grayscale, int8), Apache-2.0, see `LICENSE-tflite-person-model`.
