import base64, json, re
import pandas as pd

R = json.load(open("ml_results.json"))
H3 = json.load(open("h3_alarm.json"))
V = json.load(open("c_export/verify.json"))
KN = {"flame": "ไฟแช็ก", "gas": "แก๊สไฟแช็ก", "smoke": "ธูป"}
f3 = lambda v: f"{v:.3f}"


def tbl(rows, cols, heads):
    out = ["| " + " | ".join(heads) + " |", "| " + " | ".join("---" for _ in heads) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


T = R["test"]
fin, rule, r1m, maj, rfs = T["final"], T["rule_camera"], T["rule_camera_1min"], T["majority"], T["rf_same_features"]

cmp_rows = [dict(m=r["model"], f1=f3(r["f1"]), rc=f3(r["recall"]), pc=f3(r["precision"]), fp=r["fp"], fn=r["fn"])
            for r in R["model_compare_lodo"]]
abl_rows = [dict(s=r["set"], n=r["n_features"], lf=f3(r["lodo_f1"]), tf=f3(r["test_f1"]), tr=f3(r["test_recall"]),
                 tp=f3(r["test_precision"])) for r in R["ablation"]]
depth_rows = [dict(d=r["max_depth"], f1=f3(r["f1"]), rc=f3(r["recall"]), pc=f3(r["precision"])) for r in R["depth_grid"]]
test_rows = []
for name, m in [("Majority (ทาย 0 เสมอ)", maj), ("Rule: กล้องเห็นคนใน window นี้", rule),
                ("Rule: กล้องเห็นคนภายใน 1 นาที", r1m), ("Random Forest (ชุด feature เดียวกัน)", rfs),
                ("**โมเดลสุดท้าย (Decision Tree depth 2)**", fin)]:
    test_rows.append(dict(m=name, f1=f3(m["f1"]), rc=f3(m["recall"]), pc=f3(m["precision"]),
                          on=f"{m['on_while_empty_min']:.1f}", dark=f"{m['dark_while_occupied_min']:.1f}",
                          sw=f"{m['switches']} / {m['switches_true']}"))
ef = {r["case"]: r for r in R["errors_test_final"]}
er = {r["case"]: r for r in R["errors_test_rule"]}
eo = {r["case"]: r for r in R["errors_train_oof"]}
err_rows = []
for c in ef:
    if ef[c]["windows"] == 0:
        continue
    err_rows.append(dict(c=c, n=ef[c]["windows"], l1=ef[c]["label1"],
                         rule=f"{er[c]['fp']} / {er[c]['fn']}", mdl=f"{ef[c]['fp']} / {ef[c]['fn']}",
                         oof=(f"{eo[c]['fp']} / {eo[c]['fn']}" if eo[c]["windows"] else "ไม่มีใน train")))
hy_rows = [dict(k=r["k_off"], h=r["extra_hold_s"], f1=f3(r["f1"]), pc=f3(r["precision"]),
                on=f"{r['on_while_empty_min']:.1f}", sw=r["switches"]) for r in R["hysteresis"]]
h3_rows = [dict(d=r["day"], k=KN[r["kind"]], a=r["first_alarm_s"], b=r["first_alarm_debounced_s"]) for r in H3]
pi = R["perm_importance"]
feat_desc = [
    ("cam_max", "กล้อง", "จำนวนคนสูงสุดใน window"),
    ("cam_mean", "กล้อง", "จำนวนคนเฉลี่ยใน window"),
    ("cam_pos_frac", "กล้อง", "สัดส่วนแถวที่กล้องเห็น ≥ 1 คน"),
    ("cam_missing_frac", "กล้อง", "สัดส่วนแถวที่กล้องไม่ส่งข้อมูล (`-1`)"),
    ("cam_max_roll6", "กล้อง", "`cam_max` สูงสุดใน 6 window ล่าสุด (1 นาที)"),
    ("cam_mean_roll3", "กล้อง", "`cam_mean` เฉลี่ย 3 window ล่าสุด (30 s)"),
    ("since_cam_s", "กล้อง", "วินาทีนับจาก window ล่าสุดที่กล้องเห็น ≥ 1 คน (เพดาน 900)"),
    ("door_any", "ประตู", "IR = 0 หรือ gray > 1,000 ใน window นี้"),
    ("door_events", "ประตู", "จำนวนครั้งที่ประตูเริ่มมีวัตถุผ่าน"),
    ("door_recent_2m", "ประตู", "มีกิจกรรมที่ประตูใน 2 นาทีที่ผ่านมา"),
    ("door_events_5m", "ประตู", "จำนวนครั้งที่มีวัตถุผ่านประตูใน 5 นาที"),
    ("since_door_s", "ประตู", "วินาทีนับจากกิจกรรมที่ประตูครั้งล่าสุด"),
    ("temp, hum, mq2", "สภาพแวดล้อม", "ค่าเฉลี่ย/median ใน window"),
    ("temp_slope_5m", "สภาพแวดล้อม", "อุณหภูมิเปลี่ยนต่อนาที ในรอบ 5 นาที"),
    ("ldr_mean", "LDR", "ค่าเฉลี่ย `analog_1_raw` (ใช้เฉพาะทดสอบ leakage)"),
]
feat_rows = [dict(f=f"`{a}`", g=b, d=c) for a, b, c in feat_desc]
n_fp_pliers = ef["ลืมคีมในกล่อง (ห้องว่าง)"]["fp"]

md = f"""# รายงาน Machine Learning: ทำนายการจ่ายไฟห้องประชุมจำลอง

> ข้อมูลที่ใช้เป็น**ข้อมูลจำลอง (synthetic)** จากรายงานการทดลองฉบับก่อน ผลในรายงานนี้แสดงวิธีวิเคราะห์ และต้องยืนยันด้วยข้อมูลจริงอีกครั้ง
> ตัวเลขทุกตัวคำนวณจากโค้ดในโฟลเดอร์ `ml/` (`run_ml.py`, `export_c.py`)

## บทสรุป

โมเดลที่เลือกได้คือ Decision Tree ลึก 2 ชั้น ซึ่งลดรูปเหลือกฎข้อเดียว: **จ่ายไฟถ้ากล้องเห็นคนภายใน 35 วินาทีที่ผ่านมา**
ในวันทดสอบ (วันที่ 4) ได้ F1 {f3(fin['f1'])}, recall {f3(fin['recall'])} คือไม่เคยตัดไฟใส่คนเลย และ precision {f3(fin['precision'])}
ข้อผิดพลาดทั้งหมด {fin['fp']} window (ไฟเปิดทิ้ง {fin['on_while_empty_min']:.1f} นาที) และ {n_fp_pliers} window ในนั้นเกิดช่วงที่ลืมคีมไว้ในกล่องขณะห้องว่าง ซึ่งเป็นกรณีที่ไม่มีใน train
เซนเซอร์ประตู อุณหภูมิ ความชื้น MQ-2 และ LDR ไม่ช่วยเพิ่มความแม่นยำ โมเดลมีขนาด {V['header_bytes']} bytes เมื่อเป็นโค้ด C และให้ผลตรงกับ Python ครบ {V['match_vs_threshold']:,}/{V['n']:,} window

## 1. นิยามปัญหา

| หัวข้อ | ค่า |
| --- | --- |
| งาน | Binary classification: `power_on` = 1 (จ่ายไฟ) หรือ 0 (ตัดไฟ) |
| หน่วยการทำนาย | 1 window = 10 วินาที (20 แถวของ log 2 Hz) ทำนายทุก 10 วินาที |
| Input | feature จาก window ปัจจุบันและ window ก่อนหน้า (ห้ามใช้ข้อมูลอนาคต) |
| ข้อจำกัด | ต้องรันบน ESP32 ได้: โมเดลเล็ก คำนวณ feature ด้วย buffer ย้อนหลังไม่เกิน 5 นาที |
| ความผิดพลาดที่แย่ที่สุด | ตัดไฟขณะมีคน (FN) จึงตั้งเป้า recall ≥ 0.99 ก่อน แล้วค่อยลดไฟเปิดทิ้ง (FP) |
| ความปลอดภัย | ไม่อยู่ในโมเดล ใช้ `alarm` เป็น hard rule แยกต่างหาก (หัวข้อ 11) |

## 2. ข้อมูลและการเตรียมข้อมูล

| ขั้น | รายละเอียด |
| --- | --- |
| แหล่งข้อมูล | `train.csv` (วันที่ 1–3, 64,787 แถว) และ `test.csv` (วันที่ 4, 21,597 แถว) |
| Sentinel | `person_count = -1` เป็น NaN, `temp_c`/`humidity` = `nan` คงเป็น NaN |
| แบ่ง window | ใช้เวลาใน session แบ่งเป็นช่วง 10 วินาที แยกตาม `day` และ `boot` (feature ย้อนหลังไม่ข้ามการรีเซ็ตของบอร์ด) |
| Warm-up | ตัด 3 นาทีแรกของแต่ละ session (MQ-2 ยังไม่นิ่ง และห้องว่างตาม protocol) |
| label ของ window | `max(power_on)` ใน window: ถ้ามีวินาทีใดควรจ่ายไฟ ทั้ง window เป็น 1 |
| จำนวน window | train {R['windows']['train']:,} (วันที่ 1: {R['windows']['per_day']['1']:,}, วันที่ 2: {R['windows']['per_day']['2']:,}, วันที่ 3: {R['windows']['per_day']['3']:,}), test {R['windows']['test']:,} |
| สัดส่วน label = 1 | train {R['windows']['pos_train']:.3f}, test {R['windows']['pos_test']:.3f} |

## 3. Feature

ทุก feature คำนวณจาก window ปัจจุบันและอดีตเท่านั้น จึงคำนวณบน ESP32 ได้แบบ real-time

{tbl(feat_rows, ['f', 'g', 'd'], ['feature', 'กลุ่ม', 'ความหมาย'])}

ตัด `temp_f` และ heat index ออก เพราะคำนวณมาจากอุณหภูมิและความชื้นโดยตรง ส่วน LDR ใช้เฉพาะเพื่อวัดผลของ leakage เพราะค่าสะท้อนสถานะ LED ที่ผู้ทดลองเปิดตาม label

## 4. การออกแบบ validation

![pipeline](figures/ml1_pipeline.png)

- **Test set** คือวันที่ 4 ทั้งวัน ใช้ประเมินครั้งเดียวหลังตัดสินใจทุกอย่างแล้ว
- **การตัดสินใจทุกอย่าง** (ชนิดโมเดล, ชุด feature, ความลึก, threshold) ใช้ **leave-one-day-out (LODO)** บน train: เทรน 2 วัน ทดสอบวันที่เหลือ วน 3 รอบ แล้วรวมผล
- **ไม่สุ่มแบ่งแถว** เพราะ window ที่ติดกันมีค่าเกือบเหมือนกัน (ACF ของจำนวนคนจากกล้องที่ระยะ 10 วินาทีเท่ากับ 0.93) การสุ่มจะทำให้ผลดีเกินจริง
- **กติกาเลือก**: เลือกตัวที่ F1 ของ LODO สูงสุด ถ้ามีหลายตัวต่างกันไม่เกิน 0.002 ให้เลือกตัวที่เล็กหรือง่ายที่สุด เพราะต้องรันบน ESP32

## 5. Baseline และการเปรียบเทียบโมเดล

เทียบบนชุด feature กล้อง + ประตู ด้วย LODO บน train (threshold 0.5)

![models](figures/ml2_models.png)

{tbl(cmp_rows, ['m', 'f1', 'rc', 'pc', 'fp', 'fn'], ['โมเดล', 'F1', 'recall', 'precision', 'FP', 'FN'])}

Decision Tree ได้ F1 สูงสุด ({f3(R['family_choice']['lodo_f1'])}) และเล็กที่สุดในกลุ่ม ML จึงถูกเลือก Random Forest ใกล้เคียงแต่ใหญ่กว่าหลายสิบเท่า ส่วน rule "กล้องเห็นคนใน window นี้" ได้ recall ต่ำ เพราะตัดไฟทันทีที่กล้องพลาดไป 1 window

## 6. Ablation: เซนเซอร์กลุ่มไหนช่วย

ใช้ Decision Tree depth 4 เท่ากันทุกชุด

![ablation](figures/ml3_ablation.png)

{tbl(abl_rows, ['s', 'n', 'lf', 'tf', 'tr', 'tp'], ['ชุด feature', 'จำนวน', 'F1 LODO', 'F1 test', 'recall test', 'precision test'])}

- **ประตูไม่ช่วย**: B ได้ F1 LODO สูงกว่า A เพียง {abs(R['ablation'][1]['lodo_f1'] - R['ablation'][0]['lodo_f1']):.3f} ซึ่งอยู่ในเกณฑ์ 0.002 จึงเลือก A ที่ใช้ feature น้อยกว่า
- **อุณหภูมิ ความชื้น MQ-2 ทำให้แย่ลง** (C) เพราะในกล่องจำลองค่าเหล่านี้เปลี่ยนตามแอร์และ heater ไม่ใช่ตามคน
- **LDR ได้ F1 LODO สูงสุด** (D) แต่ตัดออกตั้งแต่ต้น เพราะเป็น leakage: ระบบจริงที่โมเดลเป็นคนสั่งเปิดไฟ ค่า LDR จะสะท้อนการตัดสินใจของโมเดลเอง ไม่ใช่การมีคน
- ชุด C และ D ถูกตัดออกตั้งแต่ขั้น EDA และแสดงไว้เพื่อยืนยันเท่านั้น ไม่ได้ใช้ในการเลือก

## 7. โมเดลสุดท้าย

ความลึกของต้นไม้บนชุด A (LODO):

{tbl(depth_rows, ['d', 'f1', 'rc', 'pc'], ['max_depth', 'F1', 'recall', 'precision'])}

depth 2 ได้ F1 สูงสุด จึงถูกเลือก threshold ที่ให้ recall ≥ 0.99 บน OOF ได้ {R['threshold']['value']} (เท่ากับ 0.5 ในทางปฏิบัติ เพราะใบของต้นไม้มีความน่าจะเป็นแค่ไม่กี่ค่า)

![rule](figures/ml4_rule.png)

ต้นไม้ที่ได้:

```
{R['tree_text'].strip()}
```

split ที่สองไม่เปลี่ยนคำตอบ ต้นไม้จึงเท่ากับกฎ `power_on = (since_cam_s <= 35)` จุดตัด 35 วินาทีมีเหตุผล: label มี grace 30 วินาที และ window ยาว 10 วินาที กราฟซ้ายแสดงว่าค่าที่สั้นกว่านี้ทำให้ recall ตก ส่วนค่าที่ยาวกว่านี้ทำให้ precision ตก

**ประโยชน์ของ ML ในงานนี้** คือหาค่า 35 วินาทีจากข้อมูล แทนการเดา และยืนยันว่าเซนเซอร์อื่นไม่ช่วย ซึ่งช่วยตัดอุปกรณ์ที่ไม่จำเป็นออกได้

**Feature importance** (permutation บน test, 30 รอบ): `since_cam_s` ลด F1 ได้ {pi[0]['mean']:.3f} เมื่อถูกสลับค่า ส่วน feature อื่นทั้งหมดได้ 0 ยืนยันว่าโมเดลใช้ feature เดียว (ไม่ได้ใช้ SHAP เพราะโมเดลมี split ที่มีผลเพียงจุดเดียว อ่านจากต้นไม้ได้ตรงกว่า)

## 8. ผลบน test (วันที่ 4)

{tbl(test_rows, ['m', 'f1', 'rc', 'pc', 'on', 'dark', 'sw'], ['วิธี', 'F1', 'recall', 'precision', 'ไฟเปิดทิ้ง (นาที)', 'ตัดไฟใส่คน (นาที)', 'จำนวนครั้งเปิด/ปิด (ทำนาย / จริง)'])}

Confusion matrix ของโมเดลสุดท้าย:

| | ทำนาย 0 | ทำนาย 1 |
| --- | --- | --- |
| **จริง 0** | {fin['tn']} | {fin['fp']} |
| **จริง 1** | {fin['fn']} | {fin['tp']} |

![test timeline](figures/ml5_test_timeline.png)

- ผลบน test ({f3(fin['f1'])}) ต่ำกว่า LODO ({f3(R['threshold']['oof_at_thr']['f1'])}) เพราะวันที่ 4 มีกรณีลืมคีมในกล่องขณะห้องว่าง ซึ่งไม่มีใน train
- เทียบกับ rule ที่ใช้กล้องอย่างเดียว: โมเดลลดเวลาตัดไฟใส่คนจาก {rule['dark_while_occupied_min']:.1f} นาที เหลือ 0 นาที โดยไฟเปิดทิ้งเท่าเดิม ({rule['on_while_empty_min']:.1f} → {fin['on_while_empty_min']:.1f} นาที)
- เทียบกับ rule "กล้องเห็นคนภายใน 1 นาที": recall เท่ากัน แต่โมเดลเปิดไฟทิ้งน้อยกว่า ({r1m['on_while_empty_min']:.1f} → {fin['on_while_empty_min']:.1f} นาที) เพราะใช้เวลาค้าง 35 วินาทีแทน 60

## 9. Error analysis ตามกรณีพิเศษ

ค่าในตารางคือ FP / FN (จำนวน window) ของแต่ละกรณี window หนึ่งอยู่ได้หลายกรณี

![errors](figures/ml6_errors.png)

{tbl(err_rows, ['c', 'n', 'l1', 'rule', 'mdl', 'oof'], ['กรณี', 'window (test)', 'label = 1', 'Rule กล้อง', 'โมเดล (test)', 'โมเดล (train, LODO)'])}

- **โมเดลแก้ได้**: grace หลังคนออก, กล้องหลุดสั้น ๆ, กลุ่มถัดไปเข้าทันที และคนออกชั่วคราว ทั้งหมดได้ประโยชน์จากการค้างไฟ 35 วินาที
- **โมเดลแก้ไม่ได้**: ลืมคีมในกล่องขณะห้องว่าง ({n_fp_pliers} FP) กล้องเห็นคีมเป็นคนตลอด และใน train ไม่มีกรณีนี้ (กรณีเดียวใน train เกิดขณะมีคน จึงไม่ทำให้ผิด) เซนเซอร์ประตูก็ช่วยไม่ได้ เพราะคีมถูกลืมไว้ตอนคีบตุ๊กตาตัวสุดท้ายออก ประตูจึงมีกิจกรรมอยู่แล้วในช่วงนั้น
- **มือในกล่องตอนห้องว่าง**: ผิด 2 จาก 3 window เพราะกล้องเห็นมือก่อนตุ๊กตาตัวแรกเข้า ผลคือเปิดไฟเร็วไปไม่กี่วินาที ไม่ใช่ปัญหาในการใช้งาน
- **ตุ๊กตาในมุมอับ**: วันทดสอบไม่ผิดเลย เพราะทุกครั้งมีตุ๊กตาตัวอื่นที่กล้องเห็นอยู่ด้วย แต่ใน train ตัดไฟใส่คน {eo['ตุ๊กตาอยู่มุมอับ']['fn']} window เกือบทั้งหมดเกิดตอนที่ในห้องเหลือตุ๊กตาตัวเดียวและตัวนั้นอยู่มุมอับ กล้องจึงไม่เห็นใครเลยนานสูงสุด 2 นาที นี่คือจุดอ่อนจริงของการใช้กล้องตัวเดียว

## 10. Threshold และ hysteresis

hysteresis คือรอให้โมเดลทำนาย 0 ติดกัน k window ก่อนตัดไฟ

{tbl(hy_rows, ['k', 'h', 'f1', 'pc', 'on', 'sw'], ['k', 'ค้างเพิ่ม (วินาที)', 'F1', 'precision', 'ไฟเปิดทิ้ง (นาที)', 'จำนวนครั้งเปิด/ปิด'])}

hysteresis ไม่ช่วย เพราะโมเดลค้างไฟ 35 วินาทีอยู่แล้ว ไม่มีการเปิดปิดกะพริบ (18 ครั้ง เทียบกับของจริง 20 ครั้ง) การค้างเพิ่มทำให้ไฟเปิดทิ้งนานขึ้นอย่างเดียว จึงใช้ k = 1 (ไม่มี hysteresis)

## 11. ระบบเตือนไฟไหม้ (hard rule)

| วัน | การทดสอบ | `alarm` ติดหลังเริ่ม (วินาที) | หลัง debounce 2 s (วินาที) |
| --- | --- | --- | --- |
{chr(10).join(f"| {r['d']} | {r['k']} | {r['a']} | {r['b']} |" for r in h3_rows)}

- `alarm` ติดครบทั้ง 8 ครั้ง ภายใน 2 วินาทีสำหรับไฟแช็กและแก๊ส และ 19.4 วินาทีสำหรับธูป (ควันต้องสะสมจนเกิน threshold)
- วันที่ 4 มี alarm หลอกจากแดด 7 ครั้ง (11 แถว) เมื่อกำหนดให้ `flame_do` ต้องเป็น 0 ติดกัน 4 แถว (2 วินาที) alarm หลอกหายทั้งหมด แลกกับการเตือนไฟแช็กช้าลงประมาณ 1.5 วินาที

## 12. การนำไปใช้บน ESP32

| รายการ | ผล |
| --- | --- |
| Export | `micromlgen` แปลงต้นไม้เป็น `PowerModel.h` ขนาด {V['header_bytes']} bytes |
| ตรวจความถูกต้อง | คอมไพล์ด้วย g++ แล้วป้อน feature ของ test ทั้ง {V['n']:,} window ผลตรงกับ Python {V['match_vs_threshold']:,}/{V['n']:,} |
| ขนาดโค้ดที่คอมไพล์แล้ว | 110 bytes (x86, `-Os`) ยังไม่ได้วัดบน ESP32 |
| Feature ที่ต้องคำนวณบนบอร์ด | ตัวเดียว: นับวินาทีนับจากครั้งล่าสุดที่กล้องส่ง `person_count ≥ 1` |

โค้ดบน ESP32 ที่เทียบเท่าโมเดล:

```cpp
// เรียกทุก 10 วินาที (จบ 1 window)
if (camMaxInWindow >= 1) secSinceCam = 0;
else if (cameraOk)       secSinceCam += 10;
// ถ้ากล้องหลุด (cameraOk == false) ไม่นับเพิ่ม เพื่อไม่ให้ไฟดับใส่คน

bool powerOn = (secSinceCam <= 35);
bool relay   = powerOn && !alarmDebounced;   // ไฟไหม้ตัดไฟเสมอ
```

**ข้อเสนอเรื่อง fail-safe**: โมเดลที่เทรนมาให้ `since_cam_s` นับต่อแม้กล้องไม่ส่งข้อมูล ถ้ากล้องหลุดนานกว่า 35 วินาทีขณะมีคน ไฟจะดับ (เกิดใน train 1 window ช่วงกล้องหลุด 45 วินาทีของวันที่ 2) โค้ดข้างบนจึงหยุดนับขณะกล้องหลุด

## 13. ทบทวนสมมติฐาน

| | สมมติฐาน | ผล |
| --- | --- | --- |
| H1 | กล้อง + เซนเซอร์ประตูได้ F1 ≥ 0.90 ในวันที่ไม่เคยเห็น | **สนับสนุน** F1 {f3(fin['f1'])} แต่กล้องอย่างเดียวก็ได้ผลเท่ากัน เซนเซอร์ประตูไม่จำเป็น |
| H2 | อุณหภูมิและความชื้นไม่ช่วยในห้องจำลอง | **สนับสนุน** F1 LODO ลดจาก {f3(R['ablation'][1]['lodo_f1'])} เป็น {f3(R['ablation'][2]['lodo_f1'])} เมื่อเพิ่มเข้าไป |
| H3 | `alarm` ติดทุกการทดสอบภายใน 20 วินาที | **สนับสนุน** 8/8 ครั้ง (ช้าสุด 19.4 วินาทีที่ธูป) แต่ต้องเพิ่ม debounce เพื่อกัน alarm หลอกจากแดด |

## 14. ข้อจำกัดและงานต่อไป

1. **Test มีเพียง 1 วัน** ผลอาจเปลี่ยนมากเมื่อเจอกรณีใหม่ เช่นที่เกิดกับคีมในกล่อง ควรเก็บข้อมูลอย่างน้อย 2–3 สัปดาห์ แล้วใช้ forward-chaining validation
2. **ข้อมูลจำลองแยกง่ายเกินจริง**: นอกจากกรณีมุมอับ กล้องในแบบจำลองแทบไม่พลาดนานเกิน 35 วินาที ข้อมูลจริงอาจพลาดบ่อยกว่านี้ ซึ่งจะทำให้เซนเซอร์ประตูมีประโยชน์ขึ้น
3. **ตุ๊กตาไม่ปล่อยความร้อนหรือเสียง**: ข้อสรุปว่าอุณหภูมิไม่ช่วยใช้ได้กับกล่องเท่านั้น ในห้องจริงควรทดสอบซ้ำ และควรเพิ่มไมโครโฟนวัดเสียงสนทนา
4. **กรณีของที่ลืมไว้ในห้อง** แก้ด้วยโมเดลนี้ไม่ได้ ต้องเก็บตัวอย่างลงใน train หรือเทรนกล้องใหม่ให้แยกคนออกจากสิ่งของ
5. **ยังไม่ได้วัดบน ESP32 จริง**: ต้องวัด RAM, เวลา และยืนยันว่า `since_cam_s` ที่คำนวณบนบอร์ดตรงกับใน Python
6. **ควรวัดผลด้วยตัวชี้วัดของผู้ใช้**: นาทีที่ไฟเปิดทิ้ง (พลังงาน) และจำนวนครั้งที่ไฟดับใส่คน (ความรำคาญ) มีความหมายกว่า F1 เมื่อรายงานต่อผู้ใช้งานจริง
"""
open("ML_REPORT.md", "w").write(md)


def emb(m):
    b = base64.b64encode(open(m.group(2), "rb").read()).decode()
    return f"![{m.group(1)}](data:image/png;base64,{b})"


open("ML_REPORT_embedded.md", "w").write(re.sub(r"!\[([^\]]*)\]\((figures/[^)]+\.png)\)", emb, md))
print("ok", len(md))
