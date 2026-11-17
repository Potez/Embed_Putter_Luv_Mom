// predictor_glue.h — feeds raw 2 Hz rows to Flame's RoomSensePredictor (RandomForest, feature set 03)
// and returns one power_on decision per 10 s window.
//
// Raw row (exactly the dataset columns the model was trained on):
//   person_count  (-1 = camera silent -> NaN inside the model)
//   digital_do    (E18 door IR, active-low: 0 = object)
//   analog_2_raw  (TCRT5000 gray sensor in the dataset; we feed ANALOG_2_RAW_DEFAULT = 0)
// LDR / DHT11 are deliberately NOT inputs (LDR = label leakage per RoomSense ML report).
#pragma once
#include <Arduino.h>

// The 12 features of set "03 window + history" (RoomSense ML report), order as in the report.
// Filled from RoomSensePredictor::x (Flame) or computed by the fallback build.
struct WindowFeatures {
  float cam_max, cam_mean, cam_pos_frac, cam_missing_frac;   // NaN when the camera sent nothing
  float door_any, door_events;
  float cam_mean_roll3, cam_max_roll6, door_recent_2m, door_events_5m;
  float since_cam_s, since_door_s;                           // capped at 900
};

struct WindowResult {
  bool power_on;
  WindowFeatures f;
  bool from_flame_model;   // false = fallback rule (RoomSensePredictor.h not on include path)
};

void predictor_init();
// Feed one row (every SAMPLE_MS). Returns true when a 20-row window just completed -> *out valid.
bool predictor_add_row(int16_t person_count, uint8_t digital_do, uint16_t analog_2_raw, WindowResult* out);
const char* predictor_name();
