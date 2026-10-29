#!/usr/bin/env python3
"""SFX «Кубик и сортер» — direction.md §5.3, тайминги script.md §4.

Все касания ставятся на первый кадр контакта: t = кадр / 30 (без опережения).
Пики — из колонки «Пик» §5.3 (до мастера). Панорама — за кубиком: pan = x_world / 2.1 · 0.35.
Свист падения «вжж» — один сэмпл 1.1 с, положенный по кругу с 14.3 с: часть [0; 0.7) →
14.3–15.0, часть [0.7; 1.1) → 0.0–0.4. Фаза непрерывна, шов петли проходит внутри сэмпла,
поэтому на стыке нет ни разрыва, ни кроссфейда (кроссфейд из §5.3 был бы страховкой).

Выход: sfx.wav — 48 кГц, 24 бит, стерео, ровно 720 000 сэмплов.
Детерминизм: np.random.default_rng(2610). Запуск: python3 gen_sfx.py
"""
import os

import numpy as np

from dsp import (FS, N, SEED, bpf, bpf_q, db, exp_env, exp_sweep, fade, lpf, hpf,
                 norm_peak, osc, pink, place, svf, write_wav24, to_db)

OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(SEED)


def fr(k):                      # кадр → секунды
    return k / 30.0


def ns(sec):
    return int(round(sec * FS))


def click(ms=1.0, lp=None, hp=None):
    n = max(2, ns(ms / 1000))
    x = rng.standard_normal(n + 256)
    if lp:
        x = lpf(x, lp)
    if hp:
        x = hpf(x, hp)
    x = x[256:] * np.hanning(n)
    return x / np.max(np.abs(x))


def pad(x, n):
    y = np.zeros(n)
    y[:min(n, len(x))] += x[:n]
    return y


# ------------------------------------------------------------------ рецепты
def whoosh_fall():
    """«вжж» 1.1 с: синус 1600→500 (эксп.) + шум BPF (центр 2·f0, Q 3) 40 %; амплитуда t²."""
    n = ns(1.1)
    f = exp_sweep(1600, 500, n)
    tone = osc(f)
    air = svf(rng.standard_normal(n), 2 * f, 3.0, "bp")
    air /= np.max(np.abs(air))
    u = np.arange(n) / n
    x = (tone + 0.4 * air) * u ** 2
    nf = ns(0.005)                            # обрыв на касании 0.4 — 5 мс
    x[-nf:] *= np.cos(0.5 * np.pi * np.linspace(0, 1, nf))
    return x


def plop_bonk():                # 0.4 «плюх»-бонк
    n = ns(0.6)
    f = exp_sweep(240, 120, n, 0.08)
    ph = 2 * np.pi * np.cumsum(f) / FS
    body = (np.sin(ph) + 0.3 * np.sin(2 * ph)) * exp_env(n, 0.15, 0.001)
    cl = pad(click(2, lp=3000), n) * 0.5
    pl = lpf(rng.standard_normal(n), 800) * exp_env(n, 0.06, 0.002)
    pl /= np.max(np.abs(pl))
    return body + cl + 0.6 * pl


def tuk(f0, f1=None, tau=0.04, dur=0.25):
    n = ns(dur)
    f = exp_sweep(f0, f1 if f1 else f0 * 2 / 3, n, 0.03)
    x = osc(f) * exp_env(n, tau, 0.0005)
    return x + 0.4 * pad(click(1, hp=1500), n)


def tonal_tuk(f0):              # «тук» в тон аккорда: малый свип вниз
    return tuk(f0 * 1.06, f0, tau=0.05, dur=0.3)


def spring(dur, f1, f0=180.0):
    n = ns(dur)
    f = exp_sweep(f0, f1, n)
    t = np.arange(n) / FS
    f = f * (1 + 0.08 * np.sin(2 * np.pi * 14 * t))
    u = np.arange(n) / n
    x = osc(f) * (0.15 + 0.85 * u ** 1.5)
    return fade(x, 0.01, 0.015)


def bonk_mid():                 # 2.6 «БОНК!»
    n = ns(0.8)
    f = exp_sweep(330, 160, n, 0.1)
    ph = 2 * np.pi * np.cumsum(f) / FS
    x = (np.sin(ph) + 0.2 * np.sin(2.7 * ph) + 0.25 * np.sin(2 * ph)) * exp_env(n, 0.2, 0.001)
    return x + 0.5 * pad(click(2), n)


def swish(dur, f0=2000, f1=800, am=None):
    n = ns(dur)
    x = svf(rng.standard_normal(n), exp_sweep(f0, f1, n), 4.0, "bp")
    env = np.hanning(n)
    if am:
        t = np.arange(n) / FS
        env = env * (0.6 + 0.4 * np.sin(2 * np.pi * am * t))
    return x * env


def tyk():
    n = ns(0.15)
    return osc(np.full(n, 1100.0)) * exp_env(n, 0.025, 0.0005)


def bonk_krrk():                # 5.0 «БОНК-КРРК!» + «дзынь» дерева — самый громкий
    n = ns(1.0)
    f = exp_sweep(260, 110, n, 0.12)
    ph = 2 * np.pi * np.cumsum(f) / FS
    bonk = (np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
            + 0.1 * np.sin(4 * ph)) * exp_env(n, 0.25, 0.001)
    t = np.arange(n) / FS
    wood = (np.sin(2 * np.pi * 620 * t) * np.exp(-t / 0.12)
            + 0.6 * np.sin(2 * np.pi * 1710 * t) * np.exp(-t / 0.06)
            + 0.35 * np.sin(2 * np.pi * 3380 * t) * np.exp(-t / 0.03))
    wood[:48] *= np.linspace(0, 1, 48)
    krk = np.zeros(n)
    starts = np.sort(rng.uniform(0.0, 0.116, 8))
    for k, s in enumerate(starts):
        p = bpf(rng.standard_normal(ns(0.004) + 256), 2000, 4000)[256:] * np.hanning(ns(0.004))
        i = ns(0.01 + s)
        krk[i:i + len(p)] += p / np.max(np.abs(p)) * (1 - 0.06 * k)
    return bonk + 0.45 * wood + 0.5 * krk + 0.5 * pad(click(2), n)


def chpok():                    # 6.1 «ЧПОК» пробка
    n = ns(0.3)
    f = exp_sweep(400, 1200, n, 0.03)
    x = osc(f) * exp_env(n, 0.05, 0.0005)
    x = x + 0.5 * pad(click(1), n)
    res = bpf_q(x, 900, 8)
    return x + 0.6 * res / np.max(np.abs(res))


def buh(lp_hz=None):            # 6.5 «бух» (и 12.1 — из коробки, LPF 300)
    n = ns(0.6)
    f = exp_sweep(90, 50, n, 0.15)
    ph = 2 * np.pi * np.cumsum(f) / FS
    body = (np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.15 * np.sin(3 * ph)) * exp_env(n, 0.12, 0.002)
    # телефоны < 100 Гц не играют: верхние гармоники (4–6), тихо, быстро гаснут
    body += (0.18 * np.sin(4 * ph) + 0.1 * np.sin(5 * ph)) * exp_env(n, 0.06, 0.002)
    nz = lpf(rng.standard_normal(n), 500) * exp_env(n, 0.05, 0.002)
    x = body + 0.5 * nz / np.max(np.abs(nz))
    if lp_hz:
        x = lpf(x, lp_hz)
    return x


def shorkh():                   # 6.7 перекат
    n = ns(0.2)
    x = lpf(pink(rng, n + 2048), 800)[2048:]
    return x * np.bartlett(n)


def ambient():                  # 7.0–9.6: розовый шум LPF 400
    t0, t1 = 7.0, 9.6
    n = ns(t1 - t0)
    x = lpf(pink(rng, n + 4096), 400)[4096:]
    t = np.arange(n) / FS + t0
    g = np.clip((t - 7.0) / 0.3, 0, 1)                         # fade-in 0.3 с
    g = g * np.where(t < 9.1, 1.0, db(-6))                      # под музыку −6 дБ
    g = g * np.clip((9.6 - t) / 0.5, 0, 1)                      # выкл. к 9.6
    g = np.convolve(g, np.ones(ns(0.03)) / ns(0.03), "same")    # без ступенек
    return x * g


def dzin():                     # 7.9 блик: колокольчик C7 + «искра»
    n = ns(1.6)
    t = np.arange(n) / FS
    f = 2093.0
    x = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.8)
         + 0.25 * np.sin(2 * np.pi * 2.76 * f * t) * np.exp(-t / 0.3)
         + 0.08 * np.sin(2 * np.pi * 5.4 * f * t) * np.exp(-t / 0.1))
    x[:48] *= np.linspace(0, 1, 48)
    sp = fade(osc(exp_sweep(3000, 5000, ns(0.15))), 0.005, 0.05) * db(-12)
    return x + pad(sp, n)


def vzhik():                    # 8.1–8.6 поворот, 0.15 с с центром 8.3
    n = ns(0.15)
    x = svf(rng.standard_normal(n), np.full(n, 1500.0), 2.0, "bp")
    return x * np.hanning(n)


def asmr_click():               # 11.0 «чпок-шшух» — самый мягкий удар, чистый
    n = ns(0.4)
    imp = np.zeros(n)
    imp[:ns(0.002)] = np.hanning(ns(0.002))
    c = bpf_q(imp, 3000, 10)
    c /= np.max(np.abs(c))
    thok = osc(np.full(n, 180.0)) * exp_env(n, 0.06, 0.001)
    thok += 0.35 * osc(np.full(n, 360.0)) * exp_env(n, 0.04, 0.001)   # слышно на телефоне
    air = lpf(rng.standard_normal(n), 2500)
    ne = ns(0.2)
    env = np.zeros(n)
    env[:ne] = np.linspace(1, 0, ne) ** 2
    env[:ns(0.004)] *= np.linspace(0, 1, ns(0.004))
    air = air / np.max(np.abs(air)) * env
    return 0.8 * c + thok + 0.35 * air


def slide():                    # 11.2–11.8 «шшшух»: LPF 3 кГц → 400, 0 → −12 дБ
    n = ns(0.6)
    x = svf(rng.standard_normal(n), exp_sweep(3000, 400, n), 0.707, "lp")
    u = np.arange(n) / n
    return fade(x * db(-12 * u), 0.03, 0.06)


def ping(f):
    n = ns(1.0)
    return osc(np.full(n, f)) * exp_env(n, 0.2, 0.001)


# ------------------------------------------------------------------ таблица событий
def events():
    E = []      # (t, сэмпл, пик dBFS, pan, метка)
    E += [(fr(12), plop_bonk(), -6, -0.11, "плюх-бонк 0.4")]
    E += [(fr(21), tuk(900, 600), -14, -0.11, "тук 0.7")]
    E += [(fr(51), tuk(640), -16, -0.16, "тук шажок 1.7")]
    E += [(fr(60), tuk(600), -16, -0.20, "тук шажок 2.0")]
    E += [(fr(63), spring(fr(69) - fr(63) + 0.02, 420), -14, -0.20, "набор 2.1–2.3")]
    E += [(fr(78), bonk_mid(), -4, -0.23, "БОНК 2.6")]
    E += [(fr(81), swish(fr(90) - fr(81)), -16, -0.17, "свист кувырка 2.7–3.0")]
    E += [(fr(93), tuk(900, 600), -14, -0.12, "тук 3.1")]
    E += [(fr(98), tyk(), -18, -0.12, "тык 3.25")]
    E += [(fr(120), tuk(560), -16, -0.15, "тук шаг назад 4.0")]
    E += [(fr(126), spring(fr(135) - fr(126) + 0.02, 520), -14, -0.15, "длинный набор 4.2–4.5")]
    E += [(fr(135), swish(fr(150) - fr(135), am=10), -16, -0.07, "свист вращения 4.5–5.0")]
    E += [(fr(150), bonk_krrk(), -1.5, 0.0, "БОНК-КРРК 5.0")]
    E += [(fr(183), chpok(), -6, 0.0, "ЧПОК 6.1")]
    E += [(fr(195), buh(), -7, 0.05, "бух 6.5")]
    E += [(fr(201), shorkh(), -20, 0.05, "шорх 6.7")]
    E += [(7.0, ambient(), -42, 0.0, "амбиент 7.0–9.6")]
    E += [(fr(237), dzin(), -12, 0.30, "дзинь 7.9")]
    E += [(8.3 - 0.075, vzhik(), -22, 0.05, "вжик 8.3")]
    E += [(fr(282), tyk(), -18, 0.05, "тык 9.4")]
    for k, f, p in [(294, 587.33, 0.10), (303, 659.26, 0.15), (312, 698.46, 0.20)]:
        E += [(fr(k), tonal_tuk(f), -15, p, f"тук {f:.0f} Гц {k / 30:.1f}")]
    E += [(fr(315), spring(fr(321) - fr(315) + 0.02, 380), -18, 0.20, "набор 10.5–10.7")]
    E += [(fr(330), asmr_click(), -8, 0.23, "чпок-шшух 11.0")]
    E += [(fr(336), slide(), -16, 0.23, "шшшух 11.2–11.8")]
    E += [(fr(363), buh(lp_hz=300), -12, 0.23, "бух из коробки 12.1")]
    pr = np.random.default_rng([SEED, 1225])
    for t, f in zip([12.2, 12.25, 12.32, 12.38, 12.45, 12.52],
                    [2093.0, 2637.0, 3136.0, 3520.0, 4186.0, 3136.0]):
        E += [(t, ping(f), -20, float(pr.uniform(-0.3, 0.3)), f"динь {f:.0f} {t}")]
    return E


def main():
    out = np.zeros((2, N))
    ev = events()
    for t, x, pk, pan, label in ev:
        place(out, norm_peak(x, pk), t, pan)
    # «вжж» на шве: один сэмпл по кругу с 14.3 (0.7 с до шва + 0.4 с после)
    w = norm_peak(whoosh_fall(), -10)
    place(out, w, 14.3, -0.11, wrap=True)
    i04 = ns(0.4)
    assert abs((ns(14.3) + len(w)) % N - i04) <= 1, "свист должен оборваться ровно на 0.4"
    write_wav24(os.path.join(OUT, "sfx.wav"), out)
    print(f"sfx.wav: {N} сэмплов, {N / FS:.3f} с, пик {to_db(np.max(np.abs(out))):.1f} dBFS, "
          f"событий {len(ev) + 1}")
    d = np.abs(np.diff(np.concatenate([out[:, -3:], out[:, :3]], axis=1), axis=1)).max()
    print(f"шов 15.0→0.0: макс. разность соседних сэмплов {d:.2e}")


if __name__ == "__main__":
    main()
