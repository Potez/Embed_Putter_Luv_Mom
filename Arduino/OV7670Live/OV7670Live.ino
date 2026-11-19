// OV7670 live stream + always-on person detection. Board: ESP32 Dev Module, core esp32 2.0.17.
// Core 1 (loop): streams frames over USB when the PC sends 's'.
// Core 1 (detectTask): continuously runs PersonDetector on the newest frame (~5 s each).
#include "esp_camera.h"
#include "esp_log.h"
#include "PersonDetector.h"

PersonDetector detector(0.6f);
static uint8_t* detBuf = nullptr;            // frame copy owned by the detector task
static size_t detLen = 0;
static volatile bool detBusy = false;
static SemaphoreHandle_t detGo;
static volatile Detection lastDet = {0, 0, false, 0};
static volatile uint32_t detCount = 0;

void detectTask(void*) {
  for (;;) {
    xSemaphoreTake(detGo, portMAX_DELAY);
    Detection d = detector.detect(detBuf, detLen);
    lastDet.person = d.person; lastDet.noPerson = d.noPerson; lastDet.isPerson = d.isPerson; lastDet.ms = d.ms;
    detCount++;
    detBusy = false;
  }
}

void setup() {
  Serial.begin(921600);
  esp_log_level_set("*", ESP_LOG_NONE);
  // Allocate biggest blocks first, before the heap fragments: model arena (81KB), frame copy (38KB), then camera.
  bool ok = detector.begin();
  detBuf = (uint8_t*)malloc(160 * 120 * 2);
  camera_config_t c = {};
  c.pin_pwdn = -1; c.pin_reset = 14; c.pin_xclk = 32;
  c.pin_sccb_sda = 21; c.pin_sccb_scl = 22;
  c.pin_d0 = 36; c.pin_d1 = 39; c.pin_d2 = 18; c.pin_d3 = 19;
  c.pin_d4 = 23; c.pin_d5 = 25; c.pin_d6 = 26; c.pin_d7 = 27;
  c.pin_vsync = 34; c.pin_href = 35; c.pin_pclk = 33;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_0; c.ledc_channel = LEDC_CHANNEL_0;
  c.pixel_format = PIXFORMAT_RGB565; c.frame_size = FRAMESIZE_QQVGA;
  c.fb_count = 1; c.fb_location = CAMERA_FB_IN_DRAM; c.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t err = esp_camera_init(&c);
  detGo = xSemaphoreCreateBinary();
  xTaskCreatePinnedToCore(detectTask, "detect", 8192, nullptr, 1, nullptr, 1);  // core 1, same priority as loop(): they time-slice, camera driver keeps core 0
  Serial.printf("\nINIT camera=%s detector=%s heap=%u detBuf=%s\n", err == ESP_OK ? "OK" : "FAIL", ok ? "OK" : "FAIL", ESP.getFreeHeap(), detBuf ? "OK" : "FAIL");
}

void loop() {
  int cmd = Serial.read();
  bool wantFrame = (cmd == 's');
  if (!wantFrame && detBusy) { delay(2); return; }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { delay(10); return; }

  if (!detBusy && detBuf && fb->len <= 160 * 120 * 2) {   // hand newest frame to the detector
    memcpy(detBuf, fb->buf, fb->len); detLen = fb->len;
    detBusy = true; xSemaphoreGive(detGo);
  }
  if (wantFrame) {
    Serial.printf("FRAME %u %u %u\n", fb->len, fb->width, fb->height);
    Serial.write(fb->buf, fb->len);
    Serial.printf("\nDET %.3f %.3f %d %u %u\n", lastDet.person, lastDet.noPerson, lastDet.isPerson ? 1 : 0, lastDet.ms, detCount);
  }
  esp_camera_fb_return(fb);
}
