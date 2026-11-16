#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""สร้างโฟลเดอร์ ../RoomSense_public/ สำหรับเผยแพร่ข้อมูล
Run (ในโฟลเดอร์ box_dataset/):  python export_public.py
ใช้ episodes()/cases() จาก report_figures.py เพื่อให้ตัวเลขตรงกับ RoomSense_dataset.md
"""
import glob
import os
import re
import shutil
import pandas as pd
from report_figures import CAT, episodes, cases, load_day

OUT = "../RoomSense_public"


def hms(s):
    return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:04.1f}"


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    for d in ("data", "bookings", "events", "raw", "ground_truth", "figures"):
        os.makedirs(f"{OUT}/{d}")
    shutil.copy("../RoomSense_dataset.md", OUT)
    for f in ("train.csv", "test.csv"):
        shutil.copy(f, f"{OUT}/data/{f}")
    for f in ("sessions.csv", "known_issues.csv"):
        shutil.copy(f, OUT)
    for d in ("events", "raw", "ground_truth", "figures"):
        for f in glob.glob(f"{d}/*"):
            shutil.copy(f, f"{OUT}/{d}/")

    issues = pd.read_csv("known_issues.csv")
    all_cases = []
    for p in sorted(glob.glob("events/day*_events.csv")):
        tag, day, ev, gt = load_day(p)
        eps = episodes(ev)
        C = cases(day, ev, gt, eps, issues[issues.day == day])

        on = ev[ev.event == "led_on"].t.values
        off = ev[ev.event == "led_off"]
        assert len(on) == len(off) == len(eps), (day, len(on), len(off), len(eps))
        rows = []
        for k, (e, a, b) in enumerate(zip(eps, on, off.itertuples()), 1):
            inside = [CAT[c][0] for t0, _, c, *_ in C if e["t0"] <= t0 <= e["t1"] and c not in ("full", "short")]
            arr = ((ev.event == "arrange") & ev.t.between(e["t0"], e["t1"])).sum()
            rows.append(dict(
                day=day, episode=k, start=hms(e["t0"]), end=hms(e["t1"]),
                duration_min=round((e["t1"] - e["t0"]) / 60, 1), max_figurines=e["n"], entries=e["n_in"],
                late=len(e["late"]), early_leave=len(e["early"]), left_and_returned=len(e["ret"]), arrange=int(arr),
                led_on=hms(a), led_off=hms(b.t), forgot_light="ลืมปิดไฟ" in str(b.note),
                other_cases="; ".join(sorted(set(inside) - {"มาสาย", "ออกก่อน", "ออกแล้วกลับเข้ามา"})),
            ))
        pd.DataFrame(rows).to_csv(f"{OUT}/bookings/{tag}_bookings.csv", index=False)

        # case_id ตรงกับหมายเลข # ในตารางกรณีพิเศษของ RoomSense_dataset.md
        for i, (a, b, c, d, lab) in enumerate(C, 1):
            ep = next((k for k, e in enumerate(eps, 1) if e["t0"] <= a <= e["t1"]), None)
            all_cases.append(dict(day=day, case_id=i, start=hms(a), end=hms(b) if b is not None else "",
                                  duration_s=round(b - a, 1) if b is not None else "", episode=ep or "",
                                  type=c, type_th=CAT[c][0], detail=d, power_on_label=lab))
        for r in ev[ev.event == "arrange"].itertuples():
            ep = next((k for k, e in enumerate(eps, 1) if e["t0"] <= r.t <= e["t1"]), "")
            all_cases.append(dict(day=day, case_id="", start=r.wall_time, end="", duration_s="", episode=ep,
                                  type="arrange", type_th="ขยับตุ๊กตา", detail=r.note, power_on_label="ไม่เปลี่ยน"))

    sc = pd.DataFrame(all_cases)
    sc["_t"] = sc.start.map(lambda s: tuple(float(x) for x in s.split(":")))
    sc.sort_values(["day", "_t"]).drop(columns="_t").to_csv(f"{OUT}/special_cases.csv", index=False)

    # self-check: จำนวนกรณีต่อวันต้องตรงกับตารางใน RoomSense_dataset.md
    md = open("../RoomSense_dataset.md", encoding="utf-8").read()
    n_md = [len(re.findall(r"^\| \d+ \| \d\d:\d\d", part.split("### ")[0], re.M))
            for part in re.split(r"\*\*กรณีพิเศษและการทดสอบไฟ\*\*", md)[1:]]
    n_csv = sc[sc.type != "arrange"].groupby("day").size().tolist()
    assert n_md == n_csv, (n_md, n_csv)
    print(f"ok -> {OUT}  cases/day={n_csv}")


if __name__ == "__main__":
    main()
