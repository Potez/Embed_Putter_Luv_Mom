// espnow_rx.h — ESP-NOW receiver: queue from callback, per-sender seq tracking, ACK, auto-peer.
#pragma once
#include <Arduino.h>
#include "packets.h"

struct SenderStats {
  bool     used;
  uint8_t  type;        // PKT_NODE / PKT_CAM
  uint8_t  id;
  uint8_t  mac[6];
  uint32_t last_seq;
  uint32_t rx;          // unique packets accepted
  uint32_t lost;        // gaps in seq
  uint32_t dup;         // retries / duplicates (re-ACKed, not processed)
  uint32_t resets;      // seq restarted (sender rebooted)
  uint32_t last_rx_ms;  // millis() of last packet
  int8_t   rssi;
};

// What the sampler sees every 500 ms. Latches are cleared by espnow_take_sample().
struct RxSnapshot {
  bool       cam_fresh;      // CAM packet within CAM_STALE_MS
  int8_t     person_count;   // valid if cam_fresh
  uint8_t    ai_conf;        // 0..100, valid if cam_fresh
  bool       node_fresh;     // node packet within NODE_STALE_MS
  NodePacket node;           // latest node packet (valid if node_ever)
  bool       node_ever;
  bool       door_seen;      // some packet since the last sample had door_do == 0
  bool       pir_seen;       // some packet since the last sample had pir == 1
  bool       flame_now;      // latest fresh node packet says flame (flame_do == 0)
  uint16_t   sound_max;      // max sound_raw since the last sample
};

bool espnow_init();                         // call after WiFi.mode(WIFI_STA) + connect
void espnowTask(void* arg);
void espnow_take_sample(RxSnapshot* out);   // consume latches (sampler only)
bool espnow_get_stats(uint8_t type, uint8_t id, SenderStats* out);
uint32_t espnow_queue_overflows();
