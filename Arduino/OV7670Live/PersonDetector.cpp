#include <TensorFlowLite_ESP32.h>
#include "PersonDetector.h"
#include "person_detect_model_data.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <stdlib.h>

namespace {
constexpr int kArenaSize = 81 * 1024;
constexpr int kPersonIndex = 1, kNoPersonIndex = 0;
// OV7670 on this wiring: ESP32 drops 1 byte per 320-byte line, so lines are 319 bytes / 159 px.
constexpr int kLineBytes = 319, kLinePx = 159;

tflite::MicroInterpreter* interp = nullptr;
TfLiteTensor* input = nullptr;

inline uint8_t green(const uint8_t* p) { return ((p[0] << 8 | p[1]) >> 5) & 63; }
inline uint8_t luma(const uint8_t* p) {
  uint16_t v = p[0] << 8 | p[1];
  uint32_t r = ((v >> 11) & 31) << 3, g = ((v >> 5) & 63) << 2, b = (v & 31) << 3;
  return (r * 77 + g * 150 + b * 29) >> 8;
}
}  // namespace

bool PersonDetector::begin() {
  static tflite::MicroErrorReporter reporter;
  const tflite::Model* model = tflite::GetModel(g_person_detect_model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION) return false;

  uint8_t* arena = (uint8_t*)heap_caps_malloc(kArenaSize, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!arena) return false;

  static tflite::MicroMutableOpResolver<5> ops;
  ops.AddAveragePool2D(); ops.AddConv2D(); ops.AddDepthwiseConv2D(); ops.AddReshape(); ops.AddSoftmax();

  static tflite::MicroInterpreter s(model, ops, arena, kArenaSize, &reporter);
  interp = &s;
  if (interp->AllocateTensors() != kTfLiteOk) return false;
  input = interp->input(0);
  ready_ = true;
  return true;
}

void PersonDetector::preprocess(const uint8_t* raw, size_t len, int8_t* out) {
  // 1. Find where lines really start (the dropped byte must fall at a line edge):
  //    pick the offset K that makes neighbouring pixels smoothest.
  int bestK = 0; uint32_t bestScore = UINT32_MAX;
  for (int K = 0; K < kLineBytes; K++) {
    int rows = (len - K) / kLineBytes; uint32_t s = 0;
    for (int y = 3; y < rows - 1; y += 10) {
      const uint8_t* line = raw + K + y * kLineBytes;
      for (int x = 0; x < kLinePx - 2; x += 4) s += abs(green(line + 2 * x) - green(line + 2 * x + 2));
    }
    if (s < bestScore) { bestScore = s; bestK = K; }
  }
  int H = (len - bestK) / kLineBytes;  // ~108 sensor rows
  const uint8_t* img = raw + bestK;

  // 2. Rotate 90° CCW (camera is mounted sideways) -> upright image H wide x 159 tall,
  //    centre-crop to H x H, resize (nearest) to 96x96 grayscale.
  int side = H, top = (kLinePx - side) / 2;
  for (int i = 0; i < kSize; i++) {
    int r = top + i * side / kSize;           // row in rotated image = column in sensor
    for (int j = 0; j < kSize; j++) {
      int c = j * side / kSize;               // column in rotated image = row in sensor
      uint8_t g = luma(img + c * kLineBytes + 2 * (kLinePx - 1 - r));
      gray_[i * kSize + j] = g;
      out[i * kSize + j] = (int8_t)(g ^ 0x80);  // uint8 -> int8 (subtract 128)
    }
  }
}

Detection PersonDetector::detect(const uint8_t* rgb565, size_t len) {
  Detection d = {0, 0, false, 0};
  if (!ready_ || len < (size_t)kLineBytes * 60) return d;
  int64_t t0 = esp_timer_get_time();
  preprocess(rgb565, len, input->data.int8);
  if (interp->Invoke() != kTfLiteOk) return d;
  TfLiteTensor* o = interp->output(0);
  d.person   = (o->data.int8[kPersonIndex]   - o->params.zero_point) * o->params.scale;
  d.noPerson = (o->data.int8[kNoPersonIndex] - o->params.zero_point) * o->params.scale;
  d.isPerson = d.person >= threshold_;
  d.ms = (esp_timer_get_time() - t0) / 1000;
  return d;
}
