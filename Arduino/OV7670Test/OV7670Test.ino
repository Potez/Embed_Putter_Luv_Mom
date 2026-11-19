// OV7670 (no FIFO) on ESP32 DevKit (WROOM, no PSRAM)
// Board: "ESP32 Dev Module". Uses esp_camera.h bundled with the ESP32 Arduino core.
#include "esp_camera.h"

// Avoids strapping pins (0, 2, 5, 12, 15) so the board still boots with the camera attached.
#define PIN_SIOD  21
#define PIN_SIOC  22
#define PIN_XCLK  32
#define PIN_PCLK  33
#define PIN_VSYNC 34
#define PIN_HREF  35
#define PIN_D0    36  // VP, input-only, OK for data
#define PIN_D1    39  // VN, input-only
#define PIN_D2    18
#define PIN_D3    19
#define PIN_D4    23
#define PIN_D5    25
#define PIN_D6    26
#define PIN_D7    27

void setup() {
  Serial.begin(115200);

  camera_config_t c = {};
  c.pin_pwdn = -1;   // tie PWDN to GND
  c.pin_reset = 14;  // RST wired to GPIO14 (DevKit has only one 3V3 pin)
  c.pin_xclk = PIN_XCLK;
  c.pin_sccb_sda = PIN_SIOD;
  c.pin_sccb_scl = PIN_SIOC;
  c.pin_d0 = PIN_D0; c.pin_d1 = PIN_D1; c.pin_d2 = PIN_D2; c.pin_d3 = PIN_D3;
  c.pin_d4 = PIN_D4; c.pin_d5 = PIN_D5; c.pin_d6 = PIN_D6; c.pin_d7 = PIN_D7;
  c.pin_vsync = PIN_VSYNC;
  c.pin_href = PIN_HREF;
  c.pin_pclk = PIN_PCLK;
  c.xclk_freq_hz = 10000000;          // ponytail: 10MHz is stable on jumper wires; try 20MHz with short wires
  c.ledc_timer = LEDC_TIMER_0;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.pixel_format = PIXFORMAT_RGB565;  // OV7670 has no JPEG
  c.frame_size = FRAMESIZE_QQVGA;     // 160x120x2 = 38KB, fits DRAM without PSRAM
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x (check SIOD/SIOC wiring + pull-ups)\n", err);
    while (true) delay(1000);
  }
  Serial.printf("Camera OK, sensor PID=0x%x\n", esp_camera_sensor_get()->id.PID);  // OV7670 = 0x76
}

void loop() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { Serial.println("Capture failed"); delay(1000); return; }

  // Average brightness from the green channel (RGB565, high byte first). Cover the lens -> value should drop.
  uint32_t sum = 0;
  size_t n = fb->len / 2;
  for (size_t i = 0; i < fb->len; i += 2) {
    uint16_t p = (fb->buf[i] << 8) | fb->buf[i + 1];
    sum += (p >> 5) & 0x3F;
  }
  Serial.printf("%ux%u len=%u brightness=%lu/63\n", fb->width, fb->height, fb->len, sum / n);

  esp_camera_fb_return(fb);
  delay(1000);
}
