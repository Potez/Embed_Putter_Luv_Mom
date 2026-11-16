import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
from sklearn.metrics import f1_score, precision_score, recall_score
import os

os.makedirs("figures", exist_ok=True)
SURF, INK, INK2, MUTED, AXIS, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#c3c2b7", "#ebeae6"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"
plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF, "font.family": ["DejaVu Sans", "Loma"],
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
})
R = json.load(open("ml_results.json"))


def title(fig, t):
    fig.suptitle(t, x=0.01, ha="left", fontsize=12.5, weight="bold")


def box(ax, x, y, w, h, head, body, hl=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.1",
                                fc="#eaf2fc" if hl else "none", ec=BLUE if hl else AXIS, lw=1.6 if hl else 1.2))
    ax.text(x + w / 2, y + h - 0.32, head, ha="center", va="center", fontsize=9.8, weight="bold")
    ax.text(x + w / 2, y + (h - 0.55) / 2, body, ha="center", va="center", fontsize=8.4, color=INK2, linespacing=1.45)


# ---------- F1 pipeline ----------
fig = plt.figure(figsize=(12, 2.9)); ax = fig.add_axes([0.01, 0.01, 0.98, 0.82]); ax.axis("off")
ax.set_xlim(0, 12); ax.set_ylim(0, 2.3)
steps = [("1. Log 2 Hz", "train 64,787 แถว\ntest 21,597 แถว"),
         ("2. Window 10 s", "train 3,186\ntest 1,062\nตัด warm-up"),
         ("3. Features", "สถิติใน window\n+ ย้อนหลัง\n(อดีตเท่านั้น)"),
         ("4. เลือกด้วย LODO", "ชนิดโมเดล → ชุด feature\n→ ความลึก → threshold\n(ใช้วันที่ 1–3 เท่านั้น)"),
         ("5. ทดสอบครั้งเดียว", "เทรนวันที่ 1–3\nประเมินวันที่ 4"),
         ("6. Export C", "micromlgen\nเทียบผลกับ Python")]
w, gap = 1.75, 0.27
for i, (h, b) in enumerate(steps):
    x = 0.05 + i * (w + gap)
    box(ax, x, 0.1, w, 2.1, h, b, hl=i in (3, 4))
    if i < len(steps) - 1:
        ax.add_patch(FancyArrowPatch((x + w + 0.02, 1.15), (x + w + gap - 0.02, 1.15), arrowstyle="-|>",
                                     mutation_scale=11, color=MUTED))
title(fig, "Pipeline: ทุกการตัดสินใจใช้แค่วันที่ 1–3 ส่วนวันที่ 4 ถูกเปิดดูครั้งเดียวตอนท้าย")
fig.savefig("figures/ml1_pipeline.png", dpi=150); plt.close(fig)

# ---------- F2 model comparison ----------
cmp = pd.DataFrame(R["model_compare_lodo"])
cmp = cmp[cmp.model != "Majority (ทาย 0 เสมอ)"].iloc[::-1]
fig, ax = plt.subplots(figsize=(9, 3.6))
cols = [MUTED if m.startswith("Rule") else (BLUE if m.startswith("Decision") else "#9cc1ee") for m in cmp.model]
ax.barh(cmp.model, cmp.f1, color=cols, height=0.6)
for y, v in enumerate(cmp.f1):
    ax.text(v + 0.0008, y, f"{v:.3f}", va="center", fontsize=8.5)
ax.set_xlim(0.955, 0.995); ax.set_xlabel("F1 (leave-one-day-out บน train)"); ax.grid(axis="y", visible=False)
ax.set_title("Decision Tree ได้ F1 สูงสุดและเล็กที่สุดในกลุ่ม (ชุด feature กล้อง + ประตู)", loc="left", fontsize=10.5, weight="bold")
fig.tight_layout(); fig.savefig("figures/ml2_models.png", dpi=150); plt.close(fig)

# ---------- F3 ablation ----------
ab = pd.DataFrame(R["ablation"])
fig, ax = plt.subplots(figsize=(9, 3.8))
x = np.arange(len(ab))
ax.bar(x - 0.18, ab.lodo_f1, 0.34, color=BLUE, label="LODO (train)")
ax.bar(x + 0.18, ab.test_f1, 0.34, color=ORANGE, label="test (วันที่ 4)")
for i, (a, b) in enumerate(zip(ab.lodo_f1, ab.test_f1)):
    ax.text(i - 0.18, a + 0.0008, f"{a:.3f}", ha="center", fontsize=8); ax.text(i + 0.18, b + 0.0008, f"{b:.3f}", ha="center", fontsize=8)
ax.set_xticks(x, ab.set); ax.set_ylim(0.96, 0.995); ax.set_ylabel("F1"); ax.legend(loc="upper left", ncol=2)
ax.grid(axis="x", visible=False)
ax.set_title("ทุกชุด feature ได้ F1 ใกล้กัน (0.973–0.989): กล้องอย่างเดียวก็พอ", loc="left", fontsize=10.5, weight="bold")
fig.tight_layout(); fig.savefig("figures/ml3_ablation.png", dpi=150); plt.close(fig)

# ---------- F4 hold-time curve (train windows) + tree ----------
tr = pd.read_csv("windows_train.csv")
hs = np.arange(0, 125, 5)
f1s, rcs, pcs = [], [], []
for h in hs:
    p = (tr.since_cam_s <= h).astype(int)
    f1s.append(f1_score(tr.label, p)); rcs.append(recall_score(tr.label, p)); pcs.append(precision_score(tr.label, p))
fig, (a0, a1) = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw=dict(width_ratios=[1.25, 1]))
a0.plot(hs, rcs, color=ORANGE, lw=2, label="recall"); a0.plot(hs, pcs, color=AQUA, lw=2, label="precision")
a0.plot(hs, f1s, color=BLUE, lw=2.4, label="F1")
a0.axvline(35, color=INK2, ls="--", lw=1); a0.text(36.5, 0.905, "ต้นไม้เลือก 35 s", fontsize=8.5, color=INK)
a0.axvspan(0, 30, color=YELLOW, alpha=0.12, lw=0); a0.text(1.5, 0.905, "grace ของ label 30 s", fontsize=8, color=INK2)
a0.set_xlabel("เปิดไฟค้างไว้กี่วินาทีหลังกล้องเห็นคนครั้งสุดท้าย"); a0.set_ylim(0.9, 1.003); a0.legend(loc="lower right")
a0.set_title("กฎ \"since_cam_s ≤ h\" บน train วันที่ 1–3", loc="left", fontsize=10, weight="bold")
a1.axis("off"); a1.set_xlim(0, 10); a1.set_ylim(0, 6)
a1.add_patch(FancyBboxPatch((2.5, 4.2), 5, 1.2, boxstyle="round,pad=0,rounding_size=0.12", fc="#eaf2fc", ec=BLUE, lw=1.6))
a1.text(5, 4.8, "since_cam_s ≤ 35 s ?", ha="center", va="center", fontsize=11, weight="bold")
for xx, lab, txt, col in [(1.0, "ใช่", "power_on = 1\nจ่ายไฟ", BLUE), (5.8, "ไม่ใช่", "power_on = 0\nตัดไฟ", ORANGE)]:
    a1.add_patch(FancyBboxPatch((xx, 1.2), 3.2, 1.4, boxstyle="round,pad=0,rounding_size=0.12", fc="none", ec=col, lw=1.6))
    a1.text(xx + 1.6, 1.9, txt, ha="center", va="center", fontsize=10, weight="bold", linespacing=1.4)
    a1.add_patch(FancyArrowPatch((5, 4.15), (xx + 1.6, 2.65), arrowstyle="-|>", mutation_scale=12, color=MUTED))
    a1.text((5 + xx + 1.6) / 2 + (-0.5 if xx < 5 else 0.5), 3.45, lab, ha="center", fontsize=9, color=INK2)
a1.text(5, 0.45, "ต้นไม้ depth 2 มี 4 ใบ แต่ split ที่สองไม่เปลี่ยนคำตอบ\nจึงเหลือกฎเดียว", ha="center", fontsize=8.5, color=INK2)
a1.set_title("โมเดลสุดท้าย", loc="left", fontsize=10, weight="bold")
title(fig, "โมเดลที่เรียนได้คือ \"จ่ายไฟถ้ากล้องเห็นคนภายใน 35 วินาทีที่ผ่านมา\"")
fig.tight_layout(rect=(0, 0, 1, 0.93)); fig.savefig("figures/ml4_rule.png", dpi=150); plt.close(fig)

# ---------- F5 test timeline ----------
pr = pd.read_csv("test_predictions.csv")
S = json.load(open("../experiment/schedule.json"))
t = pr.t_start_s / 60
fig, axes = plt.subplots(3, 1, figsize=(13, 5.6), sharex=True, gridspec_kw=dict(height_ratios=[1.5, 1, 1]))
axes[0].fill_between(t, pr.true_max, step="post", color=BLUE, alpha=0.3, lw=0)
axes[0].step(t, pr.cam_max.fillna(-0.5), where="post", color=ORANGE, lw=0.7, label="กล้อง (max ใน window)")
axes[0].set_ylabel("คน"); axes[0].legend(loc="upper right", fontsize=8)
for ax, col, name in [(axes[1], "pred", "โมเดล"), (axes[2], "rule", "Rule: กล้องเห็นคน")]:
    ax.fill_between(t, pr.label * 0.45 + 0.55, 0.55, step="post", color=BLUE, alpha=0.35, lw=0)
    ax.fill_between(t, pr[col] * 0.45, 0, step="post", color=GREEN, alpha=0.45, lw=0)
    fp = (pr[col] == 1) & (pr.label == 0); fn = (pr[col] == 0) & (pr.label == 1)
    ax.scatter(t[fp], np.full(fp.sum(), 0.5), marker="|", color=RED, s=60, label="เปิดไฟทั้งที่ห้องว่าง (FP)")
    ax.scatter(t[fn], np.full(fn.sum(), 0.5), marker="|", color=VIOLET, s=60, label="ตัดไฟใส่คน (FN)")
    ax.set_yticks([0.225, 0.775], [name, "label"]); ax.set_ylim(0, 1.05); ax.grid(False)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.98), fontsize=7.5, ncol=2)
for m0, dur, _ in S["4"]["cam_fp_object"]:
    for ax in axes:
        ax.axvspan(m0, m0 + dur, color=VIOLET, alpha=0.08, lw=0)
    axes[0].text(m0 + 0.5, 6.1, "ลืมคีมในกล่อง", fontsize=8, color=INK2)
axes[0].set_ylim(-0.8, 7)
axes[-1].set_xlabel("นาทีนับจากเริ่ม session (วันที่ 4)")
title(fig, "วันทดสอบ: โมเดลไม่เคยตัดไฟใส่คน ความผิดพลาดเกือบทั้งหมดอยู่ช่วงที่ลืมคีมไว้ในกล่อง")
fig.tight_layout(rect=(0, 0, 1, 0.94)); fig.savefig("figures/ml5_test_timeline.png", dpi=150); plt.close(fig)

# ---------- F6 error analysis ----------
ef = pd.DataFrame(R["errors_test_final"]); er = pd.DataFrame(R["errors_test_rule"])
ef = ef[ef.windows > 0].reset_index(drop=True); er = er.set_index("case").loc[ef.case].reset_index()
fig, ax = plt.subplots(figsize=(10, 5.2))
y = np.arange(len(ef))[::-1]
for i, (a, b) in enumerate(zip(er.acc, ef.acc)):
    ax.plot([a, b], [y[i], y[i]], color=AXIS, lw=1.2, zorder=1)
ax.scatter(er.acc, y, color=MUTED, s=42, label="Rule: กล้องเห็นคน", zorder=2)
ax.scatter(ef.acc, y, color=BLUE, s=42, label="โมเดล", zorder=3)
ax.set_yticks(y, [f"{c}  (n={n})" for c, n in zip(ef.case, ef.windows)])
ax.set_xlabel("accuracy ในกลุ่ม (test วันที่ 4)"); ax.set_xlim(-0.03, 1.05); ax.legend(loc="lower left")
ax.set_title("โมเดลแก้กรณี grace, กล้องหลุด และคนออกชั่วคราวได้ แต่ลืมคีมในกล่องยังผิดเหมือน rule", loc="left", fontsize=10.5, weight="bold")
fig.tight_layout(); fig.savefig("figures/ml6_errors.png", dpi=150); plt.close(fig)
print("figures ok")
