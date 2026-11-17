// config.h — RoomSense gateway (ESP32-WROOM / esp32dev) configuration.
#pragma once

// ---------------------------------------------------------------- build mode
// 1 = no wiring needed: DHT11/LDR are simulated and the on-board LED stands in for the servo.
//     The simulated LDR follows a simulated wall switch that the "servo" toggles, so the
//     closed loop (press -> verify via LDR) works end-to-end on a bare board.
// 0 = real sensors and servo.
#ifndef MOCK_SENSORS
#define MOCK_SENSORS 1
#endif

// 1 = use Flame's RoomSensePredictor (Roomsense_dataset/src/predictor_class/RoomSensePredictor).
// 0 = built-in fallback rule.
// Auto-enabled when RoomSensePredictor.h is on the include path (see platformio.ini).
// 1 = build fails (#error) if RoomSensePredictor.h is not found. Use 1 for the real build.
#ifndef REQUIRE_PREDICTOR
#define REQUIRE_PREDICTOR 0
#endif

#ifndef USE_FLAME_PREDICTOR
#  if __has_include("RoomSensePredictor.h")
#    define USE_FLAME_PREDICTOR 1
#  else
#    define USE_FLAME_PREDICTOR 0
#  endif
#endif
#if REQUIRE_PREDICTOR && !__has_include("RoomSensePredictor.h")
#  error "REQUIRE_PREDICTOR=1 but RoomSensePredictor.h not found - check -I paths in platformio.ini"
#endif

// ---------------------------------------------------------------- pins
#define PIN_DHT11     4
#define PIN_LDR       34   // must be ADC1 (ADC2 does not work while Wi-Fi is on)
#define PIN_SERVO     18
#define PIN_STOP_BTN  27   // INPUT_PULLUP, button to GND
#define PIN_LED       2

// ---------------------------------------------------------------- identity
#define ROOM_ID     "room-A"
#define GATEWAY_ID  "gw-1"
#define NODE_ID     "node-A"   // devices/{NODE_ID}/health
#define NODE_NUM_ID 1          // NodePacket.node_id that belongs to this room

// ---------------------------------------------------------------- sampling / model
#define SAMPLE_MS        500
#define WINDOW_ROWS      20     // 20 x 500 ms = 10 s window (same as Flame's training)
#define CAM_STALE_MS     2000   // older CAM value -> person_count = -1
#define NODE_STALE_MS    2000   // older node value -> digital_do = 1 (no object)
// The model was trained with door = (digital_do == 0) || (analog_2_raw > 1000).
// We have no TCRT5000 gray sensor, so feed 0 -> door comes from the E18 only.
#define ANALOG_2_RAW_DEFAULT 0

// ---------------------------------------------------------------- cloud timing
#define UPLOAD_EVERY_WINDOWS   1          // 1 reading per 10 s window
#define HEALTH_MS              30000UL
#define CONTROL_POLL_MS        3000UL
#define TOKEN_REFRESH_MS       (55UL * 60UL * 1000UL)
#define NODE_OFFLINE_MS        60000UL
#define HTTP_TIMEOUT_MS        5000
#define TLS_HANDSHAKE_TIMEOUT_S 10
#define BACKOFF_MIN_MS         1000UL
#define BACKOFF_MAX_MS         30000UL
#define LOGIN_MIN_GAP_MS       30000UL    // never call signInWithPassword more often than this
#define CONTROL_MAX_AGE_MS     (5UL * 60UL * 1000UL)   // older control commands: mark done, don't run
#define WIFI_CONNECT_WAIT_MS   15000UL
#define NTP_SERVER             "pool.ntp.org"
#define NTP_VALID_AFTER        1700000000UL   // time() above this = synced

// ---------------------------------------------------------------- actuator / closed loop
#define MANUAL_OVERRIDE_MIN    10
#define LDR_ON_THRESHOLD       1500   // raw ADC (0..4095) above this = light is on (calibrate!)
#define LDR_INVERT             0      // 1 if your KY-018 wiring reads LOWER when brighter
#define LDR_SAMPLES            8
#define SERVO_PRESS_ANGLE      60
#define SERVO_REST_ANGLE       0
#define SERVO_MOVE_MS          350    // time to reach an angle
#define SERVO_MIN_GAP_MS       3000   // never press more often than this
#define LIGHT_VERIFY_WAIT_MS   2000   // wait after a press before reading the LDR
#define LIGHT_FAIL_COOLDOWN_MS 60000  // after light_fail, don't auto-retry the same state for 60 s
#define STOP_DEBOUNCE_LOW_MS   50     // STOP must read LOW continuously this long (and be released before the next press)
#define SERVO_STOP_REST_MS     300    // on STOP: move to rest, wait this long, then detach

// ---------------------------------------------------------------- DHT11
#define DHT_MIN_INTERVAL_MS 2000      // DHT11 must not be read faster than this

// ---------------------------------------------------------------- buffers / RTOS
#define RING_CAPACITY      200        // readings kept in RAM while offline
#define EVENT_QUEUE_LEN    24
#define ESPNOW_QUEUE_LEN   32
#define WDT_TIMEOUT_MS     60000
#define MAX_SENDERS        8          // seq trackers (node + cam ids)
#define SEQ_RESET_MAX      16         // seq below this after going backwards ...
#define SEQ_RESET_SILENT_MS 2000      // ... and sender silent longer than this = sender rebooted

// ---------------------------------------------------------------- secrets
#if __has_include("secrets.h")
#  include "secrets.h"
#else
#  error "src/secrets.h not found - copy src/secrets.example.h to src/secrets.h and fill it in"
#endif
