#!/usr/bin/env python3
"""«Хамелеон в пенале» — рисованная 2D-анимация (pycairo), 1080×1920, 30 fps, 450 кадров.

Сцена в профиль (Точка слева, Хамми справа), «играющая» камера — 2D-кадрирование.
Состояние кадра — чистая функция номера кадра; кадр 449 стыкуется с кадром 0 (петля).
Точки — комплексные числа x + 1j*z (метры сцены, масштаб ×10).

Запуск:  ~/bpyenv/bin/python draw2d.py --frames 0-449 --out <папка> [--scale 0.5]
"""
import argparse
import cmath
import math
import os
import time

import cairo

FPS, NF = 30, 450
TAU = 2 * math.pi
W_PX, H_PX = 1080, 1920

FLOOR = 0.02
R0 = 0.055
L_BODY = 1.35
S_A = 0.55
ANCH = complex(0.4425, FLOOR + R0)
DEPTH_Z, DEPTH_X = 0.42, 0.10      # псевдоперспектива: ряд глубже — выше и правее


# ---------------------------------------------------------------- утилиты
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def sm(e0, e1, x):
    if e0 == e1:
        return float(x >= e1)
    t = clamp((x - e0) / (e1 - e0))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def track(f, keys):
    if f <= keys[0][0]:
        return keys[0][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f <= f1:
            return lerp(v0, v1, sm(f0, f1, f))
    return keys[-1][1]


def spring(f, f0, freq=3.0, damp=6.0, amp=1.0):
    if f < f0:
        return 0.0
    t = (f - f0) / FPS
    return amp * math.exp(-damp * t) * math.sin(TAU * freq * t)


def fl(f, k, ph=0.0):
    return math.sin(TAU * k / 15 * f / FPS + ph)


def blink(f, period, offset, dur=3):
    return 1.0 if (f - offset) % period < dur else 0.0


def unit(c):
    a = abs(c)
    return c / a if a > 1e-12 else 1 + 0j


def rot(deg):
    return cmath.exp(1j * math.radians(deg))


def hx(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


def mixc(a, b, t):
    return tuple(lerp(x, y, t) for x, y in zip(a, b))


def shade(c, k):
    return (c[0] * k, c[1] * k, c[2] * k, c[3])


def bez(a, m, b, t):
    return a * (1 - t) ** 2 + m * (2 * (1 - t) * t) + b * t * t


def hash01(*k):
    h = 2166136261
    for v in k:
        h = ((h ^ (int(v) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return (h % 10007) / 10007


INK = hx("#3A2320")
GREEN = (hx("#55BE5C"), hx("#2F8C46"), hx("#A8E58A"))      # база, тень, блик
RED = (hx("#E8392F"), hx("#A3201F"), hx("#FF8A72"))
WOOD = (hx("#EECB97"), hx("#C99A62"), hx("#FFE6BF"))
LEAD = hx("#3A3A42")
BUG = (hx("#2A2A33"), hx("#17171D"), hx("#5A5A6E"))
SHELL = (hx("#E8392F"), hx("#A8221F"), hx("#FF9A86"))
PINK = hx("#FF8FA0", 0.55)
NAVY = (hx("#30478A"), hx("#22346A"), hx("#5571BE"))
SKIN = (hx("#F6CFAE"), hx("#D9A07E"), hx("#FFE8D6"))
SWEATER = (hx("#E0A93F"), hx("#B07D22"), hx("#F5CB6E"))
PENCILS = [("violet", 0.35, "#7B4CC2", -0.05), ("orange", 0.22, "#F07A2A", 0.02), ("blue", 0.09, "#2F6BD8", -0.03),
           ("yellow", -0.04, "#F2C230", 0.04), ("red", -0.17, "#E5322D", 0.0)]
Y_H = -0.30


# ---------------------------------------------------------------- камера и рисование
class Cam:
    def __init__(self, cx, cz, width, rot_deg=0.0):
        self.c = complex(cx, cz)
        self.s = W_PX / width
        self.r = rot(-rot_deg)

    def __call__(self, p):
        q = (p - self.c) * self.r * self.s
        return W_PX / 2 + q.real, H_PX / 2 - q.imag

    def lw(self, k=1.0):
        return clamp(0.0095 * self.s, 3.0, 9.0) * k


class Pen:
    """Обёртка над cairo: мировые координаты, «живая» линия (дрожит 15 раз/с)."""

    def __init__(self, ctx, cam, f):
        self.ctx, self.cam, self.f = ctx, cam, f
        self.boil = f // 2

    def jit(self, i):
        return (hash01(i, self.boil, 1) - 0.5) * 1.3, (hash01(i, self.boil, 2) - 0.5) * 1.3

    def poly(self, pts, close=True, jitter=True):
        c = self.ctx
        c.new_path()
        for i, p in enumerate(pts):
            x, y = self.cam(p)
            if jitter:
                dx, dy = self.jit(i)
                x, y = x + dx, y + dy
            c.line_to(x, y)
        if close:
            c.close_path()

    def circle(self, p, r):
        x, y = self.cam(p)
        self.ctx.new_path()
        self.ctx.arc(x, y, max(r * self.cam.s, 0.01), 0, TAU)

    def ellipse(self, p, rx, rz, ang=0.0):
        c = self.ctx
        x, y = self.cam(p)
        c.new_path()
        c.save()
        c.translate(x, y)
        c.rotate(-ang - cmath.phase(self.cam.r))
        c.scale(max(rx * self.cam.s, 0.01), max(rz * self.cam.s, 0.01))
        c.arc(0, 0, 1, 0, TAU)
        c.restore()

    def fill(self, col, keep=False):
        self.ctx.set_source_rgba(*col)
        (self.ctx.fill_preserve if keep else self.ctx.fill)()

    def stroke(self, col=INK, k=1.0, keep=False):
        self.ctx.set_source_rgba(*col)
        self.ctx.set_line_width(self.cam.lw(k) * (1 + 0.08 * (hash01(self.boil, 7) - 0.5)))
        self.ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        self.ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        (self.ctx.stroke_preserve if keep else self.ctx.stroke)()

    def blob(self, path_fn, base, light=-0.35 + 0.55j, k=0.22, outline=True, hl=True, size=0.1):
        """Мультяшная заливка: тень, база со сдвигом к свету, блик, контур."""
        c = self.ctx
        path_fn()
        c.save()
        c.clip_preserve()
        self.fill(base[1], keep=True)
        c.new_path()
        c.save()
        x0, y0 = self.cam(0j)
        x1, y1 = self.cam(light * size * k)
        c.translate(x1 - x0, y1 - y0)
        path_fn()
        self.fill(base[0])
        c.restore()
        if hl:
            c.save()
            x2, y2 = self.cam(light * size * k * 2.2)
            c.translate(x2 - x0, y2 - y0)
            c.scale(1.0, 1.0)
            path_fn()
            c.restore()
            g = list(base[2])
            g[3] = 0.0
            c.set_source_rgba(*g)
            c.new_path()
        c.restore()
        if outline:
            path_fn()
            self.stroke()

    def hose(self, a, m, b, width, col, n=14):
        pts = [bez(a, m, b, i / n) for i in range(n + 1)]
        for w, cc in ((width + 2 * self.cam.lw() / self.cam.s, INK), (width, col[0])):
            self.poly(pts, close=False, jitter=False)
            self.ctx.set_source_rgba(*cc)
            self.ctx.set_line_width(w * self.cam.s)
            self.ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            self.ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            self.ctx.stroke()
        # блик вдоль конечности
        self.poly([q + 1j * width * 0.22 for q in pts[2:-2]], close=False, jitter=False)
        self.ctx.set_source_rgba(*col[2][:3], 0.5)
        self.ctx.set_line_width(width * 0.22 * self.cam.s)
        self.ctx.stroke()

    def ball(self, p, r, col, light=True):
        def pth():
            self.circle(p, r)
        self.blob(pth, col, size=r * 2.2)
        if light:
            self.ellipse(p + (-0.35 + 0.42j) * r, r * 0.28, r * 0.18, 0.5)
            self.fill((1, 1, 1, 0.55))


# ---------------------------------------------------------------- Хамми: позвоночник
def body_spine(st):
    M = 64
    ds = L_BODY / (M - 1)
    R = st["R"]
    ia = round(S_A * (M - 1))
    phi = []
    for i in range(M):
        s = i / (M - 1)
        if i <= ia:
            a = st["lift"] * (math.radians(46) * sm(0.5, 0.22, s) - math.radians(40) * sm(0.17, 0.0, s))
            a -= st["hang"] * math.radians(70) * sm(0.55, 0.15, s)
        else:
            q = clamp((s - 0.74) / 0.26)
            a = st["curl"] * TAU * 1.9 * q * q
            a -= st["hang"] * math.radians(70) * sm(0.55, 0.9, s)
        phi.append(a + st["swing"])
    pts = [0j] * M
    pts[ia] = st["anchor"]
    for i in range(ia - 1, -1, -1):
        pts[i] = pts[i + 1] + ds * complex(-math.cos(phi[i]), math.sin(phi[i]))
    for i in range(ia + 1, M):
        pts[i] = pts[i - 1] + ds * complex(math.cos(phi[i]), math.sin(phi[i]))
    rad = []
    for i in range(M):
        s = i / (M - 1)
        r = R0 * (1 + 0.42 * R * math.exp(-((s - 0.55) / 0.2) ** 2) - 0.12 * R * math.exp(-((s - 0.12) / 0.08) ** 2))
        r *= lerp(1.0, 1 - 0.84 * clamp((s - 0.7) / 0.3) ** 0.8, R)
        r *= 1 - st["pinch"] * 0.22 * math.exp(-((s - 0.55) / 0.06) ** 2)
        r *= 1 + st["breath"]
        rad.append(r)
    amp, ph = st["ripple"]
    if amp:
        for i in range(M):
            s = i / (M - 1)
            pts[i] += 1j * amp * math.sin(TAU * (ph - s * 1.4)) * sm(0.0, 0.3, s)
    sx, sz = st["squash"]
    base = complex(st["anchor"].real, FLOOR)
    if sz != 1.0:
        pts = [base + (p - base).real * sx + 1j * (p - base).imag * sz for p in pts]
    return pts, rad


def head_points(pts, rad, R, pitch_deg=0.0):
    """Заточка / морда: последовательность от основания головы (seq[0]=pts[0]) к носу."""
    T0 = unit(pts[0] - pts[1])
    D = T0 * rot(pitch_deg if T0.real > 0 else -pitch_deg)
    Lh = lerp(0.25, 0.25, R)
    Mh = 18
    seq, rads, ts = [pts[0]], [rad[0]], [0.0]
    rb = rad[0]
    for k in range(1, Mh + 1):
        t = k / Mh
        d = unit(T0 + (D - T0) * sm(0.0, 0.5, t))
        seq.append(seq[-1] + d * (Lh / Mh))
        rc = rb * (1 - t)
        rr = rb * (1.25 + 0.12 * math.sin(math.pi * t)) * math.sqrt(clamp(1 - t ** 2.3))
        rads.append(lerp(rc, rr, R))
        ts.append(t)
    return seq, rads, ts, D, Lh


def tube_outline(pts, rad, a=-1.0, b=1.0):
    """Полигон полосы между долями ширины a..b (−1 — живот/низ, +1 — спина/верх)."""
    n = len(pts)
    L, Rr = [], []
    for i in range(n):
        t = unit(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)])
        nn = t * 1j
        L.append(pts[i] + nn * rad[i] * b)
        Rr.append(pts[i] + nn * rad[i] * a)
    return L + Rr[::-1]


def seg_quads(pts, rad, a, b, i0, i1):
    n = len(pts)
    out = []
    for i in range(i0, i1):
        j = min(i + 2, n - 1)
        sub_p, sub_r = pts[i:j + 1], rad[i:j + 1]
        if len(sub_p) >= 2:
            out.append((i, tube_outline(sub_p, sub_r, a, b)))
    return out


# ---------------------------------------------------------------- состояния
T_LINES = [(9, 24), (50, 60), (204, 223), (309, 316), (381, 403)]
H_LINES = [(78, 82), (99, 138), (150, 195)]


def talk(f, lines):
    for a, b in lines:
        if a <= f < b:
            t = (f - a) / FPS
            return 0.25 + 0.75 * abs(math.sin(TAU * 4.2 * t + 0.4)) * sm(a, a + 2, f) * sm(b, b - 2, f)
    return 0.0


def hand_pinch(f):
    """Точка щипка руки человека (в координатах ряда Хамми)."""
    if f < 420:
        keys = [(320, (0.75, 3.4)), (336, (0.36, 0.48)), (340, (0.38, 0.46)), (344, (0.47, 0.47)),
                (347, (0.40, 0.46)), (351, (0.44, 0.44)), (354, (ANCH.real, ANCH.imag)),
                (360, (ANCH.real, 0.5)), (376, (ANCH.real, 3.4))]
        # 336–347: колеблется — над красным карандашом (ряд глубже) и над Хамми
    else:
        keys = [(420, (ANCH.real, 1.30)), (425, (ANCH.real, 1.36)), (440, (ANCH.real - 0.1, 3.5))]
    x = track(f, [(k, v[0]) for k, v in keys])
    z = track(f, [(k, v[1]) for k, v in keys])
    return complex(x, z)


def hand_depth(f):
    """0 — над Хамми, 1 — над соседним красным карандашом."""
    return track(f, [(330, 1.0), (338, 1.0), (342, 0.0), (345, 0.0), (347, 1.0), (349, 1.0), (352, 0.0)])


def hammy_state(f):
    R = track(f, [(77, 0.0), (84, 1.0), (300, 1.0), (309, 0.25), (420, 0.25), (436, 0.0)])
    st = dict(R=R, lift=R * track(f, [(95, 1.0), (102, 0.8), (136, 0.8), (142, 1.0)]),
              hang=track(f, [(354, 0.0), (362, 1.0), (420, 1.0), (430, 0.0)]),
              pinch=track(f, [(351, 0.0), (354, 1.0), (420, 1.0), (424, 0.0)]),
              breath=0.012 * R * fl(f, 3), swing=0.0)
    st["curl"] = max(R, track(f, [(300, 0.0), (307, 1.0), (420, 1.0), (432, 0.0)]))
    a = ANCH
    if 78 <= f <= 87:
        a += 1j * 0.14 * math.sin(math.pi * (f - 78) / 9)
    if 354 <= f < 420:
        a = hand_pinch(f)
        st["swing"] = math.radians(10) * math.sin(TAU * 0.8 * (f - 354) / FPS) * math.exp(-(f - 354) / 40)
    elif 420 <= f < 432:
        t = (f - 420) / 12
        a = complex(ANCH.real, 1.30 - (1.30 - ANCH.imag) * t * t)
    st["anchor"] = a
    sz = track(f, [(75, 1.0), (78, 0.86), (80, 1.25), (84, 0.94), (88, 1.0)])
    if f >= 430:
        sz = track(f, [(431, 1.0), (432, 0.72), (435, 1.12), (438, 0.97), (441, 1.0)])
    st["squash"] = (1 / math.sqrt(sz), sz)
    st["ripple"] = (0.016 * sm(255, 262, f) * sm(292, 280, f), (f - 255) / FPS * 3.0)
    st["pitch"] = track(f, [(96, 0), (104, 16), (118, 6), (126, 18), (138, 16), (146, 0),
                            (160, 0), (170, 22), (183, 22), (188, 10), (195, 8), (200, 0)])
    st["hide"] = sm(162, 170, f) * sm(190, 182, f)
    st["eo"] = track(f, [(68, 0.0), (72, 1.15), (75, 1.0), (430, 1.0), (437, 0.0)])
    st["lid"] = [track(f, [(69, 1.0), (71, 0.0)]), track(f, [(71, 1.0), (73, 0.0)])]
    if 74 < f < 300:
        for i, off in enumerate((132, 134)):
            st["lid"][i] = max(st["lid"][i], blink(f, 90, off, 3))
    st["armw"] = track(f, [(229, 0.0), (244, 1.0), (276, 1.0), (283, 0.0)])
    st["press"] = track(f, [(245, 0.0), (249, 1.0), (274, 1.0), (277, 0.0)])
    st["skin"] = track(f, [(74, 0.0), (84, 1.0), (300, 1.0), (309, 0.0)])
    st["wA"] = track(f, [(285, -0.05), (300, 1.5)])
    st["wB"] = track(f, [(420, -0.25), (429, 1.3)])
    st["blush"] = max(sm(100, 108, f) * sm(140, 132, f), sm(150, 158, f) * sm(198, 190, f),
                      0.8 * sm(286, 296, f) * sm(312, 304, f))
    st["mouth"] = talk(f, H_LINES)
    return st


def tochka_state(f):
    if f < 9:
        t = f / 9
        loc = complex(lerp(-1.12, -0.90, sm(0, 1, t)), 0.16 * (1 - t) + FLOOR * t + 0.07 * math.sin(math.pi * t))
        ang = -38 * math.sin(math.pi * t)
    elif f >= 432:
        t = clamp((f - 432) / 14)
        loc = complex(lerp(-0.78, -1.12, sm(0, 1, t)), lerp(FLOOR, 0.16, t) + 0.32 * math.sin(math.pi * t))
        ang = 360 * sm(0.05, 0.95, t)
    else:
        x = track(f, [(9, -0.90), (45, -0.90), (58, -0.80), (66, -0.80), (78, -0.80), (84, -0.85),
                      (90, -0.85), (98, -0.82), (222, -0.82), (240, -0.77), (276, -0.77), (284, -0.79)])
        z = FLOOR
        if 45 <= f < 58:
            z += 0.012 * abs(math.sin(math.pi * (f - 45) / 4.33))
        if 233 <= f < 244:
            z += 0.035 * abs(math.sin(math.pi * (f - 233) / 5.5))
        loc = complex(x, z)
        ang = -track(f, [(52, 0), (58, 9), (64, 0), (77, 0), (81, -18), (90, -6), (98, 0),
                         (204, 0), (210, -10), (219, -10), (226, 6), (240, 0),
                         (328, 0), (345, -12), (375, -8), (390, 0)])
    if 309 <= f < 326:
        ang += 5 * math.sin(TAU * 7 * (f - 309) / FPS) * sm(309, 311, f) * sm(326, 320, f)
    sz = 1.0
    if f < 30:
        sz *= track(f, [(6, 1.0), (9, 0.8), (12, 1.08), (15, 1.0)])
    if 70 < f < 100:
        sz *= track(f, [(77, 1.0), (80, 0.86), (88, 0.88), (96, 1.0)])
    if 233 <= f < 246:
        sz *= 1.0 + 0.035 * math.cos(TAU * ((f - 233) / 5.5))
    if f >= 444:
        sz *= track(f, [(445, 1.0), (446, 0.82), (448, 1.05), (449, 1.0)])
    st = dict(loc=loc, ang=ang, sx=1 / math.sqrt(sz), sz=sz)
    hp = track(f, [(9, 0), (12, -8), (36, -6), (44, 0), (50, 0), (56, -12), (62, -6), (75, 0),
                   (136, 0), (141, 14), (148, 14), (152, 0),
                   (204, 0), (210, -15), (223, -12), (231, 0), (326, 0), (340, -38), (372, -38),
                   (380, -28), (398, -24), (404, -14), (417, -14), (428, 0)])
    hp += 6 * math.sin(TAU * 2.2 * f / FPS) * sm(10, 14, f) * sm(36, 30, f)
    st["head"] = -hp
    st["blink"] = blink(f, 90, 20, 3)
    st["happy"] = 1.0 if 310 <= f < 322 else 0.0
    st["mouth"] = talk(f, T_LINES)
    r = 0.12 + 0.035j
    w = math.sin(TAU * 3 * (f - 9) / FPS)
    r = lerp(r, 0.27 + 0.31j + 0.03 * w + 0.025j * w, sm(9, 13, f) * sm(36, 31, f))
    r = lerp(r, 0.03 + 0.30j, sm(77, 80, f) * sm(92, 86, f))
    r = lerp(r, 0.10 + 0.17j, sm(211, 216, f) * sm(222, 219, f))
    r = lerp(r, 0.30 + 0.17j, sm(219, 225, f))
    w2 = math.sin(TAU * 1.5 * (f - 381) / FPS)
    r = lerp(r, 0.12 + 0.30j + 0.03 * w2, sm(380, 386, f) * sm(419, 412, f))
    st["rhand"] = r
    st["lhand"] = lerp(0.10 + 0.04j, 0.05 + 0.30j, sm(77, 80, f) * sm(92, 86, f))
    st["rw"] = sm(229, 244, f) * sm(284, 277, f)
    st["mouthw"] = sm(308, 311, f) * sm(325, 320, f)
    st["ant"] = sum(spring(f, e, 3.5, 5.0, a) for e, a in ((9, 0.035), (80, 0.04), (246, 0.02), (446, 0.035), (0, 0.03)))
    st["ant"] += 0.008 * math.sin(TAU * 12 * f / FPS) * sm(10, 14, f) * sm(36, 30, f)
    st["touch"] = sm(55, 60, f) * sm(68, 63, f)
    st["blushT"] = sm(204, 210, f) * sm(232, 226, f) + sm(309, 312, f) * sm(326, 320, f)
    return st


class TochkaRig:
    def __init__(self, st):
        self.st = st
        self.r = rot(st["ang"])
        hc = self.L(0.16 + 0.185j)
        self.hc = hc
        self.hr = rot(st["ang"] + st["head"])

    def L(self, p):
        s = self.st
        return s["loc"] + self.r * complex(p.real * s["sx"], p.imag * s["sz"])

    def H(self, p):
        return self.hc + self.hr * p * math.sqrt(self.st["sx"] * self.st["sz"])


# ---------------------------------------------------------------- рисование сцены
def draw_background(pen, cam, f):
    c = pen.ctx
    # параллакс: дальний план сдвигается слабее
    bg = Cam(cam.c.real * 0.3 - 0.2, cam.c.imag * 0.3 + 0.55, W_PX / cam.s * 0.55 + 2.2)
    g = cairo.LinearGradient(0, 0, 0, H_PX)
    g.add_color_stop_rgba(0, *hx("#F3E2C4"))
    g.add_color_stop_rgba(1, *hx("#E6CDA6"))
    c.set_source(g)
    c.paint()
    # окно с мягким светом
    x, y = bg(-1.6 + 1.6j)
    s = bg.s
    rg = cairo.RadialGradient(x, y, 0, x, y, 1.6 * s)
    rg.add_color_stop_rgba(0, 1, 0.98, 0.9, 0.85)
    rg.add_color_stop_rgba(1, 1, 0.95, 0.85, 0.0)
    c.set_source(rg)
    c.paint()
    c.set_source_rgba(1, 0.99, 0.95, 0.55)
    c.rectangle(x - 0.55 * s, y - 0.75 * s, 1.1 * s, 1.5 * s)
    c.fill()
    c.set_source_rgba(*hx("#D9BF98", 0.9))
    c.set_line_width(max(2, 0.05 * s))
    c.move_to(x, y - 0.75 * s)
    c.line_to(x, y + 0.75 * s)
    c.move_to(x - 0.55 * s, y)
    c.line_to(x + 0.55 * s, y)
    c.stroke()
    # боке лампы и кружка (не в фокусе)
    for p, r, col in ((2.1 + 1.25j, 0.35, (1.0, 0.75, 0.45, 0.55)), (2.5 + 0.9j, 0.18, (1.0, 0.85, 0.6, 0.4)),
                      (-2.3 + 0.55j, 0.5, hx("#8CC2B3", 0.6))):
        x, y = bg(p)
        rg = cairo.RadialGradient(x, y, 0, x, y, r * bg.s)
        rg.add_color_stop_rgba(0, *col)
        rg.add_color_stop_rgba(0.75, *col[:3], col[3] * 0.8)
        rg.add_color_stop_rgba(1, *col[:3], 0)
        c.set_source(rg)
        c.arc(x, y, r * bg.s, 0, TAU)
        c.fill()
    # стол
    x0, ytab = cam(complex(0, -0.06))
    g = cairo.LinearGradient(0, ytab, 0, H_PX)
    g.add_color_stop_rgba(0, *hx("#CF915A"))
    g.add_color_stop_rgba(1, *hx("#A8683A"))
    c.set_source(g)
    c.rectangle(0, ytab, W_PX, H_PX - ytab)
    c.fill()
    _, yback = cam(complex(0, 0.55))
    g = cairo.LinearGradient(0, yback, 0, ytab)
    g.add_color_stop_rgba(0, *hx("#B97A45"))
    g.add_color_stop_rgba(1, *hx("#D49A62"))
    c.set_source(g)
    c.rectangle(0, yback, W_PX, ytab - yback)
    c.fill()
    c.set_source_rgba(*hx("#8E5530", 0.25))
    c.set_line_width(max(1.5, cam.lw(0.4)))
    for k in range(7):
        zz = -0.1 - k * 0.09
        pen.poly([complex(-3 + 0.25 * i, zz + 0.012 * math.sin(i * 1.3 + k)) for i in range(25)], close=False, jitter=False)
        c.stroke()


def case_pt(x, depth, z):
    """Точка пенала: x, глубина (−0.45 … 0.5 — от переднего края к задней стенке), высота."""
    d = depth - Y_H
    return complex(x + d * DEPTH_X, z + d * DEPTH_Z)


def draw_case_back(pen, cam):
    navy = NAVY
    lining = (hx("#A9CBEA"), hx("#86ABD3"), hx("#CFE3F5"))
    # крышка сзади
    lid = [case_pt(-1.18, 0.55, 0.16), case_pt(1.18, 0.55, 0.16), case_pt(1.22, 0.62, 1.1), case_pt(-1.14, 0.62, 1.1)]
    pen.blob(lambda: pen.poly(lid), navy, size=0.6)
    pen.poly([case_pt(-1.1, 0.56, 0.22), case_pt(1.1, 0.56, 0.22), case_pt(1.14, 0.61, 1.03), case_pt(-1.1, 0.61, 1.03)])
    pen.ctx.set_dash([cam.lw(1.6), cam.lw(1.6)])
    pen.stroke(hx("#8FA6E0", 0.8), 0.6)
    pen.ctx.set_dash([])
    # дно (подкладка) и задняя стенка
    floor = [case_pt(-1.12, -0.47, FLOOR), case_pt(1.12, -0.47, FLOOR), case_pt(1.12, 0.48, FLOOR), case_pt(-1.12, 0.48, FLOOR)]
    pen.blob(lambda: pen.poly(floor), lining, outline=False, hl=False, size=0.4)
    back = [case_pt(-1.15, 0.5, FLOOR), case_pt(1.15, 0.5, FLOOR), case_pt(1.15, 0.5, 0.17), case_pt(-1.15, 0.5, 0.17)]
    pen.blob(lambda: pen.poly(back), navy, size=0.2)
    pen.poly([case_pt(-1.12 + 0.022 * i, 0.5, 0.17) for i in range(103)], close=False, jitter=False)
    pen.ctx.set_dash([cam.lw(0.9), cam.lw(0.7)])
    pen.stroke(hx("#22222A"), 1.4)
    pen.ctx.set_dash([])
    # левая стенка (на ней сидит Точка в кадре 0)
    wall = [case_pt(-1.17, -0.47, FLOOR), case_pt(-1.12, -0.47, FLOOR), case_pt(-1.12, -0.47, 0.16),
            case_pt(-1.12, 0.5, 0.16), case_pt(-1.17, 0.5, 0.16), case_pt(-1.17, -0.47, 0.16)]
    pen.blob(lambda: pen.poly(wall), navy, size=0.2)
    wall_r = [case_pt(1.12, -0.47, FLOOR), case_pt(1.17, -0.47, FLOOR), case_pt(1.17, -0.47, 0.16),
              case_pt(1.17, 0.5, 0.16), case_pt(1.12, 0.5, 0.16), case_pt(1.12, -0.47, 0.16)]
    pen.blob(lambda: pen.poly(wall_r), navy, size=0.2)


def draw_case_front(pen, cam):
    navy = NAVY
    lip = [case_pt(-1.18, -0.47, -0.005), case_pt(1.18, -0.47, -0.005), case_pt(1.2, -0.52, 0.035), case_pt(-1.2, -0.52, 0.035)]
    flap = [case_pt(-1.2, -0.52, 0.0), case_pt(1.2, -0.52, 0.0), case_pt(1.2, -1.05, -0.06), case_pt(-1.2, -1.05, -0.06)]
    pen.blob(lambda: pen.poly(flap), navy, size=0.3)
    pen.poly([case_pt(-1.14, -0.58, 0.0), case_pt(1.14, -0.58, 0.0), case_pt(1.14, -0.99, -0.055), case_pt(-1.14, -0.99, -0.055)])
    pen.ctx.set_dash([cam.lw(1.6), cam.lw(1.6)])
    pen.stroke(hx("#9DB3EA", 0.8), 0.6)
    pen.ctx.set_dash([])
    pen.blob(lambda: pen.poly(lip), navy, size=0.1)
    pen.poly([case_pt(-1.1 + 0.022 * i, -0.53, 0.012) for i in range(101)], close=False, jitter=False)
    pen.ctx.set_dash([cam.lw(0.9), cam.lw(0.7)])
    pen.stroke(hx("#22222A"), 1.4)
    pen.ctx.set_dash([])


def body_colors(st, u, dA):
    red = clamp((st["wA"] - dA) / 0.07 + 0.5) * clamp((u - st["wB"]) / 0.07 + 0.5)
    return red


def draw_tube_body(pen, pts, rad, ts_head, colfn, R, skin, wood_alpha, lead_thr):
    """Тело-трубка: пояс тени, база, блик, древесина/грифель заточки, контур."""
    c = pen.ctx
    outline = tube_outline(pts, rad)
    pen.poly(outline)
    c.save()
    c.clip()
    n = len(pts)
    nh = len(ts_head)
    bands = [(-1.05, 1.05, 0), (-1.05, lerp(-0.33, -0.38, R), 1), (lerp(0.33, 0.42, R), lerp(1.05, 0.78, R), 2)]
    for a, b, k in bands:
        for i, quad in seg_quads(pts, rad, a, b, 0, n - 1):
            col = colfn(i)[k]
            if k == 2:
                col = (*col[:3], lerp(0.85, 0.55, R))
            pen.poly(quad, jitter=False)
            pen.fill(col)
    # заточка: древесина и грифель (у Хамми древесина бледнеет, когда он раскрыт)
    if wood_alpha > 0.01:
        for a, b, k in bands:
            for i, quad in seg_quads(pts, rad, a, b, 0, nh - 1):
                col = WOOD[k]
                pen.poly(quad, jitter=False)
                pen.fill((*col[:3], wood_alpha * (0.8 if k == 2 else 1.0)))
        # «гребешки» заточки на границе дерева и краски
        base_i = nh - 1
        p0, r0 = pts[base_i], rad[base_i]
        t = unit(pts[base_i - 1] - pts[base_i])
        sc = [p0 + t * 1j * r0 * (1 - 2 * k / 6) + t * (0.018 * (1 - abs(math.cos(math.pi * k / 6)))) for k in range(7)]
        pen.poly(sc, close=False)
        pen.stroke(shade(INK, 1.0), 0.6)
    for i, quad in seg_quads(pts, rad, -1.05, 1.05, 0, nh - 1):
        if ts_head[i] > lead_thr:
            pen.poly(quad, jitter=False)
            pen.fill(LEAD)
    if R < 0.6:
        for a in (-0.33, 0.33):
            pen.poly([pts[i] + unit(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]) * 1j * rad[i] * a
                      for i in range(nh, n)], close=False, jitter=False)
            pen.stroke((*INK[:3], 0.35 * (1 - R / 0.6)), 0.4)
    c.restore()
    pen.poly(outline)
    pen.stroke()


def draw_pencil(pen, name, depth, col, dx):
    st = dict(R=0.0, lift=0.0, curl=0.0, hang=0.0, swing=0.0, anchor=ANCH + dx, pinch=0.0,
              breath=0.0, ripple=(0.0, 0.0), squash=(1.0, 1.0))
    pts, rad = body_spine(st)
    seq, hr, ts, D, Lh = head_points(pts, rad, 0.0)
    head = seq[::-1]
    allp = [case_pt(p.real, depth, p.imag) for p in head + pts]
    allr = hr[::-1] + rad
    base = hx(col)
    cs = (base, shade(base, 0.7), mixc(base, (1, 1, 1, 1), 0.45))
    draw_tube_body(pen, allp, allr, ts[::-1], lambda i: cs, 0.0, 0.0, 1.0, 0.76)


def draw_hammy(pen, st, P, gaze_t, f, layer):
    """layer: 'back' — дальние лапы и дальний глаз; 'body'; 'front' — ближние лапы, глаз."""
    pts, rad = st["_pts"], st["_rad"]
    seq, hr, ts, D, Lh = st["_head"]
    R = st["R"]
    up = D * 1j
    if up.imag < 0:
        up = -up
    eo = st["eo"]
    re = 0.05 * clamp(eo, 0, 1.2)
    Pe = seq[int(len(seq) * 0.36)]
    rh = hr[int(len(seq) * 0.36)]
    turrets = [Pe + up * rh * 0.62 - D * 0.012, Pe + up * rh * 0.9 - D * 0.05]   # ближний, дальний
    legv = sm(0.15, 0.9, R)
    nb = len(pts)

    def dA_s(s):
        return 0.12 + abs(s - 0.27) * 1.15

    def legs(near):
        if legv < 0.02:
            return
        for ii, front in ((17, True), (46, False)):
            hip = pts[ii] - 1j * rad[ii] * 0.35
            sgx = -1 if front else 1
            foot = complex(hip.real + 0.03 * sgx, FLOOR + 0.022)
            dang = hip + complex(-0.04 if front else 0.03, -0.13)
            foot = lerp(foot, dang, max(sm(0.14, 0.26, hip.imag), st["hang"]))
            if not near:
                hip += 0.02
                foot += 0.035
            press = 0.0
            if near and front:
                foot = lerp(foot, P + 0.017, st["armw"])
                foot = lerp(foot, seq[-1] + up * 0.03 - D * 0.02, st["hide"])
                press = st["press"]
            u = ii / (nb - 1)
            red = body_colors(st, u, 0.02 if (near and front) else dA_s(u))
            col = tuple(mixc(g, r, red) for g, r in zip(GREEN, RED))
            if not near:
                col = tuple(shade(x, 0.78) for x in col)
            mid = (hip + foot) / 2 + (0.03 if front else -0.03) + 0.03j
            pen.hose(hip, mid, foot, 0.042 * legv, col)
            pr = 0.032 * legv * (1 + 0.15 * press)
            fc = foot + unit(foot - mid) * 0.006
            pen.ellipse(fc, pr * (1 - 0.3 * press), pr, cmath.phase(unit(foot - mid)))
            pen.blob(lambda: pen.ellipse(fc, pr * (1 - 0.3 * press), pr, cmath.phase(unit(foot - mid))), col, size=pr * 2)
            for k in (-1, 1):
                toe = fc + unit(foot - mid) * pr * 0.6 + unit(foot - mid) * 1j * pr * 0.55 * k
                pen.circle(toe, pr * 0.42)
                pen.fill(col[0], keep=True)
                pen.stroke(k=0.7)

    def turret(i, near):
        if re < 0.002:
            return
        C = turrets[0 if near else 1]
        g = gaze_t[i]
        red = body_colors(st, -0.05, dA_s(0) + 0.03)
        col = tuple(mixc(g_, r_, red) for g_, r_ in zip(GREEN, RED))
        if not near:
            col = tuple(shade(x, 0.85) for x in col)
        rr = re * (1.0 if near else 0.88)
        pen.blob(lambda: pen.circle(C, rr * 1.12), col, size=rr * 2)
        for k in (0.82, 0.62):
            pen.ctx.new_path()
            x, y = pen.cam(C)
            ang0 = -cmath.phase(g)
            pen.ctx.arc(x, y, rr * 1.12 * k * pen.cam.s, ang0 + 0.9, ang0 + 5.4)
            pen.stroke((*INK[:3], 0.35), 0.45)
        ap = C + g * rr * 0.52
        lid = st["lid"][i]
        pen.circle(ap, rr * 0.5)
        pen.fill(hx("#FBF7EE"), keep=True)
        pen.stroke(k=0.6)
        if lid < 0.5:
            pupil = ap + g * rr * 0.12
            pen.circle(pupil, rr * 0.3)
            pen.fill(hx("#121216"))
            pen.circle(pupil + (-0.4 + 0.45j) * rr * 0.2, rr * 0.1)
            pen.fill((1, 1, 1, 0.95))
        else:
            pen.circle(ap, rr * 0.5)
            pen.fill(col[0], keep=True)
            pen.stroke(k=0.6)

    if layer == "back":
        legs(False)
        turret(1, False)
        return
    if layer == "front":
        turret(0, True)
        legs(True)
        return
    # тело
    allp = seq[::-1] + pts
    allr = hr[::-1] + rad
    nh = len(seq)
    ts_rev = ts[::-1]

    def colfn(i):
        if i < nh:
            u, dA = -ts_rev[i] * 0.2, dA_s(0) + ts_rev[i] * 0.1
        else:
            u = (i - nh) / (nb - 1)
            dA = dA_s(u)
        red = body_colors(st, u, dA)
        return tuple(mixc(g, r, red) for g, r in zip(GREEN, RED))

    draw_tube_body(pen, allp, allr, ts_rev, colfn, R, st["skin"], 1 - st["skin"], lerp(0.76, 0.88, R))
    # пятна «как у Точки» прорастают за фронтом волны
    pen.poly(tube_outline(allp, allr))
    pen.ctx.save()
    pen.ctx.clip()
    for k, (s, ac, rs) in enumerate(SPOTS):
        i = int(s * (nb - 1))
        red = body_colors(st, s, dA_s(s))
        grow = clamp((st["wA"] - dA_s(s)) * 5) * clamp((s - st["wB"]) * 8)
        if red < 0.3 or grow < 0.02:
            continue
        t = unit(pts[min(i + 1, nb - 1)] - pts[max(i - 1, 0)])
        p = pts[i] + t * 1j * rad[i] * ac
        pen.circle(p, rs * rad[i] * min(1.1, grow * 1.1))
        pen.fill(hx("#1A1416"))
    pen.ctx.restore()
    # румянец, рот (на морде)
    k_m = int(len(seq) * 0.7)
    cheek = seq[k_m] - up * hr[k_m] * 0.25
    if st["blush"] > 0.01 and R > 0.3:
        pen.ellipse(cheek, 0.035, 0.018, cmath.phase(D))
        pen.fill((*PINK[:3], PINK[3] * st["blush"]))
    if R > 0.3:
        mp = seq[k_m] - up * hr[k_m] * 0.55 + D * 0.01
        mo = st["mouth"]
        if mo > 0.05:
            pen.ellipse(mp, 0.016 + 0.006 * mo, 0.006 + 0.016 * mo, cmath.phase(D))
            pen.fill(hx("#5B1A22"), keep=True)
            pen.stroke(k=0.6)
        else:
            a, b = mp - D * 0.022, mp + D * 0.012
            pen.poly([a, (a + b) / 2 - up * 0.006, b], close=False)
            pen.stroke(k=0.6)


SPOTS = [(0.07, 0.45, 0.42), (0.13, -0.35, 0.38), (0.20, 0.5, 0.4), (0.25, -0.1, 0.34), (0.30, 0.45, 0.45), (0.42, -0.2, 0.38), (0.52, 0.55, 0.5), (0.60, -0.35, 0.42), (0.68, 0.3, 0.36),
         (0.78, -0.1, 0.4), (0.36, -0.55, 0.3), (0.86, 0.3, 0.45)]


def draw_tochka(pen, ts, rig, gaze, Hnose, P, f, layer):
    L, H = rig.L, rig.H
    s = math.sqrt(ts["sx"] * ts["sz"])
    if layer == "back":
        # дальние лапки и дальняя рука
        for lx in (-0.06, 0.06):
            pen.hose(L(lx + 0.06j), L(lx - 0.01 + 0.03j), L(lx + 0.02 + 0.012j), 0.016, tuple(shade(c, 0.8) for c in BUG))
            pen.ball(L(lx + 0.03 + 0.016j), 0.02, tuple(shade(c, 0.8) for c in BUG), light=False)
        sh = L(0.07 + 0.11j)
        hw = L(ts["lhand"])
        pen.hose(sh, (sh + hw) / 2 - 0.02j, hw, 0.03 * s, tuple(shade(c, 0.8) for c in BUG))
        pen.ball(hw, 0.028 * s, tuple(shade(c, 0.8) for c in BUG), light=False)
        return
    if layer == "body":
        # брюшко, панцирь с пятнами, голова, глаза, рот, усики
        pen.blob(lambda: pen.ellipse(L(0.0 + 0.10j), 0.15 * ts["sx"], 0.075 * ts["sz"], math.radians(ts["ang"])), BUG, size=0.2)
        dome = [L(complex(0.165 * math.cos(a), 0.12 + 0.14 * math.sin(a))) for a in
                [math.radians(-12 + 204 * k / 40) for k in range(41)]]
        pen.poly(dome)
        pen.ctx.save()
        pen.ctx.clip()
        pen.blob(lambda: pen.poly(dome, jitter=False), SHELL, outline=False, size=0.3)
        for p, r in ((-0.08 + 0.21j, 0.032), (0.0 + 0.24j, 0.028), (0.085 + 0.15j, 0.04), (-0.125 + 0.14j, 0.026),
                     (-0.03 + 0.15j, 0.027), (0.06 + 0.225j, 0.022)):
            pen.circle(L(p), r * s)
            pen.fill(hx("#17141A"))
        pen.ctx.restore()
        pen.poly(dome)
        pen.stroke()
        pen.ellipse(L(-0.05 + 0.235j), 0.06, 0.018, math.radians(ts["ang"] + 15))
        pen.fill((1, 1, 1, 0.55))
        # голова
        hc = rig.hc
        hr = 0.088 * s
        pen.ball(hc, hr, BUG)
        if ts["blushT"] > 0.01:
            pen.ellipse(H(0.035 - 0.035j), 0.022, 0.012, math.radians(ts["ang"] + ts["head"]))
            pen.fill((*PINK[:3], 0.7 * ts["blushT"]))
        # глаза: дальний чуть выше и сзади, ближний крупнее
        g = unit(gaze - hc)
        for k, (pc, er) in enumerate(((0.068 + 0.05j, 0.034), (0.045 + 0.022j, 0.041))):
            C = H(pc)
            er *= s
            pen.circle(C, er)
            pen.fill(hx("#FBF7EE"), keep=True)
            pen.stroke(k=0.75)
            if ts["happy"] > 0.5:
                pen.circle(C, er)
                pen.fill(BUG[0])
                pen.ctx.new_path()
                x, y = pen.cam(C - 0.004j)
                pen.ctx.arc(x, y, er * 0.65 * pen.cam.s, math.pi * 1.15, math.pi * 1.85)
                pen.stroke(hx("#FBF7EE"), 0.9)
                continue
            if ts["blink"] > 0.5:
                pen.circle(C, er)
                pen.fill(BUG[0], keep=True)
                pen.stroke(k=0.75)
                continue
            ic = C + g * er * 0.38
            pen.circle(ic, er * 0.6)
            pen.fill(hx("#8A5A2B"))
            pen.circle(ic + g * er * 0.06, er * 0.36)
            pen.fill(hx("#0E0E12"))
            pen.circle(ic + (-0.35 + 0.45j) * er * 0.38, er * 0.17)
            pen.fill((1, 1, 1, 0.95))
            pen.circle(ic + (0.3 - 0.35j) * er * 0.3, er * 0.07)
            pen.fill((1, 1, 1, 0.8))
        # рот
        mp = H(0.072 - 0.038j)
        mo = ts["mouth"]
        hang = math.radians(ts["ang"] + ts["head"])
        if mo > 0.05:
            pen.ellipse(mp, 0.016 + 0.004 * mo, 0.005 + 0.016 * mo, hang)
            pen.fill(hx("#7A1C2B"), keep=True)
            pen.stroke(hx("#F4E9E0"), 0.5)
            pen.ellipse(mp - 0.006j * mo, 0.009, 0.004 * mo, hang)
            pen.fill(hx("#FF8597"))
        else:
            a, b = H(0.052 - 0.034j), H(0.088 - 0.03j)
            pen.poly([a, (a + b) / 2 - 0.012j, b], close=False)
            pen.stroke(hx("#F4E9E0"), 0.55)
        # усики
        for k, (b0, tip0) in enumerate(((-0.012 + 0.082j, 0.055 + 0.20j), (0.018 + 0.086j, 0.09 + 0.21j))):
            b = H(b0)
            tip = H(tip0 + ts["ant"] + 0.5j * ts["ant"])
            if k == 1:
                tip = lerp(tip, Hnose - 0.012 + 0.004j, ts["touch"])
            m = H(b0 + 0.02 + 0.08j)
            pen.hose(b, m, tip, 0.009, BUG)
            pen.ball(tip, 0.017 * (1 - 0.25 * ts["touch"] * k), BUG)
        return
    # front: ближние лапки и ближняя рука
    for lx in (-0.07, 0.05):
        pen.hose(L(lx + 0.05j), L(lx - 0.012 + 0.02j), L(lx + 0.02 + 0.012j), 0.018, BUG)
        pen.ball(L(lx + 0.03 + 0.016j), 0.022, BUG)
    sh = L(0.07 + 0.115j)
    hw = L(ts["rhand"])
    hw = lerp(hw, P - 0.017, ts["rw"])
    hw = lerp(hw, H(0.075 - 0.04j), ts["mouthw"])
    pen.hose(sh, (sh + hw) / 2 - 0.025j, hw, 0.032 * s, BUG)
    pr = 0.032 * s * (1 + 0.15 * ts.get("press", 0.0))
    pen.ball(hw, pr, BUG)


def draw_hand(pen, Hp, op, part):
    """Рука человека: 'back' — указательный палец (за Хамми), 'front' — ладонь, большой палец, рукав."""
    gap = 0.07 + op * 0.12
    if part == "back":
        pen.hose(Hp + 0.10 + 0.40j, Hp + 0.17 + 0.18j, Hp + gap * 0.6 + 0.03j, 0.12, SKIN)
        pen.ball(Hp + gap * 0.6 + 0.03j, 0.068, SKIN)
        return
    sleeve = [Hp + complex(-0.40, 0.95), Hp + complex(0.36, 0.95), Hp + complex(0.42, 4.0), Hp + complex(-0.46, 4.0)]
    palm = lambda: pen.ellipse(Hp + 0.02 + 0.60j, 0.34, 0.36, 0.1)
    pen.blob(palm, SKIN, size=0.6)
    for k, x in enumerate((0.20, 0.30)):
        pen.ball(Hp + complex(x - 0.02 * k, 0.36 - 0.05 * k), 0.075, SKIN)
    pen.blob(lambda: pen.poly(sleeve), SWEATER, size=0.8)
    pen.poly([Hp + complex(-0.43, 1.02), Hp + complex(0.39, 1.02)], close=False)
    pen.stroke(k=0.8)
    pen.hose(Hp - 0.22 + 0.55j, Hp - 0.25 + 0.25j, Hp - gap + 0.0j, 0.13, SKIN)
    pen.ball(Hp - gap, 0.072, SKIN)
    pen.ellipse(Hp - gap - 0.01 + 0.035j, 0.03, 0.02, 0.4)
    pen.fill(hx("#FFF4EA", 0.9))


# ---------------------------------------------------------------- камера по блокам
def camera(f, TH, HH, P, Hp, Hanch):
    def shot(c, w, r=0.0):
        return (c, w, r)

    def B(w=0.62):
        return shot(TH + 0.08 - 0.06j, w)

    def C(w=0.72):
        return shot(HH - 0.06 - 0.08j, w)

    def D(w=1.2):
        m = (TH + HH) / 2
        return shot(m - 0.12j, w)

    A = shot(complex(-0.82, 0.25), 1.15)

    def blend(a, b, t):
        return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))

    if f < 9:
        s = blend(A, shot(A[0] + 0.02, A[1] * 0.97), f / 9)
    elif f < 36:
        s = B(lerp(0.62, 0.58, (f - 9) / 27))
    elif f < 45:
        s = shot(complex(-0.45, 0.12), 0.75, 4 * sm(36, 44, f))
    elif f < 66:
        s = B(0.66)
    elif f < 78:
        s = blend(B(0.66), C(0.5), sm(66, 70, f))
    elif f < 87:
        s = blend(C(0.5), D(1.5), sm(78, 82, f))
    elif f < 99:
        s = blend(D(1.5), D(1.4), (f - 87) / 12)
    elif f < 138:
        s = C(0.68)
    elif f < 150:
        s = B(0.6)
    elif f < 195:
        s = C(lerp(0.74, 0.68, (f - 150) / 45))
    elif f < 231:
        b = B(lerp(0.62, 0.59, (f - 195) / 36) * (0.96 if f >= 219 else 1.0))
        s = blend(C(0.7), b, sm(195, 199, f))
    elif f < 241:
        s = D(1.15)
    elif f < 268:
        s = shot(P + 0.02j, 0.42, 2.0 * math.sin(TAU * (f - 241) / 40))
    elif f < 285:
        s = D(1.2)
    elif f < 309:
        s = C(lerp(1.0, 0.8, sm(292, 308, f)))
    elif f < 324:
        s = B(0.62)
    elif f < 375:
        c0 = lerp(complex(-0.15, 0.55), complex(0.2, 1.0), sm(354, 374, f))
        s = shot(c0, lerp(2.6, 2.9, sm(354, 374, f)))
    elif f < 420:
        s = shot(TH + 0.06 + 0.12j, 0.62, -6)
    else:
        z = lerp(0.25, 1.05, sm(420, 423, f)) if f < 423 else max(Hanch.imag, 0.28)
        s1 = shot(complex(ANCH.real - 0.1, z), 1.6)
        s = blend(s1, A, sm(426, 449, f))
    c, w, r = s
    c += complex(fl(f, 4), fl(f, 3, 1.0)) * 0.006 * w
    r += 0.6 * fl(f, 2, 0.5)
    if 78 <= f < 90:
        a = 0.03 * w * math.exp(-(f - 78) / 4)
        c += complex(math.sin(f * 2.3), math.cos(f * 3.1)) * a
    return Cam(c.real, c.imag, w, r)


# ---------------------------------------------------------------- кадр
def scene_state(f):
    hs = hammy_state(f)
    ts = tochka_state(f)
    pts, rad = body_spine(hs)
    hs["_pts"], hs["_rad"] = pts, rad
    seq, hr, tsh, D, Lh = head_points(pts, rad, hs["R"], hs["pitch"])
    hs["_head"] = (seq, hr, tsh, D, Lh)
    up = D * 1j
    if up.imag < 0:
        up = -up
    k = int(len(seq) * 0.36)
    HH = seq[k] + up * hr[k] * 0.8
    Hnose = seq[-1]
    ts["press"] = hs["press"]
    rig = TochkaRig(ts)
    TH = rig.hc + rig.hr * 0.04
    Ts = rig.L(0.07 + 0.115j)
    Hs = pts[17] - 1j * rad[17] * 0.35
    shake = sum(0.045 * math.exp(-((f - c) / 2.6) ** 2) for c in (258, 266, 273))
    P = (Ts + Hs) / 2 + 0.06j - 1j * shake
    Hp = hand_pinch(f)
    return hs, ts, rig, HH, Hnose, TH, P, Hp


def gazes(f, hs, HH, TH, P, Hp, Hnose):
    if f < 12 or f >= 436:
        tg = Hnose
    elif 240 <= f < 278:
        tg = P
    elif 324 <= f < 354:
        tg = Hp
    elif 354 <= f < 376 or 420 <= f < 436:
        tg = hs["anchor"]
    elif 376 <= f < 420:
        tg = complex(ANCH.real, 2.2)
    else:
        tg = HH
    eye = []
    for i in range(2):
        t = TH
        if f < 75:
            t = TH if (i == 0 and f >= 71) else HH + complex(-0.3, 0.2 + 0.25 * math.sin(f * 0.9 + i * 2))
        if 99 <= f < 138:
            if (i == 1 and not (118 <= f < 126)) or (i == 0 and f >= 126):
                t = complex(HH.real - 0.3, -0.2)
        if 165 <= f < 195 and i == 1:
            t = HH + complex(1.5, 0.3)
        if 241 <= f < 278:
            t = P
        if f >= 302:
            t = HH + (complex(-1.0, 1.0) if i == 0 else complex(0.9, -0.6))
        eye.append(unit(t - HH))
    return tg, eye


def render(f, ctx):
    hs, ts, rig, HH, Hnose, TH, P, Hp = scene_state(f)
    tg, eye = gazes(f, hs, HH, TH, P, Hp, Hnose)
    cam = camera(f, TH, HH, P, Hp, hs["anchor"])
    draw_frame(ctx, f, cam, hs, ts, rig, Hnose, P, Hp, tg, eye)


def draw_frame(ctx, f, cam, hs, ts, rig, Hnose, P, Hp, tg, eye):
    pen = Pen(ctx, cam, f)
    draw_background(pen, cam, f)
    draw_case_back(pen, cam)
    hvis = 320 <= f <= 377 or 418 <= f <= 441
    op = track(f, [(320, 0.8), (350, 0.8), (354, 0.0), (420, 0.0), (425, 1.0)])
    hd = hand_depth(f) if f < 354 else 0.0
    Hp_draw = case_pt(Hp.real, Y_H + hd * 0.13, Hp.imag)
    # тень руки на пенале
    if 322 <= f < 356:
        a = 0.28 * sm(322, 336, f)
        sh = case_pt(Hp.real + 0.15, Y_H + hd * 0.13, FLOOR + 0.06)
        w = 0.25 + 0.5 * clamp((Hp.imag - 0.4) / 2.5)
        pen.ellipse(sh, w, w * 0.22)
        pen.fill((0.1, 0.06, 0.15, a))
    for name, depth, col, dx in PENCILS:
        draw_pencil(pen, name, depth, col, dx)
    if hvis and hd > 0.5:
        draw_hand(pen, Hp_draw, op, "back")
    draw_tochka(pen, ts, rig, tg, Hnose, P, f, "back")
    draw_hammy(pen, hs, P, eye, f, "back")
    if hvis and hd <= 0.5:
        draw_hand(pen, Hp_draw, op, "back")
    draw_hammy(pen, hs, P, eye, f, "body")
    draw_tochka(pen, ts, rig, tg, Hnose, P, f, "body")
    draw_hammy(pen, hs, P, eye, f, "front")
    draw_tochka(pen, ts, rig, tg, Hnose, P, f, "front")
    if hvis:
        draw_hand(pen, Hp_draw, op, "front")
    draw_case_front(pen, cam)
    # затемнение на тени руки и виньетка
    dark = 0.18 * sm(322, 332, f) * sm(342, 334, f)
    if dark > 0:
        ctx.set_source_rgba(0.12, 0.1, 0.25, dark)
        ctx.paint()
    rg = cairo.RadialGradient(W_PX / 2, H_PX * 0.45, H_PX * 0.35, W_PX / 2, H_PX * 0.45, H_PX * 0.75)
    rg.add_color_stop_rgba(0, 0, 0, 0, 0)
    rg.add_color_stop_rgba(1, 0.1, 0.05, 0.02, 0.28)
    ctx.set_source(rg)
    ctx.paint()


WHIPS = [(66, 71), (78, 83), (195, 200)]


def render_frame(f, path, scale=1.0):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(W_PX * scale), int(H_PX * scale))
    ctx = cairo.Context(surf)
    ctx.scale(scale, scale)
    if any(a <= f < b for a, b in WHIPS):
        # «смаз» камеры: 10 подкадров с разной камерой, персонажи — из этого кадра
        hs, ts, rig, HH, Hnose, TH, P, Hp = scene_state(f)
        tg, eye = gazes(f, hs, HH, TH, P, Hp, Hnose)
        for k, df in enumerate([(j + 0.5) / 10 - 0.5 for j in range(10)]):
            sub = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(W_PX * scale), int(H_PX * scale))
            sc = cairo.Context(sub)
            sc.scale(scale, scale)
            cam = camera(f + df, TH, HH, P, Hp, hs["anchor"])
            draw_frame(sc, f, cam, hs, ts, rig, Hnose, P, Hp, tg, eye)
            ctx.save()
            ctx.identity_matrix()
            ctx.set_source_surface(sub, 0, 0)
            ctx.paint_with_alpha(1.0 / (k + 1))
            ctx.restore()
    else:
        render(f, ctx)
    surf.write_to_png(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True, help="0-449, 9,60,246 или 0-449:3")
    ap.add_argument("--out", required=True, help="папка для PNG")
    ap.add_argument("--scale", type=float, default=1.0, help="масштаб кадра (0.5 — превью)")
    a = ap.parse_args()
    frames = []
    for part in a.frames.split(","):
        step = 1
        if ":" in part:
            part, st = part.split(":")
            step = int(st)
        if "-" in part:
            x, y = map(int, part.split("-"))
            frames += list(range(x, y + 1, step))
        else:
            frames.append(int(part))
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    for f in frames:
        render_frame(f, os.path.join(a.out, "f%04d.png" % f), a.scale)
    print("%d кадров, %.1f с" % (len(frames), time.time() - t0))


if __name__ == "__main__":
    main()
