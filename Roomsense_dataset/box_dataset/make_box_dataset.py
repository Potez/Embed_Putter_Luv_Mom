#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulated dataset: ห้องประชุมจำลองจากกล่องกระดาษ (1 ห้อง), เก็บ 4 วัน, logger 2 Hz

Schema ของ logger (ตามที่กำหนด):
  timestamp_ms,mq2_raw,flame_do,digital_do,temp_c,humidity,temp_f,heat_index_c,heat_index_f,
  analog_1_raw,analog_2_raw,alarm  + person_count, power_on

การตีความ column ที่ schema ไม่ได้บอก (แก้ได้ที่ SENSOR_NOTES / ฟังก์ชันเซนเซอร์):
  digital_do   = IR obstacle (FC-51) ที่ประตูกล่อง, active-low (0 = มีวัตถุ/มือผ่านประตู)
  analog_1_raw = LDR module AO ผนังด้านใน (ค่ามาก = มืด)  -> ตรงกับตัวอย่าง: มีไฟลุก ค่าลดจาก 950 เหลือ 650-700
  analog_2_raw = gray/line sensor (TCRT5000) ที่พื้นธรณีประตู หันขึ้น (ค่ามาก = มีวัตถุสะท้อนอยู่เหนือ)
  alarm        = firmware rule: flame_do == 0 OR mq2_raw > 700

Run:  python3 make_box_dataset.py      -> ./box_dataset/
"""
import os
import numpy as np
import pandas as pd
from scipy.signal import lfilter

OUT = "box_dataset"
DT = 0.5                 # วินาทีต่อ sample (logger 2 Hz)
GRACE_S = 30.0           # label: ยังควรจ่ายไฟต่อ 30 s หลังตุ๊กตาตัวสุดท้ายออก
MQ2_ALARM = 700
MAX_FIG = 6              # ห้องจำลองมี 6 ที่นั่ง
HEADER = ("timestamp_ms,mq2_raw,flame_do,digital_do,temp_c,humidity,temp_f,heat_index_c,"
          "heat_index_f,analog_1_raw,analog_2_raw,alarm,person_count,power_on")
NCOL = len(HEADER.split(","))

DAYS = [
    dict(day=1, date="2026-11-10", start="13:12:05", minutes=175, role="train", seed=101,
         room=dict(T0=30.3, slope=0.25, RH0=66.0), ac_off_min=None,
         light=dict(amb0=1.00, var=0.06, sun=False),
         specials={2: dict(leave_return=True), 5: dict(n=5)},
         tests=[("gas", 52, 3), ("flame", 128, 9)],
         cam_dropouts=[], reboot_ep=None, dropped_lines=2, cam_fp_object=[(95, 7)],
         cond="บ่าย ฟ้าครึ้ม ไม่เปิดแอร์ ไฟเพดานห้องแล็บเปิด"),
    dict(day=2, date="2026-11-11", start="09:36:40", minutes=185, role="train", seed=202,
         room=dict(T0=25.9, slope=0.05, RH0=57.0), ac_off_min=None,
         light=dict(amb0=1.15, var=0.03, sun=False),
         specials={1: dict(forgot=True), 3: dict(n=6), 6: dict(back_to_back=True)},
         tests=[("flame", 74, 11)],
         cam_dropouts=[(141, 45)], reboot_ep=4, dropped_lines=3,
         cond="เช้า เปิดแอร์ ไฟเพดานห้องแล็บเปิด"),
    dict(day=3, date="2026-11-12", start="14:03:20", minutes=180, role="train", seed=303,
         room=dict(T0=26.3, slope=0.0, RH0=56.0),
         ac_off_min=72, ac_off=dict(dT=3.4, dRH=9.0, tau_min=35),
         light=dict(amb0=0.95, var=0.05, sun=False),
         specials={2: dict(n=6), 4: dict(forgot=True), 5: dict(short=True, n=1, dur=95),
                   7: dict(leave_return=True)},
         tests=[("smoke", 98, 25), ("gas", 160, 2)],
         cam_dropouts=[], reboot_ep=None, dropped_lines=2,
         cond="บ่าย เปิดแอร์ แล้วปิดแอร์ระหว่าง session"),
    dict(day=4, date="2026-11-13", start="09:51:10", minutes=180, role="test", seed=404,
         room=dict(T0=28.6, slope=0.6, RH0=70.0), ac_off_min=None,
         light=dict(amb0=1.30, var=0.10, sun=True),
         specials={1: dict(short=True, n=1, dur=90), 2: dict(n=6, back_to_back=True),
                   4: dict(forgot=True), 6: dict(leave_return=True)},
         tests=[("flame", 47, 8), ("gas", 115, 3), ("flame", 152, 10)],
         cam_dropouts=[(88, 30)], reboot_ep=None, dropped_lines=3, cam_fp_object=[(132, 9)],
         cond="เช้า แดดส่องผ่านหน้าต่างห้องแล็บเป็นช่วง ๆ ไม่เปิดแอร์"),
]

BOOT_LINES = [
    "Brownout detector was triggered",
    "",
    "ets Jun  8 2016 00:22:57",
    "",
    "rst:0xc (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)",
    "configsip: 0, SPIWP:0xee",
    "clk_drv:0x00,q_drv:0x00,d_drv:0x00,cs0_drv:0x00,hd_drv:0x00,wp_drv:0x00",
    "mode:DIO, clock div:1",
    "load:0x3fff0030,len:1344",
    "load:0x40078000,len:13964",
    "load:0x40080400,len:3600",
    "entry 0x400805f0",
]


# ============================== helpers ==============================
def ar1(rng, n, sd, tau_s):
    """AR(1) noise ที่มี std ~= sd และ time constant tau_s"""
    phi = np.exp(-DT / tau_s)
    e = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n)
    return lfilter([1.0], [1.0, -phi], e)


def es(T):
    """saturation vapour pressure (hPa)"""
    return 6.112 * np.exp(17.67 * T / (T + 243.5))


def heat_index(Tc, RH):
    """Adafruit DHT library computeHeatIndex(): คืนค่า (°C, °F)"""
    T = Tc * 1.8 + 32
    hi = 0.5 * (T + 61.0 + (T - 68.0) * 1.2 + RH * 0.094)
    full = (-42.379 + 2.04901523 * T + 10.14333127 * RH - 0.22475541 * T * RH
            - 0.00683783 * T * T - 0.05481717 * RH * RH + 0.00122874 * T * T * RH
            + 0.00085282 * T * RH * RH - 0.00000199 * T * T * RH * RH)
    adj1 = ((13.0 - RH) * 0.25) * np.sqrt(np.clip((17.0 - np.abs(T - 95.0)) * 0.05882, 0, None))
    adj2 = ((RH - 85.0) * 0.1) * ((87.0 - T) * 0.2)
    full = np.where((RH < 13) & (T >= 80) & (T <= 112), full - adj1, full)
    full = np.where((RH > 85) & (T >= 80) & (T <= 87), full + adj2, full)
    hi = np.where(hi > 79, full, hi)
    return (hi - 32) / 1.8, hi


def idx(t):
    return int(np.ceil(t / DT))


def mask(n, ivs):
    m = np.zeros(n, bool)
    for s, e in ivs:
        m[max(idx(s), 0):max(idx(e), 0)] = True
    return m


def hms(base, t):
    return (base + pd.to_timedelta(t, unit="s")).strftime("%H:%M:%S.%f")[:-5]


# ============================== schedule ==============================
def make_episode(rng, t0, n, dur, fl):
    arrivals, prev = [t0], t0
    for _ in range(1, n):
        prev += rng.uniform(3, 15)
        arrivals.append(prev + (rng.uniform(60, 180) if rng.random() < 0.2 else 0))
    end = max(t0 + dur, max(arrivals) + 120)
    deps, d = np.empty(n), end
    for i in rng.permutation(n):
        if n > 1 and not fl.get("short") and rng.random() < 0.12 and end - arrivals[i] > 360:
            deps[i] = rng.uniform(arrivals[i] + 180, end - 60)          # ออกก่อน
        else:
            d += rng.uniform(2, 10)
            deps[i] = d
    figs, lr_done = [], False
    lr_idx = int(rng.integers(n)) if fl.get("leave_return") else -1
    for i in range(n):
        a, b = arrivals[i], deps[i]
        if i == lr_idx and b - a > 400:
            x = rng.uniform(a + 120, b - 220)
            y = x + rng.uniform(40, 120)
            figs += [(a, x), (y, b)]
            lr_done = True
        else:
            figs.append((a, b))
    hands = []
    for a, b in figs:
        for x in (a, b):
            hands.append((x - rng.uniform(0.8, 1.8), x + rng.uniform(0.8, 2.5), "move"))
    for _ in range(rng.poisson(0.7)):
        x = rng.uniform(t0 + 60, end - 40)
        hands.append((x, x + rng.uniform(3, 7), "arrange"))
    return figs, hands, max(b for _, b in figs), lr_done


def build_schedule(cfg, rng, total):
    figs, hands, leds, eps = [], [], [], []
    t, k = 190 + rng.uniform(0, 90), 0
    while True:
        fl = cfg["specials"].get(k, {})
        n = fl.get("n", int(rng.choice([1, 2, 2, 3, 3, 4, 4, 5])))
        dur = fl.get("dur", rng.uniform(300, 780))
        if t + dur + 200 > total - 240:
            break
        f, h, last, lr = make_episode(rng, t, n, dur, fl)
        first = min(a for a, _ in f)
        on = first + rng.uniform(1.5, 6)
        off = last + (rng.uniform(150, 360) if fl.get("forgot") else rng.uniform(2, 8))
        figs += f
        hands += h
        leds.append((on, off))
        eps.append(dict(k=k, t0=first, last=last, n=n, led_on=on, led_off=off,
                        forgot=bool(fl.get("forgot")), back_to_back=bool(fl.get("back_to_back")),
                        leave_return=lr, short=bool(fl.get("short"))))
        t = last + (rng.uniform(10, 25) if fl.get("back_to_back") else rng.uniform(180, 540))
        k += 1
    return figs, hands, leds, eps


def place_tests(cfg, hands, rng):
    out = []
    for kind, minute, dur in cfg["tests"]:
        t = minute * 60 + rng.uniform(-20, 20)
        while any(s - 8 < t + dur and t < e + 8 for s, e, _ in hands):
            t += 5
        out.append((kind, t, float(dur)))
    return out


# ============================== simulate one day ==============================
def simulate(cfg):
    rng = np.random.default_rng(cfg["seed"])
    total = cfg["minutes"] * 60.0
    N = int(total / DT)
    t = np.arange(N) * DT
    th = t / 3600
    base_dt = pd.Timestamp(f"{cfg['date']} {cfg['start']}")

    figs, hands, leds, eps = build_schedule(cfg, rng, total)
    tests = place_tests(cfg, hands, rng)

    true_count = np.zeros(N, int)
    blind_count = np.zeros(N, int)               # ตุ๊กตาที่วางตรงมุมอับของกล้อง
    blind = rng.random(len(figs)) < 0.12
    for (a, b), bl in zip(figs, blind):
        true_count[idx(a):idx(b)] += 1
        if bl:
            blind_count[idx(a):idx(b)] += 1
    hand = mask(N, [(s, e) for s, e, _ in hands])
    led = mask(N, leds)

    # ---------- ห้องแล็บ (นอกกล่อง) ----------
    rp = cfg["room"]
    Troom = rp["T0"] + rp["slope"] * th + ar1(rng, N, 0.12, 600)
    RHroom = rp["RH0"] - 1.5 * rp["slope"] * th + ar1(rng, N, 0.8, 600)
    if cfg["ac_off_min"]:
        a = cfg["ac_off"]
        s = np.clip(t - cfg["ac_off_min"] * 60, 0, None)
        ramp = np.where(t > cfg["ac_off_min"] * 60, 1 - np.exp(-s / (a["tau_min"] * 60)), 0)
        Troom += a["dT"] * ramp
        RHroom += a["dRH"] * ramp

    lp = cfg["light"]
    sunny = np.zeros(N)
    if lp["sun"]:
        state, i = 0, 0
        while i < N:
            dwell = int(rng.uniform(120, 600) / DT)
            sunny[i:i + dwell] = state
            state = 1 - state
            i += dwell
        sunny = pd.Series(sunny).rolling(60, min_periods=1, center=True).mean().to_numpy()
    amb = np.clip(lp["amb0"] * (1 + 0.35 * sunny + ar1(rng, N, lp["var"], 120)), 0.5, None)

    # ---------- เหตุการณ์ทดสอบ ----------
    src = np.zeros(N)            # อัตราการเพิ่มความเข้มข้นแก๊ส/ควัน (หน่วยสมมติ ต่อวินาที)
    heat = np.zeros(N)           # °C/s
    flame_on = np.zeros(N, bool)
    for kind, ts, dur in tests:
        i0, i1 = idx(ts), idx(ts + dur)
        if kind == "flame":
            puff = idx(ts + rng.uniform(0.5, 1.5))
            src[i0:puff] += 0.06                    # แก๊สหลุดก่อนจุดติด
            flame_on[puff:i1] = True
            src[puff:i1] += 0.025                   # ผลิตภัณฑ์จากการเผาไหม้
            heat[puff:i1] += 0.04
        elif kind == "gas":
            src[i0:i1] += 0.35                      # กดแก๊สไฟแช็ก (ไม่จุด)
        elif kind == "smoke":
            src[i0:i1] += 0.012                     # ธูปจ่อช่องหน้าต่าง
    flame_light = np.where(flame_on, rng.uniform(0.40, 0.70, N), 0.0)

    # ---------- dynamics ----------
    Tb, Ts = Troom[0], Troom[0]
    eb = RHroom[0] / 100 * es(Troom[0])
    Hs = RHroom[0]
    c = cs = 0.0
    Ls = amb[0]
    T_s, H_s, CS, L_s = (np.empty(N) for _ in range(4))
    for i in range(N):
        h = hand[i]
        Tb += (Troom[i] + 1.9 + 0.5 * led[i] - Tb) * DT / 900 + heat[i] * DT
        if h:
            Tb += (Troom[i] - Tb) * DT / 90
        er = RHroom[i] / 100 * es(Troom[i])
        eb += (er - eb) * DT / 900 + (((er - eb) * DT / 120 + 0.01 * DT) if h else 0.0)
        RHb = min(99.9, 100 * eb / es(Tb))
        Ts += (Tb - Ts) * DT / 8
        Hs += (RHb - Hs) * DT / 12
        c += (src[i] - c / (30 if h else 50)) * DT
        cs += (c - cs) * DT / (4 if c > cs else 15)
        Lt = (amb[i] + 6.5 * led[i] + flame_light[i]) * (0.75 if h else 1.0)
        Ls += (Lt - Ls) * (0.8 if Lt > Ls else 0.45)
        T_s[i], H_s[i], CS[i], L_s[i] = Ts, Hs, cs, Ls

    # ---------- reboot (day 2: brownout ตอนเปิด LED) ----------
    boot_starts = [0.0]
    gap_ivs = []
    if cfg["reboot_ep"] is not None:
        tr = eps[cfg["reboot_ep"]]["led_on"]
        boot_starts.append(tr + 0.3)
        gap_ivs.append((tr, tr + rng.uniform(2.9, 3.3)))
    seg = np.searchsorted(np.array(boot_starts), t, side="right") - 1
    since_boot = t - np.array(boot_starts)[seg]

    # ---------- MQ-2 ----------
    warm = np.where(seg == 0, 250, 120) * np.exp(-since_boot / 75)
    mq2 = (318 + 7 * (T_s - 28) + 1.0 * (H_s - 60) + ar1(rng, N, 6, 900) + warm
           + 2600 * (1 - np.exp(-CS)) + 4 * hand + rng.normal(0, 2.5, N))
    mq2 = np.clip(np.round(mq2), 0, 4095).astype(int)

    # ---------- flame sensor DO (active-low) ----------
    flame_do = np.ones(N, int)
    flicker = rng.random(N) < 0.85
    flame_do[flame_on & flicker] = 0
    sun_glitch = []
    if lp["sun"]:
        cand = np.where((sunny > 0.8) & (rng.random(N) < 1 / 2500))[0]
        for j in cand:
            L = int(rng.integers(1, 3))
            flame_do[j:j + L] = 0
            sun_glitch.append(t[j])

    # ---------- IR obstacle ที่ประตู (active-low) ----------
    digital_do = np.ones(N, int)
    digital_do[hand & (rng.random(N) < 0.85)] = 0
    glitch_p = 1 / 60000 + (sunny > 0.8) * (1 / 6000)
    digital_do[rng.random(N) < glitch_p] = 0

    # ---------- DHT22 (อ่านทุก 2 s, resolution 0.1) ----------
    temp_c = np.full(N, np.nan)
    hum = np.full(N, np.nan)
    first_read = 4                                  # อ่านครั้งแรกหลัง boot ~2 s
    for b in range(len(boot_starts)):
        ids = np.where(seg == b)[0]
        for j in range(first_read, len(ids), 4):
            k = ids[j:j + 4]
            if rng.random() < 0.002:
                continue                            # read fail -> nan
            temp_c[k] = np.round(T_s[ids[j]] + rng.normal(0, 0.04), 1)
            hum[k] = np.round(np.clip(H_s[ids[j]] + rng.normal(0, 0.25), 0, 99.9), 1)
    temp_f = np.round(temp_c * 1.8 + 32, 2)
    hic, hif = heat_index(temp_c, hum)

    # ---------- LDR (analog_1, ค่ามาก = มืด) ----------
    R = 0.302 * np.power(L_s, -0.7)
    a1 = 4095 * R / (R + 1) + rng.normal(0, 7, N)
    sp = rng.random(N) < 1 / 3000
    a1[sp] += rng.choice([-45, 45], sp.sum())
    analog_1 = np.clip(np.round(a1), 0, 4095).astype(int)

    # ---------- gray sensor ที่ธรณีประตู (analog_2) ----------
    a2 = 300 + 12 * led + 40 * sunny + rng.normal(0, 4, N)
    arm = hand & (rng.random(N) < 0.8)
    a2[arm] = rng.uniform(1500, 3300, arm.sum())
    part = hand & ~arm
    a2[part] += rng.uniform(0, 300, part.sum())
    analog_2 = np.clip(np.round(a2), 0, 4095).astype(int)

    # ---------- กล้อง (บอร์ดแยก ส่งจำนวนตุ๊กตาที่ detect ได้) ----------
    obj = mask(N, [(m0 * 60, (m0 + dur) * 60) for m0, dur in cfg.get("cam_fp_object", [])])
    cam = np.zeros(N, int)
    d = db = hd = fp = 0
    for i in range(N):
        n = true_count[i]
        nb = blind_count[i]
        bright = led[i] or amb[i] > 1.35
        p_stay, p_on = (0.97, 0.5) if bright else (0.87, 0.2)
        d = min(d, n - nb)
        d = rng.binomial(d, p_stay) + rng.binomial(n - nb - d, p_on)
        db = min(db, nb)
        db = rng.binomial(db, 0.6) + rng.binomial(nb - db, 0.02)
        out = d + db
        if obj[i] and rng.random() < 0.9:
            out += 1                                # ของที่ลืมไว้ในกล่องถูก detect เป็นคน
        if n >= 4 and rng.random() < 0.2:
            out -= 1                                # ตุ๊กตาอยู่ชิดกัน ถูกนับรวม
        if hand[i]:
            out = rng.binomial(out, 0.7)            # มือบังกล้อง
            hd = int(rng.random() < 0.8) if hd else int(rng.random() < 0.55)
            out += hd                               # มือถูก detect เป็นคน
        else:
            hd = 0
        if n == 0:
            if fp == 0 and rng.random() < (1 / 9000 if led[i] else 1 / 20000):
                fp = int(rng.integers(2, 9))
            if fp:
                out += 1
                fp -= 1
        cam[i] = max(out, 0)
    cam[: int(rng.uniform(8, 15) / DT)] = -1       # กล้องยังบูต/ต่อ UART ไม่เสร็จ
    for m0, dur in cfg["cam_dropouts"]:
        i0 = idx(m0 * 60)
        cam[i0:i0 + idx(dur)] = -1

    # ---------- label จาก event log ของผู้ทดลอง ----------
    logged = [(a + rng.uniform(0.2, 1.2), b + rng.uniform(0.2, 1.2)) for a, b in figs]
    occ_log = np.zeros(N, int)
    for a, b in logged:
        occ_log[idx(a):idx(b)] += 1
    last_occ = pd.Series(np.where(occ_log > 0, t, np.nan)).ffill().to_numpy()
    power_on = ((occ_log > 0) | (t - last_occ <= GRACE_S)).astype(int)
    last_true = pd.Series(np.where(true_count > 0, t, np.nan)).ffill().to_numpy()
    power_true = ((true_count > 0) | (t - last_true <= GRACE_S)).astype(int)

    alarm = ((flame_do == 0) | (mq2 > MQ2_ALARM)).astype(int)

    # ---------- แถวที่ logger บันทึกได้จริง ----------
    keep = np.ones(N, bool)
    for s, e in gap_ivs:
        keep[idx(s):idx(e)] = False
    drops = rng.choice(np.arange(200, N - 200), cfg["dropped_lines"], replace=False)
    keep[drops] = False

    ts_ms = np.zeros(N, np.int64)
    for b in range(len(boot_starts)):
        ids = np.where(seg == b)[0]
        ids = ids[since_boot[ids] >= 2.5] if b > 0 else ids
        ms = int(rng.integers(2480, 2521))
        prev = ids[0]
        ts_ms[prev] = ms
        for j in ids[1:]:
            ms += sum(500 + int(rng.random() < 0.03) for _ in range(j - prev))
            ts_ms[j] = ms
            prev = j
    if len(boot_starts) > 1:
        ids1 = np.where(seg == 1)[0]
        keep[ids1[since_boot[ids1] < 2.5]] = False

    df = pd.DataFrame({
        "timestamp_ms": ts_ms, "mq2_raw": mq2, "flame_do": flame_do, "digital_do": digital_do,
        "temp_c": temp_c, "humidity": hum, "temp_f": temp_f,
        "heat_index_c": np.round(hic, 2), "heat_index_f": np.round(hif, 2),
        "analog_1_raw": analog_1, "analog_2_raw": analog_2, "alarm": alarm,
        "person_count": cam, "power_on": power_on,
    })
    gt = pd.DataFrame({
        "t_session_s": t, "wall_time": [hms(base_dt, x) for x in t], "boot": seg,
        "timestamp_ms": ts_ms, "logged": keep.astype(int),
        "true_count": true_count, "blind_spot_count": blind_count, "hand_in_box": hand.astype(int), "led_on": led.astype(int),
        "flame_test": flame_on.astype(int), "power_on_true": power_true, "power_on_label": power_on,
    })

    # ---------- event log (สิ่งที่ผู้ทดลองจดระหว่างเก็บ) ----------
    ev = [(0.0, "logger_start", "เริ่ม capture serial, เปิดไฟเลี้ยงบอร์ด (MQ-2 เริ่ม warm-up)")]
    ev.append((180.0, "warmup_done", "ครบ 3 นาที เริ่ม scenario"))
    cnt = 0
    for tt, kind in sorted([(a, "fig_in") for a, _ in logged] + [(b, "fig_out") for _, b in logged]):
        cnt += 1 if kind == "fig_in" else -1
        ev.append((tt, kind, f"count={cnt}"))
    for e in eps:
        ev.append((e["led_on"] + rng.uniform(0.2, 1.0), "led_on", f"episode {e['k'] + 1}"))
        note = "ลืมปิดไฟ (ตั้งใจ)" if e["forgot"] else ""
        ev.append((e["led_off"] + rng.uniform(0.2, 1.0), "led_off", f"episode {e['k'] + 1} {note}".strip()))
    for s, e_, kind in hands:
        if kind == "arrange":
            ev.append((s, "arrange", "ขยับตุ๊กตา จำนวนไม่เปลี่ยน"))
    for kind, ts, dur in tests:
        what = {"flame": "จุดไฟแช็กห่างช่องหน้าต่าง ~10 cm",
                "gas": "กดแก๊สไฟแช็ก (ไม่จุด) ใกล้ MQ-2",
                "smoke": "ธูป 1 ดอก จ่อช่องหน้าต่าง"}[kind]
        ev.append((ts, f"{kind}_test_start", what))
        ev.append((ts + dur, f"{kind}_test_end", ""))
    if cfg["reboot_ep"] is not None:
        ev.append((boot_starts[1], "board_reset", "บอร์ดรีเซ็ตเองตอนเปิด LED (สงสัย brownout)"))
    if cfg["ac_off_min"]:
        ev.append((cfg["ac_off_min"] * 60, "room_ac_off", "ปิดแอร์ห้องแล็บ"))
    ev.append((total - DT, "logger_stop", "หยุด capture"))
    events = pd.DataFrame(sorted(ev), columns=["t_session_s", "event", "note"])
    events.insert(0, "wall_time", [hms(base_dt, x) for x in events["t_session_s"]])
    events["t_session_s"] = events["t_session_s"].round(1)

    info = dict(eps=eps, tests=tests, n_blind=int(blind.sum()), sun_glitch=sun_glitch, keep=keep, gap_ivs=gap_ivs,
                boot_starts=boot_starts, drops=sorted(t[drops]), base_dt=base_dt)
    return df, gt, events, info


# ============================== write raw serial capture ==============================
def fmt_row(r):
    def f2(x):
        return "nan" if pd.isna(x) else f"{x:.2f}"
    return ",".join([str(r.timestamp_ms), str(r.mq2_raw), str(r.flame_do), str(r.digital_do),
                     f2(r.temp_c), f2(r.humidity), f2(r.temp_f), f2(r.heat_index_c),
                     f2(r.heat_index_f), str(r.analog_1_raw), str(r.analog_2_raw),
                     str(r.alarm), str(r.person_count), str(r.power_on)])


def write_raw(path, df, info):
    keep = info["keep"]
    gap_start = idx(info["gap_ivs"][0][0]) if info["gap_ivs"] else None
    lines = [HEADER]
    last_kept = None
    for i, r in enumerate(df.itertuples(index=False)):
        if gap_start is not None and i == gap_start:
            # บรรทัดที่กำลังพิมพ์อยู่ตอนไฟตก ถูกตัดกลางคัน
            cut = last_kept._replace(timestamp_ms=last_kept.timestamp_ms + 500)
            lines.append(",".join(fmt_row(cut).split(",")[:5]))
            lines += BOOT_LINES
            lines.append(HEADER)
        if keep[i]:
            lines.append(fmt_row(r))
            last_kept = r
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def parse_raw(path):
    """parser แบบเดียวกับที่ควรใช้กับ log จริง: ข้ามบรรทัดที่ไม่ใช่ข้อมูลครบ 14 ช่อง"""
    rows, boot, last_ms, skipped = [], 0, None, 0
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) != NCOL or parts[0] == "timestamp_ms":
                skipped += line.strip() != "" and parts[0] != "timestamp_ms"
                continue
            try:
                vals = [float(p) for p in parts]
            except ValueError:
                skipped += 1
                continue
            if last_ms is not None and vals[0] < last_ms:
                boot += 1
            last_ms = vals[0]
            rows.append([boot] + vals)
    df = pd.DataFrame(rows, columns=["boot"] + HEADER.split(","))
    for c in ["timestamp_ms", "mq2_raw", "flame_do", "digital_do", "analog_1_raw",
              "analog_2_raw", "alarm", "person_count", "power_on"]:
        df[c] = df[c].astype(int)
    return df, skipped


# ============================== main ==============================
def main():
    for sub in ("raw", "ground_truth", "events"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    parsed, sessions, issues = [], [], []
    for cfg in DAYS:
        df, gt, events, info = simulate(cfg)
        tag = f"day{cfg['day']}_{cfg['date']}"
        raw_path = os.path.join(OUT, "raw", f"{tag}.csv")
        write_raw(raw_path, df, info)
        gt.to_csv(os.path.join(OUT, "ground_truth", f"{tag}_truth.csv"), index=False)
        events.to_csv(os.path.join(OUT, "events", f"{tag}_events.csv"), index=False)

        p, skipped = parse_raw(raw_path)
        p.insert(0, "day", cfg["day"])
        parsed.append((cfg, p))

        eps = info["eps"]
        base = info["base_dt"]
        sessions.append(dict(
            day=cfg["day"], date=cfg["date"], weekday=base.strftime("%a"), split=cfg["role"],
            raw_file=f"raw/{tag}.csv", logger_start=cfg["start"], duration_min=cfg["minutes"],
            rows=len(p), boots=p["boot"].nunique(), episodes=len(eps),
            max_figurines=max(e["n"] for e in eps),
            tests="; ".join(f"{k}@{hms(base, ts)[:8]}" for k, ts, _ in info["tests"]),
            room=cfg["cond"], power_on_ratio=round(p["power_on"].mean(), 3),
        ))
        for e in eps:
            if e["forgot"]:
                issues.append((cfg["day"], hms(base, e["led_off"])[:8], "LED ค้างหลังห้องว่าง (ตั้งใจ, ลืมปิดไฟ)"))
            if e["back_to_back"]:
                issues.append((cfg["day"], hms(base, e["last"])[:8], "กลุ่มถัดไปเข้าภายใน 25 s (label ไม่ตกเป็น 0)"))
            if e["leave_return"]:
                issues.append((cfg["day"], hms(base, e["t0"])[:8], "ตุ๊กตา 1 ตัวออกแล้วกลับเข้ามา"))
        if info["gap_ivs"]:
            issues.append((cfg["day"], hms(base, info["gap_ivs"][0][0])[:8],
                           "บอร์ดรีเซ็ต (brownout): มีบรรทัดขาดครึ่ง, boot log, header ซ้ำ, timestamp_ms เริ่มใหม่, MQ-2 warm-up ซ้ำ"))
        for m0, dur in cfg["cam_dropouts"]:
            issues.append((cfg["day"], hms(base, m0 * 60)[:8], f"กล้องไม่ส่งข้อมูล ~{dur} s (person_count = -1)"))
        for m0, dur in cfg.get("cam_fp_object", []):
            issues.append((cfg["day"], hms(base, m0 * 60)[:8],
                           f"ลืมคีมคีบตุ๊กตาไว้ในกล่อง ~{dur} นาที กล้องนับเป็นคน 1 คน"))
        n_blind = info["n_blind"]
        if n_blind:
            issues.append((cfg["day"], "หลายช่วง", f"ตุ๊กตา {n_blind} ครั้งถูกวางตรงมุมอับของกล้อง (person_count ต่ำกว่าจริงทั้งช่วง)"))
        for x in info["drops"]:
            issues.append((cfg["day"], hms(base, x)[:8], "บรรทัดหาย 1 บรรทัด (USB serial)"))
        if info["sun_glitch"]:
            issues.append((cfg["day"], "หลายช่วง", f"แดดทำให้ flame_do = 0 หลอก {len(info['sun_glitch'])} ครั้ง -> alarm หลอก"))
        print(f"day{cfg['day']}: rows={len(p)} skipped_lines={skipped} boots={p['boot'].nunique()} "
              f"episodes={len(eps)} power_on={p['power_on'].mean():.3f} alarm_rows={p['alarm'].sum()}")

    train = pd.concat([p for c, p in parsed if c["role"] == "train"], ignore_index=True)
    test = pd.concat([p for c, p in parsed if c["role"] == "test"], ignore_index=True)
    fmt = dict(index=False, float_format="%.2f", na_rep="nan")
    train.to_csv(os.path.join(OUT, "train.csv"), **fmt)
    test.to_csv(os.path.join(OUT, "test.csv"), **fmt)
    pd.DataFrame(sessions).to_csv(os.path.join(OUT, "sessions.csv"), index=False)
    pd.DataFrame(issues, columns=["day", "time", "issue"]).sort_values(
        ["day", "time"], kind="stable").to_csv(os.path.join(OUT, "known_issues.csv"), index=False)
    print("train", train.shape, "test", test.shape)


if __name__ == "__main__":
    main()
