// ring_buffer.h — store-and-forward buffer for readings (E4). Thread-safe (mutex).
#pragma once
#include <Arduino.h>

// One reading = one object in rooms/{roomId}/readings/{ts}. Nullable fields use sentinels.
struct Reading {
  uint32_t ts;          // gateway Unix s (key in readings/)
  uint32_t node_ts;     // 0 -> null
  uint32_t node_seq;
  bool     node_valid;  // false -> node_ts/node_seq/pir/people_ir/sound_db/flame = null
  int8_t   people_ai;   // -1 -> null (CAM silent / could not count)
  uint8_t  ai_conf;     // 0..100, 255 -> null
  int16_t  people_ir;   // -1 -> null
  bool     pir;
  bool     light_on;    // REAL state from the LDR
  uint16_t ldr;
  float    temp_c;      // NAN -> null
  float    humidity;    // NAN -> null
  uint8_t  sound_db;
  bool     flame;
  bool     power_on;    // model output for this window (extra field, debug)
  bool     buffered;    // set when the reading was not delivered on the first try
};

void   ring_init();
// Merges into the newest entry if it has the same ts (flame=true wins); otherwise appends.
// Overwrites the oldest when full (returns false then).
bool   ring_push(const Reading& r);
bool   ring_peek_oldest(Reading* out);
bool   ring_peek_newest(Reading* out);
void   ring_pop_oldest();
void   ring_mark_all_buffered();
size_t ring_depth();
uint32_t ring_dropped();                       // readings lost because the buffer overflowed
