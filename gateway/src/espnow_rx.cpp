#include "espnow_rx.h"
#include "config.h"
#include "firebase_client.h"   // events_post()
#include <WiFi.h>
#include <esp_now.h>
#include <esp_task_wdt.h>
#include <string.h>

struct RxItem {
  uint8_t  mac[6];
  uint8_t  len;
  int8_t   rssi;
  uint32_t rx_ms;
  uint8_t  data[32];
};

static QueueHandle_t s_q = nullptr;
static SemaphoreHandle_t s_mtx = nullptr;     // guards s_stats + s_state
static SenderStats s_stats[MAX_SENDERS];
static uint32_t s_overflows = 0;   // only written by the Wi-Fi task callback

static struct {
  CamPacket  cam;   uint32_t cam_ms = 0;  bool cam_ever = false;
  NodePacket node;  uint32_t node_ms = 0; bool node_ever = false;
  bool door_latch = false, pir_latch = false;
  uint16_t sound_max = 0;
  int16_t last_people_ir = -1;
} s_state;

// ---------------------------------------------------------------- ISR-context callback: copy only
static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len <= 0 || len > (int)sizeof(RxItem::data)) return;
  RxItem it;
  memcpy(it.mac, info->src_addr, 6);
  it.len = (uint8_t)len;
  it.rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
  it.rx_ms = millis();
  memcpy(it.data, data, len);
  if (xQueueSend(s_q, &it, 0) != pdTRUE) s_overflows++;
}

bool espnow_init() {
  s_q = xQueueCreate(ESPNOW_QUEUE_LEN, sizeof(RxItem));
  s_mtx = xSemaphoreCreateMutex();
  if (esp_now_init() != ESP_OK) {
    Serial.println("[espnow] init FAILED");
    return false;
  }
  esp_now_register_recv_cb(onRecv);
  Serial.println("[espnow] ready");
  return true;
}

// ---------------------------------------------------------------- helpers
static void ensurePeer(const uint8_t* mac) {
  if (esp_now_is_peer_exist(mac)) return;
  esp_now_peer_info_t p = {};
  memcpy(p.peer_addr, mac, 6);
  p.channel = 0;              // 0 = current Wi-Fi channel (follows the router)
  p.ifidx = WIFI_IF_STA;
  p.encrypt = false;
  esp_err_t e = esp_now_add_peer(&p);
  Serial.printf("[espnow] add peer %02X:%02X:%02X:%02X:%02X:%02X -> %s\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], e == ESP_OK ? "ok" : esp_err_to_name(e));
}

static void sendAck(const uint8_t* mac, uint8_t type, uint8_t id, uint32_t seq) {
  ensurePeer(mac);
  AckPacket a{PKT_ACK, type, id, seq};
  esp_now_send(mac, (const uint8_t*)&a, sizeof(a));
}

static SenderStats* statsFor(uint8_t type, uint8_t id, const uint8_t* mac) {
  SenderStats* freeSlot = nullptr;
  for (auto& s : s_stats) {
    if (s.used && s.type == type && s.id == id) return &s;
    if (!s.used && !freeSlot) freeSlot = &s;
  }
  if (!freeSlot) return nullptr;
  memset(freeSlot, 0, sizeof(*freeSlot));
  freeSlot->used = true; freeSlot->type = type; freeSlot->id = id;
  memcpy(freeSlot->mac, mac, 6);
  return freeSlot;
}

// Returns true if the packet is NEW (should be processed); false for duplicates.
// Handles: retries (same seq), gaps (lost), and seq restart after the sender reboots.
static bool trackSeq(SenderStats* st, uint32_t seq, uint32_t rx_ms, int8_t rssi, const uint8_t* mac) {
  const uint32_t silentMs = rx_ms - st->last_rx_ms;   // gap since the previous packet
  st->last_rx_ms = rx_ms;
  st->rssi = rssi;
  memcpy(st->mac, mac, 6);
  if (st->rx == 0) {                       // first packet ever from this sender
    st->rx = 1; st->last_seq = seq; return true;
  }
  if (seq == st->last_seq) { st->dup++; return false; }
  if (seq > st->last_seq) {
    st->lost += seq - st->last_seq - 1;
    st->last_seq = seq; st->rx++; return true;
  }
  // seq went backwards. Count a reboot ONLY if seq is small AND the sender was silent > 2 s
  // (a reboot takes seconds); anything else is a late retry/duplicate.
  if (seq < SEQ_RESET_MAX && silentMs > SEQ_RESET_SILENT_MS) {
    st->resets++; st->last_seq = seq; st->rx++; return true;
  }
  st->dup++;
  return false;
}

// ---------------------------------------------------------------- task
void espnowTask(void*) {
  esp_task_wdt_add(nullptr);
  RxItem it;
  for (;;) {
    esp_task_wdt_reset();
    if (xQueueReceive(s_q, &it, pdMS_TO_TICKS(1000)) != pdTRUE) continue;

    const uint8_t type = it.data[0];
    if (type == PKT_NODE && it.len == sizeof(NodePacket)) {
      NodePacket p; memcpy(&p, it.data, sizeof(p));
      xSemaphoreTake(s_mtx, portMAX_DELAY);
      SenderStats* st = statsFor(PKT_NODE, p.node_id, it.mac);
      bool fresh = st && trackSeq(st, p.node_seq, it.rx_ms, it.rssi, it.mac);
      int16_t prevIr = s_state.last_people_ir;
      const bool mine = p.node_id == NODE_NUM_ID;   // other rooms' nodes are ACKed but not used
      if (fresh && mine) {
        s_state.node = p; s_state.node_ms = it.rx_ms; s_state.node_ever = true;
        if (p.door_do == 0) s_state.door_latch = true;
        if (p.pir) s_state.pir_latch = true;
        if (p.sound_raw > s_state.sound_max) s_state.sound_max = p.sound_raw;
        if (p.people_ir >= 0) s_state.last_people_ir = p.people_ir;
      }
      xSemaphoreGive(s_mtx);
      sendAck(it.mac, PKT_NODE, p.node_id, p.node_seq);   // ACK duplicates too (lost-ACK case)

      // enter / exit events from the door counter
      if (fresh && mine && p.people_ir >= 0 && prevIr >= 0 && p.people_ir != prevIr) {
        char d[24];
        snprintf(d, sizeof d, "%d->%d", prevIr, p.people_ir);
        events_post(p.people_ir > prevIr ? EVT_ENTER : EVT_EXIT, d);
      }
    } else if (type == PKT_CAM && it.len == sizeof(CamPacket)) {
      CamPacket p; memcpy(&p, it.data, sizeof(p));
      xSemaphoreTake(s_mtx, portMAX_DELAY);
      SenderStats* st = statsFor(PKT_CAM, p.cam_id, it.mac);
      bool fresh = st && trackSeq(st, p.seq, it.rx_ms, it.rssi, it.mac);
      if (fresh) { s_state.cam = p; s_state.cam_ms = it.rx_ms; s_state.cam_ever = true; }
      xSemaphoreGive(s_mtx);
      sendAck(it.mac, PKT_CAM, p.cam_id, p.seq);
    } else {
      Serial.printf("[espnow] unknown packet type=%u len=%u\n", type, it.len);
    }
  }
}

void espnow_take_sample(RxSnapshot* o) {
  const uint32_t now = millis();
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  o->cam_fresh = s_state.cam_ever && (now - s_state.cam_ms) <= CAM_STALE_MS;
  o->person_count = o->cam_fresh ? s_state.cam.person_count : -1;
  o->ai_conf = o->cam_fresh ? s_state.cam.ai_conf : 0;
  o->node_ever = s_state.node_ever;
  o->node = s_state.node;
  o->node_fresh = s_state.node_ever && (now - s_state.node_ms) <= NODE_STALE_MS;
  o->door_seen = o->node_fresh && s_state.door_latch;
  o->pir_seen = o->node_fresh && s_state.pir_latch;
  o->flame_now = o->node_fresh && s_state.node.flame_do == 0;
  o->sound_max = s_state.sound_max;
  s_state.door_latch = false;
  s_state.pir_latch = false;
  s_state.sound_max = 0;
  xSemaphoreGive(s_mtx);
}

bool espnow_get_stats(uint8_t type, uint8_t id, SenderStats* out) {
  bool ok = false;
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  for (auto& s : s_stats)
    if (s.used && s.type == type && (id == 0 || s.id == id)) { *out = s; ok = true; break; }
  xSemaphoreGive(s_mtx);
  return ok;
}

uint32_t espnow_queue_overflows() { return s_overflows; }
