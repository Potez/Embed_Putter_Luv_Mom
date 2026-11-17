#include "predictor_glue.h"
#include "config.h"
#include <math.h>

#if USE_FLAME_PREDICTOR
// =================================================================================================
// Flame's model, referenced (not copied, not edited):
//   Roomsense_dataset/src/predictor_class/RoomSensePredictor/RoomSensePredictor.h
//   Roomsense_dataset/src/predictor_class/RoomSensePredictor/model_weights.h  (RandomForest 50 trees)
// API:  int update(int people_ai, int door_ir, int gray)   -- call every 500 ms, returns power 0/1
//       long windows   -- number of closed 10 s windows (RS_WIN = 20 rows)
//       float x[12]    -- features of the last window, order of HISTORY in common.py:
//         0 cam_max 1 cam_mean 2 cam_pos_frac 3 cam_missing_frac 4 door_any 5 door_events
//         6 cam_max_roll6 7 cam_mean_roll3 8 door_recent_2m 9 door_events_5m 10 since_cam_s 11 since_door_s
// The class does the windowing, history features, imputer and scaler itself.
// =================================================================================================
#include "RoomSensePredictor.h"
static_assert(RS_WIN == WINDOW_ROWS, "gateway WINDOW_ROWS must match the model's RS_WIN");
static_assert(RS_N_FEATURES == 12, "predictor_glue expects the 12-feature HISTORY set");

static RoomSensePredictor s_model;

void predictor_init() {}

const char* predictor_name() { return "RoomSensePredictor (RandomForest 50 trees, Flame)"; }

bool predictor_add_row(int16_t pc, uint8_t ddo, uint16_t a2, WindowResult* out) {
  const long before = s_model.windows;
  const int power = s_model.update(pc, ddo, a2);     // people_ai (-1 = camera silent), door_ir, gray
  if (s_model.windows == before) return false;       // window not closed yet
  const float* x = s_model.x;
  WindowFeatures& f = out->f;
  f.cam_max = x[0];        f.cam_mean = x[1];       f.cam_pos_frac = x[2];   f.cam_missing_frac = x[3];
  f.door_any = x[4];       f.door_events = x[5];
  f.cam_max_roll6 = x[6];  f.cam_mean_roll3 = x[7]; f.door_recent_2m = x[8]; f.door_events_5m = x[9];
  f.since_cam_s = x[10];   f.since_door_s = x[11];
  out->power_on = power != 0;
  out->from_flame_model = true;
  return true;
}

#else
// =================================================================================================
// FALLBACK (RoomSensePredictor.h not on the include path). Same 12 features as the model, computed
// the same way as RoomSensePredictor.h, but decided by a simple rule that mirrors the label:
// power_on = someone seen in the last 30 s (or, if the camera is completely silent, door activity
// in the last 2 min). Build with -DREQUIRE_PREDICTOR=1 to make a missing model a compile error.
// =================================================================================================
#define HIST 30
static int16_t s_pc[WINDOW_ROWS];
static uint8_t s_door[WINDOW_ROWS];
static int s_n = 0;
static bool s_prevDoor = false;
static float s_hSeen[HIST], s_hMean[HIST], s_hDoor[HIST], s_hEv[HIST];
static long s_windows = 0, s_sinceCam = -1, s_sinceDoor = -1;

void predictor_init() { s_n = 0; s_windows = 0; s_sinceCam = s_sinceDoor = -1; }

const char* predictor_name() {
  return "FALLBACK rule (since_cam_s<=30) - RoomSensePredictor.h not found";
}

static float lastOf(const float* a, int i) { return a[(s_windows - 1 - i + HIST) % HIST]; }

static void closeWindow(WindowFeatures* f) {
  int n = 0, pos = 0, mx = -1, ev = 0; long sum = 0; bool any = false;
  for (int i = 0; i < WINDOW_ROWS; i++) {
    if (s_pc[i] >= 0) { n++; sum += s_pc[i]; pos += s_pc[i] > 0; if (s_pc[i] > mx) mx = s_pc[i]; }
    const bool d = s_door[i];
    if (d && (i == 0 || !s_prevDoor)) ev++;              // rising edge, first row of window counts
    any |= d; s_prevDoor = d;
  }
  const int slot = s_windows % HIST;
  s_hSeen[slot] = n ? mx : 0;
  s_hMean[slot] = n ? (float)sum / n : NAN;
  s_hDoor[slot] = any; s_hEv[slot] = ev;
  s_windows++;
  s_sinceCam = s_hSeen[slot] > 0 ? 0 : (s_sinceCam < 0 ? -1 : s_sinceCam + 1);
  s_sinceDoor = any ? 0 : (s_sinceDoor < 0 ? -1 : s_sinceDoor + 1);
  float roll6 = 0, m3 = 0, d2m = 0, ev5 = 0; int n3 = 0;
  for (int i = 0; i < 30 && i < s_windows; i++) {
    if (i < 6 && lastOf(s_hSeen, i) > roll6) roll6 = lastOf(s_hSeen, i);
    if (i < 3 && !isnan(lastOf(s_hMean, i))) { m3 += lastOf(s_hMean, i); n3++; }
    if (i < 12 && lastOf(s_hDoor, i)) d2m = 1;
    ev5 += lastOf(s_hEv, i);
  }
  f->cam_max = n ? mx : NAN;               f->cam_mean = s_hMean[slot];
  f->cam_pos_frac = n ? (float)pos / n : NAN;
  f->cam_missing_frac = 1.0f - (float)n / WINDOW_ROWS;
  f->door_any = any;                       f->door_events = ev;
  f->cam_max_roll6 = roll6;                f->cam_mean_roll3 = n3 ? m3 / n3 : NAN;
  f->door_recent_2m = d2m;                 f->door_events_5m = ev5;
  f->since_cam_s = s_sinceCam < 0 ? 900.0f : fminf(s_sinceCam * 10.0f, 900.0f);
  f->since_door_s = s_sinceDoor < 0 ? 900.0f : fminf(s_sinceDoor * 10.0f, 900.0f);
}

bool predictor_add_row(int16_t pc, uint8_t ddo, uint16_t a2, WindowResult* out) {
  s_pc[s_n] = pc;
  s_door[s_n] = (ddo == 0) || (a2 > 1000);
  if (++s_n < WINDOW_ROWS) return false;
  s_n = 0;
  closeWindow(&out->f);
  const WindowFeatures& f = out->f;
  out->power_on = f.since_cam_s <= 30.0f || (f.cam_missing_frac >= 0.99f && f.door_recent_2m > 0);
  out->from_flame_model = false;
  return true;
}
#endif
