// RoomSense mock sender — simulates Pat's node (2 Hz) and Flame's ESP32-CAM (~3 Hz) over ESP-NOW,
// using the shared packets.h, with ACK wait 300 ms + up to 3 retries (same seq).
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_mac.h>
#include <time.h>
#include "packets.h"
#include "config.h"

static uint8_t s_gw[6] = GATEWAY_MAC;
static TaskHandle_t s_nodeTask = nullptr, s_camTask = nullptr;
static volatile uint32_t s_waitSeq[4] = {0, 0, 0, 0};   // index = PacketType

struct Stats { uint32_t sent = 0, ok = 0, fail = 0, retries = 0; };
static Stats s_node, s_cam;

// ---------------------------------------------------------------- simulated room
// Occupancy script (seconds, people). Repeats forever: enter -> grow -> shrink -> leave.
struct Phase { uint16_t secs; uint8_t people; };
static const Phase SCRIPT[] = { {40, 0}, {30, 1}, {30, 2}, {40, 4}, {20, 3}, {20, 1}, {60, 0} };
static const int NPH = sizeof(SCRIPT) / sizeof(SCRIPT[0]);

static uint8_t occupancyNow() {
  uint32_t total = 0;
  for (auto& p : SCRIPT) total += p.secs;
  uint32_t t = (millis() / 1000) % total;
  for (auto& p : SCRIPT) { if (t < p.secs) return p.people; t -= p.secs; }
  return 0;
}

static uint32_t nowTs() {
  time_t t = time(nullptr);
  return t > 1700000000 ? (uint32_t)t : 0;
}

// ---------------------------------------------------------------- ESP-NOW
static void onRecv(const esp_now_recv_info_t*, const uint8_t* data, int len) {
  if (len != sizeof(AckPacket) || data[0] != PKT_ACK) return;
  AckPacket a; memcpy(&a, data, sizeof a);
  if (a.src_type == PKT_NODE && a.seq == s_waitSeq[PKT_NODE] && s_nodeTask) xTaskNotifyGive(s_nodeTask);
  if (a.src_type == PKT_CAM  && a.seq == s_waitSeq[PKT_CAM]  && s_camTask)  xTaskNotifyGive(s_camTask);
}

// Send, wait ESPNOW_ACK_TIMEOUT_MS for the matching ACK, retry up to ESPNOW_MAX_RETRIES times.
static bool sendReliable(uint8_t type, const void* pkt, size_t len, uint32_t seq, Stats& st) {
  st.sent++;
  s_waitSeq[type] = seq;
  for (int attempt = 0; attempt <= ESPNOW_MAX_RETRIES; attempt++) {
    ulTaskNotifyTake(pdTRUE, 0);                 // clear stale notifications
    esp_now_send(s_gw, (const uint8_t*)pkt, len);
    if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(ESPNOW_ACK_TIMEOUT_MS))) {
      st.ok++; st.retries += attempt;
      return true;
    }
  }
  st.fail++;
  return false;
}

// ---------------------------------------------------------------- node (Pat) simulation
static void nodeTask(void*) {
  s_nodeTask = xTaskGetCurrentTaskHandle();
  uint32_t seq = 0;
  int16_t lastOcc = 0;
  int doorPulses = 0;
  TickType_t last = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(NODE_PERIOD_MS));
    const uint8_t occ = occupancyNow();
    if (occ != lastOcc) { doorPulses += abs(occ - lastOcc); lastOcc = occ; }  // 1 door pass per person

    NodePacket p{};
    p.packet_type = PKT_NODE;
    p.node_id = MOCK_NODE_ID;
    p.node_seq = ++seq;
    p.node_ts = nowTs();
    p.door_do = 1;
    if (doorPulses > 0) { p.door_do = 0; doorPulses--; }                      // active-low, latched
    else if (random(100) < 1) p.door_do = 0;                                  // rare glitch
    p.pir = occ > 0 ? (random(100) < 70) : (random(100) < 2);
    p.people_ir = occ;
    p.sound_raw = occ > 0 ? constrain(800 + occ * 300 + (int)random(-400, 400), 0, 4095)
                          : constrain(100 + (int)random(-80, 80), 0, 4095);
    const uint32_t ph = millis() % FLAME_EVERY_MS;
    p.flame_do = (ph >= FLAME_EVERY_MS - FLAME_HOLD_MS) ? 0 : 1;              // active-low
    sendReliable(PKT_NODE, &p, sizeof p, p.node_seq, s_node);
  }
}

// ---------------------------------------------------------------- CAM (Flame) simulation
static void camTask(void*) {
  s_camTask = xTaskGetCurrentTaskHandle();
  uint32_t seq = 0;
  uint32_t blindUntil = 0;
  TickType_t last = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(CAM_PERIOD_MS));
    const uint8_t occ = occupancyNow();
    CamPacket p{};
    p.packet_type = PKT_CAM;
    p.cam_id = MOCK_CAM_ID;
    p.seq = ++seq;
    p.ts = nowTs();
    if (random(1000) < 4) blindUntil = millis() + 4000;                       // ~every 80 s: 4 s blind
    if (millis() < blindUntil || random(100) < 4) {
      p.person_count = -1; p.ai_conf = 0;                                     // could not count
    } else {
      int c = occ;
      if (random(100) < 5) c += random(2) ? 1 : -1;                           // counting noise
      p.person_count = (int8_t)max(0, c);
      p.ai_conf = (uint8_t)random(70, 98);
    }
    sendReliable(PKT_CAM, &p, sizeof p, p.seq, s_cam);
  }
}

static void printStats(const char* name, const Stats& s) {
  Serial.printf("  %-4s sent=%lu ok=%lu fail=%lu retries=%lu  delivery=%.1f%%\n", name,
                (unsigned long)s.sent, (unsigned long)s.ok, (unsigned long)s.fail,
                (unsigned long)s.retries, s.sent ? 100.0 * s.ok / s.sent : 100.0);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  randomSeed(esp_random());
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  if (strlen(MOCK_WIFI_SSID)) {
    WiFi.begin(MOCK_WIFI_SSID, MOCK_WIFI_PASS);
    Serial.printf("[mock] joining %s for channel + NTP", MOCK_WIFI_SSID);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print('.'); }
    Serial.println(WiFi.status() == WL_CONNECTED ? " ok" : " failed");
    configTime(0, 0, "pool.ntp.org");
  } else {
    WiFi.disconnect();
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  }
  if (esp_now_init() != ESP_OK) { Serial.println("[mock] esp_now_init FAILED"); return; }
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, s_gw, 6);
  peer.channel = 0;                    // current channel
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  uint8_t mac[6]; esp_read_mac(mac, ESP_MAC_WIFI_STA);
  uint8_t ch; wifi_second_chan_t sc; esp_wifi_get_channel(&ch, &sc);
  Serial.printf("[mock] my MAC %02X:%02X:%02X:%02X:%02X:%02X  channel %u  -> gateway %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], ch,
                s_gw[0], s_gw[1], s_gw[2], s_gw[3], s_gw[4], s_gw[5]);

  xTaskCreatePinnedToCore(nodeTask, "node", 4096, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(camTask,  "cam",  4096, nullptr, 2, nullptr, 1);
}

void loop() {
  delay(STATS_PERIOD_MS);
  Serial.printf("[mock] t=%lus occupancy=%u flame=%s ts=%lu\n", millis() / 1000, occupancyNow(),
                (millis() % FLAME_EVERY_MS) >= FLAME_EVERY_MS - FLAME_HOLD_MS ? "YES" : "no",
                (unsigned long)nowTs());
  printStats("node", s_node);
  printStats("cam", s_cam);
}
