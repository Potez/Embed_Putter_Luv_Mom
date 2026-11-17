#include "health.h"
#include "config.h"
#include "espnow_rx.h"
#include "ring_buffer.h"
#include "actuator.h"
#include <Preferences.h>
#include <WiFi.h>
#include <esp_system.h>

static uint32_t s_reboots = 0;
static uint32_t s_reconnects = 0;
static const char* s_reason = "unknown";

static const char* reasonStr(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return "power_on";
    case ESP_RST_EXT:       return "external_pin";
    case ESP_RST_SW:        return "software";
    case ESP_RST_PANIC:     return "panic";
    case ESP_RST_INT_WDT:   return "int_watchdog";
    case ESP_RST_TASK_WDT:  return "task_watchdog";
    case ESP_RST_WDT:       return "other_watchdog";
    case ESP_RST_DEEPSLEEP: return "deep_sleep";
    case ESP_RST_BROWNOUT:  return "brownout";
    case ESP_RST_SDIO:      return "sdio";
    default:                return "unknown";
  }
}

void health_init() {
  s_reason = reasonStr(esp_reset_reason());
  Preferences p;
  p.begin("roomsense", false);
  s_reboots = p.getUInt("reboots", 0) + 1;
  p.putUInt("reboots", s_reboots);
  p.end();
  Serial.printf("[health] boot #%lu, reset reason: %s\n", (unsigned long)s_reboots, s_reason);
}

uint32_t health_reboots() { return s_reboots; }
const char* health_reset_reason() { return s_reason; }
void health_count_reconnect() { s_reconnects++; }
uint32_t health_reconnects() { return s_reconnects; }

static float pdr(const SenderStats& s) {
  uint32_t total = s.rx + s.lost;
  return total ? (float)s.rx / total : 1.0f;
}

// Only the fields in firebase-schema.md v0.1. Extra diagnostics go to Serial (health_print_serial).
void health_build_gateway(JsonDocument& d, uint32_t now) {
  d["kind"] = "gateway";
  d["online"] = true;
  d["rssi"] = WiFi.RSSI();
  d["uptime_s"] = (uint32_t)(millis() / 1000);
  d["heap_free"] = ESP.getFreeHeap();
  d["last_seen"] = now;
  d["reboots"] = s_reboots;
  d["reconnects"] = s_reconnects;
  d["buffer_depth"] = (uint32_t)ring_depth();
}

bool health_build_node(JsonDocument& d, uint32_t now) {
  SenderStats s;
  bool seen = espnow_get_stats(PKT_NODE, NODE_NUM_ID, &s);
  uint32_t age = seen ? millis() - s.last_rx_ms : UINT32_MAX;
  bool online = seen && age <= NODE_OFFLINE_MS;
  d["kind"] = "node";
  d["room_id"] = ROOM_ID;
  d["online"] = online;
  if (seen) { d["last_seen"] = now - age / 1000; d["rssi"] = s.rssi; }
  else      { d["last_seen"] = nullptr;          d["rssi"] = nullptr; }
  d["uptime_s"] = nullptr;    // not known by the gateway (not in NodePacket)
  d["heap_free"] = nullptr;
  return online;
}

void health_print_serial() {
  Serial.printf("[health] ch=%d rssi=%d heap=%lu buf=%u dropped=%lu auto=%s override=%s espnow_ovf=%lu\n",
                (int)WiFi.channel(), (int)WiFi.RSSI(), (unsigned long)ESP.getFreeHeap(),
                (unsigned)ring_depth(), (unsigned long)ring_dropped(),
                actuator_stop_latched() ? "OFF(stop)" : "on", actuator_override_active() ? "yes" : "no",
                (unsigned long)espnow_queue_overflows());
  SenderStats s;
  if (espnow_get_stats(PKT_NODE, NODE_NUM_ID, &s))
    Serial.printf("[health] node id=%u seq=%lu rx=%lu lost=%lu dup=%lu resets=%lu pdr=%.4f rssi=%d age=%lus\n",
                  s.id, (unsigned long)s.last_seq, (unsigned long)s.rx, (unsigned long)s.lost,
                  (unsigned long)s.dup, (unsigned long)s.resets, pdr(s), s.rssi,
                  (unsigned long)((millis() - s.last_rx_ms) / 1000));
  if (espnow_get_stats(PKT_CAM, 0, &s))
    Serial.printf("[health] cam  id=%u seq=%lu rx=%lu lost=%lu dup=%lu resets=%lu pdr=%.4f rssi=%d\n",
                  s.id, (unsigned long)s.last_seq, (unsigned long)s.rx, (unsigned long)s.lost,
                  (unsigned long)s.dup, (unsigned long)s.resets, pdr(s), s.rssi);
}
