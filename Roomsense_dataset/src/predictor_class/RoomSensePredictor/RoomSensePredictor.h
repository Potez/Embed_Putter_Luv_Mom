// RoomSensePredictor: ทำนายว่าควรจ่ายไฟให้ห้องหรือไม่ (power 0/1) — ทำหน้าที่นี้อย่างเดียว
// - การนับคนจากกล้อง (โมเดล FOMO) เป็นงานแยก class นี้รับ "จำนวนคนที่กล้องนับได้" มาเป็น input
// - ไม่มี relay / alarm / firebase ในนี้ (alarm ไฟไหม้เป็น hard rule แยก: relay = power && !alarm)
// - feature ต้องตรงกับ src/ml_pipeline/common.py: windows() ชุด HISTORY ทุกตัว (ตรวจแล้วใน export_model.ipynb)
// - weight มาจาก model_weights.h ที่ export_model.ipynb สร้าง
#pragma once
#include <math.h>
#include "model_weights.h"

class RoomSensePredictor {
 public:
  int power = 0;      // ผลล่าสุด 0/1 (เปลี่ยนทุก 10 s)
  long windows = 0;   // จำนวน window ที่ปิดแล้ว

  // เรียกทุก 500 ms (2 Hz) ชื่อ input ตาม firebase-schema: people_ai
  //   people_ai = จำนวนคนจากโมเดลกล้อง, -1 = กล้องไม่ส่งข้อมูล
  //   door_ir   = ขา DO ของ IR obstacle ที่ประตู (active-low: 0 = มีวัตถุ)
  //   gray      = ADC ของ gray sensor ที่ธรณีประตู
  int update(int people_ai, int door_ir, int gray) {
    bool door = door_ir == 0 || gray > 1000;
    if (people_ai >= 0) {
      camN++; camSum += people_ai; camPos += people_ai > 0;
      if (people_ai > camMax) camMax = people_ai;
    }
    if (door && (k == 0 || !prevDoor)) doorEv++;   // ขอบขาขึ้น (นับแถวแรกของ window ด้วย)
    doorAny |= door; prevDoor = door;
    if (++k == RS_WIN) closeWindow();
    return power;
  }

  float x[RS_N_FEATURES];   // feature ของ window ล่าสุด (เปิดไว้ให้ debug)

 private:
  static const int H = 30;  // เก็บย้อนหลัง 30 window = 5 นาที
  int k = 0, camN = 0, camMax = -1, camPos = 0, doorEv = 0;
  long camSum = 0;
  bool doorAny = false, prevDoor = false;
  double hSeen[H], hMean[H]; int hDoor[H], hEv[H];
  long sinceCam = -1, sinceDoor = -1;   // -1 = ยังไม่เคยเห็น

  double last(const double *a, int i) { return a[(windows - 1 - i + H) % H]; }
  int last(const int *a, int i) { return a[(windows - 1 - i + H) % H]; }

  void closeWindow() {
    double cmax = camN ? camMax : NAN, cmean = camN ? (double)camSum / camN : NAN;
    int slot = windows % H;
    hSeen[slot] = camN ? camMax : 0; hMean[slot] = cmean; hDoor[slot] = doorAny; hEv[slot] = doorEv;
    windows++;
    sinceCam = hSeen[slot] > 0 ? 0 : (sinceCam < 0 ? -1 : sinceCam + 1);
    sinceDoor = doorAny ? 0 : (sinceDoor < 0 ? -1 : sinceDoor + 1);

    double roll6 = 0, m3 = 0, door2m = 0, ev5m = 0; int n3 = 0;
    for (int i = 0; i < 30 && i < windows; i++) {
      if (i < 6 && last(hSeen, i) > roll6) roll6 = last(hSeen, i);
      if (i < 3 && !isnan(last(hMean, i))) { m3 += last(hMean, i); n3++; }
      if (i < 12 && last(hDoor, i)) door2m = 1;
      ev5m += last(hEv, i);
    }
    double f[RS_N_FEATURES] = {   // ลำดับเดียวกับ HISTORY ใน common.py
      cmax, cmean, camN ? (double)camPos / camN : NAN, 1.0 - (double)camN / RS_WIN, (double)doorAny, (double)doorEv,
      roll6, n3 ? m3 / n3 : NAN, door2m, ev5m,
      sinceCam < 0 ? 900.0 : fmin(sinceCam * 10.0, 900.0), sinceDoor < 0 ? 900.0 : fmin(sinceDoor * 10.0, 900.0)};
    power = predict(f);
    k = camN = camPos = doorEv = 0; camSum = 0; camMax = -1; doorAny = false;
  }

  int predict(const double *f) {
    double z[RS_N_FEATURES];
    for (int i = 0; i < RS_N_FEATURES; i++) {
      x[i] = f[i];
      z[i] = ((isnan(f[i]) ? RS_MEDIAN[i] : f[i]) - RS_MEAN[i]) / RS_SCALE[i];   // SimpleImputer + StandardScaler
    }
#ifdef RS_LOGREG
    double s = RS_INTERCEPT;
    for (int i = 0; i < RS_N_FEATURES; i++) s += RS_COEF[i] * z[i];
    return s > 0;
#else
    double p0 = 0, p1 = 0;   // DecisionTree = ป่า 1 ต้น
    for (int t = 0; t < RS_N_TREES; t++) {
      int n = RS_ROOT[t];
      while (RS_LEFT[n] >= 0) n = (float)z[RS_FEAT[n]] <= RS_THR[n] ? RS_LEFT[n] : RS_RIGHT[n];   // sklearn เทียบแบบ float32
      p0 += 1 - RS_P1[n]; p1 += RS_P1[n];
    }
    return p1 > p0;
#endif
  }
};
