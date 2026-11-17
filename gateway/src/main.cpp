// RoomSense gateway — ESP32-WROOM (esp32dev), Jeen.
//
// Tasks (E1, communicate only through queues / mutexes, all registered with the task watchdog):
//   espnowTask   (core 1, prio 4)  ESP-NOW rx queue -> seq check -> ACK -> latest state
//   sensorTask   (core 1, prio 3)  500 ms sampler -> RoomSensePredictor -> closed loop -> Reading
//   actuatorTask (core 1, prio 2)  servo press + LDR verification, STOP button (ISR)
//   cloudTask    (core 0, prio 1)  Firebase auth, readings, events, health, control, backfill
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_mac.h>
#include <esp_task_wdt.h>
#include "config.h"
#include "health.h"
#include "sensors.h"
#include "actuator.h"
#include "ring_buffer.h"
#include "espnow_rx.h"
#include "sampler.h"
#include "predictor_glue.h"
#include "firebase_client.h"

static void setupWatchdog() {
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = WDT_TIMEOUT_MS;
  cfg.idle_core_mask = 0;
  cfg.trigger_panic = true;          // hung task -> reboot (counted in reboots, reason task_watchdog)
  if (esp_task_wdt_reconfigure(&cfg) != ESP_OK) esp_task_wdt_init(&cfg);
}

static void printBanner() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  uint8_t ch = 0; wifi_second_chan_t sc;
  esp_wifi_get_channel(&ch, &sc);
  Serial.println();
  Serial.println("==================================================================");
  Serial.printf ("  RoomSense GATEWAY  %s / %s   MOCK_SENSORS=%d\n", GATEWAY_ID, ROOM_ID, MOCK_SENSORS);
  Serial.printf ("  Gateway MAC (give to Pat & Flame): %02X:%02X:%02X:%02X:%02X:%02X\n",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.printf ("  Wi-Fi channel (ESP-NOW senders MUST use this): %u\n", ch);
  Serial.printf ("  Wi-Fi: %s  ip=%s  rssi=%d\n", WiFi.status() == WL_CONNECTED ? "connected" : "NOT connected",
                 WiFi.localIP().toString().c_str(), WiFi.RSSI());
  Serial.printf ("  Model: %s\n", predictor_name());
  Serial.println("==================================================================");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  setupWatchdog();
  health_init();
  ring_init();
  sensors_init();
  actuator_init();
  sampler_init();
  cloud_init();

  // Wi-Fi first: ESP-NOW must run on the router's channel
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);              // modem sleep makes ESP-NOW miss packets
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[wifi] connecting to %s", WIFI_SSID);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_CONNECT_WAIT_MS) { delay(250); Serial.print('.'); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " ok" : " TIMEOUT (will keep retrying in background)");

  configTime(0, 0, NTP_SERVER);      // UTC; ts = Unix seconds
  espnow_init();
  printBanner();

  xTaskCreatePinnedToCore(espnowTask,   "espnow",   4096,  nullptr, 4, nullptr, 1);
  xTaskCreatePinnedToCore(sensorTask,   "sensor",   6144,  nullptr, 3, nullptr, 1);
  xTaskCreatePinnedToCore(actuatorTask, "actuator", 4096,  nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(cloudTask,    "cloud",    12288, nullptr, 1, nullptr, 0);
}

void loop() {
  vTaskDelete(nullptr);              // everything runs in the tasks above
}
