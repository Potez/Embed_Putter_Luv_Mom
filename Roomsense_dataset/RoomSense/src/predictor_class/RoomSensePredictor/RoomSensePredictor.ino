// ตัวอย่างใช้ RoomSensePredictor บน ESP32: อ่านเซนเซอร์ทุก 500 ms แล้วได้ power 0/1
// จำนวนคน (people_ai) มาจากบอร์ดกล้องที่รันโมเดลนับคนแยกต่างหาก ส่งมาทาง UART
// gateway เอา power ไปเขียน firebase เป็น status: power ? "in_use" : "vacant" (ดู firebase-schema.md)
#include "RoomSensePredictor.h"

const int PIN_DOOR_IR = 27;   // ponytail: ขาตามบอร์ดเรา แก้ให้ตรงกับที่ต่อจริง
const int PIN_GRAY = 35;

RoomSensePredictor predictor;
int people_ai = -1;           // ค่าล่าสุดจากบอร์ดกล้อง, -1 = ยังไม่ได้รับ

void setup() {
  Serial.begin(115200);
  Serial2.begin(115200);      // UART จากบอร์ดกล้อง: 1 บรรทัด = จำนวนคน
  pinMode(PIN_DOOR_IR, INPUT);
}

void loop() {
  static unsigned long next = 0, lastCam = 0;
  while (Serial2.available()) { people_ai = Serial2.parseInt(); lastCam = millis(); }
  if (millis() - lastCam > 2000) people_ai = -1;   // กล้องเงียบเกิน 2 s = ไม่มีข้อมูล

  if (millis() >= next) {
    next += 500;
    int power = predictor.update(people_ai, digitalRead(PIN_DOOR_IR), analogRead(PIN_GRAY));
    Serial.println(power);
  }
}
