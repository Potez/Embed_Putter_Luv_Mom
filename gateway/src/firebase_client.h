// firebase_client.h — Firebase Realtime Database over REST/HTTPS + cloudTask.
// Paths and objects follow firebase-schema.md (data contract v0.1).
#pragma once
#include <Arduino.h>

enum EventType : uint8_t {
  EVT_ENTER, EVT_EXIT, EVT_LIGHT_ON, EVT_LIGHT_OFF, EVT_LIGHT_FAIL,
  EVT_MANUAL, EVT_REBOOT, EVT_RECONNECT, EVT_BACKFILL,
};

struct Event {
  uint32_t ts;           // Unix s; 0 = fill in at upload time
  uint8_t  type;         // EventType
  char     detail[48];
  char     by[32];
  int32_t  latency_ms;   // -1 = omit
  uint16_t count;        // backfill only
  uint32_t from, to;     // backfill only
};

void cloud_init();                 // queues + Wi-Fi event hooks (call before starting tasks)
void cloudTask(void* arg);
bool cloud_time_synced();
uint32_t cloud_now();              // Unix seconds (0 if not synced)

// Thread-safe, non-blocking. Events wait in a queue until they are uploaded.
bool events_post(EventType type, const char* detail = nullptr, const char* by = nullptr,
                 int32_t latency_ms = -1);
