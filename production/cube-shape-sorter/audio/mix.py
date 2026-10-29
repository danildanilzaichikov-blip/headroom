#!/usr/bin/env python3
"""Сведение «Кубик и сортер»: vo_track + music (сайдчейн) + sfx → mix.wav.

Слои (direction §5.1–5.6):
  1. Голос  vo_track.wav (моно) → стерео, pan за кубиком по таблице voiceover.md
             (pan меняется только в паузах между вокализациями).
  2. Музыка music.wav: сайдчейн-дакинг под голос (детектор attack 5 мс / release 150 мс,
             до −6 дБ) + плановые провалы §5.2: 2.6 −4 дБ/0.2 с, 5.0 −8 дБ/0.3 с,
             11.0 −3 дБ/0.3 с (attack 5 мс, release 150 мс). Уровень шины — так, чтобы
             короткая громкость музыки в мастере была ≈ −22 LUFS (§5.6).
  3. SFX    sfx.wav — как есть (иерархия ударов заложена пиками в gen_sfx.py).
  Мастер: общий гейн до −14 LUFS интегрально + true-peak лимитер (lookahead 5 мс,
  оверсемплинг ×4, потолок −1.3 dBTP, release 80 мс). Все огибающие считаются по кругу —
  шов петли 15.0 → 0.0 не создаёт ступенек.

Выход: mix.wav (48 кГц, 24 бит, стерео, 720 000 сэмплов). Запуск: python3 mix.py
"""
import os

import numpy as np
from scipy import ndimage, signal

from dsp import (FS, N, db, lufs_integrated, lufs_short_term, pan_gains, read_wav,
                 to_db, true_peak, write_wav24)

OUT = os.path.dirname(os.path.abspath(__file__))
TARGET_LUFS = -14.0
CEIL_DBTP = -1.3
MUSIC_ST_TARGET = -22.0

# pan голоса: (t_from, t_to, pan) — константа на вокализациях, линейный переход в паузах
VO_PAN = [(0.00, 2.45, -0.11), (2.60, 3.40, -0.23), (3.70, 4.90, -0.11),
          (5.00, 6.40, 0.00), (6.65, 9.60, 0.05), (11.30, 14.40, 0.23)]

DIPS = [(78 / 30, -4.0, 0.2), (150 / 30, -8.0, 0.3), (330 / 30, -3.0, 0.3)]


def pan_curve():
    t = np.arange(N) / FS
    xs, ys = [], []
    for a, b, p in VO_PAN:
        xs += [a, b]
        ys += [p, p]
    # замыкаем по кругу: к 15.0 возвращаемся к pan кадра 0
    xs += [14.95]
    ys += [VO_PAN[0][2]]
    return np.interp(t, xs, ys)


def follower(x, att=0.005, rel=0.150, circular=True):
    """Пиковый детектор attack/release; circular — прогон с прокруткой хвоста в начало."""
    a_att = np.exp(-1 / (att * FS))
    a_rel = np.exp(-1 / (rel * FS))
    src = np.concatenate([x[-FS:], x]) if circular else x
    out = np.empty(len(src))
    e = 0.0
    for i, v in enumerate(src.tolist()):
        c = a_att if v > e else a_rel
        e = c * e + (1 - c) * v
        out[i] = e
    return out[FS:] if circular else out


def duck_gain(vo_mono):
    env = follower(np.abs(vo_mono))
    env_db = 20 * np.log10(env + 1e-9)
    red = -6.0 * np.clip((env_db + 40) / 20, 0, 1)          # до −6 дБ при голосе ≥ −20 dBFS
    t = np.arange(N) / FS
    plan = np.zeros(N)
    for t0, d, hold in DIPS:
        plan = np.minimum(plan, np.where((t >= t0) & (t < t0 + hold), d, 0.0))
    # сглаживание плана тем же attack/release (по величине провала)
    plan_s = -follower(-plan)
    return db(np.minimum(red, plan_s)), red, plan_s


def limiter(x, ceil_db=CEIL_DBTP, look=0.005, rel=0.080, os_=4):
    """True-peak лимитер: пик по ×4-оверсемплу, lookahead-min (по кругу), release, сглаживание."""
    ceil = db(ceil_db)
    up = np.stack([signal.resample_poly(np.concatenate([c[-4096:], c, c[:4096]]), os_, 1)
                   for c in x])
    pk = np.max(np.abs(up), axis=0).reshape(-1, os_).max(axis=1)[4096:4096 + N]
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-12))
    L = int(look * FS)
    # минимум по окну [n; n+L] — заранее (lookahead), по кругу
    g = ndimage.minimum_filter1d(need, size=L + 1, origin=-(L // 2), mode="wrap")
    a = np.exp(-1 / (rel * FS))
    src = np.concatenate([g[-FS:], g]).tolist()
    r = np.empty(len(src))
    e = 1.0
    for i, v in enumerate(src):
        e = v if v < e else a * e + (1 - a) * v
        r[i] = e
    r = r[FS:]
    # скользящее среднее по L (окно назад): сглаживает атаку и не превышает need
    k = np.ones(L) / L
    rr = np.concatenate([r[-L:], r])
    sm = np.convolve(rr, k, "valid")[1:]
    assert len(sm) == N
    return x * sm, sm


def main():
    vo = read_wav(os.path.join(OUT, "vo_track.wav"))[0]
    music = read_wav(os.path.join(OUT, "music.wav"))
    sfx = read_wav(os.path.join(OUT, "sfx.wav"))
    assert vo.shape[0] == N and music.shape[1] == N and sfx.shape[1] == N

    gl, gr = pan_gains(pan_curve())
    vo_st = np.stack([vo * gl, vo * gr])
    dg, red, plan = duck_gain(vo)

    # уровень шины музыки: короткая громкость в т.1–3 после мастера ≈ −22 LUFS
    m_st = np.median(lufs_short_term(music[:, int(0.4 * FS):int(6.4 * FS)])[:, 1])
    g_music_db, g_master_db = 0.0, 0.0
    for _ in range(4):
        mus = music * dg * db(g_music_db)
        pre = vo_st + mus + sfx
        g_master_db = 0.0
        for _ in range(6):                 # гейн мастера с учётом лимитера
            y, gr_curve = limiter(pre * db(g_master_db))
            li = lufs_integrated(y)
            g_master_db += TARGET_LUFS - li
            if abs(TARGET_LUFS - li) < 0.02:
                break
        g_music_db = MUSIC_ST_TARGET - (m_st + g_master_db)
    mus = music * dg * db(g_music_db)
    pre = vo_st + mus + sfx
    y, gr_curve = limiter(pre * db(g_master_db))

    write_wav24(os.path.join(OUT, "mix.wav"), y)

    li = lufs_integrated(y)
    tp = to_db(true_peak(y))
    print(f"шина музыки {g_music_db:+.1f} дБ, мастер {g_master_db:+.1f} дБ")
    print(f"mix.wav: I = {li:.2f} LUFS, true peak = {tp:.2f} dBTP (×4, python), "
          f"sample peak = {to_db(np.max(np.abs(y))):.2f} dBFS")
    print(f"лимитер: макс. ослабление {to_db(gr_curve.min()):.1f} дБ; "
          f"работал {np.mean(gr_curve < 0.999) * 15:.2f} с из 15")
    # иерархия ударов после мастера
    for t0, name in [(0.4, "плюх 0.4"), (2.6, "бонк 2.6"), (5.0, "бонк-крк 5.0"), (11.0, "клик 11.0")]:
        i = int(t0 * FS)
        seg = y[:, i:i + int(0.12 * FS)]
        print(f"  {name:14s} пик {to_db(np.max(np.abs(seg))):6.1f} dBFS, "
              f"ослабл. лимитера {to_db(gr_curve[i:i + int(0.12 * FS)].min()):5.1f} дБ")
    ms = lufs_short_term(mus * db(g_master_db))
    sel = (ms[:, 0] > 1.9) & (ms[:, 0] < 5.0)
    print(f"музыка в мастере: short-term ≈ {np.median(ms[sel, 1]):.1f} LUFS (т.1–3, с дакингом)")


if __name__ == "__main__":
    main()
