#!/usr/bin/env python3
"""Синтез неречевых вокализаций кубика («Кубик и сортер»).

Рецепт — direction.md §5.4: мягкая «пила» (гармоники 1..16, 1/n) с f0-контуром,
вибрато 6 Гц ±1.5 %, джиттер ±0.5 %, две параллельные форманты (BPF, Q 6),
придыхание шумом через те же форманты, огибающая 10/40 мс, согласные х/ф/р/й/м.

Зависимости: только numpy (фильтры — собственный SVF с переменной частотой).
Детерминизм: seed 2610, у каждой вокализации свой дочерний генератор [2610, idx].

Выход (рядом со скриптом):
  vo_<id>.wav     — отдельные вокализации, 48 кГц / 24 бит / моно, пик −3 dBFS,
                    тишина по краям ≤ 5 мс;
  vo_track.wav    — общая дорожка ровно 720 000 сэмплов (15.000 с), все вокализации
                    на своих местах с пиковыми уровнями из таблицы §5.4, пик ≤ −1 dBFS.
Запуск: python3 gen_vo.py
"""
import os
import wave

import numpy as np

FS = 48000
TRACK_LEN = 720000
SEED = 2610
OUT = os.path.dirname(os.path.abspath(__file__))

# Форманты «маленького рта» (уже ×1.35), Гц: F1, F2
VOWELS = {
    "a": (1080, 1620),
    "o": (675, 1215),
    "u": (430, 1080),
    "y": (510, 2160),   # «ы»
    "e": (740, 2430),
    "j": (400, 3000),   # цель глайда «й»
}


# ---------------------------------------------------------------- утилиты
def db(x):
    return 10.0 ** (x / 20.0)


def svf(x, fc, q=0.707, mode="bp"):
    """TPT state-variable filter с покадровой (посэмпловой) частотой среза.
    mode: 'lp' | 'bp' (нормированный, пик 1) | 'hp'."""
    n = len(x)
    fc = np.broadcast_to(np.asarray(fc, dtype=np.float64), (n,))
    fc = np.clip(fc, 20.0, FS * 0.45)
    g = np.tan(np.pi * fc / FS)
    k = 1.0 / q
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    lp = np.empty(n)
    bp = np.empty(n)
    ic1 = ic2 = 0.0
    xs = x.tolist()
    a1l, a2l, a3l = a1.tolist(), a2.tolist(), a3.tolist()
    for i in range(n):
        v3 = xs[i] - ic2
        v1 = a1l[i] * ic1 + a2l[i] * v3
        v2 = ic2 + a2l[i] * ic1 + a3l[i] * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        bp[i] = v1
        lp[i] = v2
    if mode == "lp":
        return lp
    if mode == "bp":
        return k * bp
    return x - k * bp - lp


def curve(points, n, log=True):
    """Кусочно-линейная кривая по точкам (t_norm, value); log=True — по логарифму
    (экспоненциальный глайд высоты)."""
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    ts = np.array([p[0] for p in points])
    vs = np.array([p[1] for p in points], dtype=np.float64)
    if log:
        return np.exp(np.interp(t, ts, np.log(vs)))
    return np.interp(t, ts, vs)


def smooth_noise(rng, n, win):
    w = max(1, int(win))
    r = rng.standard_normal(n + w)
    c = np.convolve(r, np.ones(w) / w, mode="same")[:n]
    return c / (np.max(np.abs(c)) + 1e-12)


def env_ar(n, attack=0.010, release=0.040):
    """Огибающая: подъём/спад по полукосинусу."""
    e = np.ones(n)
    na = min(n, int(attack * FS))
    nr = min(n - na, int(release * FS))
    if na:
        e[:na] = 0.5 - 0.5 * np.cos(np.pi * np.arange(na) / na)
    if nr:
        e[n - nr:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(nr) / nr)
    return e


def noise_burst(rng, dur, lo=None, hi=None, hp=None, attack=0.008, release=0.025):
    n = int(round(dur * FS))
    w = rng.standard_normal(n)
    if lo is not None:
        fc = np.sqrt(lo * hi)
        q = fc / (hi - lo)
        w = svf(svf(w, fc, q, "bp"), fc, q, "bp")
    if hp is not None:
        w = svf(svf(w, hp, 0.707, "hp"), hp, 0.707, "hp")
        w = svf(w, 9000, 0.707, "lp")          # без «стеклянного» верха
    w /= np.max(np.abs(w)) + 1e-12
    return w * env_ar(n, attack, release)


# ---------------------------------------------------------------- голос
def voice(rng, dur, f0_pts, vowel_pts=None, nasal=False, vib_rate=6.0,
          vib_depth=0.015, breath=0.10, attack=0.010, release=0.040,
          f2_mul=1.0, am=None, jitter=0.005):
    """Голосовой звук. f0_pts/vowel_pts — точки (t_norm, ...).
    vowel_pts: [(t, 'o'), (t, 'j'), ...] — форманты интерполируются.
    am: (rate, depth, t0, t1) — амплитудная модуляция на участке (норм. время)."""
    n = int(round(dur * FS))
    t = np.arange(n) / FS
    f0 = curve(f0_pts, n)
    if vib_depth > 0:
        # вибрато мягко входит за первые 60 мс
        ramp = np.clip(t / 0.06, 0, 1)
        f0 = f0 * (1.0 + vib_depth * ramp * np.sin(2 * np.pi * vib_rate * t))
    if jitter > 0:
        f0 = f0 * (1.0 + jitter * smooth_noise(rng, n, FS * 0.015))
    phase = 2 * np.pi * np.cumsum(f0) / FS
    src = np.zeros(n)
    for h in range(1, 17):
        fh = h * f0
        mask = np.clip((17000.0 - fh) / 2000.0, 0.0, 1.0)  # без алиасинга
        src += mask * np.sin(h * phase) / h
    src /= 2.0
    # придыхание: шум, слегка окрашенный
    br = rng.standard_normal(n) * 0.5

    if nasal:
        # «м»: гармоники → LPF 900 Гц + носовая форманта 340 Гц
        voiced = 0.8 * svf(svf(src, 900, 0.707, "lp"), 900, 0.707, "lp") \
            + 0.9 * svf(src, 340, 6, "bp")
        noisy = 0.6 * svf(br, 340, 6, "bp") + 0.3 * svf(br, 900, 0.707, "lp")
    else:
        vt = np.linspace(0, 1, n, endpoint=False)
        ts = np.array([p[0] for p in vowel_pts])
        F1 = np.interp(vt, ts, [VOWELS[p[1]][0] for p in vowel_pts])
        F2 = np.interp(vt, ts, [VOWELS[p[1]][1] for p in vowel_pts]) * f2_mul
        voiced = svf(src, F1, 6, "bp") + 0.55 * svf(src, F2, 6, "bp") \
            + 0.30 * svf(src, 1200, 0.707, "lp")         # «тело», округлость
        noisy = svf(br, F1, 6, "bp") + 0.55 * svf(br, F2, 6, "bp")
    sig = voiced / (np.max(np.abs(voiced)) + 1e-12)
    nz = noisy / (np.max(np.abs(noisy)) + 1e-12)
    out = (1.0 - breath) * sig + breath * nz
    if am is not None:
        rate, depth, t0, t1 = am
        vt = np.linspace(0, 1, n, endpoint=False)
        w = ((vt >= t0) & (vt < t1)).astype(float)
        w = np.convolve(w, np.ones(240) / 240, mode="same")   # 5 мс сглаживание
        out *= 1.0 - depth * w * (0.5 + 0.5 * np.cos(2 * np.pi * rate * t))
    out = svf(out, 7500, 0.707, "lp")                         # мягкий верх
    return out * env_ar(n, attack, release)


def place(dst, src, start_s, gain=1.0):
    i = int(round(start_s * FS))
    j = min(len(dst), i + len(src))
    dst[i:j] += gain * src[: j - i]
    return dst


def silence(dur):
    return np.zeros(int(round(dur * FS)))


def echoes(x, taps):
    """taps: [(delay_s, gain_db)] — добавляет отражения, удлиняет хвост."""
    tail = int(max(d for d, _ in taps) * FS) + 1
    y = np.concatenate([x, np.zeros(tail)])
    for d, g in taps:
        place(y, x, d, db(g))
    return y


# ---------------------------------------------------------------- вокализации
def v_uf(rng):            # «уф!» 0.17 с: у 700→450 (эксп.), ф 50 мс в конце
    u = voice(rng, 0.13, [(0, 700), (1, 450)], [(0, "u"), (1, "u")], breath=0.15)
    y = np.concatenate([u, silence(0.04)])
    f = noise_burst(rng, 0.06, hp=3000, attack=0.010, release=0.040)
    return place(y, 0.22 * f, 0.11)


def v_hm_q(rng):          # «хм?» 0.30 с: 420 ровно 0.18 с → 620 (последние 40 %)
    x = silence(0.30)
    place(x, 0.30 * noise_burst(rng, 0.04, 1000, 3000), 0.0)
    m = voice(rng, 0.27, [(0, 420), (0.15 / 0.27, 420), (1, 620)], nasal=True,
              breath=0.08)
    return place(x, m, 0.03)


def v_oi(rng):            # «ой!» 0.15 с: 900 → 1100 → 800, о → й
    return voice(rng, 0.15, [(0, 900), (0.45, 1100), (1, 800)],
                 [(0, "o"), (0.55, "o"), (0.82, "j"), (1, "j")], breath=0.08)


def v_hm_firm(rng):       # «хм!» решительное 0.20 с: 500 → 380, без вибрато, атака 5 мс
    x = silence(0.20)
    place(x, 0.25 * noise_burst(rng, 0.025, 1000, 3000, attack=0.004,
                                release=0.012), 0.0)
    m = voice(rng, 0.18, [(0, 500), (1, 380)], nasal=True, vib_depth=0.0,
              attack=0.005, breath=0.06)
    return place(x, m, 0.02)


def v_oioi(rng):          # «ой-ой!» 2×0.12 + пауза 0.04: 1000→1150, 1100→1300
    kw = dict(vib_rate=8.0, vib_depth=0.03, breath=0.08)
    vp = [(0, "o"), (0.5, "o"), (0.8, "j"), (1, "j")]
    a = voice(rng, 0.12, [(0, 1000), (1, 1150)], vp, **kw)
    b = voice(rng, 0.12, [(0, 1100), (1, 1300)], vp, **kw)
    return np.concatenate([a, silence(0.04), b])


def make_yh(base):        # «ых!» 0.12 с: ы, внутри −10 %, натуга АМ 30 Гц 20 %, «х» в конце
    def f(rng):
        y = voice(rng, 0.09, [(0, base), (1, base * 0.9)], [(0, "y"), (1, "y")],
                  breath=0.15, am=(30.0, 0.20, 0.0, 1.0), release=0.025)
        x = np.concatenate([y, silence(0.03)])
        return place(x, 0.35 * noise_burst(rng, 0.045, 1000, 3000, attack=0.006,
                                           release=0.030), 0.075)
    return f


def v_yy_sigh(rng):       # «ыы…» 0.32 с: 520 → 300, придыхание 30 %, релиз 120 мс
    return voice(rng, 0.32, [(0, 520), (0.3, 470), (1, 300)],
                 [(0, "y"), (0.6, "y"), (1, "u")], breath=0.30, release=0.120,
                 vib_depth=0.012)


def v_hnyk(rng):          # «хнык» 0.10 с: блип 700 Гц 30 мс + вдох носом (шум 3–6 кГц)
    x = silence(0.10)
    blip = voice(rng, 0.03, [(0, 720), (1, 680)], nasal=True, vib_depth=0.0,
                 attack=0.004, release=0.015, breath=0.2)
    place(x, blip, 0.0)
    place(x, 0.6 * noise_burst(rng, 0.07, 3000, 6000, attack=0.015,
                               release=0.035), 0.03)
    return x


def v_m_q(rng):           # «м?» 0.18 с: 450 → 560, тихо, любопытство
    return voice(rng, 0.18, [(0, 450), (0.35, 450), (1, 560)], nasal=True,
                 breath=0.08, attack=0.015)


def v_a(rng):             # «а!» 0.25 с: 600 → 950, держать 950 последние 0.08 с
    return voice(rng, 0.25, [(0, 600), (0.17 / 0.25, 950), (1, 950)],
                 [(0, "a"), (1, "a")], f2_mul=1.10, vib_rate=7.0, breath=0.08)


def _ura_dry(rng):        # у 0.12 + ра 0.10 + а 0.25 = 0.47 с, 650 → 780 → 980
    d = 0.47
    v = voice(rng, d, [(0, 650), (0.12 / d, 700), (0.22 / d, 780), (0.30 / d, 980),
                       (1, 980)],
              [(0, "u"), (0.10 / d, "u"), (0.17 / d, "a"), (1, "a")],
              breath=0.08, am=(25.0, 0.6, 0.12 / d, 0.18 / d), vib_rate=6.5)
    return v


def v_ura(rng):           # «ура!» уходящее: LPF 8 к → 1.5 к и −6 дБ за 0.4 с + 3 отражения
    v = _ura_dry(rng)
    n = len(v)
    k = np.clip(np.arange(n) / (0.4 * FS), 0, 1)
    fc = 8000.0 * (1500.0 / 8000.0) ** k
    v = svf(svf(v, fc, 0.707, "lp"), fc, 0.707, "lp") * db(-6.0 * k)
    return echoes(v, [(0.030, -8), (0.055, -12), (0.080, -16)])


def v_ura_echo(rng):      # эхо «ура!»: тот же сэмпл, LPF 900, эхо 180/360 мс (−6/−12)
    v = v_ura(np.random.default_rng([SEED, 10]))  # тот же сэмпл, что и vo_ura
    v = svf(svf(v, 900, 0.707, "lp"), 900, 0.707, "lp")
    return echoes(v, [(0.180, -6), (0.360, -12)])


# id, функция, старт в дорожке (с), пик в дорожке (dBFS), номинальная длит. (с)
CUES = [
    ("uf",       v_uf,        0.43, -10, 0.17),
    ("hm_q",     v_hm_q,      1.33, -12, 0.30),
    ("oi",       v_oi,        2.65,  -9, 0.15),
    ("hm_firm",  v_hm_firm,   3.80, -11, 0.20),
    ("oioi",     v_oioi,      5.05,  -8, 0.28),
    ("yh1",      make_yh(400), 5.43, -12, 0.12),
    ("yh2",      make_yh(460), 5.68, -10, 0.12),
    ("yh3",      make_yh(530), 5.93,  -8, 0.12),
    ("yy_sigh",  v_yy_sigh,   6.73, -14, 0.32),
    ("hnyk",     v_hnyk,      7.40, -20, 0.10),
    ("m_q",      v_m_q,       8.13, -16, 0.18),
    ("a",        v_a,         9.13,  -8, 0.25),
    ("ura",      v_ura,      11.50, -10, 0.47),
    ("ura_echo", v_ura_echo, 13.40, -24, 0.47),
]


# ---------------------------------------------------------------- запись
def write_wav24(path, x):
    x = np.clip(x, -1.0, 1.0 - 2.0 ** -23)
    i = np.round(x * 8388607.0).astype(np.int32)
    b = np.empty((len(i), 3), dtype=np.uint8)
    b[:, 0] = i & 0xFF
    b[:, 1] = (i >> 8) & 0xFF
    b[:, 2] = (i >> 16) & 0xFF
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(FS)
        w.writeframes(b.tobytes())


def trim(x, thr_db=-60.0, keep=0.004):
    """Убрать тишину по краям, оставив ≤ 5 мс (4 мс)."""
    a = np.abs(x)
    thr = np.max(a) * db(thr_db)
    idx = np.nonzero(a > thr)[0]
    k = int(keep * FS)
    s = max(0, idx[0] - k)
    e = min(len(x), idx[-1] + 1 + k)
    return x[s:e], s / FS


def active_dur(x, thr_db=-40.0):
    a = np.abs(x)
    idx = np.nonzero(a > np.max(a) * db(thr_db))[0]
    return (idx[-1] - idx[0] + 1) / FS


def main():
    track = np.zeros(TRACK_LEN)
    report = []
    for idx, (cid, fn, start, peak_db, nom) in enumerate(CUES):
        rng = np.random.default_rng([SEED, idx])
        x = fn(rng)
        x = x - np.mean(x)                       # без DC
        x, lead = trim(x)
        x = x / np.max(np.abs(x)) * db(-3.0)     # файл: пик −3 dBFS
        write_wav24(os.path.join(OUT, f"vo_{cid}.wav"), x)
        g = db(peak_db) / db(-3.0)
        place(track, x, start + lead, g)
        report.append((cid, start, len(x) / FS, active_dur(x), nom, peak_db))
    pk = np.max(np.abs(track))
    if pk > db(-1.0):                            # страховка, не должна срабатывать
        track *= db(-1.0) / pk
    assert len(track) == TRACK_LEN
    write_wav24(os.path.join(OUT, "vo_track.wav"), track)
    print(f"{'id':10s} {'start':>6s} {'file_s':>7s} {'act_s':>6s} {'nom_s':>6s} {'peak':>5s}")
    for cid, st, fl, ac, nom, pdb in report:
        print(f"{cid:10s} {st:6.2f} {fl:7.3f} {ac:6.3f} {nom:6.2f} {pdb:5d}")
    print(f"track: {len(track)} samples, peak {20*np.log10(np.max(np.abs(track))):.2f} dBFS")


if __name__ == "__main__":
    main()
