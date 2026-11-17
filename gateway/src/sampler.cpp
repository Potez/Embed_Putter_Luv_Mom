#include "sampler.h"
#include "config.h"
#include "espnow_rx.h"
#include "predictor_glue.h"
#include "sensors.h"
#include "actuator.h"
#include "ring_buffer.h"
#include "firebase_client.h"
#include <esp_task_wdt.h>
#include <math.h>

// window aggregates (reset every window)
static bool s_pirAny = false, s_flameAny = false;
static uint16_t s_soundMax = 0;
static bool s_prevFlame = false;
// latency "person detected -> light confirmed"
static bool s_roomEmpty = true;
static uint32_t s_tDetectMs = 0;
static uint32_t s_windows = 0;
static bool s_lastPower = false;   // model output of the last closed window

void sampler_init() { predictor_init(); }

static Reading buildReading(const RxSnapshot& s, bool powerOn) {
  Reading r{};
  r.ts = cloud_now();
  r.node_valid = s.node_fresh;
  r.node_ts = s.node.node_ts;
  r.node_seq = s.node.node_seq;
  r.people_ai = (s.cam_fresh && s.person_count >= 0) ? s.person_count : -1;
  r.ai_conf = r.people_ai >= 0 ? min<uint8_t>(s.ai_conf, 100) : 255;
  r.people_ir = s.node.people_ir;
  r.pir = s_pirAny;
  r.ldr = sensors_read_ldr();
  r.light_on = r.ldr > LDR_ON_THRESHOLD;     // real state, not the commanded one
  r.temp_c = sensors_temp_c();
  r.humidity = sensors_humidity();
  r.sound_db = sound_raw_to_db(s_soundMax);
  r.flame = s_flameAny || s.flame_now;
  r.power_on = powerOn;
  r.buffered = false;
  return r;
}

static uint32_t s_lastPushTs = 0;
static bool s_lastPushFlame = false;

// flame + window in the same second -> one reading, flame=true wins. ring_push() merges while the
// first one is still queued; this also covers the case where it was already uploaded (same key).
static void pushReading(Reading r, const char* why) {
  if (!r.ts) { Serial.printf("[sampler] %s reading skipped: NTP not synced yet\n", why); return; }
  if (r.ts == s_lastPushTs && s_lastPushFlame) r.flame = true;
  s_lastPushFlame = (r.ts == s_lastPushTs ? s_lastPushFlame : false) || r.flame;
  s_lastPushTs = r.ts;
  if (!ring_push(r)) Serial.println("[sampler] ring buffer full - oldest reading dropped");
}

void sensorTask(void*) {
  esp_task_wdt_add(nullptr);
  TickType_t last = xTaskGetTickCount();
  RxSnapshot snap;
  WindowResult res;
  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(SAMPLE_MS));
    esp_task_wdt_reset();

    espnow_take_sample(&snap);
    sensors_poll();                                   // DHT11 internally limited to every 2 s

    // ---- raw row, exactly like the training dataset
    const int16_t person_count = snap.cam_fresh ? snap.person_count : -1;
    const uint8_t digital_do = snap.door_seen ? 0 : 1;  // stale node -> 1 (no object)
    const uint16_t analog_2_raw = ANALOG_2_RAW_DEFAULT;

    // ---- window aggregates for the Reading (NOT model inputs)
    s_pirAny |= snap.pir_seen;
    s_flameAny |= snap.flame_now;
    if (snap.sound_max > s_soundMax) s_soundMax = snap.sound_max;

    // ---- latency start: first row with people after the room was empty
    if (person_count > 0 && s_roomEmpty && !s_tDetectMs) s_tDetectMs = millis();

    // ---- flame: hard rule + immediate upload (do not wait for the window)
    if (snap.flame_now && !s_prevFlame) {
      Serial.println("[sampler] !!! FLAME detected -> immediate reading, light auto blocked");
      pushReading(buildReading(snap, s_lastPower), "flame");
      actuator_request_auto(false, 0);   // want_light = ... && !alarm
    }
    s_prevFlame = snap.flame_now;

    if (!predictor_add_row(person_count, digital_do, analog_2_raw, &res)) continue;

    // ================= window complete (every 10 s) =================
    const bool alarm = s_flameAny || snap.flame_now;
    const bool stop = actuator_stop_latched();
    const bool override_ = actuator_override_active();
    const bool wantLight = res.power_on && !alarm && !stop && !override_;
    const WindowFeatures& f = res.f;
    s_lastPower = res.power_on;
    Serial.printf("[window %lu] cam_max=%.0f cam_mean=%.2f miss=%.2f door_any=%.0f ev=%.0f "
                  "roll3=%.2f roll6=%.0f d2m=%.0f d5m=%.0f since_cam=%.0f since_door=%.0f "
                  "-> power_on=%d alarm=%d stop=%d override=%d => want_light=%d (%s)\n",
                  (unsigned long)s_windows, f.cam_max, f.cam_mean, f.cam_missing_frac, f.door_any,
                  f.door_events, f.cam_mean_roll3, f.cam_max_roll6, f.door_recent_2m, f.door_events_5m,
                  f.since_cam_s, f.since_door_s, res.power_on, alarm, stop, override_, wantLight,
                  res.from_flame_model ? "model" : "fallback");

    if (!stop && !override_) actuator_request_auto(wantLight, wantLight ? s_tDetectMs : 0);

    // latency bookkeeping: a window with nobody seen = empty room -> next detection restarts the clock
    const bool nobody = isnan(f.cam_max) || f.cam_max <= 0;
    if (nobody) { s_roomEmpty = true; s_tDetectMs = 0; }
    else if (sensors_light_on()) { s_roomEmpty = false; s_tDetectMs = 0; }   // light confirmed / already on

    if (s_windows % UPLOAD_EVERY_WINDOWS == 0) pushReading(buildReading(snap, res.power_on), "window");
    s_windows++;
    s_pirAny = false; s_flameAny = false; s_soundMax = 0;
  }
}
