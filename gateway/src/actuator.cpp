#include "actuator.h"
#include "config.h"
#include "sensors.h"
#include "firebase_client.h"
#include <esp_task_wdt.h>
#if !MOCK_SENSORS
#include <ESP32Servo.h>
static Servo s_servo;
#endif

static QueueHandle_t s_q = nullptr;
static TaskHandle_t s_task = nullptr;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;   // guards override + stop latch

static volatile bool s_abort = false;            // stop the current press NOW
static volatile bool s_stopLatched = false;      // STOP pressed: auto control disabled until pressed again
static volatile bool s_stopEventPending = false;
static uint32_t s_overrideUntil = 0;             // guarded by s_mux
static bool s_overrideActive = false;            // guarded by s_mux

// STOP button debounce state (ISR only flags a candidate; the task confirms it)
static volatile bool s_stopCandidate = false;    // set by ISR on a falling edge
static uint32_t s_stopLowSinceMs = 0;
static bool s_stopArmed = true;                  // must see the button released before the next press
static uint32_t s_stopHighSinceMs = 0;

static uint32_t s_lastPressMs = 0;
static bool s_havePressed = false;
static uint32_t s_failUntil = 0;                 // light_fail cooldown
static bool s_failWant = false;

// ---------------------------------------------------------------- STOP button ISR (E2)
// Only flags + wakes the actuator task. The task confirms LOW >= STOP_DEBOUNCE_LOW_MS.
static void IRAM_ATTR onStopIsr() {
  s_stopCandidate = true;
  BaseType_t woken = pdFALSE;
  if (s_task) vTaskNotifyGiveFromISR(s_task, &woken);
  portYIELD_FROM_ISR(woken);
}

// Called every <= 10 ms from the actuator task (also inside waits during a press).
static void pollStopButton() {
  const uint32_t now = millis();
  const bool low = digitalRead(PIN_STOP_BTN) == LOW;
  if (!low) {
    s_stopCandidate = false;
    s_stopLowSinceMs = 0;
    if (!s_stopHighSinceMs) s_stopHighSinceMs = now;
    if (!s_stopArmed && now - s_stopHighSinceMs >= STOP_DEBOUNCE_LOW_MS) s_stopArmed = true;  // released
    return;
  }
  s_stopHighSinceMs = 0;
  if (!s_stopCandidate && !s_stopLowSinceMs) return;        // no edge seen yet
  if (!s_stopLowSinceMs) s_stopLowSinceMs = now;
  if (s_stopArmed && now - s_stopLowSinceMs >= STOP_DEBOUNCE_LOW_MS) {   // confirmed press
    s_stopArmed = false;
    s_stopCandidate = false;
    s_abort = true;
    portENTER_CRITICAL(&s_mux);
    s_stopLatched = !s_stopLatched;
    portEXIT_CRITICAL(&s_mux);
    s_stopEventPending = true;
  }
}

void actuator_init() {
  s_q = xQueueCreate(6, sizeof(ActuatorCmd));
  pinMode(PIN_STOP_BTN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_STOP_BTN), onStopIsr, FALLING);
#if !MOCK_SENSORS
  ESP32PWM::allocateTimer(0);
  s_servo.setPeriodHertz(50);
#endif
}

bool actuator_stop_latched() { return s_stopLatched; }

bool actuator_override_active() {
  const uint32_t now = millis();
  portENTER_CRITICAL(&s_mux);
  if (s_overrideActive && (int32_t)(now - s_overrideUntil) >= 0) s_overrideActive = false;
  const bool a = s_overrideActive;
  portEXIT_CRITICAL(&s_mux);
  return a;
}

void actuator_request_auto(bool want_on, uint32_t t_detect_ms) {
  ActuatorCmd c{};
  c.source = SRC_AUTO; c.action = ACT_SET_LIGHT; c.want_on = want_on; c.t_detect_ms = t_detect_ms;
  xQueueSend(s_q, &c, 0);   // never block the sampler; a full queue just skips one window
}

bool actuator_request_manual(CtrlAction action, bool want_on, const char* by) {
  ActuatorCmd c{};
  c.source = SRC_MANUAL; c.action = action; c.want_on = want_on;
  strlcpy(c.by, by ? by : "", sizeof c.by);
  if (action == ACT_SERVO_STOP) {                // takes effect immediately, queue only logs it
    s_abort = true;
    portENTER_CRITICAL(&s_mux);
    s_stopLatched = true;
    portEXIT_CRITICAL(&s_mux);
  } else if (xQueueSend(s_q, &c, pdMS_TO_TICKS(100)) != pdTRUE) {
    return false;                                // caller retries on the next control poll
  }
  const uint32_t until = millis() + MANUAL_OVERRIDE_MIN * 60UL * 1000UL;
  portENTER_CRITICAL(&s_mux);
  s_overrideUntil = until;
  s_overrideActive = true;
  portEXIT_CRITICAL(&s_mux);
  if (s_task) xTaskNotifyGive(s_task);
  return true;
}

// ---------------------------------------------------------------- helpers
// Sleep in 10 ms slices while watching the STOP button; returns false if aborted.
static bool waitAbortable(uint32_t ms) {
  const uint32_t start = millis();
  while (millis() - start < ms) {
    pollStopButton();
    if (s_abort) return false;
    esp_task_wdt_reset();
    ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10));
  }
  pollStopButton();
  return !s_abort;
}

// Abort path: go back to the rest angle first (so the arm does not stay pressing the switch),
// wait ~300 ms, then detach.
static void servoToRestAndRelease() {
#if MOCK_SENSORS
  Serial.println("[act] (mock) servo -> rest, detach");
#else
  if (!s_servo.attached()) s_servo.attach(PIN_SERVO, 500, 2400);
  s_servo.write(SERVO_REST_ANGLE);
  vTaskDelay(pdMS_TO_TICKS(SERVO_STOP_REST_MS));
  esp_task_wdt_reset();
  s_servo.detach();
#endif
}

// One press of the wall switch. Servo is attached only during the press.
static bool pressSwitch() {
  if (s_havePressed && millis() - s_lastPressMs < SERVO_MIN_GAP_MS) {
    if (!waitAbortable(SERVO_MIN_GAP_MS - (millis() - s_lastPressMs))) return false;
  }
  s_lastPressMs = millis();
  s_havePressed = true;
#if MOCK_SENSORS
  Serial.println("[act] (mock) servo press");
  if (!waitAbortable(SERVO_MOVE_MS)) return false;
  sensors_mock_press_switch();
  return waitAbortable(SERVO_MOVE_MS);
#else
  s_servo.attach(PIN_SERVO, 500, 2400);
  s_servo.write(SERVO_PRESS_ANGLE);
  if (!waitAbortable(SERVO_MOVE_MS)) return false;          // caller moves to rest + detaches
  s_servo.write(SERVO_REST_ANGLE);
  if (!waitAbortable(SERVO_MOVE_MS)) return false;
  s_servo.detach();
  return true;
#endif
}

// Press until the LDR shows the wanted state: press -> 2 s -> check -> press again -> 2 s -> fail.
static void ensureLight(const ActuatorCmd& c) {
  const bool want = c.want_on;
  if (sensors_light_on() == want) return;
  if (c.source == SRC_AUTO && s_failWant == want && (int32_t)(millis() - s_failUntil) < 0) return;

  s_abort = false;
  for (int attempt = 1; attempt <= 2; attempt++) {
    if (c.source == SRC_AUTO && (s_stopLatched || actuator_override_active())) return;
    if (!pressSwitch() || !waitAbortable(LIGHT_VERIFY_WAIT_MS)) {
      servoToRestAndRelease();
      Serial.println("[act] press aborted (STOP)");
      return;
    }
    if (sensors_light_on() == want) {
      int32_t lat = -1;
      if (want && c.t_detect_ms) lat = (int32_t)(millis() - c.t_detect_ms);
      char d[32];
      snprintf(d, sizeof d, "%s, attempt %d", c.source == SRC_AUTO ? "auto" : "manual", attempt);
      events_post(want ? EVT_LIGHT_ON : EVT_LIGHT_OFF, d, c.source == SRC_MANUAL ? c.by : nullptr, lat);
      Serial.printf("[act] light %s confirmed by LDR (latency %ld ms)\n", want ? "ON" : "OFF", (long)lat);
      return;
    }
  }
  char d[40];
  snprintf(d, sizeof d, "want=%s ldr=%u after 2 presses", want ? "on" : "off", sensors_read_ldr());
  events_post(EVT_LIGHT_FAIL, d, c.source == SRC_MANUAL ? c.by : nullptr);
  Serial.printf("[act] LIGHT FAIL: %s\n", d);
  s_failWant = want;
  s_failUntil = millis() + LIGHT_FAIL_COOLDOWN_MS;
}

// ---------------------------------------------------------------- task
void actuatorTask(void*) {
  s_task = xTaskGetCurrentTaskHandle();
  esp_task_wdt_add(nullptr);
  ActuatorCmd c;
  for (;;) {
    esp_task_wdt_reset();
    pollStopButton();
    if (s_stopEventPending) {
      s_stopEventPending = false;
      if (s_stopLatched) servoToRestAndRelease();
      Serial.printf("[act] STOP button -> auto %s\n", s_stopLatched ? "DISABLED" : "enabled");
      events_post(EVT_MANUAL, s_stopLatched ? "stop: auto disabled" : "stop released: auto enabled",
                  "stop_button");
    }
    // short timeout so the STOP button is polled every 10 ms
    if (xQueueReceive(s_q, &c, pdMS_TO_TICKS(10)) != pdTRUE) continue;

    if (c.source == SRC_MANUAL) {
      ensureLight(c);
    } else {
      if (s_stopLatched || actuator_override_active()) continue;
      ensureLight(c);
    }
  }
}
