"""ML pipeline
ทุกการตัดสินใจ (ชนิดโมเดล, ชุด feature, hyperparameter, threshold) ใช้ leave-one-day-out (LODO) บน train วันที่ 1–3
test วันที่ 4 ใช้ประเมินครั้งเดียวตอนท้าย
กติกาเลือก: F1 ของ LODO สูงสุด ถ้าต่างกันไม่เกิน 0.002 เลือกตัวที่เล็ก/ง่ายกว่า (เพราะต้องรันบน ESP32)
"""
import json, pickle
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (balanced_accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, precision_recall_curve)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text
from features import WIN_S, build_windows, feature_list, load

TOL = 0.002
R = {}
S = json.load(open("../experiment/schedule.json"))

tr = build_windows(load("train"))
te = build_windows(load("test"))
tr.to_csv("windows_train.csv", index=False)
te.to_csv("windows_test.csv", index=False)
y_tr, y_te = tr.label.astype(int).values, te.label.astype(int).values
days = tr.day.values
R["windows"] = dict(train=len(tr), test=len(te), pos_train=float(y_tr.mean()), pos_test=float(y_te.mean()),
                    per_day={int(d): int((tr.day == d).sum()) for d in sorted(tr.day.unique())})


def metrics(y, p, w=None):
    tn, fp, fn, tp = confusion_matrix(y, p, labels=[0, 1]).ravel()
    out = dict(f1=f1_score(y, p, zero_division=0), recall=recall_score(y, p, zero_division=0),
               precision=precision_score(y, p, zero_division=0), bacc=balanced_accuracy_score(y, p),
               tp=int(tp), fp=int(fp), fn=int(fn), tn=int(tn),
               on_while_empty_min=fp * WIN_S / 60, dark_while_occupied_min=fn * WIN_S / 60)
    if w is not None:
        out["switches"] = int(sum(np.abs(np.diff(p[w.day.values == d])).sum() for d in np.unique(w.day)))
        out["switches_true"] = int(sum(np.abs(np.diff(y[w.day.values == d])).sum() for d in np.unique(w.day)))
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def lodo_proba(model, X, y, groups):
    oof = np.zeros(len(y))
    for d in np.unique(groups):
        m = groups == d
        oof[m] = clone(model).fit(X[~m], y[~m]).predict_proba(X[m])[:, 1]
    return oof


def dt(depth):
    return make_pipeline(SimpleImputer(strategy="median"),
                         DecisionTreeClassifier(max_depth=depth, min_samples_leaf=5, class_weight="balanced",
                                                random_state=0))


def rf(n, depth):
    return make_pipeline(SimpleImputer(strategy="median"),
                         RandomForestClassifier(n_estimators=n, max_depth=depth, min_samples_leaf=5,
                                                class_weight="balanced", random_state=0, n_jobs=-1))


# ---------- 1) baselines + เปรียบเทียบชนิดโมเดล (ชุด B: กล้อง + ประตู) ----------
FB = feature_list(["camera", "door"])
families = {  # เรียงจากง่ายไปซับซ้อน
    "Logistic Regression": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                         LogisticRegression(max_iter=3000, class_weight="balanced")),
    "Decision Tree (depth 4)": dt(4),
    "Random Forest (50 ต้น, depth 8)": rf(50, 8),
    "Gradient Boosting (HGB)": HistGradientBoostingClassifier(max_depth=4, max_iter=150, class_weight="balanced",
                                                              random_state=0),
}
cmp_rows = [dict(model="Majority (ทาย 0 เสมอ)", **metrics(y_tr, np.zeros_like(y_tr), tr)),
            dict(model="Rule: กล้องเห็นคนใน window นี้", **metrics(y_tr, (tr.cam_max.fillna(0) > 0).astype(int).values, tr)),
            dict(model="Rule: กล้องเห็นคนภายใน 1 นาที", **metrics(y_tr, (tr.cam_max_roll6 > 0).astype(int).values, tr))]
for name, m in families.items():
    pr = lodo_proba(m, tr[FB].values, y_tr, days)
    cmp_rows.append(dict(model=name, **metrics(y_tr, (pr >= 0.5).astype(int), tr)))
R["model_compare_lodo"] = cmp_rows
fam = pd.DataFrame(cmp_rows[3:])
best = fam.f1.max()
FAMILY = fam[fam.f1 >= best - TOL].iloc[0].model          # ตัวแรก = ง่ายที่สุด
R["family_choice"] = dict(model=FAMILY, lodo_f1=float(fam[fam.model == FAMILY].f1.iloc[0]), best=float(best))
assert FAMILY.startswith("Decision Tree"), FAMILY

# ---------- 2) ablation ชุด feature (Decision Tree depth 4) ----------
sets = {"A กล้อง": ["camera"], "B กล้อง + ประตู": ["camera", "door"],
        "C = B + อุณหภูมิ/ความชื้น/MQ-2": ["camera", "door", "env"], "D = B + LDR": ["camera", "door", "ldr"]}
abl = []
for name, gs in sets.items():
    F = feature_list(gs)
    pr = lodo_proba(dt(4), tr[F].values, y_tr, days)
    pt = dt(4).fit(tr[F].values, y_tr).predict_proba(te[F].values)[:, 1]
    mt = metrics(y_te, (pt >= 0.5).astype(int))
    abl.append(dict(set=name, n_features=len(F), lodo_f1=round(f1_score(y_tr, (pr >= 0.5).astype(int)), 4),
                    lodo_recall=round(recall_score(y_tr, (pr >= 0.5).astype(int)), 4),
                    test_f1=mt["f1"], test_recall=mt["recall"], test_precision=mt["precision"]))
R["ablation"] = abl
cand = pd.DataFrame(abl[:2])                       # C และ D ตัดออกตั้งแต่ EDA (confounder / leakage)
bestF = cand.lodo_f1.max()
SET = cand[cand.lodo_f1 >= bestF - TOL].sort_values("n_features").iloc[0].set
F = feature_list(sets[SET])
R["set_choice"] = dict(set=SET, features=F)

# ---------- 3) ความลึกของต้นไม้ ----------
grid = []
for depth in (2, 3, 4, 5, 6, 8):
    pr = lodo_proba(dt(depth), tr[F].values, y_tr, days)
    grid.append(dict(max_depth=depth, **metrics(y_tr, (pr >= 0.5).astype(int))))
g = pd.DataFrame(grid)
DEPTH = int(g[g.f1 >= g.f1.max() - TOL].sort_values("max_depth").iloc[0].max_depth)
R["depth_grid"] = grid
R["depth_choice"] = DEPTH

# ---------- 4) threshold จาก OOF ----------
oof = lodo_proba(dt(DEPTH), tr[F].values, y_tr, days)
prec, rec, thr = precision_recall_curve(y_tr, oof)
RECALL_TARGET = 0.99
cands = [(t_, p_, r_) for p_, r_, t_ in zip(prec[:-1], rec[:-1], thr) if r_ >= RECALL_TARGET]
THR = float(max(cands, key=lambda x: x[0])[0])     # threshold สูงสุดที่ยังได้ recall ≥ 0.99 (precision สูงสุด)
R["threshold"] = dict(value=round(THR, 3), recall_target=RECALL_TARGET, oof_at_thr=metrics(y_tr, (oof >= THR).astype(int), tr),
                      oof_at_05=metrics(y_tr, (oof >= 0.5).astype(int), tr))
pd.DataFrame({"precision": prec[:-1], "recall": rec[:-1], "threshold": thr}).to_csv("oof_pr_curve.csv", index=False)


# ---------- 5) error analysis tags ----------
def tags(w):
    t = pd.DataFrame(index=w.index)
    tm = w.t_start_s / 60
    t["grace 30 s หลังคนสุดท้ายออก"] = (w.true_max == 0) & (w.label == 1)
    t["ลืมปิดไฟ"] = (w.label == 0) & (w.led_frac > 0)
    t["ลืมคีมในกล่อง (ห้องว่าง)"] = False
    t["ลืมคีมในกล่อง (มีคน)"] = False
    t["ตุ๊กตาอยู่มุมอับ"] = w.blind_any > 0
    t["กล้องหลุด"] = w.cam_missing_frac > 0.5
    t["กลุ่มถัดไปเข้าทันที"] = False
    t["แวะสั้น"] = False
    t["ออกแล้วกลับเข้ามา"] = False
    t["30 s แรกที่คนเข้า"] = False
    t["ทดสอบไฟ / alarm"] = (w.flame_test_any > 0) | (w.alarm_any > 0)
    t["มือในกล่องตอนห้องว่าง"] = (w.hand_any > 0) & (w.true_max == 0)
    for d in np.unique(w.day):
        v = S[str(int(d))]
        md = w.day == d
        for m0, dur, _ in v["cam_fp_object"]:
            inside = md & (tm >= m0) & (tm < m0 + dur)
            t.loc[inside & (w.true_max == 0), "ลืมคีมในกล่อง (ห้องว่าง)"] = True
            t.loc[inside & (w.true_max > 0), "ลืมคีมในกล่อง (มีคน)"] = True
        eps = v["episodes"]
        for i, e in enumerate(eps):
            inside = md & (tm >= e["t0_min"] - WIN_S / 60) & (tm <= e["t1_min"])
            if "แวะสั้น" in e["notes"]:
                t.loc[inside, "แวะสั้น"] = True
            if "ออกแล้วกลับเข้ามา" in e["notes"]:
                t.loc[inside, "ออกแล้วกลับเข้ามา"] = True
            t.loc[md & (tm >= e["t0_min"] - WIN_S / 60) & (tm < e["t0_min"] + 0.5), "30 s แรกที่คนเข้า"] = True
            if "กลุ่มถัดไปเข้าทันที" in e["notes"] and i + 1 < len(eps):
                t.loc[md & (tm >= e["t1_min"] - WIN_S / 60) & (tm <= eps[i + 1]["t0_min"] + 0.5), "กลุ่มถัดไปเข้าทันที"] = True
    special = t.any(axis=1)
    t["ปกติ: มีคน"] = ~special & (w.label == 1)
    t["ปกติ: ห้องว่าง"] = ~special & (w.label == 0)
    return t


def error_table(w, y, p):
    t = tags(w)
    rows = []
    for c in t.columns:
        m = t[c].values
        rows.append(dict(case=c, windows=int(m.sum()), label1=int(y[m].sum()),
                         fp=int(((p == 1) & (y == 0) & m).sum()), fn=int(((p == 0) & (y == 1) & m).sum()),
                         acc=round(float((p[m] == y[m]).mean()), 4) if m.sum() else None))
    return rows


R["errors_train_oof"] = error_table(tr, y_tr, (oof >= THR).astype(int))
R["errors_train_rule"] = error_table(tr, y_tr, (tr.cam_max.fillna(0) > 0).astype(int).values)

# ---------- 6) FINAL: เทรนวันที่ 1–3 ทั้งหมด ประเมินวันที่ 4 ครั้งเดียว ----------
final = dt(DEPTH).fit(tr[F].values, y_tr)
pt = final.predict_proba(te[F].values)[:, 1]
pred = (pt >= THR).astype(int)
rule = (te.cam_max.fillna(0) > 0).astype(int).values
R["test"] = dict(majority=metrics(y_te, np.zeros_like(y_te), te), rule_camera=metrics(y_te, rule, te),
                 rule_camera_1min=metrics(y_te, (te.cam_max_roll6 > 0).astype(int).values, te),
                 final=metrics(y_te, pred, te),
                 rf_same_features=metrics(y_te, (rf(50, 8).fit(tr[F].values, y_tr).predict_proba(te[F].values)[:, 1] >= 0.5).astype(int), te))
R["errors_test_final"] = error_table(te, y_te, pred)
R["errors_test_rule"] = error_table(te, y_te, rule)
R["tree_text"] = export_text(final[-1], feature_names=F, decimals=1, show_weights=False)


# ---------- 7) hysteresis ----------
def hysteresis(p, k_off):
    out, state, zeros = np.zeros_like(p), 0, 0
    for i, v in enumerate(p):
        if v == 1:
            state, zeros = 1, 0
        else:
            zeros += 1
            if zeros >= k_off:
                state = 0
        out[i] = state
    return out


R["hysteresis"] = [dict(k_off=k, extra_hold_s=int((k - 1) * WIN_S), **metrics(y_te, hysteresis(pred, k), te))
                   for k in (1, 2, 3, 6)]

# ---------- 8) importance ----------
pi = permutation_importance(final, te[F].values, y_te, scoring="f1", n_repeats=30, random_state=0)
R["perm_importance"] = sorted([dict(feature=f, mean=round(float(m), 4), std=round(float(s), 4))
                               for f, m, s in zip(F, pi.importances_mean, pi.importances_std)], key=lambda x: -x["mean"])
R["tree_importance"] = sorted([dict(feature=f, value=round(float(v), 4)) for f, v in
                               zip(F, final[-1].feature_importances_)], key=lambda x: -x["value"])

R["imputer_medians"] = dict(zip(F, [float(x) for x in final[0].statistics_]))
R["n_leaves"] = int(final[-1].get_n_leaves())
pickle.dump(dict(model=final, features=F, threshold=THR), open("final_model.pkl", "wb"))
pd.DataFrame({"day": te.day, "t_start_s": te.t_start_s, "label": y_te, "proba": pt, "pred": pred, "rule": rule,
              "true_max": te.true_max, "cam_max": te.cam_max, "led_frac": te.led_frac}).to_csv("test_predictions.csv", index=False)
pd.DataFrame({"day": tr.day, "t_start_s": tr.t_start_s, "label": y_tr, "oof": oof}).to_csv("train_oof.csv", index=False)
json.dump(R, open("ml_results.json", "w"), ensure_ascii=False, indent=1, default=float)
for k in ["family_choice", "ablation", "set_choice", "depth_grid", "depth_choice", "threshold", "test", "n_leaves"]:
    print(k, json.dumps(R[k], ensure_ascii=False, default=float)[:900])
print(R["tree_text"])
for k in ["errors_train_oof", "errors_test_final", "errors_test_rule", "hysteresis", "perm_importance"]:
    print(k); print(pd.DataFrame(R[k]).to_string())
