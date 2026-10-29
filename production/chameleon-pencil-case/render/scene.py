#!/usr/bin/env python3
"""«Хамелеон в пенале» — процедурная сцена и анимация в Blender (bpy 5.2, Cycles + OIDN).

Состояние каждого кадра — чистая функция номера кадра (update(f)); ключей нет, рендер
детерминирован, кадр 449 стыкуется с кадром 0 (петля).

Запуск:  ~/bpyenv/bin/python scene.py --frames 0-449 --res 960 --spp 32 --out <папка>
         --frames 9,60,246   отдельные кадры;   --frames 0-449:3   каждый третий
"""
import argparse
import math
import os
import sys
import time

FPS, NF = 30, 450
TAU = 2 * math.pi


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True, help="0-449, 9,60,246 или 0-449:3")
    ap.add_argument("--res", type=int, default=960, help="высота кадра, px (ширина = 9/16)")
    ap.add_argument("--spp", type=int, default=32, help="сэмплов на пиксель")
    ap.add_argument("--out", required=True, help="папка для PNG")
    ap.add_argument("--skip-existing", action="store_true", help="не перерендеривать готовые кадры")
    return ap.parse_args()


def frame_list(spec):
    out = []
    for part in spec.split(","):
        step = 1
        if ":" in part:
            part, st = part.split(":")
            step = int(st)
        if "-" in part:
            a, b = map(int, part.split("-"))
            out += list(range(a, b + 1, step))
        else:
            out.append(int(part))
    return out


ARGS = parse_args()  # до импорта bpy: --help ничего не рендерит

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402

# ---------------------------------------------------------------- константы сцены (×10)
FLOOR = 0.02            # дно пенала
R0 = 0.055              # радиус карандаша
Y_H = -0.30             # ряд Хамми (ближний к камере)
L_BODY = 1.35           # длина корпуса карандаша без заточки
ANCH = Vector((0.4425, Y_H, FLOOR + R0))   # середина тела Хамми, s = 0.55 (точка щипка)
S_A = 0.55
KEYDIR = Vector((-0.55, -0.45, 0.7)).normalized()


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


def V(*a):
    return Vector(a)


def _cv(v):
    return Vector(v) if isinstance(v, (tuple, list, Vector)) else v


def track(f, keys):
    """Плавная интерполяция (smoothstep) между ключами [(кадр, значение), ...]."""
    if f <= keys[0][0]:
        return _cv(keys[0][1])
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f <= f1:
            t = sm(f0, f1, f)
            a, b = _cv(v0), _cv(v1)
            return a.lerp(b, t) if isinstance(a, Vector) else lerp(a, b, t)
    return _cv(keys[-1][1])


def spring(f, f0, freq=3.0, damp=6.0, amp=1.0):
    if f < f0:
        return 0.0
    t = (f - f0) / FPS
    return amp * math.exp(-damp * t) * math.sin(TAU * freq * t)


def fl(f, k, ph=0.0):
    """Петлевой шум: частота k/15 Гц, период кратен 15 с."""
    return math.sin(TAU * k / 15 * f / FPS + ph)


def hx(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def blink(f, period, offset, dur=3):
    return 1.0 if (f - offset) % period < dur else 0.0


# ---------------------------------------------------------------- материалы
def setin(sock, v):
    dv = sock.default_value
    if isinstance(v, tuple) and hasattr(dv, "__len__") and len(dv) == 4 and len(v) == 3:
        v = (*v, 1.0)
    sock.default_value = v


def mat(name, color, rough=0.5, **inp):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    b = m.node_tree.nodes["Principled BSDF"]
    inp["Base Color"] = color
    inp["Roughness"] = rough
    for k, v in inp.items():
        setin(b.inputs[k], v)
    return m


def link_or(nt, dst, src):
    if isinstance(src, bpy.types.NodeSocket):
        nt.links.new(src, dst)
    else:
        setin(dst, src)


def mixc(nt, fac, a, b):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    ins = {s.identifier: s for s in n.inputs}
    link_or(nt, ins["Factor_Float"], fac)
    link_or(nt, ins["A_Color"], a)
    link_or(nt, ins["B_Color"], b)
    return {s.identifier: s for s in n.outputs}["Result_Color"]


def mth(nt, op, a, b=0.0, clamp_=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp_
    link_or(nt, n.inputs[0], a)
    link_or(nt, n.inputs[1], b)
    return n.outputs[0]


def attr(nt, name):
    n = nt.nodes.new("ShaderNodeAttribute")
    n.attribute_name = name
    return n.outputs["Fac"]


def value(nt, name, v=0.0):
    n = nt.nodes.new("ShaderNodeValue")
    n.name = name
    n.outputs[0].default_value = v
    return n.outputs[0]


def maprange(nt, name, src, to_min, to_max):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.name = name
    n.interpolation_type = "SMOOTHSTEP"
    n.clamp = True
    link_or(nt, n.inputs["Value"], src)
    n.inputs["To Min"].default_value = to_min
    n.inputs["To Max"].default_value = to_max
    return n.outputs["Result"]


GREEN, RED, WOOD = hx("#3FAE4A"), hx("#E5322D"), hx("#E8C79A")
GRAPH, SPOT, BLACK = hx("#2B2B2E"), hx("#141414"), hx("#17171C")


def pencil_mat(name, col):
    m = mat(name, col, 0.3, **{"Coat Weight": 0.4, "Coat Roughness": 0.12})
    nt = m.node_tree
    lead = tuple(c * 0.75 for c in col)
    c = mixc(nt, attr(nt, "wood"), col, WOOD)
    c = mixc(nt, attr(nt, "lead"), c, lead)
    nt.links.new(c, nt.nodes["Principled BSDF"].inputs["Base Color"])
    return m


def hammy_mat():
    m = mat("hammy", GREEN, 0.42, **{
        "Subsurface Weight": 0.25, "Subsurface Radius": (1.0, 0.45, 0.25),
        "Subsurface Scale": 0.02, "Coat Weight": 0.3, "Coat Roughness": 0.2})
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    dA, u = attr(nt, "dA"), attr(nt, "u")
    red = mth(nt, "MULTIPLY", maprange(nt, "mrA", dA, 1.0, 0.0), maprange(nt, "mrB", u, 0.0, 1.0))
    grow = mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", value(nt, "wA", -0.05), dA), 5.0, True)
    cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(mth(nt, "MULTIPLY", u, 14.0), cmb.inputs[0])
    nt.links.new(mth(nt, "MULTIPLY", attr(nt, "ang"), 4.0), cmb.inputs[1])
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 1.0
    nt.links.new(cmb.outputs[0], vor.inputs["Vector"])
    spot = mth(nt, "LESS_THAN", vor.outputs["Distance"], mth(nt, "MULTIPLY", grow, 0.3))
    spot = mth(nt, "MULTIPLY", spot, red)
    c = mixc(nt, red, GREEN, RED)
    c = mixc(nt, spot, c, SPOT)
    woodm = mth(nt, "MULTIPLY", attr(nt, "wood"), mth(nt, "SUBTRACT", 1.0, value(nt, "skin", 0.0)))
    c = mixc(nt, woodm, c, WOOD)
    c = mixc(nt, attr(nt, "lead"), c, GRAPH)
    nt.links.new(c, b.inputs["Base Color"])
    return m


def emit_mat(name, col, strength):
    m = mat(name, col, 0.5, **{"Emission Color": col, "Emission Strength": strength})
    return m


# ---------------------------------------------------------------- геометрия
SCN = bpy.context.scene


def link(o):
    SCN.collection.objects.link(o)
    return o


def obj_from_bm(name, bm, m=None, smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    if m:
        me.materials.append(m)
    return link(bpy.data.objects.new(name, me))


def sphere(name, m=None, r=1.0, seg=32, rings=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=r)
    return obj_from_bm(name, bm, m)


def box(name, size, loc, m, bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = V(v.co.x * size[0] + loc[0], v.co.y * size[1] + loc[1], v.co.z * size[2] + loc[2])
    o = obj_from_bm(name, bm, m, smooth=False)
    if bevel:
        mod = o.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 4
        o.data.shade_smooth()
    return o


def dyn(name, m):
    me = bpy.data.meshes.new(name)
    me.materials.append(m)
    return link(bpy.data.objects.new(name, me))


def set_mesh(o, geo):
    verts, faces, attrs = geo
    me = o.data
    me.clear_geometry()
    me.from_pydata(verts, [], faces)
    for k, vals in attrs.items():
        a = me.attributes.get(k) or me.attributes.new(k, "FLOAT", "POINT")
        a.data.foreach_set("value", vals)
    me.shade_smooth()
    me.update()


ATTRS = ("u", "dA", "wood", "lead", "ang")


def new_geo():
    return ([], [], {k: [] for k in ATTRS})


def tube(geo, pts, rad, attrs=None, seg=20, caps=(True, True)):
    """Трубка по точкам с радиусами; attrs — значения атрибутов на точку (или число)."""
    V_, F_, A_ = geo
    attrs = attrs or {}
    base, n = len(V_), len(pts)
    T = []
    for i in range(n):
        d = pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]
        T.append(d.normalized() if d.length > 1e-9 else (T[-1] if T else V(1, 0, 0)))
    up = V(0, 0, 1)
    ref = up if abs(T[0].dot(up)) < 0.9 else V(0, 1, 0)
    N_ = (ref - T[0] * ref.dot(T[0])).normalized()

    def av(k, i):
        v = attrs.get(k, 0.0)
        return v[i] if isinstance(v, (list, tuple)) else v

    for i in range(n):
        if i:
            M_ = N_ - T[i] * N_.dot(T[i])
            if M_.length > 1e-9:
                N_ = M_.normalized()
        B_ = T[i].cross(N_)
        for j in range(seg):
            a = math.pi + TAU * j / seg
            V_.append(tuple(pts[i] + (N_ * math.cos(a) + B_ * math.sin(a)) * rad[i]))
            for k in ATTRS:
                A_[k].append(j / seg if k == "ang" else av(k, i))
    for i in range(n - 1):
        for j in range(seg):
            a = base + i * seg + j
            b = base + i * seg + (j + 1) % seg
            F_.append((a, b, b + seg, a + seg))
    for end, first, on in ((0, True, caps[0]), (n - 1, False, caps[1])):
        if not on:
            continue
        c = len(V_)
        V_.append(tuple(pts[end]))
        for k in ATTRS:
            A_[k].append(0.0 if k == "ang" else av(k, end))
        r0 = base + end * seg
        for j in range(seg):
            a, b = r0 + j, r0 + (j + 1) % seg
            F_.append((c, b, a) if first else (c, a, b))


def bez(a, m, b, t):
    return a * (1 - t) ** 2 + m * (2 * (1 - t) * t) + b * (t * t)


def limb(geo, S, H, bend, r, palm, press=0.0, attrs=None, K=14):
    """Мягкая «резиновая» конечность: дуга S→H и шарик-варежка радиуса palm на конце."""
    if r < 1e-4:
        return
    mid = (S + H) * 0.5 + bend
    dir_end = (H - bez(S, mid, H, 0.9)).normalized()
    Hb = H - dir_end * palm * 0.7
    pts, rad = [], []
    for k in range(K + 1):
        t = k / K
        pts.append(bez(S, mid, Hb, t))
        rad.append(r)
    zt = palm * (1 - 0.25 * press)
    for k in range(1, 9):
        z = -palm * 0.7 + (zt + palm * 0.7) * k / 8
        q = z / zt if z > 0 else z / palm
        rr = palm * (1 + 0.12 * press) * math.sqrt(clamp(1 - q * q))
        pts.append(H + dir_end * z)
        rad.append(max(rr, r * (1 - k / 8)))
    tube(geo, pts, rad, attrs, seg=14)


def body_spine(st):
    """Позвоночник Хамми/карандаша: точки от s=0 (у головы) до s=1 (хвост)."""
    M = 60
    ds = L_BODY / (M - 1)
    R = st["R"]
    ia = round(S_A * (M - 1))
    phi = []
    for i in range(M):
        s = i / (M - 1)
        if i <= ia:
            a = st["lift"] * (math.radians(44) * sm(0.5, 0.22, s) - math.radians(38) * sm(0.17, 0.0, s))
            a -= st["hang"] * math.radians(70) * sm(0.55, 0.15, s)
        else:
            q = clamp((s - 0.76) / 0.24)
            a = st["curl"] * TAU * 2.1 * q * q
            a -= st["hang"] * math.radians(70) * sm(0.55, 0.9, s)
        a += st["swing"]
        phi.append(a)
    pts = [None] * M
    pts[ia] = st["anchor"].copy()
    for i in range(ia - 1, -1, -1):
        pts[i] = pts[i + 1] + V(-math.cos(phi[i]), 0, math.sin(phi[i])) * ds
    for i in range(ia + 1, M):
        pts[i] = pts[i - 1] + V(math.cos(phi[i]), 0, math.sin(phi[i])) * ds
    rad = []
    for i in range(M):
        s = i / (M - 1)
        r = R0 * (1 + 0.40 * R * math.exp(-((s - 0.55) / 0.2) ** 2) - 0.12 * R * math.exp(-((s - 0.12) / 0.08) ** 2))
        tail = clamp((s - 0.7) / 0.3)
        r *= lerp(1.0, 1 - 0.82 * tail ** 0.8, R)
        r *= 1 - st["pinch"] * 0.16 * math.exp(-((s - 0.55) / 0.06) ** 2)
        r *= 1 + st["breath"]
        rad.append(r)
    amp, ph = st["ripple"]
    if amp:
        for i in range(M):
            s = i / (M - 1)
            pts[i].z += amp * math.sin(TAU * (ph - s * 1.4)) * sm(0.0, 0.3, s)
    sx, sz = st["squash"]
    base = V(st["anchor"].x, st["anchor"].y, FLOOR)
    if sz != 1.0:
        for i in range(M):
            d = pts[i] - base
            pts[i] = base + V(d.x * sx, d.y * sx, d.z * sz)
    return pts, rad


def rot_dir(d, yaw, pitch):
    side = d.cross(V(0, 0, 1))
    if side.length < 1e-6:
        side = V(0, 1, 0)
    side.normalize()
    d = (Matrix.Rotation(-pitch, 3, side) @ d)
    return (Matrix.Rotation(yaw, 3, "Z") @ d).normalized()


def head_points(pts, rad, R, yaw=0.0, pitch=0.0):
    """Заточка карандаша / морда хамелеона: точки от кончика носа к основанию."""
    T0 = (pts[0] - pts[1]).normalized()
    D = rot_dir(T0, yaw, pitch)
    Lh = lerp(0.25, 0.24, R)
    Mh = 16
    rb = rad[0]
    seq = [pts[0]]
    dirs = []
    for k in range(1, Mh + 1):
        t = k / Mh
        d = T0.lerp(D, sm(0.0, 0.5, t)).normalized()
        dirs.append(d)
        seq.append(seq[-1] + d * (Lh / Mh))
    hp, hr, ht = [], [], []
    for k in range(Mh, 0, -1):
        t = k / Mh
        rc = rb * (1 - t)
        rr = rb * (1.22 + 0.12 * math.sin(math.pi * t)) * math.sqrt(clamp(1 - t ** 2.3))
        hp.append(seq[k])
        hr.append(lerp(rc, rr, R))
        ht.append(t)
    return hp, hr, ht, seq, dirs, Lh


def pencil_geo(geo, anchor, length_scale=1.0):
    st = dict(R=0.0, lift=0.0, curl=0.0, hang=0.0, swing=0.0, anchor=anchor, pinch=0.0,
              breath=0.0, ripple=(0.0, 0.0), squash=(1.0, 1.0))
    pts, rad = body_spine(st)
    hp, hr, ht, *_ = head_points(pts, rad, 0.0)
    P = hp + pts
    Rr = hr + rad
    n_h = len(hp)
    tube(geo, P, Rr, {"wood": [1.0] * n_h + [0.0] * len(pts),
                      "lead": [1.0 if t > 0.75 else 0.0 for t in ht] + [0.0] * len(pts)})


# ---------------------------------------------------------------- глаза
def make_eye(prefix, iris_col, lid_m=None):
    white = mat(prefix + "_white", hx("#F4F1EA"), 0.15, **{"Subsurface Weight": 0.2, "Coat Weight": 1.0, "Coat Roughness": 0.0})
    objs = {
        "white": sphere(prefix + "_white", white),
        "iris": sphere(prefix + "_iris", mat(prefix + "_iris", iris_col, 0.2, **{"Coat Weight": 1.0, "Coat Roughness": 0.0})),
        "pupil": sphere(prefix + "_pupil", mat(prefix + "_pupil", hx("#0A0A0C"), 0.2, **{"Coat Weight": 1.0, "Coat Roughness": 0.0})),
        "hl": sphere(prefix + "_hl", emit_mat(prefix + "_hl", (1, 1, 1), 6.0), seg=12, rings=6),
    }
    if lid_m:
        objs["lid"] = sphere(prefix + "_lid", lid_m)
    return objs


def set_eye(e, C, g, re, lid=0.0, fwd=None):
    if fwd is not None and g.dot(fwd) < 0.25:
        g = g.lerp(fwd, clamp(0.25 - g.dot(fwd)) * 2).normalized()
    q = g.to_track_quat("Z", "Y")
    e["white"].matrix_world = Matrix.LocRotScale(C, None, V(re, re, re))
    e["iris"].matrix_world = Matrix.LocRotScale(C + g * re * 0.84, q, V(0.6 * re, 0.6 * re, 0.22 * re))
    e["pupil"].matrix_world = Matrix.LocRotScale(C + g * re * 0.93, q, V(0.32 * re, 0.32 * re, 0.1 * re))
    h = (g * 0.75 + KEYDIR * 0.6).normalized()
    e["hl"].matrix_world = Matrix.LocRotScale(C + h * re * 0.99, None, V(1, 1, 1) * re * 0.14)
    if "lid" in e:
        s = re * 1.07 if lid > 0.5 else 0.0
        e["lid"].matrix_world = Matrix.LocRotScale(C, None, V(s, s, s))


# ---------------------------------------------------------------- сцена
def build():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    S = {}
    navy = mat("case", hx("#1F2D5A"), 0.85, **{"Sheen Weight": 0.6, "Sheen Roughness": 0.5})
    lining = mat("lining", hx("#3A5BA0"), 0.85, **{"Sheen Weight": 0.6, "Sheen Roughness": 0.5})
    zip_m = mat("zip", hx("#2A2A30"), 0.25)
    # стол
    tm = mat("table", hx("#C8874A"), 0.42, **{"Coat Weight": 0.2, "Coat Roughness": 0.2})
    nt = tm.node_tree
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 0.35
    wave.inputs["Distortion"].default_value = 5.0
    nt.links.new(mixc(nt, wave.outputs["Fac"], hx("#C8874A"), hx("#A86A35")), nt.nodes["Principled BSDF"].inputs["Base Color"])
    box("table", (14, 10, 0.1), (0, 2, -0.05), tm)
    # пенал: дно, левая/правая/задняя стенки, отогнутый передний клапан, поднятая крышка сзади
    box("case_floor", (2.3, 1.0, 0.02), (0, 0, FLOOR / 2), lining)
    box("case_bottom", (2.36, 1.04, 0.02), (0, 0, 0.004), navy, 0.008)
    for nm, sz, lc in (("wall_l", (0.05, 1.02, 0.16), (-1.15, 0, 0.08)),
                       ("wall_r", (0.05, 1.02, 0.16), (1.15, 0, 0.08)),
                       ("wall_b", (2.35, 0.05, 0.16), (0, 0.5, 0.08))):
        box(nm, sz, lc, navy, 0.02)
    box("flap", (2.35, 0.55, 0.025), (0, -0.78, 0.012), navy, 0.01)
    lid = box("lid", (2.35, 0.04, 1.0), (0, 0, 0.5), navy, 0.02)
    lid.location = (0, 0.55, 0.14)
    lid.rotation_euler = (math.radians(-18), 0, 0)
    # молния по верху стенок
    for nm, ln, lc, axis in (("zip_b", 2.3, (0, 0.5, 0.165), "X"), ("zip_l", 1.0, (-1.15, 0, 0.165), "Y")):
        z = box(nm, (0.012, 0.03, 0.012) if axis == "X" else (0.03, 0.012, 0.012),
                (lc[0] - ln / 2 if axis == "X" else lc[0], lc[1] - ln / 2 if axis == "Y" else lc[1], lc[2]), zip_m)
        ar = z.modifiers.new("arr", "ARRAY")
        ar.count = int(ln / 0.022)
        ar.use_relative_offset = False
        ar.use_constant_offset = True
        ar.constant_offset_displace = (0.022, 0, 0) if axis == "X" else (0, 0.022, 0)
    # задник: стена, кружка, лампа-боке
    box("wall", (14, 0.1, 8), (0, 4.5, 4), mat("wall", hx("#E9DCC6"), 0.9))
    mug = bpy.data.meshes.new("mug")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=48, radius1=0.45, radius2=0.45, depth=1.0)
    bm.to_mesh(mug)
    bm.free()
    mug.shade_smooth()
    mug.materials.append(mat("mug", hx("#7FB5A6"), 0.3, **{"Coat Weight": 0.5}))
    mo = link(bpy.data.objects.new("mug", mug))
    mo.location = (-2.4, 2.2, 0.5)
    lamp = sphere("lamp", emit_mat("lampm", hx("#FFB868"), 12.0))
    lamp.location = (2.2, 3.2, 1.3)
    lamp.scale = (0.18, 0.18, 0.18)
    # карандаши
    cols = {"red": (-0.17, "#E5322D", 0.0), "yellow": (-0.04, "#F2C230", 0.04),
            "blue": (0.09, "#2F6BD8", -0.03), "orange": (0.22, "#F07A2A", 0.02), "violet": (0.35, "#7B4CC2", -0.05)}
    for nm, (y, c, dx) in cols.items():
        g = new_geo()
        pencil_geo(g, V(ANCH.x + dx, y, FLOOR + R0))
        o = dyn("pencil_" + nm, pencil_mat("pm_" + nm, hx(c)))
        set_mesh(o, g)
    # Хамми
    S["hammy"] = dyn("hammy", hammy_mat())
    S["heyes"] = [make_eye("he%d" % i, hx("#9BB33A")) for i in range(2)]
    # Точка
    black = mat("tblack", BLACK, 0.38, **{"Sheen Weight": 0.3, "Subsurface Weight": 0.05})
    shell = mat("shell", RED, 0.3, **{"Coat Weight": 1.0, "Coat Roughness": 0.03, "Coat IOR": 1.5, "Subsurface Weight": 0.05})
    S["dome"] = sphere("dome", shell, seg=48, rings=24)
    S["belly"] = sphere("belly", black)
    S["thead"] = sphere("thead", black)
    S["mouth"] = sphere("mouth", mat("mouthm", hx("#8E1F33"), 0.4), seg=16, rings=8)
    S["boots"] = [sphere("boot%d" % i, black, seg=16, rings=8) for i in range(4)]
    spot_m = mat("tspot", SPOT, 0.35, **{"Coat Weight": 1.0, "Coat Roughness": 0.03})
    S["spots"] = []
    for th, el, r in ((-38, 22, 0.05), (40, 28, 0.034), (-105, 40, 0.034), (105, 40, 0.034),
                      (-150, 32, 0.03), (150, 32, 0.03), (180, 68, 0.03)):
        th, el = math.radians(th), math.radians(el)
        n = V(math.cos(el) * math.cos(th), math.cos(el) * math.sin(th), math.sin(el))
        rad = V(0.16, 0.14, 0.12)
        p = V(0, 0, 0.15) + V(n.x * rad.x, n.y * rad.y, n.z * rad.z)
        nn = V(n.x / rad.x, n.y / rad.y, n.z / rad.z).normalized()
        S["spots"].append((sphere("tsp", spot_m, seg=16, rings=8),
                           Matrix.LocRotScale(p, nn.to_track_quat("Z", "Y"), V(r, r, r * 0.35))))
    seam = new_geo()
    sp = [V(0.16 * math.cos(a), 0, 0.15 + 0.12 * math.sin(a)) * 1.005 for a in [math.radians(x) for x in range(25, 181, 8)]]
    sp = [V(p.x, 0, p.z) for p in sp]
    tube(seam, sp, [0.006] * len(sp), seg=8)
    S["seam"] = dyn("seam", black)
    set_mesh(S["seam"], seam)
    S["teyes"] = [make_eye("te%d" % i, hx("#8A5A2B"), black) for i in range(2)]
    S["tlimbs"] = dyn("tlimbs", black)
    # рука человека
    skin = mat("hskin", hx("#F1C6A8"), 0.5, **{"Subsurface Weight": 0.4, "Subsurface Radius": (1.0, 0.4, 0.25), "Subsurface Scale": 0.05})
    S["palm"] = sphere("palm", skin)
    S["fingers"] = dyn("fingers", skin)
    sw = mat("sweater", hx("#D9A441"), 0.8, **{"Sheen Weight": 0.8, "Sheen Roughness": 0.4})
    sl = new_geo()
    tube(sl, [V(0, 0.12, 0.8 + 0.4 * k) for k in range(10)], [0.36] * 10, seg=32)
    tube(sl, [V(0, 0.12, 0.78), V(0, 0.12, 0.92)], [0.39, 0.39], seg=32)
    S["sleeve"] = dyn("sleeve", sw)
    set_mesh(S["sleeve"], sl)
    # свет
    def area(nm, loc, size, energy, col, target=V(-0.3, -0.2, 0.1)):
        ld = bpy.data.lights.new(nm, "AREA")
        ld.size = size
        ld.energy = energy
        ld.color = col
        o = link(bpy.data.objects.new(nm, ld))
        o.location = loc
        o.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return o
    area("key", (-2.8, -2.4, 3.2), 1.6, 2000, (1.0, 0.88, 0.74))
    area("rim", (1.8, 2.4, 1.5), 0.9, 1400, (0.86, 0.91, 1.0))
    area("fill", (2.6, -3.2, 1.0), 3.0, 700, (1.0, 0.97, 0.94))
    w = bpy.data.worlds.new("w")
    try:
        w.use_nodes = True
    except Exception:
        pass
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*hx("#BFA88E"), 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35
    SCN.world = w
    cd = bpy.data.cameras.new("cam")
    cd.sensor_fit = "VERTICAL"
    cd.sensor_height = 24.0
    cd.dof.use_dof = True
    cd.dof.aperture_blades = 7
    cd.dof.aperture_rotation = math.radians(15)
    cam = link(bpy.data.objects.new("cam", cd))
    SCN.camera = cam
    S["cam"] = cam
    return S


# ---------------------------------------------------------------- анимация
T_LINES = [(9, 24), (50, 60), (204, 223), (309, 316), (381, 403)]
H_LINES = [(78, 82), (99, 138), (150, 195)]


def talk(f, lines):
    for a, b in lines:
        if a <= f < b:
            t = (f - a) / FPS
            return 0.25 + 0.75 * abs(math.sin(TAU * 4.2 * t + 0.4)) * sm(a, a + 2, f) * sm(b, b - 2, f)
    return 0.0


def hand_pinch(f):
    if f < 420:
        return track(f, [(320, (0.75, -0.1, 3.4)), (336, (0.38, -0.17, 0.42)), (340, (0.40, -0.17, 0.40)),
                         (344, (0.45, -0.30, 0.43)), (347, (0.42, -0.18, 0.41)), (351, (0.44, -0.30, 0.40)),
                         (354, tuple(ANCH)), (360, (ANCH.x, Y_H, 0.5)), (376, (ANCH.x, Y_H, 3.4))])
    return track(f, [(420, (ANCH.x, Y_H, 1.30)), (425, (ANCH.x, Y_H, 1.36)), (440, (ANCH.x - 0.1, Y_H + 0.3, 3.5))])


def hammy_state(f):
    R = track(f, [(77, 0.0), (84, 1.0), (300, 1.0), (309, 0.25), (420, 0.25), (436, 0.0)])
    lift_mul = track(f, [(95, 1.0), (102, 0.82), (136, 0.82), (142, 1.0)])
    st = dict(R=R, lift=R * lift_mul, hang=track(f, [(354, 0.0), (362, 1.0), (420, 1.0), (430, 0.0)]),
              pinch=track(f, [(351, 0.0), (354, 1.0), (420, 1.0), (424, 0.0)]),
              breath=0.012 * R * fl(f, 3), swing=0.0)
    st["curl"] = max(R, track(f, [(300, 0.0), (307, 1.0), (420, 1.0), (432, 0.0)]))
    # якорь (середина тела): прыжок «Ой!», полёт в руке, падение
    a = ANCH.copy()
    if 78 <= f <= 87:
        a.z += 0.13 * math.sin(math.pi * (f - 78) / 9)
    if 354 <= f < 420:
        a = hand_pinch(f)
        st["swing"] = math.radians(10) * math.sin(TAU * 0.8 * (f - 354) / FPS) * math.exp(-(f - 354) / 40)
    elif 420 <= f < 432:
        t = (f - 420) / 12
        a.z = 1.30 - (1.30 - ANCH.z) * t * t
    st["anchor"] = a
    sz = track(f, [(75, 1.0), (78, 0.86), (80, 1.25), (84, 0.94), (88, 1.0)])
    if f >= 430:
        sz = track(f, [(431, 1.0), (432, 0.72), (435, 1.12), (438, 0.97), (441, 1.0)])
    st["squash"] = (1 / math.sqrt(sz), sz)
    rip = 0.014 * sm(255, 262, f) * sm(292, 280, f)
    st["ripple"] = (rip, (f - 255) / FPS * 3.0)
    st["yaw"] = math.radians(track(f, [(160, 0), (172, 38), (183, 38), (188, 14), (195, 14), (200, 0)]))
    st["pitch"] = math.radians(track(f, [(96, 0), (104, 16), (118, 6), (126, 18), (138, 16), (146, 0),
                                         (150, 0), (156, 8), (195, 8), (200, 0)]))
    st["eo"] = track(f, [(68, 0.0), (72, 1.12), (75, 1.0), (430, 1.0), (437, 0.0)])
    st["lid"] = [track(f, [(69, 1.0), (71, 0.0)]), track(f, [(71, 1.0), (73, 0.0)])]
    if 74 < f < 300:
        for i, off in enumerate((132, 134)):
            st["lid"][i] = max(st["lid"][i], blink(f, 90, off, 3))
    st["armw"] = track(f, [(229, 0.0), (244, 1.0), (276, 1.0), (283, 0.0)])
    st["press"] = track(f, [(245, 0.0), (249, 1.0), (274, 1.0), (277, 0.0)])
    st["skin"] = track(f, [(74, 0.0), (84, 1.0), (300, 1.0), (309, 0.0)])
    st["wA"] = track(f, [(285, -0.05), (300, 1.5)])
    st["wB"] = track(f, [(420, -0.25), (429, 1.3)])
    return st


def tochka_state(f):
    """Корень Точки: позиция, ориентация, сжатие; голова; руки (локально или в мире)."""
    y = Y_H
    if f < 9:
        t = f / 9
        loc = V(lerp(-1.12, -0.90, sm(0, 1, t)), y, 0.16 * (1 - t) + FLOOR * t + 0.07 * math.sin(math.pi * t))
        pitch = math.radians(38) * math.sin(math.pi * t)
    elif f >= 432:
        t = clamp((f - 432) / 14)
        loc = V(lerp(-0.78, -1.12, sm(0, 1, t)), y, lerp(FLOOR, 0.16, t) + 0.32 * math.sin(math.pi * t))
        pitch = -TAU * sm(0.05, 0.95, t)
    else:
        x = track(f, [(9, -0.90), (45, -0.90), (58, -0.79), (66, -0.79), (78, -0.79), (84, -0.84),
                      (90, -0.84), (98, -0.81), (222, -0.81), (240, -0.76), (276, -0.76), (284, -0.78)])
        z = FLOOR
        if 45 <= f < 58:
            z += 0.012 * abs(math.sin(math.pi * (f - 45) / 4.33))
        if 233 <= f < 244:
            z += 0.035 * abs(math.sin(math.pi * (f - 233) / 5.5))
        loc = V(x, y, z)
        pitch = math.radians(track(f, [(52, 0), (58, 9), (64, 0), (77, 0), (81, -18), (90, -6), (98, 0),
                                       (204, 0), (210, -10), (219, -10), (226, 6), (240, 0),
                                       (328, 0), (345, -12), (375, -8), (390, 0)]))
    roll = 0.0
    if 309 <= f < 326:
        roll = math.radians(5) * math.sin(TAU * 7 * (f - 309) / FPS) * sm(309, 311, f) * sm(326, 320, f)
    roll += math.radians(track(f, [(398, 0), (404, 7), (417, 7), (424, 0)]))
    sz = 1.0
    sz *= track(f, [(6, 1.0), (9, 0.8), (12, 1.08), (15, 1.0)]) if f < 30 else 1.0
    sz *= track(f, [(77, 1.0), (80, 0.86), (88, 0.88), (96, 1.0)]) if 70 < f < 100 else 1.0
    if 233 <= f < 246:
        ph = ((f - 233) / 5.5) % 1.0
        sz *= 1.0 + 0.07 * math.cos(TAU * ph) * 0.5
    if f >= 444:
        sz *= track(f, [(445, 1.0), (446, 0.82), (448, 1.05), (449, 1.0)])
    st = dict(loc=loc, rot=(roll, pitch, 0.0), scale=V(1 / math.sqrt(sz), 1 / math.sqrt(sz), sz))
    hp = track(f, [(9, 0), (12, -8), (36, -6), (44, 0), (50, 0), (56, -12), (62, -6), (75, 0),
                   (204, 0), (210, -15), (223, -12), (231, 0), (326, 0), (340, -38), (372, -38),
                   (380, -28), (419, -26), (428, 0)])
    hr = track(f, [(136, 0), (141, 18), (148, 18), (152, 0), (398, 0), (404, 12), (417, 12), (424, 0)])
    hr += 6 * math.sin(TAU * 2.2 * f / FPS) * sm(10, 14, f) * sm(36, 30, f)
    st["head"] = (math.radians(hr), math.radians(hp), 0.0)
    st["blink"] = max(blink(f, 90, 20, 3), 1.0 if 310 <= f < 322 else 0.0)
    st["mouth"] = talk(f, T_LINES)
    # руки: (локальная цель, мировая цель, вес мира)
    rest_r, rest_l = V(0.12, -0.17, 0.035), V(0.12, 0.17, 0.035)
    r = rest_r
    wave = math.sin(TAU * 3 * (f - 9) / FPS)
    r = r.lerp(V(0.14, -0.23, 0.34) + V(0, 0.05 * wave, 0.02 * wave), sm(9, 13, f) * sm(36, 31, f))
    r = r.lerp(V(0.04, -0.22, 0.30), sm(77, 80, f) * sm(92, 86, f))
    r = r.lerp(V(0.135, -0.075, 0.215), sm(211, 216, f) * sm(222, 219, f))
    r = r.lerp(V(0.30, -0.13, 0.17), sm(219, 225, f))
    w2 = math.sin(TAU * 1.5 * (f - 381) / FPS)
    r = r.lerp(V(0.10, -0.25, 0.30) + V(0, 0.035 * w2, 0), sm(380, 386, f) * sm(419, 412, f))
    l = rest_l.lerp(V(0.04, 0.22, 0.30), sm(77, 80, f) * sm(92, 86, f))
    st["rhand"], st["lhand"] = r, l
    st["rw"] = sm(229, 244, f) * sm(284, 277, f)        # к рукопожатию
    st["mouthw"] = sm(308, 311, f) * sm(325, 320, f)   # «Хи-хи» — лапка ко рту
    st["ant"] = sum(spring(f, e, 3.5, 5.0, a) for e, a in ((9, 0.035), (80, 0.04), (246, 0.02), (446, 0.035), (0, 0.03)))
    st["ant"] += 0.008 * math.sin(TAU * 12 * f / FPS) * (sm(10, 14, f) * sm(36, 30, f))
    st["touch"] = sm(55, 60, f) * sm(68, 63, f)
    return st


def gaze_targets(f, HH, Hnose, P, Hp, Hanch):
    """Куда смотрит Точка; куда смотрят глаза Хамми (левый, правый)."""
    if f < 12 or f >= 436:
        tg = Hnose
    elif 240 <= f < 278:
        tg = P
    elif 324 <= f < 354:
        tg = Hp
    elif 354 <= f < 376 or 420 <= f < 436:
        tg = Hanch
    elif 376 <= f < 420:
        tg = V(ANCH.x, Y_H, 2.2)
    else:
        tg = HH
    return tg


def update(f, S):
    hs = hammy_state(f)
    ts = tochka_state(f)
    # --- Хамми: позвоночник и голова
    pts, rad = body_spine(hs)
    hp, hr, ht, seq, dirs, Lh = head_points(pts, rad, hs["R"], hs["yaw"], hs["pitch"])
    ke = int(len(seq) * 0.32)
    Pe, De = seq[ke], dirs[min(ke, len(dirs) - 1)]
    side = De.cross(V(0, 0, 1)).normalized()
    upv = side.cross(De).normalized()
    re_h = rad[0] * lerp(1.0, 1.22, hs["R"])
    HH = Pe + upv * re_h * 0.9
    Hnose = seq[-1]
    ish = 16
    Hs = pts[ish] + V(0, -1, 0) * rad[ish] * 0.6 + V(0, 0, -1) * rad[ish] * 0.3
    # --- Точка: матрицы
    Mroot = Matrix.LocRotScale(ts["loc"], Euler(ts["rot"], "XYZ"), ts["scale"])
    Mhead = Mroot @ Matrix.LocRotScale(V(0.15, 0, 0.19), Euler(ts["head"], "XYZ"), None)
    TH = Mhead @ V(0.05, 0, 0.03)
    Ts = Mroot @ V(0.07, -0.115, 0.11)
    # --- точка рукопожатия
    shake = 0.0
    for c in (258, 266, 273):
        shake += 0.045 * math.exp(-((f - c) / 2.6) ** 2)
    P = (Ts + Hs) * 0.5 + V(0, -0.06, 0.07 - shake)
    # --- рука человека
    Hp = hand_pinch(f)
    # --- меш Хамми
    g = new_geo()
    nb = len(pts)

    def dA_s(s):
        return 0.12 + abs(s - 0.27) * 1.15
    tube(g, hp + pts, hr + rad, {
        "u": [-t * 0.2 for t in ht] + [i / (nb - 1) for i in range(nb)],
        "dA": [dA_s(0) + t * 0.1 for t in ht] + [dA_s(i / (nb - 1)) for i in range(nb)],
        "wood": [1.0] * len(hp) + [0.0] * nb,
        "lead": [1.0 if t > lerp(0.75, 0.88, hs["R"]) else 0.0 for t in ht] + [0.0] * nb})
    hat = {"u": -0.05, "dA": dA_s(0) + 0.03}
    eo = hs["eo"]
    eye_c = []
    for i, sg in enumerate((-1, 1)):
        base = Pe + upv * re_h * 0.45 + side * sg * re_h * 0.5
        ax = (upv * 0.55 + side * sg * 0.85).normalized()
        rr = 0.046 * clamp(eo)
        C = base + ax * (0.025 + 0.05 * eo)
        eye_c.append((C, ax, rr))
        if rr > 1e-4:
            lid = hs["lid"][i]
            zc = 0.025 + 0.05 * eo
            zend = lerp(zc - 0.25 * rr, zc + 1.12 * rr, lid)
            tp, tr = [], []
            for k in range(13):
                z = -0.02 + (zend + 0.02) * k / 12
                q = (z - zc) / (1.12 * rr)
                tr.append(1.12 * rr * (math.sqrt(clamp(1 - q * q)) if z > zc else 1.0) * (0.85 if k == 0 else 1.0))
                tp.append(base + ax * z)
            tube(g, tp, tr, hat, seg=18, caps=(True, lid > 0.98))
    # ноги/руки Хамми
    legv = sm(0.15, 0.9, hs["R"])
    if legv > 0.01:
        for ii, sg, fr in ((ish, -1, True), (ish, 1, True), (44, -1, False), (44, 1, False)):
            hip = pts[ii] + V(0, sg, 0) * rad[ii] * 0.55 + V(0, 0, -1) * rad[ii] * 0.45
            foot = V(hip.x + 0.02, hip.y + sg * 0.075, FLOOR + 0.022)
            dang = hip + V(-0.04 if fr else 0.03, sg * 0.05, -0.13)
            foot = foot.lerp(dang, max(sm(0.14, 0.26, hip.z), hs["hang"]))
            press = 0.0
            if fr and sg < 0:
                foot = foot.lerp(P + V(0.016, 0, 0), hs["armw"])
                press = hs["press"]
            bend = V(0, sg * 0.03, 0.03)
            limb(g, hip, foot, bend, 0.021 * legv, 0.032 * legv, press,
                 {"u": ii / (nb - 1), "dA": (0.02 if (fr and sg < 0) else dA_s(ii / (nb - 1)))}, K=12)
    set_mesh(S["hammy"], g)
    # глаза Хамми
    for i, (C, ax, rr) in enumerate(eye_c):
        if rr < 1e-4:
            set_eye(S["heyes"][i], C, ax, 0.0)
            continue
        tgt = TH
        if f < 75:
            tgt = TH if (i == 1 and f >= 71) else HH + V(-0.3, -0.35 + 0.25 * math.sin(f * 0.9 + i), 0.15)
        if 99 <= f < 138:
            if (i == 0 and not (118 <= f < 126)) or (i == 1 and f >= 126):
                tgt = V(-0.45, -0.55, 0.0)
        if 165 <= f < 195 and i == 0:
            tgt = HH + V(1.5, -0.1, 0.3)
        if 241 <= f < 278:
            tgt = P
        if f >= 302:
            tgt = HH + (V(-0.3, -1.6, 0.9) if i == 0 else V(-0.2, 1.4, 1.2))
        g_ = (tgt - C).normalized()
        set_eye(S["heyes"][i], C, g_, rr * 0.98, fwd=ax)
    # --- Точка: тело
    S["dome"].matrix_world = Mroot @ Matrix.LocRotScale(V(0, 0, 0.15), None, V(0.16, 0.14, 0.12))
    S["belly"].matrix_world = Mroot @ Matrix.LocRotScale(V(0.01, 0, 0.11), None, V(0.15, 0.125, 0.08))
    S["seam"].matrix_world = Mroot
    for o, ml in S["spots"]:
        o.matrix_world = Mroot @ ml
    for i, (bx, by) in enumerate(((0.06, -0.09), (0.06, 0.09), (-0.07, -0.09), (-0.07, 0.09))):
        S["boots"][i].matrix_world = Mroot @ Matrix.LocRotScale(V(bx, by, 0.018), None, V(0.04, 0.028, 0.022))
    S["thead"].matrix_world = Mhead @ Matrix.Scale(0.085, 4)
    mo = ts["mouth"]
    mn = V(0.93, 0, -0.36).normalized()
    smile = 1.0 + 0.25 * ts["mouthw"]
    S["mouth"].matrix_world = Mhead @ Matrix.LocRotScale(mn * 0.083, mn.to_track_quat("X", "Z"),
                                                         V(0.007, 0.022 * smile, 0.004 + 0.015 * mo))
    tg = gaze_targets(f, HH, Hnose, P, Hp, hs["anchor"])
    fwd = (Mhead.to_3x3() @ V(1, 0, 0)).normalized()
    for i, sg in enumerate((-1, 1)):
        C = Mhead @ V(0.062, sg * 0.036, 0.03)
        set_eye(S["teyes"][i], C, (tg - C).normalized(), 0.037 * ts["scale"].x, ts["blink"], fwd)
    # --- Точка: усики и руки (мировые координаты)
    tl = new_geo()
    for sg in (-1, 1):
        b = Mhead @ V(0.03, sg * 0.03, 0.075)
        tip = Mhead @ V(0.085 + ts["ant"], sg * 0.065, 0.19 + 0.5 * ts["ant"])
        if sg < 0:
            tip = tip.lerp(Hnose + V(-0.012, 0, 0.004), ts["touch"])
        mid = Mhead @ V(0.03, sg * 0.04, 0.15)
        limb(tl, b, tip, mid - (b + tip) * 0.5, 0.006, 0.015, 0.6 * ts["touch"] if sg < 0 else 0.0, K=12)
    for sg, key in ((-1, "rhand"), (1, "lhand")):
        sh = Mroot @ V(0.07, sg * 0.115, 0.11)
        hw = Mroot @ ts[key]
        if sg < 0:
            hw = hw.lerp(P - V(0.016, 0, 0), ts["rw"])
            hw = hw.lerp(Mhead @ (mn * 0.1 + V(0.01, 0, -0.01)), ts["mouthw"])
        limb(tl, sh, hw, V(0, sg * 0.02, -0.03), 0.016, 0.031, hs["press"] if sg < 0 else 0.0, K=12)
    set_mesh(S["tlimbs"], tl)
    # --- рука человека
    vis = 320 <= f <= 377 or 418 <= f <= 441
    Mh = Matrix.Translation(Hp) @ Matrix.Rotation(math.radians(-25), 4, "X") @ Matrix.Rotation(math.radians(35), 4, "Z")
    if not vis:
        Mh = Matrix.Translation(V(0, 0, 40))
    op = track(f, [(320, 0.8), (350, 0.8), (354, 0.0), (420, 0.0), (425, 1.0)])
    gap = 0.115 + op * 0.2
    fg = new_geo()
    limb(fg, V(0.20, 0.0, 0.5), V(gap, 0, 0.0), V(0.08, -0.02, 0.0), 0.07, 0.075)
    limb(fg, V(-0.22, 0.05, 0.55), V(-gap, 0, 0.02), V(-0.1, -0.04, 0.0), 0.085, 0.085)
    for k, yy in enumerate((0.13, 0.23, 0.31)):
        limb(fg, V(0.14, yy, 0.5), V(0.13 - 0.02 * k, yy, 0.28 + 0.03 * k), V(0.1, 0, -0.02), 0.068 - 0.006 * k, 0.07 - 0.006 * k)
    set_mesh(S["fingers"], fg)
    S["fingers"].matrix_world = Mh
    S["palm"].matrix_world = Mh @ Matrix.LocRotScale(V(0, 0.14, 0.62), None, V(0.2, 0.34, 0.34))
    S["sleeve"].matrix_world = Mh
    # --- материал Хамми
    nt = bpy.data.materials["hammy"].node_tree
    for nm, w in (("mrA", hs["wA"]), ("mrB", hs["wB"])):
        n = nt.nodes[nm]
        n.inputs["From Min"].default_value = w - 0.035
        n.inputs["From Max"].default_value = w + 0.035
    nt.nodes["wA"].outputs[0].default_value = hs["wA"]
    nt.nodes["skin"].outputs[0].default_value = hs["skin"]
    nt.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.1 + 0.3 * (1 - hs["skin"])
    # --- камера
    camera(f, S["cam"], TH, HH, P, Hp, hs["anchor"])


# ---------------------------------------------------------------- камера
def shot_A(f):
    k = 1 - 0.02 * (f / FPS if f < 60 else 0)
    tgt = V(-0.92, -0.26, 0.15)
    return tgt + (V(-0.52, -1.48, 0.38) - tgt) * k, tgt, 35, 8.0, V(-1.0, Y_H, 0.2)


def camera(f, cam, TH, HH, P, Hp, Hanch):
    def B(lens=50, f_=5.6, off=V(0.5, -0.52, 0.04)):
        return TH + off, TH, lens, f_, TH

    def C(lens=50, f_=4.5, off=V(-0.78, -0.72, 0.12)):
        return HH + off, HH, lens, f_, HH

    def D(lens=40):
        mid = (TH + HH) * 0.5
        mid.z = (TH.z + HH.z) * 0.5 - 0.03
        return V(mid.x, mid.y - 1.45, mid.z + 0.06), mid, lens, 8.0, P

    def blend(a, b, t):
        return (a[0].lerp(b[0], t), a[1].lerp(b[1], t), lerp(a[2], b[2], t), lerp(a[3], b[3], t), a[4].lerp(b[4], t))

    if f < 9:
        s = shot_A(f)
    elif f < 36:
        s = B(lerp(50, 55, (f - 9) / 27))
    elif f < 45:
        s = (TH + V(-0.02, 0, 0.0), V(-0.35, Y_H + 0.05, 0.08), 35, 8.0, V(-0.4, Y_H, 0.08))
    elif f < 66:
        s = B(50, 4.5, V(0.42, -0.55, 0.06))
    elif f < 78:
        s = blend(B(50), C(70, 4.0, V(-0.62, -0.6, 0.08)), sm(66, 70, f))
    elif f < 87:
        s = blend(C(70, 4.0, V(-0.62, -0.6, 0.08)), D(28), sm(78, 82, f))
    elif f < 99:
        s = blend(D(28), D(31), (f - 87) / 12)
    elif f < 138:
        s = C(55, 4.5, V(-0.72, -0.7, 0.3))
    elif f < 150:
        s = B(50)
    elif f < 195:
        s = C(lerp(50, 53, (f - 150) / 45))
    elif f < 231:
        s = blend(C(50), B(lerp(50, 53, (f - 195) / 36) * (1.04 if f >= 219 else 1.0)), sm(195, 199, f))
    elif f < 241:
        s = D(32)
    elif f < 268:
        s = (P + V(0.04, -0.6, -0.02), P, 70, 4.0, P)
    elif f < 285:
        s = D(32)
    elif f < 309:
        s = C(45, 5.6, V(-0.95 + 0.2 * sm(295, 308, f), -0.9 + 0.2 * sm(295, 308, f), 0.14))
    elif f < 324:
        s = B(50)
    elif f < 375:
        tgt = V(0.0, -0.12, 0.25).lerp(V(0.25, -0.2, 0.6), sm(354, 374, f))
        foc = V(0.0, -0.1, 0.1).lerp(Hp, sm(330, 350, f))
        s = (V(0.25, -2.7, 2.2) + V(0, 0, 0.4 * sm(354, 374, f)), tgt, 28, 11.0, foc)
    elif f < 420:
        s = (TH + V(0.42, -0.42, -0.18), TH + V(0, 0, 0.06), 40, 5.6, TH)
    else:
        tgt = V(ANCH.x, Y_H, 0.1).lerp(V(ANCH.x, Y_H, 1.15), sm(420, 423, f))
        if f >= 423:
            tgt = V(ANCH.x, Y_H, max(Hanch.z, 0.1))
        s1 = (V(0.25, -2.3, 0.6), tgt, 35, 8.0, Hanch)
        s = blend(s1, shot_A(0), sm(426, 449, f))
    loc, tgt, lens, fs, foc = s
    dist = (loc - tgt).length
    loc = loc + V(fl(f, 4), fl(f, 3, 1.0), fl(f, 5, 2.0)) * 0.004 * dist
    if 78 <= f < 90:
        a = 0.02 * math.exp(-(f - 78) / 4)
        loc = loc + V(math.sin(f * 2.3), 0, math.cos(f * 3.1)) * a
    cam.location = loc
    cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    cam.data.dof.aperture_fstop = fs
    cam.data.dof.focus_distance = max(0.05, (foc - loc).length)


# ---------------------------------------------------------------- рендер
def setup_render(res, spp):
    r = SCN.render
    r.engine = "CYCLES"
    SCN.cycles.device = "CPU"
    SCN.cycles.samples = spp
    SCN.cycles.use_adaptive_sampling = True
    SCN.cycles.adaptive_threshold = 0.03
    SCN.cycles.use_denoising = True
    try:
        SCN.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    SCN.cycles.max_bounces = 4
    SCN.cycles.diffuse_bounces = 2
    SCN.cycles.glossy_bounces = 2
    SCN.cycles.transmission_bounces = 2
    SCN.cycles.caustics_reflective = False
    SCN.cycles.caustics_refractive = False
    r.resolution_y = res
    r.resolution_x = int(round(res * 9 / 16 / 2)) * 2
    r.resolution_percentage = 100
    r.use_persistent_data = True
    r.image_settings.file_format = "PNG"
    SCN.view_settings.view_transform = "AgX"
    for look in ("AgX - Punchy", "Punchy", "AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            SCN.view_settings.look = look
            break
        except Exception:
            pass
    SCN.view_settings.exposure = -0.35


def main():
    frames = frame_list(ARGS.frames)
    os.makedirs(ARGS.out, exist_ok=True)
    S = build()
    setup_render(ARGS.res, ARGS.spp)
    for f in frames:
        path = os.path.join(ARGS.out, "f%04d.png" % f)
        if ARGS.skip_existing and os.path.exists(path):
            continue
        t0 = time.time()
        SCN.frame_set(f)
        update(f, S)
        SCN.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("frame %d  %.1f s" % (f, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
