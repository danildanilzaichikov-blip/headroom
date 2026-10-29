"""Общие DSP-утилиты для gen_music.py / gen_sfx.py / mix.py («Кубик и сортер»).

Только numpy + scipy. Частота 48 кГц, дорожка ровно 720 000 сэмплов (direction §5.1).
"""
import wave

import numpy as np
from scipy import signal

FS = 48000
N = 720000          # 15.000 с
SEED = 2610


def db(x):
    return 10.0 ** (x / 20.0)


def to_db(x):
    return 20.0 * np.log10(max(float(x), 1e-12))


def t_axis(n):
    return np.arange(n) / FS


def exp_sweep(f0, f1, n, t_sweep=None):
    """Экспоненциальная кривая частоты f0→f1 за t_sweep (дальше держится f1)."""
    t = t_axis(n)
    ts = t_sweep if t_sweep else n / FS
    k = np.clip(t / ts, 0.0, 1.0)
    return f0 * (f1 / f0) ** k


def osc(freq, phase0=0.0):
    """Синус по массиву мгновенной частоты (фаза интегрируется — без разрывов)."""
    ph = phase0 + 2 * np.pi * np.cumsum(freq) / FS
    return np.sin(ph)


def exp_env(n, tau, attack=0.001):
    t = t_axis(n)
    e = np.exp(-t / tau)
    na = max(1, int(attack * FS))
    e[:na] *= np.linspace(0.0, 1.0, na, endpoint=False) if na > 1 else 1.0
    return e


def fade(x, fin=0.0, fout=0.0):
    x = x.copy()
    ni, no = int(fin * FS), int(fout * FS)
    if ni > 1:
        x[:ni] *= np.sin(0.5 * np.pi * np.linspace(0, 1, ni))
    if no > 1:
        x[-no:] *= np.cos(0.5 * np.pi * np.linspace(0, 1, no))
    return x


def _sos(kind, f, order=2):
    nyq = FS / 2
    if kind == "bp":
        lo, hi = f
        return signal.butter(order, [lo / nyq, min(hi / nyq, 0.99)], btype="band", output="sos")
    return signal.butter(order, min(f / nyq, 0.99), btype=kind, output="sos")


def lpf(x, f, order=2):
    return signal.sosfilt(_sos("low", f, order), x)


def hpf(x, f, order=2):
    return signal.sosfilt(_sos("high", f, order), x)


def bpf(x, lo, hi, order=2):
    return signal.sosfilt(_sos("bp", (lo, hi), order), x)


def bpf_q(x, fc, q):
    """Резонансный полосовой (RBJ biquad, пик 0 дБ на fc) с заданной добротностью."""
    w0 = 2 * np.pi * fc / FS
    alpha = np.sin(w0) / (2 * q)
    b = np.array([alpha, 0.0, -alpha])
    a = np.array([1 + alpha, -2 * np.cos(w0), 1 - alpha])
    return signal.lfilter(b / a[0], a / a[0], x)


def svf(x, fc, q=0.707, mode="lp"):
    """TPT state-variable filter с посэмпловой частотой среза (для свипов)."""
    n = len(x)
    fc = np.clip(np.broadcast_to(np.asarray(fc, dtype=np.float64), (n,)), 20.0, FS * 0.45)
    g = np.tan(np.pi * fc / FS)
    k = 1.0 / q
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    lp = np.empty(n)
    bp = np.empty(n)
    ic1 = ic2 = 0.0
    xs, a1l, a2l, a3l = x.tolist(), a1.tolist(), a2.tolist(), a3.tolist()
    for i in range(n):
        v3 = xs[i] - ic2
        v1 = a1l[i] * ic1 + a2l[i] * v3
        v2 = ic2 + a2l[i] * ic1 + a3l[i] * v3
        ic1 = 2 * v1 - ic1
        ic2 = 2 * v2 - ic2
        lp[i] = v2
        bp[i] = v1
    if mode == "lp":
        return lp
    if mode == "bp":
        return bp * k          # нормированный: 0 дБ на fc
    return x - k * bp - lp     # hp


def pink(rng, n):
    """Розовый шум (1/f) через FFT-формирование спектра, нормирован на пик 1."""
    w = rng.standard_normal(n)
    sp = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / FS)
    f[0] = f[1]
    sp /= np.sqrt(f)
    p = np.fft.irfft(sp, n)
    return p / np.max(np.abs(p))


def norm_peak(x, peak_dbfs):
    m = np.max(np.abs(x))
    return x * (db(peak_dbfs) / m) if m > 0 else x


def pan_gains(p):
    """Equal-power: p ∈ [−1; 1] → (gL, gR)."""
    a = (np.asarray(p) + 1) * np.pi / 4
    return np.cos(a), np.sin(a)


def place(dst, src, t0, pan=0.0, gain=1.0, wrap=False):
    """Положить моно-сэмпл src в стерео-буфер dst (2, N) с момента t0 (с).
    wrap=True — по кругу (для звуков на шве петли)."""
    i0 = int(round(t0 * FS))
    gl, gr = pan_gains(pan)
    s = src * gain
    if wrap:
        idx = (i0 + np.arange(len(s))) % dst.shape[1]
        np.add.at(dst[0], idx, s * gl)
        np.add.at(dst[1], idx, s * gr)
        return
    if i0 < 0:
        s = s[-i0:]
        i0 = 0
    s = s[: max(0, dst.shape[1] - i0)]
    dst[0, i0:i0 + len(s)] += s * gl
    dst[1, i0:i0 + len(s)] += s * gr


def write_wav24(path, x):
    """x: (2, n) или (n,) float в [−1; 1] → PCM 24 бит."""
    x = np.atleast_2d(np.asarray(x, dtype=np.float64))
    ch, n = x.shape
    q = np.clip(np.round(x.T * 8388607.0), -8388608, 8388607).astype("<i4")
    b = q.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(3)
        w.setframerate(FS)
        w.writeframes(b)


def read_wav(path):
    """WAV (16/24/32 бит PCM) → float (ch, n)."""
    with wave.open(path, "rb") as w:
        ch, sw, fs, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    assert fs == FS, fs
    if sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        i = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        i = np.where(i >= 1 << 23, i - (1 << 24), i)
        x = i / 8388608.0
    elif sw == 2:
        x = np.frombuffer(raw, "<i2") / 32768.0
    else:
        x = np.frombuffer(raw, "<i4") / 2147483648.0
    return x.reshape(-1, ch).T.astype(np.float64)


# ------------------------------------------------------------ громкость BS.1770-4
def _kweight(x):
    # коэффициенты BS.1770 для 48 кГц
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return signal.lfilter(b2, a2, signal.lfilter(b1, a1, x, axis=-1), axis=-1)


def lufs_integrated(x):
    x = np.atleast_2d(x)
    y = _kweight(x)
    blk, hop = int(0.4 * FS), int(0.1 * FS)
    ms = []
    for s in range(0, y.shape[1] - blk + 1, hop):
        ms.append(np.sum(np.mean(y[:, s:s + blk] ** 2, axis=1)))
    ms = np.array(ms)
    l = -0.691 + 10 * np.log10(ms + 1e-20)
    g = ms[l > -70]
    if len(g) == 0:
        return -np.inf
    rel = -0.691 + 10 * np.log10(np.mean(g)) - 10
    g2 = ms[(l > -70) & (l > rel)]
    return -0.691 + 10 * np.log10(np.mean(g2))


def lufs_short_term(x, hop_s=0.1):
    """Короткая громкость (окно 3 с), массив (время центра, LUFS)."""
    x = np.atleast_2d(x)
    y = _kweight(x)
    blk, hop = int(3.0 * FS), int(hop_s * FS)
    out = []
    for s in range(0, y.shape[1] - blk + 1, hop):
        ms = np.sum(np.mean(y[:, s:s + blk] ** 2, axis=1))
        out.append(((s + blk / 2) / FS, -0.691 + 10 * np.log10(ms + 1e-20)))
    return np.array(out)


def true_peak(x, os_=4):
    x = np.atleast_2d(x)
    return max(np.max(np.abs(signal.resample_poly(c, os_, 1))) for c in x)
