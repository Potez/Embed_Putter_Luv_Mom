// PersonDetector: on-device human detection for OV7670 (no FIFO) on ESP32 without PSRAM.
// Model: TFLite Micro person_detection (MobileNet v1 0.25, 96x96 grayscale, int8). Not YOLO:
// YOLO needs several MB of RAM; this board has ~300KB free.
#pragma once
#include <stdint.h>
#include <stddef.h>

struct Detection {
  float person;      // 0..1 confidence a person is in view
  float noPerson;    // 0..1 confidence nobody is in view
  bool  isPerson;    // person >= threshold
  uint32_t ms;       // preprocess + inference time
};

class PersonDetector {
 public:
  static constexpr int kSize = 96;  // model input is kSize x kSize grayscale

  explicit PersonDetector(float threshold = 0.6f) : threshold_(threshold) {}

  // Loads the model and allocates the tensor arena (~81KB internal RAM). Call once in setup().
  bool begin();

  // Runs detection on a raw RGB565 OV7670 frame (as returned by the patched driver: 319-byte lines).
  Detection detect(const uint8_t* rgb565, size_t len);

  // Last 96x96 grayscale image fed to the model (for debugging / sending to a PC).
  const uint8_t* lastInput() const { return gray_; }

 private:
  void preprocess(const uint8_t* raw, size_t len, int8_t* out);

  float threshold_;
  uint8_t gray_[kSize * kSize];
  bool ready_ = false;
};
