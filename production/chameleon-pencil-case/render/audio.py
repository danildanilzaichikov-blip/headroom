#!/usr/bin/env python3
"""Музыка и SFX для «Хамелеона в пенале» (без голоса): синтез numpy, 48 кГц, ровно 15 с, петля.

Музыка: F-dur, 3/4, ♩=120 (такт 1.5 с, 10 тактов): щипковые (Karplus–Strong) «ум-па-па» +
маримба-мелодия; на гэге с рукой (10.5–13.5 с) мелодия замолкает, остаётся тревожный бас.
Хвосты нот и SFX заворачиваются в начало — шов петли без щелчка.

Запуск:  python audio.py --out mix.wav
"""
import argparse
import wave

import numpy as np

SR = 48000
N = 15 * SR
RNG = np.random.default_rng(7)


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def pluck(freq, dur=1.2, bright=0.5, amp=0.5):
    n = int(dur * SR)
    p = max(2, int(SR / freq))
    buf = RNG.uniform(-1, 1, p)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % p]
        j = (i + 1) % p
        buf[i % p] = 0.996 * (bright * buf[i % p] + (1 - bright) * 0.5 * (buf[i % p] + buf[j]))
    env = np.minimum(1, np.arange(n) / 40)
    return out * env * amp


def marimba(freq, dur=0.9, amp=0.4):
    t = np.arange(int(dur * SR)) / SR
    s = np.sin(2 * np.pi * freq * t) * np.exp(-t * 6) + 0.35 * np.sin(2 * np.pi * freq * 4 * t) * np.exp(-t * 18)
    s *= np.minimum(1, t * 800)
    return s * amp


def add(buf, sig, t0):
    i = int(t0 * SR) % (2 * N)
    end = min(len(buf), i + len(sig))
    buf[i:end] += sig[:end - i]


def music():
    buf = np.zeros(2 * N)
    F, C, Dm, Bb, Gm = (53, [65, 69, 72]), (48, [64, 67, 72]), (50, [62, 65, 69]), (46, [62, 65, 70]), (43, [62, 67, 70])
    bars = [F, C, Dm, Bb, F, C, Gm, C, Dm, C]
    beat = 0.5
    for b, (bass, ch) in enumerate(bars):
        t = b * 1.5
        tense = b in (7, 8)
        add(buf, pluck(midi_hz(bass - 12 if tense else bass - 12), 1.4, 0.3, 0.55), t)
        if tense:
            for k in range(6):
                add(buf, pluck(midi_hz(bass - 12), 0.4, 0.2, 0.18), t + k * 0.25)
            continue
        for k in (1, 2):
            for m in ch:
                add(buf, pluck(midi_hz(m - 12), 0.6, 0.6, 0.12), t + k * beat)
    mel = {0: [72, 69, 72], 1: [74, 72, 67], 2: [69, 72, 77], 3: [77, 74, 70], 4: [72, 77, 81],
           5: [79, 76, 72], 6: [74, 70, 67], 9: [67, 69, 72]}
    for b, notes in mel.items():
        for k, m in enumerate(notes):
            add(buf, marimba(midi_hz(m), 0.8, 0.22), b * 1.5 + k * beat)
    return buf


# ---------------------------------------------------------------- SFX
def tvec(d):
    return np.arange(int(d * SR)) / SR


def env_ad(t, a, d):
    return np.minimum(1, t / a) * np.exp(-t / d)


def sweep(f0, f1, d, amp=0.3, shape="sin"):
    t = tvec(d)
    f = f0 * (f1 / f0) ** (t / d)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) if shape == "sin" else np.sign(np.sin(ph)) * 0.4
    return s * np.minimum(1, t / 0.01) * np.minimum(1, (d - t) / 0.03) * amp


def boop(f, d=0.12, amp=0.35):
    t = tvec(d)
    return np.sin(2 * np.pi * f * t * (1 + 0.6 * np.exp(-t * 40))) * env_ad(t, 0.003, d / 3) * amp


def thump(amp=0.6, f=90, d=0.25):
    t = tvec(d)
    return np.sin(2 * np.pi * f * t * np.exp(-t * 6)) * env_ad(t, 0.002, 0.06) * amp


def noise_burst(d, lo, hi, amp=0.2, dec=0.05):
    t = tvec(d)
    n = RNG.standard_normal(len(t))
    spec = np.fft.rfft(n)
    fr = np.fft.rfftfreq(len(n), 1 / SR)
    spec[(fr < lo) | (fr > hi)] = 0
    n = np.fft.irfft(spec, len(n))
    n /= np.abs(n).max() + 1e-9
    return n * env_ad(t, 0.002, dec) * amp


def boing(f=180, d=0.5, amp=0.35):
    t = tvec(d)
    f_t = f * (1 + 0.5 * np.sin(2 * np.pi * 14 * t) * np.exp(-t * 5))
    return np.sin(2 * np.pi * np.cumsum(f_t) / SR) * env_ad(t, 0.004, 0.18) * amp


def squish(d=0.18, amp=0.35):
    t = tvec(d)
    nb = noise_burst(d, 200, 2500, 0.5, 0.06)
    return (nb[:len(t)] + np.sin(2 * np.pi * 140 * t * (1 - 0.4 * t / d)) * 0.5) * env_ad(t, 0.004, 0.06) * amp


def bell(f=1568, d=1.2, amp=0.2):
    t = tvec(d)
    return (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 4)) * env_ad(t, 0.002, 0.35) * amp


def shimmer(d=0.55, amp=0.18):
    t = tvec(d)
    s = sum(np.sin(2 * np.pi * (600 + 300 * k) * (t + 0.6 * t * t / d)) for k in range(4)) / 4
    return s * np.minimum(1, t / d * 1.5) * np.minimum(1, (d - t) / 0.08) * amp


def sfx():
    buf = np.zeros(2 * N)
    ev = [(0.27, thump(0.45, 110)), (1.55, boop(1800, 0.05, 0.12)), (1.7, boop(1600, 0.05, 0.12)),
          (1.85, boop(1900, 0.05, 0.12)), (2.0, boop(1200, 0.1, 0.3)),
          (2.3, noise_burst(0.04, 2000, 8000, 0.25, 0.01)), (2.37, noise_burst(0.04, 2500, 9000, 0.25, 0.01)),
          (2.42, sweep(500, 900, 0.12, 0.08)), (2.6, boing(200, 0.6, 0.4)),
          (8.2, squish(0.2, 0.4)), (8.4, squish(0.16, 0.25)),
          (8.6, boop(520, 0.12, 0.35)), (8.85, boop(600, 0.12, 0.35)), (9.1, boop(690, 0.12, 0.35)),
          (9.2, boop(900, 0.07, 0.4)), (9.2, noise_burst(0.07, 800, 4000, 0.2, 0.02)),
          (9.45, shimmer(0.55, 0.2)), (10.0, bell(1568, 1.2, 0.2)),
          (10.02, sweep(700, 1100, 0.1, 0.07)), (10.12, sweep(1000, 600, 0.1, 0.07)),
          (10.8, sweep(80, 55, 0.9, 0.35)), (11.8, boop(2200, 0.08, 0.3)), (12.0, sweep(600, 1400, 0.5, 0.18)),
          (13.95, noise_burst(0.08, 3000, 7000, 0.18, 0.03)), (14.07, noise_burst(0.08, 3000, 7000, 0.18, 0.03)),
          (14.0, sweep(1400, 400, 0.4, 0.16)), (14.4, thump(0.6, 80, 0.35)), (14.4, squish(0.15, 0.2)),
          (14.87, boop(1500, 0.06, 0.2))]
    for t0, s in ev:
        add(buf, s, t0)
    return buf


def fold(buf):
    return buf[:N] + buf[N:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="WAV 48 кГц стерео")
    a = ap.parse_args()
    m = fold(music())
    s = fold(sfx())
    # простая «комната»: несколько задержек, тоже по кругу
    room = m * 0.0
    for d, g in ((0.031, 0.25), (0.047, 0.2), (0.071, 0.15), (0.11, 0.1)):
        room += np.roll(m + s, int(d * SR)) * g
    left = 0.8 * m + s + room * 0.6
    right = 0.8 * np.roll(m, 24) + s + np.roll(room, 37) * 0.6
    st = np.stack([left, right], 1)
    st /= np.abs(st).max() / 0.7
    with wave.open(a.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main()
