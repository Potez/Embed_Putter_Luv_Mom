"""แปลง log 2 Hz เป็น window 10 วินาที + feature ที่ใช้ข้อมูลอดีตเท่านั้น"""
import glob
import numpy as np
import pandas as pd

D = "../box_dataset/"
WIN_S = 10.0          # ความยาว window
WARMUP_S = 180.0      # ตัด MQ-2 warm-up หลังบูต

GROUPS = {
    "camera": ["cam_max", "cam_mean", "cam_pos_frac", "cam_missing_frac", "cam_max_roll6", "cam_mean_roll3",
               "since_cam_s"],
    "door": ["door_any", "door_events", "door_recent_2m", "door_events_5m", "since_door_s"],
    "env": ["temp", "temp_slope_5m", "hum", "mq2"],
    "ldr": ["ldr_mean"],
}


def load(split):
    df = pd.read_csv(D + f"{split}.csv")
    truth = []
    for d in sorted(df.day.unique()):
        g = pd.read_csv(glob.glob(D + f"ground_truth/day{d}_*_truth.csv")[0])
        g = g[g.logged == 1].reset_index(drop=True)
        assert len(g) == (df.day == d).sum()
        truth.append(g)
    g = pd.concat(truth, ignore_index=True)
    for c in ["t_session_s", "true_count", "blind_spot_count", "hand_in_box", "led_on", "flame_test"]:
        df[c] = g[c].values
    return df


def build_windows(df):
    rows = []
    for (day, boot), s in df.groupby(["day", "boot"], sort=False):
        s = s.copy()
        boot_t0 = s.t_session_s.iloc[0]
        s["since_boot"] = s.t_session_s - boot_t0
        s["cam"] = s.person_count.where(s.person_count >= 0)
        s["door"] = ((s.digital_do == 0) | (s.analog_2_raw > 1000)).astype(int)
        s["win"] = np.floor(s.t_session_s / WIN_S).astype(int)
        g = s.groupby("win")
        w = pd.DataFrame({
            "day": day, "boot": boot,
            "t_start_s": g.t_session_s.min(),
            "since_boot_s": g.since_boot.min(),
            "n_rows": g.size(),
            "cam_max": g.cam.max(), "cam_mean": g.cam.mean(),
            "cam_pos_frac": g.cam.apply(lambda x: (x > 0).mean() if x.notna().any() else np.nan),
            "cam_missing_frac": g.cam.apply(lambda x: x.isna().mean()),
            "door_any": g.door.max(),
            "door_events": g.door.apply(lambda x: int((x.diff() == 1).sum() + (x.iloc[0] == 1))),
            "temp": g.temp_c.mean(), "hum": g.humidity.mean(), "mq2": g.mq2_raw.median(),
            "ldr_mean": g.analog_1_raw.mean(),
            "alarm_any": g.alarm.max(),
            "label": g.power_on.max(),
            # ground truth สำหรับวิเคราะห์ผลเท่านั้น (ไม่ใช่ feature)
            "true_max": g.true_count.max(), "blind_any": g.blind_spot_count.max(),
            "hand_any": g.hand_in_box.max(), "led_frac": g.led_on.mean(), "flame_test_any": g.flame_test.max(),
        }).reset_index()
        # feature ย้อนหลัง (rolling มองแค่อดีต)
        cm = w.cam_max.fillna(0)
        w["cam_max_roll6"] = cm.rolling(6, min_periods=1).max()
        w["cam_mean_roll3"] = w.cam_mean.rolling(3, min_periods=1).mean()
        w["door_recent_2m"] = w.door_any.rolling(12, min_periods=1).max()
        w["door_events_5m"] = w.door_events.rolling(30, min_periods=1).sum()
        w["temp_slope_5m"] = w.temp.diff(30) / 5.0
        idx = pd.Series(np.arange(len(w)), dtype=float)
        last_cam = idx.where(cm > 0).ffill()
        last_door = idx.where(w.door_any > 0).ffill()
        w["since_cam_s"] = ((idx - last_cam) * WIN_S).clip(upper=900).fillna(900)
        w["since_door_s"] = ((idx - last_door) * WIN_S).clip(upper=900).fillna(900)
        rows.append(w)
    W = pd.concat(rows, ignore_index=True)
    # ตัด MQ-2 warm-up ตอนเริ่ม session (ห้องว่างตาม protocol); หลังรีเซ็ตกลาง session เก็บไว้ เพราะมีคนอยู่จริง
    W = W[~((W.boot == 0) & (W.since_boot_s < WARMUP_S))].reset_index(drop=True)
    return W


def feature_list(groups):
    out = []
    for g in groups:
        out += GROUPS[g]
    return out
