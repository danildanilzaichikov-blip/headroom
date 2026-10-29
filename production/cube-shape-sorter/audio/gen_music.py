#!/usr/bin/env python3
"""Музыка «игрушечное утро» — direction.md §5.2.

C-dur, 120 BPM, 4/4, доля 0.5 с, сетка долей 0.4 + 0.5·k.
Инструменты: маримба (модальный синтез), укулеле (Karplus–Strong, re-entrant G4–C4–E4–A4),
бас (синус + 2-я/3-я гармоники), шейкер (шум HPF 6 кГц), колокольчик (тихий на ферме 12.1;
основные «дзинь»/«динь-динь» — в sfx.wav по §5.3).
Форма: C (0.4) · Am (2.4) · F (4.4) · G (6.4) → tape-stop 6.5–7.0 → тишина 7.0–9.1 →
Dm7→G7 арпеджио 9.1 · F 10.4 · Gsus4→G 11.4/11.65 · стоп-тайм 11.9–12.1 ·
Cadd9 12.1 (ферма) → затухание к 13.4, fade → −∞ к 14.0 → тишина до 15.0 (шов петли).

Выход: music.wav — 48 кГц, 24 бит, стерео, ровно 720 000 сэмплов.
Детерминизм: np.random.default_rng(2610). Запуск: python3 gen_music.py
"""
import os

import numpy as np
from scipy import signal

from dsp import FS, N, SEED, db, exp_env, norm_peak, pan_gains, svf, hpf, lpf, write_wav24

OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(SEED)

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(name):
    """'C5' → Гц (A4 = 440)."""
    midi = 12 * (int(name[-1]) + 1) + NOTE[name[0]]
    return 440.0 * 2 ** ((midi - 69) / 12)


def stem(sec=16.0):
    return np.zeros(int(sec * FS))


def add(buf, x, t0):
    i = int(round(t0 * FS))
    x = x[: len(buf) - i]
    buf[i:i + len(x)] += x


# ------------------------------------------------------------------ инструменты
def marimba(f, vel=1.0, dur=1.6):
    n = int(dur * FS)
    t = np.arange(n) / FS
    x = (1.00 * np.exp(-t / 0.55) * np.sin(2 * np.pi * f * t)
         + 0.35 * np.exp(-t / 0.12) * np.sin(2 * np.pi * 3.93 * f * t)
         + 0.08 * np.exp(-t / 0.04) * np.sin(2 * np.pi * 9.2 * f * t))
    na = int(0.002 * FS)
    x[:na] *= np.linspace(0, 1, na)
    # «стук колотушки»: 1 мс шума, HPF 2 кГц, −18 дБ
    m = int(0.001 * FS)
    click = hpf(rng.standard_normal(m * 4), 2000)[:m] * np.hanning(m)
    x[:m] += db(-18) * click / (np.max(np.abs(click)) + 1e-9)
    return vel * x


def ks_string(f, dur, g=0.996, bright=4500.0, vel=1.0, mute=False):
    """Karplus–Strong: петля = задержка P + ФНЧ 1-го порядка 0.5·(1+z⁻¹) (задержка 0.5)
    + аллпас 1-го порядка для дробной части (точная настройка), коэффициент g = 0.996.
    H(z) = (1+ηz⁻¹) / [(1+ηz⁻¹) − g·0.5·z⁻ᴾ(1+z⁻¹)(η+z⁻¹)]."""
    n = int(dur * FS)
    per = FS / f
    p = int(per - 0.6)
    d = per - 0.5 - p                     # ∈ [0.1; 1.1)
    eta = (1 - d) / (1 + d)
    gg = 0.93 if mute else g
    a = np.zeros(p + 3)
    a[0] = 1.0
    a[1] = eta
    k = gg * 0.5
    # (1+z⁻¹)(η+z⁻¹) = η + (1+η)z⁻¹ + z⁻²
    a[p] -= k * eta
    a[p + 1] -= k * (1 + eta)
    a[p + 2] -= k
    b = [1.0, eta]
    exc = lpf(rng.uniform(-1, 1, p), bright, 1)
    exc -= exc.mean()
    xin = np.zeros(n)
    xin[:p] = exc
    y = signal.lfilter(b, a, xin)
    if mute:
        y *= np.exp(-np.arange(n) / FS / 0.06)
    return vel * y


UKE_CHORDS = {   # по струнам G4, C4, E4, A4 (порядок удара вниз)
    "C": ["G4", "C4", "E4", "C5"],
    "Am": ["A4", "C4", "E4", "A4"],
    "F": ["A4", "C4", "F4", "A4"],
    "G": ["G4", "D4", "G4", "B4"],
    "G7": ["G4", "D4", "F4", "B4"],
    "Gsus4": ["G4", "D4", "G4", "C5"],
    "Cadd9": ["G4", "C4", "E4", "D5"],
}


def strum(buf, chord, t0, down=True, vel=1.0, mute=False, ring=1.4, g=0.996):
    notes = UKE_CHORDS[chord]
    order = notes if down else notes[::-1]
    spread = 0.012 if down else 0.008
    for i, nm in enumerate(order):
        tt = t0 + i * spread / (len(order) - 1)
        v = vel * (1.0 if down else 0.75) * (1.0 - 0.06 * i)
        add(buf, ks_string(hz(nm), ring, g=g, vel=v, mute=mute,
                           bright=3500 if not down else 4500), tt)


def bass(f, vel=1.0, tau=0.35, dur=1.6):
    n = int(dur * FS)
    t = np.arange(n) / FS
    x = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)
         + 0.10 * np.sin(6 * np.pi * f * t)) * np.exp(-t / tau)
    na = int(0.005 * FS)
    x[:na] *= np.linspace(0, 1, na)
    return vel * x


def shaker(vel=1.0):
    n = int(0.045 * FS)
    x = hpf(rng.standard_normal(n + 512), 6000, 4)[512:]
    t = np.arange(n) / FS
    env = np.minimum(t / 0.006, 1.0) * np.exp(-t / 0.012)
    env *= np.where(t < 0.030, 1.0, np.cos(0.5 * np.pi * np.clip((t - 0.030) / 0.015, 0, 1)))
    return vel * x * env


def bell(f, vel=1.0, dur=1.5):
    n = int(dur * FS)
    t = np.arange(n) / FS
    x = (np.exp(-t / 0.8) * np.sin(2 * np.pi * f * t)
         + 0.25 * np.exp(-t / 0.3) * np.sin(2 * np.pi * 2.76 * f * t)
         + 0.08 * np.exp(-t / 0.1) * np.sin(2 * np.pi * 5.4 * f * t))
    x[:48] *= np.linspace(0, 1, 48)
    return vel * x


# ------------------------------------------------------------------ партитура
BAR = [0.4, 2.4, 4.4, 6.4]


def beat(bar_t, pos):          # pos — доля такта 1…4.5
    return bar_t + (pos - 1) * 0.5


def score():
    """Возвращает 2 набора стемов: A (до tape-stop) и B (возврат 9.1+), C (ферма 12.1)."""
    S = {k: {s: stem() for s in ("mar", "uke", "bass", "shk", "bell")} for k in "ABC"}

    # --- A: такты 1–4 (0.4–7.0)
    mel = [
        ("C", [("E5", 1), ("G5", 1.5), ("C6", 2), ("G5", 3), ("E5", 3.5), ("C5", 4)]),
        ("Am", [("E5", 1), ("A5", 1.5), ("C6", 2), ("A5", 3), ("E5", 3.5), ("C5", 4)]),
        ("F", [("F5", 1), ("A5", 1.5), ("C6", 2), ("A5", 3), ("F5", 3.5), ("A5", 4)]),
        ("G", [("G5", 1), ("B5", 1.5)]),
    ]
    roots = {"C": "C3", "Am": "A2", "F": "F3", "G": "G3"}
    A = S["A"]
    for bt, (ch, notes) in zip(BAR, mel):
        for nm, pos in notes:
            add(A["mar"], marimba(hz(nm), 1.0 if pos == 1 else 0.8), beat(bt, pos))
        # укулеле: 1 (вниз, акцент) · 2& (вверх) · 3 (вниз) · 4& (вверх)
        pattern = [(1, True, 1.0), (2.5, False, 0.6), (3, True, 0.8), (4.5, False, 0.6)]
        for pos, down, v in pattern:
            if ch == "G" and pos > 1.5:
                continue
            strum(A["uke"], ch, beat(bt, pos), down, v)
        for pos in (1, 3):
            if ch == "G" and pos > 1:
                continue
            add(A["bass"], bass(hz(roots[ch]), 1.0 if pos == 1 else 0.8), beat(bt, pos))
        for k in range(8):
            if ch == "G" and k > 1:
                continue
            add(A["shk"], shaker(db(3) if k % 2 else 1.0), bt + 0.25 * k)

    # --- B: возврат 9.1–11.9
    B = S["B"]
    arp = ["D5", "F5", "A5", "C6", "G5", "B5", "D6", "F6", "G5", "B5", "D6"]
    for i, nm in enumerate(arp):
        add(B["mar"], marimba(hz(nm), 0.55 + 0.04 * i), 9.1 + 0.125 * i)
    for nm, t in [("F5", 10.4), ("A5", 10.65), ("C6", 10.9), ("C6", 11.4), ("B5", 11.65)]:
        add(B["mar"], marimba(hz(nm), 0.9), t)
    strum(B["uke"], "G7", 9.4, True, 0.9, mute=True)
    strum(B["uke"], "G7", 9.9, True, 0.9, mute=True)
    strum(B["uke"], "F", 10.4, True, 1.0)
    strum(B["uke"], "F", 10.65, False, 0.6)
    strum(B["uke"], "Gsus4", 11.4, True, 0.9)
    strum(B["uke"], "G", 11.65, True, 0.8)
    for nm, t in [("D3", 9.1), ("G3", 9.6), ("F3", 10.4), ("F3", 10.9), ("G3", 11.4)]:
        add(B["bass"], bass(hz(nm), 0.9), t)
    for k in range(10):           # восьмые 9.4…11.65, без 10.95–11.2 (чистый «чпок» 11.0)
        t = 9.4 + 0.25 * k
        if 10.95 < t < 11.2:
            continue
        add(B["shk"], shaker(db(3) if k % 2 else 1.0), t)

    # --- C: ферма Cadd9 12.1
    C = S["C"]
    strum(C["uke"], "Cadd9", 12.1, True, 1.0, ring=2.5, g=0.998)
    add(C["bass"], bass(hz("C3"), 1.0, tau=0.9, dur=2.5), 12.1)
    add(C["bass"], bass(hz("G3"), 0.7, tau=0.8, dur=2.5), 12.1)
    add(C["mar"], marimba(hz("D5"), 0.6), 12.1)
    add(C["mar"], marimba(hz("G5"), 0.6), 12.1)
    for i in range(5):            # тремоло 16-ми C6/E6, 12.1–12.6
        add(C["mar"], marimba(hz("C6" if i % 2 == 0 else "E6"), 0.75 - 0.08 * i), 12.1 + 0.125 * i)
    add(C["bell"], bell(hz("G6"), 1.0), 12.1)
    return S


LEVELS = {"mar": -18, "uke": -20, "bass": -20, "shk": -28, "bell": -30}
PANS = {"mar": 0.15, "uke": -0.25, "bass": 0.0, "shk": 0.05, "bell": 0.15}


def bus(S):
    """Сумма стемов в стерео; уровень каждого инструмента — по общему пику (A∪B∪C)."""
    out = {k: np.zeros((2, len(S[k]["mar"]))) for k in S}
    for s, lvl in LEVELS.items():
        pk = max(np.max(np.abs(S[k][s])) for k in S)
        gl, gr = pan_gains(PANS[s])
        for k in S:
            x = S[k][s] * (db(lvl) / pk)
            out[k][0] += x * gl
            out[k][1] += x * gr
    return out


def tape_stop(a, t_start=6.5, t_end=7.0):
    """Ресэмплинг с падающей скоростью (−2 полутона за 0.5 с), ФНЧ 8 кГц → 600 Гц, гейн → −∞."""
    i0, i1 = int(t_start * FS), int(t_end * FS)
    m = i1 - i0
    u = np.arange(m) / m
    rate = 2 ** (-2 / 12 * u)
    pos = i0 + np.concatenate([[0.0], np.cumsum(rate[:-1])])
    fc = 8000 * (600 / 8000) ** u
    gain = np.cos(0.5 * np.pi * u) ** 2
    y = np.zeros((2, m))
    idx = np.arange(a.shape[1])
    for c in range(2):
        seg = np.interp(pos, idx, a[c])
        # прогрев фильтра на 20 мс до точки, чтобы не было ступеньки
        pre = a[c, i0 - 960:i0]
        f = svf(np.concatenate([pre, seg]), np.concatenate([np.full(960, 8000.0), fc]), 0.707, "lp")
        lp = f[960:]
        # плавный вход в фильтр за 20 мс (сухой → фильтрованный)
        xf = np.clip(u * m / 960, 0, 1)
        y[c] = (seg * (1 - xf) + lp * xf) * gain
    return y


def main():
    S = score()
    b = bus(S)
    out = np.zeros((2, N))
    A, B, C = b["A"], b["B"], b["C"]
    i65, i70 = int(6.5 * FS), int(7.0 * FS)
    out[:, :i65] = A[:, :i65]
    out[:, i65:i70] = tape_stop(A)
    # B: 9.1 → 11.9, к 11.9 гасим (fade 40 мс) — стоп-тайм до 12.1
    i91, i119, i121 = int(9.1 * FS), int(11.9 * FS), int(12.1 * FS)
    seg = B[:, i91:i119].copy()
    nf = int(0.04 * FS)
    seg[:, -nf:] *= np.cos(0.5 * np.pi * np.linspace(0, 1, nf))
    out[:, i91:i119] = seg
    # C: ферма 12.1 → естественное затухание, fade 13.4 → −∞ к 14.0, тишина до 15.0
    i134, i140 = int(13.4 * FS), int(14.0 * FS)
    seg = C[:, i121:i140].copy()
    k = np.arange(seg.shape[1]) + i121
    w = np.where(k < i134, 1.0, np.cos(0.5 * np.pi * np.clip((k - i134) / (i140 - i134), 0, 1)) ** 2)
    out[:, i121:i140] = seg * w
    out[:, i140:] = 0.0
    out[:, :int(0.4 * FS)] = 0.0       # музыка стартует ровно на касании 0.4
    assert out.shape == (2, N)
    pk = np.max(np.abs(out))
    write_wav24(os.path.join(OUT, "music.wav"), out)
    print(f"music.wav: {N} сэмплов, {N / FS:.3f} с, пик {20 * np.log10(pk):.1f} dBFS")


if __name__ == "__main__":
    main()
