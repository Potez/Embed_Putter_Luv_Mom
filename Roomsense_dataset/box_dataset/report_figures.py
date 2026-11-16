#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""รูปสำหรับ RoomSense_dataset.md: fig_schema.png + fig_day{1..4}.png และตารางกรณีพิเศษ (markdown -> stdout)
Run (ในโฟลเดอร์ box_dataset/):  python report_figures.py
"""
import glob
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.lines import Line2D

OUT = "figures"
os.makedirs(OUT, exist_ok=True)
SURF, INK, INK2, MUTED, AXIS, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#c3c2b7", "#ebeae6"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"
plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF, "font.family": ["Sukhumvit Set", "DejaVu Sans"],  # ponytail: Thonburi วาดสระ/วรรณยุกต์เป็นวงกลมประ
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "legend.frameon": False,
})

# ---- ประเภทกรณีพิเศษ: (ชื่อไทย, สี) ----
CAT = {
    "late": ("มาสาย", VIOLET), "early": ("ออกก่อน", MAGENTA), "return": ("ออกแล้วกลับเข้ามา", BLUE),
    "b2b": ("กลุ่มถัดไปเข้าทันที", AQUA), "short": ("แวะสั้น", AQUA), "full": ("เต็มห้อง 6 ตัว", BLUE),
    "forgot": ("ลืมปิดไฟ", YELLOW), "fire": ("ทดสอบไฟ/แก๊ส/ควัน", RED), "pliers": ("ลืมคีมในกล่อง", ORANGE),
    "cam": ("กล้องไม่ส่งข้อมูล", ORANGE), "reset": ("บอร์ดรีเซ็ต", INK2), "ac": ("ปิดแอร์ห้องแล็บ", INK2),
    "sun": ("แดด: flame หลอก", RED),
}
TEST_TH = {"flame": "ไฟแช็ก", "gas": "แก๊สไฟแช็ก (ไม่จุด)", "smoke": "ธูป"}
DAY_TH = {"Tue": "อังคาร", "Wed": "พุธ", "Thu": "พฤหัสบดี", "Fri": "ศุกร์"}


def t2s(hms):  # "13:12:05.0" -> seconds of day
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def s2hm(s):
    s = int(round(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def episodes(ev):
    """แบ่งรอบจองจาก fig_in/fig_out (count ใน note) + หากรณีพิเศษในแต่ละรอบ"""
    f = ev[ev.event.isin(["fig_in", "fig_out"])].copy()
    f["count"] = f.note.str.extract(r"count=(\d+)").astype(int)
    eps, cur = [], None
    for r in f.itertuples():
        if cur is None:
            cur = []
        cur.append((r.t, r.event, r.count))
        if r.count == 0:
            eps.append(cur)
            cur = None
    out = []
    for seq in eps:
        outs = [t for t, e, _ in seq if e == "fig_out"]
        # ชุดออกตอนจบ: ไล่ย้อนจากตัวสุดท้าย ห่างกันไม่เกิน 10.5 s
        final = [outs[-1]]
        for t in reversed(outs[:-1]):
            if final[-1] - t <= 10.5:
                final.append(t)
            else:
                break
        early, ret, late = [], [], []
        ins = [(t, c) for t, e, c in seq if e == "fig_in"]
        t0 = ins[0][0]
        for i, (t, e, c) in enumerate(seq):
            if e == "fig_out" and t not in final:
                nxt = seq[i + 1]
                if nxt[1] == "fig_in" and nxt[0] - t <= 130:
                    ret.append((t, nxt[0]))
                else:
                    early.append(t)
        reentry = {b for _, b in ret}
        on_time = [t for t, _ in ins if t not in reentry]
        prev = t0
        for t in on_time[1:]:
            if t - prev > 40:      # ปกติห่างกัน 3–15 s, มาสาย +60–180 s
                late.append(t)
            else:
                prev = t
        out.append(dict(t0=t0, t1=outs[-1], n=max(c for _, _, c in seq), n_in=len(ins),
                        early=early, ret=ret, late=late))
    return out


def load_day(path_ev):
    tag = os.path.basename(path_ev).replace("_events.csv", "")
    day = int(tag[3])
    ev = pd.read_csv(path_ev)
    ev["t"] = ev.wall_time.map(t2s)
    gt = pd.read_csv(f"ground_truth/{tag}_truth.csv")
    gt["t"] = gt.wall_time.map(t2s)
    split = "test" if day == 4 else "train"
    csv = pd.read_csv(f"{split}.csv")
    csv = csv[csv.day == day]
    gt = gt.merge(csv[["boot", "timestamp_ms", "person_count", "flame_do", "alarm", "power_on"]],
                  on=["boot", "timestamp_ms"], how="left")
    return tag, day, ev, gt


def lab_at(gt, t):
    return int(gt.power_on_label.iloc[np.searchsorted(gt.t.values, t).clip(0, len(gt) - 1)])


def cases(day, ev, gt, eps, issues):
    """รายการกรณีพิเศษ เรียงตามเวลา: (t_start, t_end, cat, รายละเอียด, label)"""
    C = []
    for k, e in enumerate(eps, 1):
        for t in e["late"]:
            C.append((t, None, "late", f"รอบ {k}: ตุ๊กตามาช้ากว่ากลุ่ม {(t - e['t0']) / 60:.1f} นาที", "1 (รอบเริ่มไปแล้ว)"))
        for t in e["early"]:
            left = int(gt.true_count.iloc[np.searchsorted(gt.t.values, t + 2)])
            C.append((t, None, "early", f"รอบ {k}: ตุ๊กตา 1 ตัวออกก่อนจบรอบ (เหลือ {left} ตัว)", "1 (ยังมีคนในห้อง)"))
        for a, b in e["ret"]:
            C.append((a, b, "return", f"รอบ {k}: ตุ๊กตา 1 ตัวออกไป {b - a:.0f} s แล้วกลับเข้ามา", "1 ตลอด (ตัวอื่นยังอยู่)"))
        if e["n"] == 6:
            C.append((e["t0"], e["t1"], "full", f"รอบ {k}: ตุ๊กตา 6 ตัว (กล้องนับยากสุด)", "1"))
        if e["t1"] - e["t0"] < 180:
            C.append((e["t0"], e["t1"], "short", f"รอบ {k}: แวะสั้น 1 ตัว {(e['t1'] - e['t0']) / 60:.1f} นาที", "1 สั้น ๆ แล้ว 0"))
        if k < len(eps) and eps[k]["t0"] - e["t1"] <= 30:
            gap = eps[k]["t0"] - e["t1"]
            seg = gt[(gt.t >= e["t1"]) & (gt.t <= eps[k]["t0"])]
            C.append((e["t1"], eps[k]["t0"], "b2b", f"รอบ {k} → {k + 1}: ห้องว่างแค่ {gap:.0f} s",
                      f"{seg.power_on_label.min()} ต่อเนื่อง ไม่ตกเป็น 0 (ห้องว่าง < 30 s)"))
    for r in ev[ev.event == "led_off"].itertuples():
        if "ลืมปิดไฟ" in str(r.note):
            last = max(e["t1"] for e in eps if e["t1"] <= r.t)
            C.append((last, r.t, "forgot", f"LED เปิดค้าง {(r.t - last) / 60:.1f} นาทีหลังห้องว่าง",
                      "0 หลังห้องว่าง 30 s (LED ยังเปิด)"))
    for kind in ("flame", "gas", "smoke"):
        s = ev[ev.event == f"{kind}_test_start"].t.values
        e_ = ev[ev.event == f"{kind}_test_end"].t.values
        for a, b in zip(s, e_):
            cnt = int(gt.true_count.iloc[np.searchsorted(gt.t.values, a)])
            win = gt[(gt.t >= a) & (gt.t <= b + 30)]
            al = "alarm ติด" if win.alarm.max() == 1 else "alarm ไม่ติด"
            who = f"มีตุ๊กตา {cnt} ตัว" if cnt else "ห้องว่าง"
            C.append((a, b, "fire", f"ทดสอบ{TEST_TH[kind]} {b - a:.0f} s ({who}), {al}",
                      f"{lab_at(gt, a)} (label ไม่สนไฟไหม้ ใช้ alarm แยก)"))
    for r in ev[ev.event == "board_reset"].itertuples():
        C.append((r.t, None, "reset", "บอร์ดรีเซ็ต (ไฟตก) ข้อมูลหาย ~3 s, timestamp_ms เริ่มนับใหม่", str(lab_at(gt, r.t))))
    for r in ev[ev.event == "room_ac_off"].itertuples():
        C.append((r.t, None, "ac", "ปิดแอร์ห้องแล็บ อุณหภูมิในกล่องค่อย ๆ ขึ้น", "ไม่เกี่ยว"))
    for r in issues.itertuples():
        if "คีม" in r.issue:
            t = t2s(r.time)
            mins = float(r.issue.split("~")[1].split()[0])
            C.append((t, t + mins * 60, "pliers", f"ลืมคีมในกล่อง {mins:.0f} นาที กล้องนับคีมเป็นคน",
                      f"{lab_at(gt, t + 60)} (label มาจาก event log ไม่ใช่กล้อง)"))
        elif "กล้องไม่ส่ง" in r.issue:
            t = t2s(r.time)
            secs = float(r.issue.split("~")[1].split()[0])
            C.append((t, t + secs, "cam", f"กล้องไม่ส่งข้อมูล {secs:.0f} s (person_count = -1)", str(lab_at(gt, t))))
    # แดดทำให้ flame_do = 0 นอกช่วงทดสอบ
    tests = [(a, b) for a, b, c, *_ in C if c == "fire"]
    fl = gt[(gt.flame_do == 0)]
    fl = fl[[not any(a - 2 <= t <= b + 15 for a, b in tests) for t in fl.t]]
    if len(fl):
        grp = (fl.t.diff() > 5).cumsum()
        for _, g in fl.groupby(grp):
            C.append((g.t.iloc[0], None, "sun", f"แดดส่อง flame_do = 0 หลอก {len(g) * 0.5:.1f} s → alarm หลอก",
                      str(lab_at(gt, g.t.iloc[0]))))
    return sorted(C, key=lambda c: c[0])


# ============================== day figure ==============================
def day_fig(tag, day, ev, gt, eps, C, sess):
    t = gt.t.values / 3600  # ชั่วโมงของวัน
    fig, ax = plt.subplots(5, 1, figsize=(16, 7.6), sharex=True,
                           gridspec_kw=dict(height_ratios=[0.55, 2.0, 0.6, 0.6, 1.25], hspace=0.12))
    names = ["รอบจอง", "จำนวนตุ๊กตา\n(ตัว)", "label\npower_on", "ไฟ LED", "กรณีพิเศษ\n& ทดสอบไฟ"]
    for a, n in zip(ax, names):
        a.set_ylabel(n, rotation=0, ha="right", va="center", fontsize=10.5, color=INK, labelpad=10)
        a.tick_params(left=False)
        a.grid(axis="x", color=GRID, lw=0.6)
        a.spines["left"].set_visible(False)
        a.axvspan(t[0], ev[ev.event == "warmup_done"].t.iloc[0] / 3600, color=GRID, zorder=0)
    
    # ① รอบจอง
    for k, e in enumerate(eps, 1):
        x0, x1 = e["t0"] / 3600, e["t1"] / 3600
        ax[0].add_patch(FancyBboxPatch((x0, 0.15), x1 - x0, 0.7, boxstyle="round,pad=0,rounding_size=0.004",
                                       fc="#dedcd5", ec="none"))
        ax[0].text((x0 + x1) / 2, 0.5, str(k), ha="center", va="center", fontsize=10, weight="bold", color=INK)
    ax[0].set_ylim(0, 1); ax[0].set_yticks([])

    # ② จำนวนตุ๊กตา
    ax[1].fill_between(t, gt.true_count, step="post", color=BLUE, alpha=0.22, lw=0)
    ax[1].step(t, gt.true_count, where="post", color=BLUE, lw=1.4, label="จำนวนจริง (ground truth)")
    pc = gt.person_count.where(gt.person_count >= 0)
    ax[1].plot(t, pc.rolling(20, min_periods=1).median(), color=ORANGE, lw=0.9, alpha=0.85,
               label="กล้องนับได้ (person_count)")
    ax[1].set_ylim(0, 7.2); ax[1].set_yticks(range(0, 7, 2))
    ax[1].tick_params(left=True); ax[1].grid(axis="y", color=GRID, lw=0.6)
    ax[1].legend(loc="upper right", fontsize=9, ncol=2, bbox_to_anchor=(1, 1.12))

    # ③ label
    ax[2].fill_between(t, gt.power_on_label, step="post", color=GREEN, alpha=0.75, lw=0)
    ax[2].set_ylim(0, 1); ax[2].set_yticks([0.5]); ax[2].set_yticklabels(["1 = จ่ายไฟ"], fontsize=8.5, color=GREEN)

    # ④ LED (+ ช่วงลืมปิดไฟ)
    ax[3].fill_between(t, gt.led_on, step="post", color=YELLOW, alpha=0.8, lw=0)
    for a, b, c, *_ in C:
        if c == "forgot":
            ax[3].axvspan(a / 3600, b / 3600, ymax=1, fc="none", ec=RED, hatch="////", lw=0)
            ax[3].text((a + b) / 7200, 1.08, "ลืมปิดไฟ", color=RED, fontsize=9, ha="center", va="bottom")
    ax[3].set_ylim(0, 1); ax[3].set_yticks([0.5]); ax[3].set_yticklabels(["เปิด"], fontsize=8.5, color="#a87300")

    # ⑤ กรณีพิเศษ: หมายเลขวงกลม สีตามประเภท, ช่วงเวลาเป็นแถบ
    levels, last_x = [2.2, 1.2, 0.2], [-1] * 3
    for i, (a, b, c, *_rest) in enumerate(C, 1):
        x = a / 3600
        lv = next((j for j in range(3) if x - last_x[j] > 0.045), int(np.argmin(last_x)))
        last_x[lv] = x
        y = levels[lv] + 0.45
        col = CAT[c][1]
        if b is not None and b - a > 20:
            ax[4].plot([x, b / 3600], [y, y], color=col, lw=5, alpha=0.35, solid_capstyle="butt")
        ax[4].scatter([x], [y], s=210, color=col, zorder=3, ec="white", lw=0.8)
        ax[4].text(x, y, str(i), color="white", fontsize=8, weight="bold", ha="center", va="center", zorder=4)
        if c == "fire":
            for a_ in ax[1:4]:
                a_.axvline(x, color=RED, lw=1.0, ls="--", alpha=0.8)
    for r in ev[ev.event == "arrange"].itertuples():
        ax[4].plot([r.t / 3600], [0.05], marker="^", ms=5, color=MUTED, ls="none")
    ax[4].set_ylim(-0.1, 3.2); ax[4].set_yticks([])

    used = list(dict.fromkeys(c for _, _, c, *_ in C))
    h = [Line2D([], [], marker="o", ls="none", ms=9, color=CAT[c][1], label=CAT[c][0]) for c in used]
    h.append(Line2D([], [], marker="^", ls="none", ms=6, color=MUTED, label="ขยับตุ๊กตา (จำนวนไม่เปลี่ยน)"))
    h.append(Patch(color=GRID, label="warm-up MQ-2 (ห้องว่าง)"))
    fig.legend(handles=h, loc="lower center", ncol=min(len(h), 7), fontsize=9.5, bbox_to_anchor=(0.5, 0.0))

    lo, hi = t[0], t[-1]
    ticks = np.arange(np.ceil(lo * 4) / 4, hi + 1e-9, 0.25)
    ax[4].set_xticks(ticks)
    ax[4].set_xticklabels([s2hm(x * 3600) for x in ticks])
    ax[4].set_xlim(lo, hi)
    ax[4].set_xlabel("เวลา (นาฬิกา)")
    s = sess
    fig.suptitle(f"วันที่ {day} ({s.split.upper()}) · {DAY_TH[s.weekday]} {s.date} · {s.room}",
                 x=0.06, ha="left", fontsize=13, weight="bold", y=0.97)
    fig.subplots_adjust(left=0.095, right=0.99, top=0.91, bottom=0.2)
    fig.savefig(f"{OUT}/fig_day{day}.png", dpi=110)
    plt.close(fig)


# ============================== schema figure ==============================
def schema_fig():
    fig, ax = plt.subplots(figsize=(16, 7.4))
    ax.set_xlim(0, 100); ax.set_ylim(0, 60); ax.axis("off")

    def box(x, y, w, h, title, sub="", fc="#ffffff", ec=AXIS, tc=INK, fs=10.5):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=0.8", fc=fc, ec=ec, lw=1.2))
        ax.text(x + w / 2, y + h - (0.6 if h < 6 else 1.6), title, ha="center", va="top", fontsize=fs, weight="bold", color=tc)
        if sub:
            ax.text(x + w / 2, y + h - (3.0 if h < 6 else 4.4), sub, ha="center", va="top", fontsize=8.8, color=INK2, linespacing=1.35)

    def arrow(x0, y0, x1, y1, text="", col=INK2):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="-|>", color=col, lw=1.4))
        if text:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.9, text, ha="center", va="bottom", fontsize=8.6, color=col)

    ax.text(0, 59, "แหล่งที่มาของแต่ละคอลัมน์ใน train.csv / test.csv", fontsize=13, weight="bold", va="top")
    sensors = [
        ("MQ-2", "ใต้ฝากล่อง", "mq2_raw"), ("Flame sensor", "ผนังหลัง หันหาหน้าต่าง", "flame_do"),
        ("IR obstacle FC-51", "ข้างกรอบประตู", "digital_do"), ("DHT22", "ผนังข้าง", "temp_c, humidity"),
        ("LDR", "ผนังข้าง หันเข้าใน", "analog_1_raw"), ("Gray TCRT5000", "พื้นธรณีประตู", "analog_2_raw"),
        ("กล้อง ESP32-S3 + FOMO", "กลางฝา มองลง (UART ~3 fps)", "person_count"),
    ]
    y0 = 49.6
    for i, (n, pos, col) in enumerate(sensors):
        y = y0 - i * 5.9
        box(1, y, 22, 5.0, n, pos, fs=9.8)
        ax.text(24.2, y + 2.5, "→ " + col, va="center", fontsize=9.5, color=BLUE, family="monospace")
        arrow(37.5, y + 2.5, 41.5, 31, col=AXIS)

    box(42, 21.5, 15, 19, "ESP32 logger", "อ่านทุก 500 ms (2 Hz)\n\nคำนวณใน firmware:\ntemp_f, heat_index_c/f\nalarm = flame_do==0\n   หรือ mq2_raw > 700\n\n+ timestamp_ms (millis)")
    arrow(57.6, 31, 62.5, 31, "USB serial\n115200 baud")
    box(63, 25, 14, 12, "raw/dayN.csv", "1 ไฟล์ต่อวัน\nมี boot log, header ซ้ำ,\nบรรทัดขาด")
    arrow(77.6, 31, 82.5, 31, "parse +\nday, boot")
    box(83, 22, 16, 18, "train.csv / test.csv", "train = วัน 1–3, test = วัน 4\n1 แถว = 0.5 วินาที\n16 คอลัมน์ = feature + label", fc="#eef4fc", ec=BLUE)

    # label path
    box(1, 3, 22, 7.5, "ผู้ทดลอง", "กดปุ่มบน laptop ทุกครั้งที่คีบตุ๊กตา\nfig_in / fig_out / led_on / test", fc="#eef7ee", ec=GREEN, tc=GREEN)
    arrow(23.6, 6.8, 42.5, 6.8, "event logger")
    box(43, 3, 18, 7.5, "events/dayN_events.csv", "wall_time, event, note(count=N)", fc="#eef7ee", ec=GREEN, tc=GREEN)
    ax.plot([61.6, 83.5], [6.8, 6.8], color=GREEN, lw=1.6)
    ax.text(72, 8.2, "power_on = 1 ตั้งแต่ fig_in ตัวแรก\nถึง 30 s หลัง fig_out ที่ทำให้ห้องว่าง", ha="center",
            va="bottom", fontsize=9, color=GREEN)
    ax.annotate("", xy=(91, 21.7), xytext=(83.5, 6.8),
                arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.6, connectionstyle="angle,angleA=0,angleB=90"))
    ax.text(92, 14, "label\npower_on\n(merge ตามเวลา)", fontsize=9.5, color=GREEN, weight="bold", va="center")
    ax.text(42, 14.5, "label ไม่ได้มาจากเซนเซอร์ใด ๆ → ไม่มี leakage จาก feature", fontsize=9, color=MUTED)
    fig.savefig(f"{OUT}/fig_schema.png", dpi=110, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def main():
    sessions = pd.read_csv("sessions.csv").set_index("day")
    issues = pd.read_csv("known_issues.csv")
    schema_fig()
    for p in sorted(glob.glob("events/day*_events.csv")):
        tag, day, ev, gt = load_day(p)
        eps = episodes(ev)
        # self-check: นับจาก event log ต้องตรงกับรายงาน/sessions.csv
        assert len(eps) == sessions.loc[day, "episodes"], (day, len(eps))
        assert sum(e["n_in"] for e in eps) == {1: 33, 2: 34, 3: 40, 4: 39}[day]
        assert abs(gt.power_on.mean() - sessions.loc[day, "power_on_ratio"]) < 0.002
        C = cases(day, ev, gt, eps, issues[issues.day == day])
        day_fig(tag, day, ev, gt, eps, C, sessions.loc[day])
        print(f"\n#### ตารางกรณีพิเศษ วันที่ {day}\n")
        print("| # | เวลา | กรณี | สิ่งที่เกิด | label `power_on` ช่วงนั้น |\n| :-: | :-- | :-- | :-- | :-- |")
        for i, (a, b, c, d, lab) in enumerate(C, 1):
            tt = s2hm(a) + (f"–{s2hm(b)}" if b is not None and b - a >= 60 else "")
            print(f"| {i} | {tt} | {CAT[c][0]} | {d} | {lab} |")
        arr = ev[ev.event == "arrange"].wall_time.str[:5].tolist()
        print(f"\nขยับตุ๊กตา (▲ ในรูป, label ไม่เปลี่ยน): {len(arr)} ครั้ง เวลา {', '.join(arr)}")
        late = sum(len(e['late']) for e in eps); early = sum(len(e['early']) for e in eps)
        print(f"<!-- check: late={late} early={early} -->")


if __name__ == "__main__":
    main()
