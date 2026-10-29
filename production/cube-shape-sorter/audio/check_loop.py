#!/usr/bin/env python3
"""Проверка шва петли: mix.wav склеивается сам с собой, стык 15.0 → 0.0 сравнивается с
окрестностью. Щелчок = скачок соседних сэмплов и всплеск энергии > 8 кГц на стыке.
Запуск: python3 check_loop.py [файл.wav]  (по умолчанию mix.wav рядом со скриптом)
"""
import os
import sys

import numpy as np

from dsp import FS, hpf, read_wav, to_db

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "mix.wav")
x = read_wav(path)
n = x.shape[1]
y = np.concatenate([x, x], axis=1)
s = n                                            # индекс первого сэмпла второй копии

d = np.abs(np.diff(y, axis=1)).max(axis=0)       # макс. по каналам |x[i+1] − x[i]|
w = int(0.066 * FS)                              # ±2 кадра
jump = d[s - 1]
neigh = np.concatenate([d[s - w:s - 1], d[s:s + w]])
print(f"стык: |x[0] − x[N−1]| = {jump:.2e}; окрестность ±2 кадра: медиана {np.median(neigh):.2e}, "
      f"99-й перцентиль {np.percentile(neigh, 99):.2e}, макс {neigh.max():.2e}")

r = int(0.010 * FS)
def rms(a):
    return to_db(np.sqrt(np.mean(a ** 2)))
print(f"RMS 10 мс до стыка {rms(y[:, s - r:s]):.1f} dBFS, после {rms(y[:, s:s + r]):.1f} dBFS")

hf = np.stack([hpf(c, 8000, 4) for c in y])
e = np.sqrt(np.mean(hf[:, s - 240:s + 240] ** 2))
e_ref = np.sqrt(np.mean(np.concatenate([hf[:, s - 4800:s - 960], hf[:, s + 960:s + 4800]], axis=1) ** 2))
print(f"энергия > 8 кГц на стыке (±5 мс) {to_db(e):.1f} dBFS против окрестности {to_db(e_ref):.1f} dBFS")

ok = jump <= max(2 * np.percentile(neigh, 99), 1e-4) and to_db(e) <= to_db(e_ref) + 3
print("ШОВ:", "OK — щелчка нет" if ok else "ПРОБЛЕМА — возможен щелчок")
sys.exit(0 if ok else 1)
