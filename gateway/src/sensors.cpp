#include "config.h"
#include "sensors.h"
#include <math.h>
#if !MOCK_SENSORS
#include <DHT.h>
static DHT s_dht(PIN_DHT11, DHT11);
#endif

static SemaphoreHandle_t s_mtx = nullptr;     // ADC + cached values are used by 2 tasks
static float s_temp = NAN, s_hum = NAN;
static uint32_t s_lastDhtMs = 0;

#if MOCK_SENSORS
static volatile bool s_mockLight = false;
void sensors_mock_press_switch() {
  s_mockLight = !s_mockLight;
  digitalWrite(PIN_LED, s_mockLight ? HIGH : LOW);   // on-board LED = the room light
}
bool sensors_mock_light_state() { return s_mockLight; }
#endif

void sensors_init() {
  s_mtx = xSemaphoreCreateMutex();
#if MOCK_SENSORS
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  randomSeed(esp_random());
#else
  s_dht.begin();
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_LDR, ADC_11db);   // full 0..3.3 V range
#endif
}

void sensors_poll() {
  const uint32_t now = millis();
  if (s_lastDhtMs != 0 && now - s_lastDhtMs < DHT_MIN_INTERVAL_MS) return;
  s_lastDhtMs = now;
#if MOCK_SENSORS
  float t = 25.0f + (float)random(-150, 150) / 100.0f;
  float h = 55.0f + (float)random(-500, 500) / 100.0f;
#else
  float h = s_dht.readHumidity();
  float t = s_dht.readTemperature();
#endif
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  if (!isnan(t) && !isnan(h)) { s_temp = t; s_hum = h; }   // keep last good value on read errors
  xSemaphoreGive(s_mtx);
}

float sensors_temp_c()   { xSemaphoreTake(s_mtx, portMAX_DELAY); float v = s_temp; xSemaphoreGive(s_mtx); return v; }
float sensors_humidity() { xSemaphoreTake(s_mtx, portMAX_DELAY); float v = s_hum;  xSemaphoreGive(s_mtx); return v; }

uint16_t sensors_read_ldr() {
#if MOCK_SENSORS
  int base = s_mockLight ? 2600 : 450;
  return (uint16_t)constrain(base + (int)random(-120, 120), 0, 4095);
#else
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  uint32_t sum = 0;
  for (int i = 0; i < LDR_SAMPLES; i++) sum += analogRead(PIN_LDR);
  xSemaphoreGive(s_mtx);
  uint16_t v = sum / LDR_SAMPLES;
  return LDR_INVERT ? (uint16_t)(4095 - v) : v;
#endif
}

bool sensors_light_on() { return sensors_read_ldr() > LDR_ON_THRESHOLD; }

// KY-037 gives an analog voltage that rises with sound pressure, but it is NOT calibrated and
// has no fixed reference, so this is a RELATIVE level on a dB-like 30..100 scale:
//   level = 30 + 20*log10(1 + raw/41)  (raw 0 -> 30, raw 4095 -> ~70) ... scaled to 30..100.
// Use it for "quiet vs talking" comparisons only; do not quote it as real dB SPL.
uint8_t sound_raw_to_db(uint16_t raw) {
  float rel = 20.0f * log10f(1.0f + (float)raw / 41.0f);   // 0 .. ~40
  float db = 30.0f + rel * (70.0f / 40.1f);                // 30 .. 100
  return (uint8_t)constrain((int)lroundf(db), 30, 100);
}
