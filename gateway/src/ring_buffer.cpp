#include "ring_buffer.h"
#include "config.h"

static Reading s_buf[RING_CAPACITY];
static size_t s_head = 0;   // index of oldest
static size_t s_count = 0;
static uint32_t s_dropped = 0;
static SemaphoreHandle_t s_mtx = nullptr;

void ring_init() { s_mtx = xSemaphoreCreateMutex(); }

bool ring_push(const Reading& r) {
  bool ok = true;
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  if (s_count) {                           // same second as the newest (flame + window) -> one reading
    Reading& last = s_buf[(s_head + s_count - 1) % RING_CAPACITY];
    if (last.ts == r.ts) {
      const bool flame = last.flame || r.flame, buffered = last.buffered || r.buffered;
      last = r;                            // newer values win ...
      last.flame = flame;                  // ... except flame=true always wins
      last.buffered = buffered;
      xSemaphoreGive(s_mtx);
      return true;
    }
  }
  if (s_count == RING_CAPACITY) {          // full: drop the oldest
    s_head = (s_head + 1) % RING_CAPACITY;
    s_count--;
    s_dropped++;
    ok = false;
  }
  s_buf[(s_head + s_count) % RING_CAPACITY] = r;
  s_count++;
  xSemaphoreGive(s_mtx);
  return ok;
}

bool ring_peek_oldest(Reading* out) {
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  bool ok = s_count > 0;
  if (ok) *out = s_buf[s_head];
  xSemaphoreGive(s_mtx);
  return ok;
}

bool ring_peek_newest(Reading* out) {
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  bool ok = s_count > 0;
  if (ok) *out = s_buf[(s_head + s_count - 1) % RING_CAPACITY];
  xSemaphoreGive(s_mtx);
  return ok;
}

void ring_pop_oldest() {
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  if (s_count) { s_head = (s_head + 1) % RING_CAPACITY; s_count--; }
  xSemaphoreGive(s_mtx);
}

void ring_mark_all_buffered() {
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  for (size_t i = 0; i < s_count; i++) s_buf[(s_head + i) % RING_CAPACITY].buffered = true;
  xSemaphoreGive(s_mtx);
}

size_t ring_depth() {
  xSemaphoreTake(s_mtx, portMAX_DELAY);
  size_t n = s_count;
  xSemaphoreGive(s_mtx);
  return n;
}

uint32_t ring_dropped() { return s_dropped; }
