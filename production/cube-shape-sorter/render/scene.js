// «Кубик и сортер» — сцена как детерминированная функция номера кадра.
// three.js r170, ES-модуль. Время = номер кадра (t = f/30); никаких rAF / performance.now /
// Math.random. Все кривые — из shotlist.md (§2–§4; §6 имеет приоритет над direction.md).
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export const W = 1080, H = 1920, FPS = 30, NFRAMES = 450;

// ---------------------------------------------------------------- PRNG (seeded)
// В сцене нет случайностей (искорки заданы таблицей §4.4). PRNG оставлен как единственный
// разрешённый источник «случайного», если понадобится (seed фиксирован, как у звука).
export function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const rng = mulberry32(2610);

// ---------------------------------------------------------------- интерполяции (§0.3)
const EASE = {
  H: () => 0,
  L: (u) => u,
  EI: (u) => u * u,
  EO: (u) => 1 - (1 - u) * (1 - u),
  S: (u) => -(Math.cos(Math.PI * u) - 1) / 2,
};
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const D2R = Math.PI / 180;

function segIndex(keys, f) {
  let i = 0;
  for (let k = 0; k < keys.length; k++) { if (keys[k][0] <= f) i = k; else break; }
  return i;
}
// keys: [кадр, значение, интерп → след.]; ключ действует с кадра f (§0.3)
function ch(keys, f) {
  if (f < keys[0][0]) return keys[0][1];
  const i = segIndex(keys, f);
  const k = keys[i], n = keys[i + 1], it = k[2] || 'H';
  if (!n || it === 'H') return k[1];
  const u = (f - k[0]) / (n[0] - k[0]);
  return k[1] + (n[1] - k[1]) * EASE[it](u);
}

// ---------------------------------------------------------------- опорные точки (§0.1)
const HOME = new THREE.Vector3(-0.68, 1.2, -0.55);
const CIR = new THREE.Vector3(-1.35, 1.2, 0.45);
const TRI = new THREE.Vector3(0.0, 1.2, 0.45);
const SQ = new THREE.Vector3(1.35, 1.2, 0.45);
// доработка QA (утв. 2026-10-29): треугольник 1.0 → 1.08 — больше нельзя: вырез сольётся с вырезом квадрата
export let TRI_SIDE = 1.08; // сторона треугольного отверстия (внутренний край канта)
// доработка QA: вершина треугольника к камере (+1; было −1 «от камеры»): тогда угол куба,
// направленный строго вниз, совпадает с отверстием при ry ≈ 0 — лицо смотрит в камеру
export let TRI_DIR = 1;
const EYE = 1.4;            // доработка QA: глаза и брови ×1.4

// ---------------------------------------------------------------- кубик: каналы (§3.2)
const X = [[0,-0.68,'H'],[47,-0.68,'L'],[51,-0.95,'H'],[55,-0.95,'L'],[60,-1.22,'H'],[69,-1.22,'L'],
  [78,-1.38,'H'],[81,-1.38,'L'],[93,-0.70,'H'],[116,-0.70,'L'],[120,-0.92,'H'],[135,-0.92,'L'],
  [150,0.000,'H'],[183,0.000,'L'],[195,-0.35,'H'],[289,-0.35,'L'],[294,0.12,'H'],[298,0.12,'L'],
  [303,0.58,'H'],[307,0.58,'L'],[312,1.02,'H'],[321,1.02,'L'],[330,1.35,'H'],[438,-0.68,'H']];
const Z = [[0,-0.55,'H'],[47,-0.55,'L'],[51,-0.58,'H'],[55,-0.58,'L'],[60,-0.62,'H'],[69,-0.62,'L'],
  [78,0.30,'H'],[81,0.30,'L'],[93,-0.60,'H'],[116,-0.60,'L'],[120,-0.66,'H'],[135,-0.66,'L'],
  [150,0.450,'H'],[183,0.450,'L'],[195,-0.62,'H'],[289,-0.62,'L'],[294,-0.68,'H'],[298,-0.68,'L'],
  [303,-0.66,'H'],[307,-0.66,'L'],[312,-0.64,'H'],[321,-0.64,'L'],[330,0.45,'H'],[438,-0.55,'H']];
// sy (squash); в воздухе между ключами — S; f201–243 — формула «дыхания»
const SY = [[0,1.20,'H'],[10,1.20,'L'],[11,1.15,'H'],[12,0.65,'H'],[13,0.68,'EO'],[14,1.00,'EO'],
  [16,1.05,'EI'],[21,0.90,'EO'],[23,1.04,'S'],[26,0.98,'S'],[30,1.00,'H'],
  [45,1.00,'EI'],[47,0.88,'S'],[48,1.08,'S'],[50,1.00,'S'],[51,0.90,'EO'],[53,1.00,'EI'],
  [55,0.88,'S'],[56,1.08,'S'],[58,1.00,'S'],[60,0.90,'EO'],[62,1.00,'H'],[63,1.00,'EI'],
  [67,0.75,'H'],[69,0.75,'S'],[70,1.20,'S'],[73,1.00,'S'],[76,1.08,'S'],[78,0.80,'H'],
  [81,0.80,'S'],[82,1.10,'S'],[88,1.00,'S'],[92,1.05,'S'],[93,0.80,'EO'],[95,1.00,'S'],
  [98,0.92,'EO'],[102,1.00,'H'],[113,1.00,'S'],[115,0.90,'H'],[116,0.90,'S'],[118,1.04,'S'],
  [120,0.90,'EO'],[122,1.00,'H'],[126,1.00,'EI'],[133,0.70,'H'],[135,0.70,'S'],[136,1.25,'S'],
  [140,1.00,'S'],[146,1.05,'S'],[149,1.00,'H'],[150,0.92,'EO'],[153,1.00,'H'],[180,1.00,'EI'],
  [182,0.92,'H'],[183,1.20,'S'],[186,1.05,'S'],[190,1.00,'S'],[194,1.05,'S'],[195,0.80,'EO'],
  [197,1.00,'H'],[201,0.92,'H'],[243,0.92,'S'],[249,1.00,'H'],[274,1.00,'EI'],[276,0.88,'S'],
  [278,1.10,'S'],[280,1.00,'S'],[282,0.85,'EO'],[285,1.03,'S'],[288,1.00,'EI'],[289,0.90,'S'],
  [291,1.06,'S'],[294,0.90,'EO'],[296,1.00,'EI'],[298,0.88,'S'],[300,1.07,'S'],[303,0.90,'EO'],
  [305,1.00,'EI'],[307,0.88,'S'],[309,1.08,'S'],[312,0.90,'EO'],[315,1.00,'EI'],[319,0.80,'H'],
  [321,0.80,'S'],[322,1.15,'S'],[326,1.00,'S'],[329,1.02,'S'],[330,1.00,'H'],[336,1.00,'EI'],
  [338,1.05,'H'],[438,1.20,'H']];
function sy(f) {
  if (f >= 201 && f < 243) return 0.92 + 0.006 * Math.sin(2 * Math.PI * (f - 201) / 30);
  return ch(SY, f);
}
// y: число | 'G' (на опоре: 1.2 + 0.5·sy) | 'C' (правило опоры, §0.2);
// интерп: имя кривой | 'G' (держать на опоре) | {B: hp} (баллистика) | 'C' (опора + смещение)
const Y = [[12,1.525,'H'],[13,1.540,'EO'],[14,1.700,'EO'],[16,1.875,'EI'],[21,'G','G'],
  [47,'G',{B:0.25}],[51,'G','G'],[55,'G',{B:0.25}],[60,'G','G'],[69,1.575,'EO'],[74,2.650,'EI'],
  [78,'C','H'],[81,'C','EO'],[87,2.400,'EI'],[93,'G','G'],[95,'G',{B:0.06}],[98,'G','G'],
  [116,'G',{B:0.12}],[120,'G','G'],[135,1.550,'EO'],[142,3.450,'EI'],[150,'C','C'],
  [183,1.620,'EO'],[188,2.750,'EI'],[195,'G','G'],[197,1.700,'S'],[199,1.860,'S'],[201,'G','G'],
  [276,'G',{B:0.30}],[282,'G','G'],[289,'G',{B:0.22}],[294,'G','G'],[298,'G',{B:0.26}],
  [303,'G','G'],[307,'G',{B:0.30}],[312,'G','G'],[321,1.600,'EO'],[325,2.550,'EI'],
  [330,1.700,'EO'],[336,1.640,'EI'],[356,0.300,'H']];
// смещение над опорой на застревании (рывки f162/170/177)
const COFF = [[150,0,'H'],[160,0,'EO'],[162,0.030,'H'],[165,0.030,'S'],[168,0,'EO'],[170,0.045,'H'],
  [173,0.045,'S'],[175,0,'EO'],[177,0.060,'H'],[180,0.060,'EI'],[182,0.030,'H']];
const RX = [[0,0,'H'],[110,0,'EI'],[113,10,'EO'],[116,0,'H'],[140,0,'S'],[149,-35.26,'H'],
  [183,-35.26,'S'],[190,0,'H'],[258,0,'S'],[263,8,'H'],[268,8,'S'],[272,0,'H']];
const RY = [[0,0,'H'],[63,0,'S'],[69,20,'H'],[81,20,'S'],[93,0,'H'],[102,0,'S'],[104,8,'S'],
  [106,-8,'S'],[108,0,'H'],[126,0,'S'],[135,-15,'H'],[140,-15,'S'],[149,-5,'H'],[183,-5,'S'],[195,0,'H'],[246,0,'S'],
  [258,28,'H'],[288,28,'L'],[312,10,'H'],[321,10,'S'],[329,0,'H']];
const RZ = [[0,0,'H'],[37,0,'S'],[43,12,'H'],[45,12,'S'],[51,4,'H'],[53,4,'S'],[58,0,'H'],
  [72,0,'S'],[78,-12,'H'],[81,-12,'S'],[87,0,'H'],[140,0,'S'],[149,45,'H'],[160,45,'EO'],
  [162,42,'H'],[165,42,'S'],[168,45,'EO'],[170,49.5,'H'],[173,49.5,'S'],[175,45,'EO'],
  [177,39,'H'],[183,39,'S'],[192,0,'H'],[321,0,'S'],[323,-6,'S'],[329,0,'H']];
const FLIPZ = [[0,0,'H'],[81,0,'S'],[91,-90,'H'],[93,0,'H'],[137,0,'S'],[148,-360,'H'],[150,0,'H']];
const FLIPX = [[0,0,'H'],[184,0,'S'],[194,-90,'H'],[197,-90,'S'],[199,-45,'S'],[201,0,'H']];

// ---------------------------------------------------------------- глаза и брови (§3.4)
const LID = [[0,0,'H'],[11,0,'EI'],[12,1,'H'],[24,1,'S'],[30,0,'H'],[33,0,'EI'],[36,1,'H'],
  [37,1,'EO'],[40,0,'H'],[160,0,'EO'],[162,0.40,'H'],[165,0.40,'S'],[168,0,'EO'],[170,0.45,'H'],
  [173,0.45,'S'],[175,0,'EO'],[177,0.50,'H'],[180,0.50,'S'],[183,0,'H'],[194,0,'EO'],[195,1,'H'],
  [197,1,'S'],[199,0,'H'],[201,0,'S'],[206,0.35,'H'],[216,0.35,'EI'],[222,1,'H'],[225,1,'EO'],
  [231,0.35,'H'],[243,0.35,'S'],[246,0,'H'],[280,0,'S'],[282,0.30,'S'],[285,0,'H'],
  [327,0,'S'],[330,0.20,'H'],[346,0.20,'EI'],[348,1,'H'],[438,0,'H']];
const PUPIL = [[0,1,'H'],[76,1,'EO'],[78,0.85,'H'],[81,0.85,'S'],[93,1,'H'],[108,1,'S'],
  [112,0.85,'H'],[140,0.85,'S'],[149,0.90,'H'],[183,0.90,'S'],[190,1,'H'],[273,1,'EO'],
  [276,1.30,'H'],[309,1.30,'S'],[312,1.15,'H'],[438,1,'H']];
const WHITE = [[0,1,'H'],[76,1,'EO'],[78,1.15,'H'],[81,1.15,'S'],[93,1,'H'],[140,1,'S'],
  [149,1.20,'H'],[183,1.25,'S'],[190,1,'H'],[273,1,'EO'],[276,1.10,'H'],[309,1.10,'S'],
  [312,1.05,'H'],[438,1,'H']];
const GLINT = [[0,1,'H'],[273,1,'EO'],[276,1.60,'H'],[309,1.60,'S'],[312,1.30,'H'],[438,1,'H']];
const BROW = [[0,0,'H'],[11,0,'EI'],[12,8,'H'],[24,8,'S'],[30,0,'H'],[63,0,'S'],[69,6,'H'],
  [76,6,'EO'],[78,0,'H'],[108,0,'S'],[112,18,'H'],[140,18,'S'],[149,0,'H'],[157,0,'S'],
  [160,10,'H'],[180,10,'S'],[183,0,'H'],[201,0,'S'],[206,-12,'H'],[243,-12,'S'],[249,0,'H'],
  [273,0,'EO'],[276,-4,'H'],[309,-4,'S'],[312,0,'H'],[438,0,'H']];
const BROWY = [[0,0,'H'],[76,0,'EO'],[78,0.03,'H'],[81,0.03,'S'],[93,0,'H'],[140,0,'S'],
  [149,0.04,'H'],[183,0.05,'S'],[190,0,'H'],[273,0,'EO'],[276,0.04,'H'],[309,0.04,'S'],
  [312,0.02,'H'],[438,0,'H']];
const BROWL_A = [[0,0,'H'],[38,0,'S'],[43,-10,'H'],[45,-10,'S'],[51,0,'H']]; // «вопрос», левая
const BROWL_Y = [[0,0,'H'],[38,0,'S'],[43,0.03,'H'],[45,0.03,'S'],[51,0,'H']];
// взгляд: [кадр, цель, интерп]
const GAZE = [[0,'HOME','H'],[24,'HOME','S'],[30,'CAM','H'],[34,'CAM','S'],[39,'CIR','H'],
  [81,'CIR','S'],[93,'CAM','H'],[108,'CAM','S'],[112,'TRI','H'],[140,'TRI','S'],[149,'CAM','H'],
  [201,'CAM','S'],[206,'SELF','H'],[240,'SELF','S'],[243,'SQ','H'],[258,'SQ','S'],
  [262,'SELF','H'],[269,'SELF','S'],[272,'SQ','H'],[327,'SQ','S'],[330,'CAM','H'],[438,'HOME','H']];

// ---------------------------------------------------------------- сортер и эффекты (§4)
const LIDDY = [[0,0,'H'],[150,0,'EO'],[152,0.030,'EI'],[156,0,'H'],[363,0,'EO'],[365,0.020,'EI'],[369,0,'H']];
const CIRE = [[0,0,'H'],[78,0,'EO'],[80,0.8,'EI'],[84,0,'H']];
const SQE = [[0,0,'H'],[237,0,'EO'],[241,0.6,'S'],[246,0.15,'H'],[330,0.15,'EO'],[336,0,'H']];
const STRIP_C = [[237,-0.75,'S'],[246,0.75,'H']];
const STRIP_A = [[237,0,'EO'],[240,1,'H'],[243,1,'EI'],[246,0,'H']];
const SPARKS = [ // рождение, dx, dz, v, r, цвет, жизнь
  [366,-0.15, 0.05,[-0.6,3.2, 0.3],0.07,'#FFD23F',12],
  [368, 0.12,-0.08,[ 0.7,3.5,-0.2],0.06,'#FF8A2A',12],
  [370, 0.00, 0.12,[ 0.1,3.8, 0.5],0.08,'#FFF3C4',13],
  [371,-0.20,-0.10,[-0.9,2.9,-0.3],0.05,'#FFD23F',11],
  [374, 0.18, 0.10,[ 0.8,3.1, 0.4],0.06,'#FFF3C4',12],
  [376,-0.05, 0.00,[-0.3,3.4, 0.2],0.07,'#FF8A2A',12]];

// ---------------------------------------------------------------- камера (§2)
// доработка QA: ближе (14.15 → 13.10) и сортер выше к центру кадра; dolly-in −5% сохранён
const D0 = 13.10, D1 = D0 * 13.44 / 14.15;
const DOLLY = [[0,D0,'H'],[210,D0,'S'],[237,D1,'H'],[378,D1,'S'],[402,D0,'H']];
const CAM_TARGET = new THREE.Vector3(0.30, 1.55, 0);
const CAM_DIR = new THREE.Vector3(0, 0.5739, 0.8191).normalize();
function shake(f) { // {dx, dy, roll°}
  let n;
  if (f >= 12 && f <= 17) { n = f - 12; return { dx: 0, dy: -0.03 * Math.exp(-n / 1.5) * (1 - n / 6), roll: 0 }; }
  if (f >= 78 && f <= 84) { n = f - 78; const e = (1 - n / 6) ** 2; return { dx: 0, dy: 0.04 * Math.sin(2 * Math.PI * 18 * n / 30) * e, roll: 0 }; }
  if (f >= 150 && f <= 159) {
    n = f - 150; const e = (1 - n / 9) ** 2, w = 2 * Math.PI * 16 * n / 30;
    return { dx: 0.08 * Math.sin(w + Math.PI / 2) * e, dy: 0.08 * Math.sin(w) * e, roll: 0.6 * Math.sin(w + Math.PI / 4) * e };
  }
  if (f >= 363 && f <= 366) { n = f - 363; return { dx: 0, dy: -0.015 * (1 - n / 3), roll: 0 }; }
  return { dx: 0, dy: 0, roll: 0 };
}
export function cameraPose(f) {
  const t = f / FPS, s = shake(f);
  const target = CAM_TARGET.clone().add(new THREE.Vector3(s.dx, s.dy, 0));
  const pos = target.clone().addScaledVector(CAM_DIR, ch(DOLLY, f))
    .add(new THREE.Vector3(0.03 * Math.sin(2 * Math.PI * t / 15), 0.02 * Math.sin(4 * Math.PI * t / 15), 0));
  return { pos, target, roll: s.roll };
}

// ---------------------------------------------------------------- падение-петля (§3.1)
const FALL_K = 0.82;
function fallY(f) {
  const t = f < 30 ? f / FPS + 15 : f / FPS;
  const tau = t - 14.6;
  // доработка QA: высоты над точкой касания ×FALL_K (камера ближе) — касание f12 и шов петли те же
  return 1.7 + FALL_K * (7.90 - 1.615 * tau - 7.669 * tau * tau - 1.7);
}
const inFall = (f) => f < 12 || f >= 438;

// ================================================================= построение сцены
const COL = {
  cube: '#FF8A2A', sheen: '#FFC48A', white: '#FFFFFF', pupil: '#1E1A2B', brow: '#7A3A12',
  sorter: '#F4EBDD', cir: '#5BB8F5', tri: '#6CCB6A', sq: '#FFD23F', inside: '#5A4E44',
  bg: '#CFEFE6', shadow: '#3E7F6E',
};

function roundedRectPath(p, w, h, r, cx = 0, cy = 0) {
  const x = cx - w / 2, y = cy - h / 2;
  p.moveTo(x + r, y); p.lineTo(x + w - r, y); p.quadraticCurveTo(x + w, y, x + w, y + r);
  p.lineTo(x + w, y + h - r); p.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  p.lineTo(x + r, y + h); p.quadraticCurveTo(x, y + h, x, y + h - r);
  p.lineTo(x, y + r); p.quadraticCurveTo(x, y, x + r, y);
  return p;
}
// shape-координаты: (x, sy) → мир (x, −z) после rotateX(−π/2)
function trianglePath(p, side, cx, cyShape) {
  const R = side / Math.sqrt(3), r = side / (2 * Math.sqrt(3));
  const sx = -TRI_DIR; // сохраняем обход контура (CCW) при любом направлении вершины
  p.moveTo(cx, cyShape - TRI_DIR * R); p.lineTo(cx + sx * side / 2, cyShape + TRI_DIR * r); p.lineTo(cx - sx * side / 2, cyShape + TRI_DIR * r); p.closePath();
  return p;
}
function circlePath(p, rad, cx, cy) { // явный многоугольник (absarc даёт шов-«засечку» в точке старта)
  const n = 96; p.moveTo(cx + rad, cy);
  for (let i = 1; i < n; i++) p.lineTo(cx + rad * Math.cos(2 * Math.PI * i / n), cy + rad * Math.sin(2 * Math.PI * i / n));
  p.closePath(); return p; }
function squarePath(p, s, cx, cy) { return roundedRectPath(p, s, s, 0.02, cx, cy); }

// кольцо-кант: внешний контур = отверстие + 0.06, внутренний = номинальное отверстие
function rimGeometry(kind) {
  const sh = new THREE.Shape(), hole = new THREE.Path();
  const cy = -0.45;
  if (kind === 'cir') { circlePath(sh, 0.46, -1.35, cy); circlePath(hole, 0.40, -1.35, cy); }
  if (kind === 'tri') { trianglePath(sh, TRI_SIDE + 2 * 0.06 * Math.sqrt(3), 0, cy); trianglePath(hole, TRI_SIDE, 0, cy); }
  if (kind === 'sq') { squarePath(sh, 1.18, 1.35, cy); squarePath(hole, 1.06, 1.35, cy); }
  sh.holes.push(hole);
  const g = new THREE.ExtrudeGeometry(sh, { depth: 0.30, bevelEnabled: false, curveSegments: 48 });
  g.rotateX(-Math.PI / 2); g.translate(0, 0.92, 0); // y 0.92 … 1.22 (закрывает торец крышки снизу)
  return g;
}
function radialTexture(size = 128) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const x = c.getContext('2d'); const g = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.45, 'rgba(255,255,255,0.75)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.NoColorSpace; return t;
}
function aoTexture() {
  const c = document.createElement('canvas'); c.width = 480; c.height = 300;
  const x = c.getContext('2d'); x.filter = 'blur(22px)'; x.fillStyle = '#fff';
  x.beginPath(); x.roundRect(50, 40, 380, 220, 30); x.fill();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.NoColorSpace; return t;
}

let S = null; // состояние сцены

export function init(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.3; // §2.2: передняя грань на f30 ≈ #FF8A2A ±10% (при 1.0 было −20%)
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = true;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COL.bg);
  scene.fog = new THREE.Fog(COL.bg, 16, 34);

  const camera = new THREE.PerspectiveCamera(41, W / H, 0.5, 60);

  // свет (§2.4)
  const key = new THREE.DirectionalLight('#FFF4E5', 2.6);
  key.position.set(-3, 10, 4); key.target.position.set(0, 1.2, 0);
  key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 1, far: 25 });
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02;
  scene.add(key, key.target);
  scene.add(new THREE.HemisphereLight('#FFFFFF', '#BFE3D6', 1.3));
  const rim = new THREE.DirectionalLight('#E8FFF8', 0.7); rim.position.set(3, 4, -5); scene.add(rim);

  // пол + AO под сортером
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60),
    new THREE.MeshStandardMaterial({ color: COL.bg, roughness: 0.95, metalness: 0 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const ao = new THREE.Mesh(new THREE.PlaneGeometry(4.8 * 1.26, 3.0 * 1.36),
    new THREE.MeshBasicMaterial({ color: COL.shadow, map: aoTexture(), transparent: true, opacity: 0.25, depthWrite: false }));
  ao.rotation.x = -Math.PI / 2; ao.position.y = 0.004; scene.add(ao);

  // корпус сортера: рамка-стенки (ExtrudeGeometry) + тёмная внутренность
  const sorterMat = new THREE.MeshStandardMaterial({ color: COL.sorter, roughness: 0.7, metalness: 0 });
  const frameSh = roundedRectPath(new THREE.Shape(), 4.2, 2.4, 0.15);
  frameSh.holes.push(roundedRectPath(new THREE.Path(), 3.9, 2.1, 0.06));
  const frameG = new THREE.ExtrudeGeometry(frameSh, { depth: 1.0, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03, bevelSegments: 3, curveSegments: 12 });
  frameG.rotateX(-Math.PI / 2); frameG.translate(0, 0.03, 0); // y 0 … 1.06
  const frame = new THREE.Mesh(frameG, sorterMat); frame.castShadow = frame.receiveShadow = true; scene.add(frame);
  // внутренность: без прямого света (иначе солнечное пятно через отверстие «мелит» дыру),
  // вертикальный градиент #5A4E44 (верх) → темнее к дну
  const insideMat = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, toneMapped: false, fog: false });
  const insideG = new THREE.BoxGeometry(3.78, 0.98, 1.98, 1, 4, 1);
  { const top = new THREE.Color(COL.inside), bot = new THREE.Color('#2E2722'), c = new THREE.Color(), pa = insideG.attributes.position, cols = [];
    for (let i = 0; i < pa.count; i++) { c.copy(bot).lerp(top, (pa.getY(i) + 0.49) / 0.98); cols.push(c.r, c.g, c.b); }
    insideG.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3)); }
  const inside = new THREE.Mesh(insideG, insideMat);
  inside.position.y = 0.1 + 0.49; inside.receiveShadow = true; scene.add(inside);

  // крышка (подпрыгивает целиком с кантами и бликом)
  const lidGroup = new THREE.Group(); scene.add(lidGroup);
  const lidSh = roundedRectPath(new THREE.Shape(), 4.2, 2.4, 0.15);
  const holeC = circlePath(new THREE.Path(), 0.46 + 0.03, -1.35, -0.45);
  const holeT = trianglePath(new THREE.Path(), TRI_SIDE + 2 * 0.09 * Math.sqrt(3), 0, -0.45);
  const holeS = squarePath(new THREE.Path(), 1.18 + 0.06, 1.35, -0.45);
  lidSh.holes.push(holeC, holeT, holeS);
  const lidG = new THREE.ExtrudeGeometry(lidSh, { depth: 0.12, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03, bevelSegments: 3, curveSegments: 32 });
  lidG.rotateX(-Math.PI / 2); lidG.translate(0, 1.05, 0); // y 1.02 … 1.20
  const lid = new THREE.Mesh(lidG, sorterMat); lid.castShadow = lid.receiveShadow = true; lidGroup.add(lid);
  const rimMats = {};
  for (const [k, c] of [['cir', COL.cir], ['tri', COL.tri], ['sq', COL.sq]]) {
    rimMats[k] = new THREE.MeshStandardMaterial({ color: c, roughness: 0.45, metalness: 0, emissive: c, emissiveIntensity: 0, side: THREE.DoubleSide });
    const m = new THREE.Mesh(rimGeometry(k), rimMats[k]); m.castShadow = m.receiveShadow = true; lidGroup.add(m);
  }
  // блик-«солнце» по жёлтому канту (§4.3, шейдер)
  const stripMat = new THREE.ShaderMaterial({
    uniforms: { uC: { value: 0 }, uA: { value: 0 }, uDy: { value: 0 } },
    vertexShader: `varying vec3 vW; void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform float uC; uniform float uA; varying vec3 vW;
      void main(){ float s = (vW.x-1.35) + 0.35*(vW.z-0.45);
        float I = uA*(1.0 - smoothstep(0.02, 0.04, abs(s-uC)));
        gl_FragColor = vec4(vec3(I), 1.0); }`,
    blending: THREE.AdditiveBlending, depthWrite: false, transparent: true,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  });
  const strip = new THREE.Mesh(rimGeometry('sq'), stripMat); strip.visible = false; lidGroup.add(strip);

  // ---- кубик: риг §0.2
  const cubeRoot = new THREE.Group(), squash = new THREE.Group(), rot = new THREE.Group();
  rot.rotation.order = 'YXZ';
  cubeRoot.add(squash); squash.add(rot); scene.add(cubeRoot);
  const cubeMat = new THREE.MeshPhysicalMaterial({
    color: COL.cube, roughness: 0.55, metalness: 0, clearcoat: 0.15, clearcoatRoughness: 0.4,
    sheen: 0.3, sheenColor: new THREE.Color(COL.sheen), sheenRoughness: 0.6 });
  const body = new THREE.Mesh(new RoundedBoxGeometry(1, 1, 1, 6, 0.18), cubeMat);
  body.castShadow = false; body.receiveShadow = true; rot.add(body);
  const face = new THREE.Group(); rot.add(face);
  const whiteMat = new THREE.MeshStandardMaterial({ color: COL.white, roughness: 0.25, metalness: 0 });
  const pupilMat = new THREE.MeshStandardMaterial({ color: COL.pupil, roughness: 0.2, metalness: 0 });
  const glintMat = new THREE.MeshBasicMaterial({ color: COL.white });
  const browMat = new THREE.MeshStandardMaterial({ color: COL.brow, roughness: 0.6, metalness: 0 });
  const sphere = new THREE.SphereGeometry(1, 32, 20);
  const eyes = [];
  for (const sx of [-1, 1]) {
    const eye = new THREE.Group(); eye.position.set(0.19 * sx, 0.06, 0.5); face.add(eye);
    const white = new THREE.Mesh(sphere, whiteMat);
    const pupil = new THREE.Mesh(sphere, pupilMat);
    const glint = new THREE.Mesh(sphere, glintMat);
    eye.add(white, pupil, glint);
    const happy = new THREE.Mesh(new THREE.TorusGeometry(0.09 * EYE, 0.022 * EYE, 8, 16, Math.PI), pupilMat);
    happy.position.set(0.19 * sx, 0.04, 0.535); happy.visible = false; face.add(happy);
    const brow = new THREE.Mesh(new RoundedBoxGeometry(0.2 * EYE, 0.04 * EYE, 0.04 * EYE, 2, 0.02 * EYE), browMat);
    face.add(brow);
    eyes.push({ sx, eye, white, pupil, glint, happy, brow });
  }
  // контактная тень (§4.5)
  const shadowMat = new THREE.MeshBasicMaterial({ color: COL.shadow, map: radialTexture(), transparent: true, depthWrite: false, opacity: 0 });
  const cshadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), shadowMat);
  cshadow.rotation.x = -Math.PI / 2; scene.add(cshadow);
  // искорки (§4.4)
  const sparks = SPARKS.map((p) => {
    const m = new THREE.Mesh(sphere, new THREE.MeshBasicMaterial({ color: p[5], toneMapped: false }));
    m.visible = false; scene.add(m); return m;
  });

  S = { renderer, scene, camera, key, lidGroup, rimMats, strip, stripMat, cubeRoot, squash, rot, body, face,
    cubeMat, whiteMat, pupilMat, glintMat, browMat, eyes, cshadow, shadowMat, sparks, box: new THREE.Box3() };
  return S;
}

// ---------------------------------------------------------------- поза кубика
function poseRig(p) {
  S.cubeRoot.position.set(p.x, p.y, p.z);
  const sxz = 1 / Math.sqrt(p.sy);
  S.squash.scale.set(sxz, p.sy, sxz);
  S.rot.rotation.set((p.rx + p.flipX) * D2R, p.ry * D2R, (p.rz + p.flipZ) * D2R, 'YXZ');
  S.face.rotation.z = -p.flipZ * D2R;
  S.cubeRoot.updateMatrixWorld(true);
}
function basePose(f) {
  return { x: ch(X, f), z: ch(Z, f), sy: sy(f), rx: ch(RX, f), ry: ch(RY, f), rz: ch(RZ, f),
    flipZ: ch(FLIPZ, f), flipX: ch(FLIPX, f), y: 0 };
}
// ---------------------------------------------------------------- коллизии с крышкой
// Правило опоры §0.2, обобщённое: кубик поднимается ровно настолько, чтобы ни одна точка
// поверхности крышки/кантов (сетка + кромки отверстий) не оказалась внутри скруглённого куба.
// Наклонные позы (f37–55, 110–116, 258–272), кант-«ступенька» 0.02 и застревание углом в
// треугольнике (f150–182) решаются одной функцией; точки внутри отверстий — не опора.
let LIDPTS = null;
function contourPts(kind, off, step) {
  const pts = [];
  if (kind === 'cir') {
    const r = 0.40 + off, n = Math.ceil(2 * Math.PI * r / step);
    for (let i = 0; i < n; i++) { const a = 2 * Math.PI * i / n; pts.push([-1.35 + r * Math.cos(a), 0.45 + r * Math.sin(a)]); }
  } else {
    let V;
    if (kind === 'tri') { const sd = TRI_SIDE + 2 * off * Math.sqrt(3), R = sd / Math.sqrt(3), r = sd / (2 * Math.sqrt(3));
      V = [[0, 0.45 + TRI_DIR * R], [-sd / 2, 0.45 - TRI_DIR * r], [sd / 2, 0.45 - TRI_DIR * r]]; }
    else { const h = 0.53 + off; V = [[1.35 - h, 0.45 - h], [1.35 + h, 0.45 - h], [1.35 + h, 0.45 + h], [1.35 - h, 0.45 + h]]; }
    for (let i = 0; i < V.length; i++) {
      const a = V[i], b = V[(i + 1) % V.length], L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.ceil(L / step);
      for (let j = 0; j < n; j++) pts.push([a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n]);
    }
  }
  return pts;
}
function lidPoints() {
  if (LIDPTS) return LIDPTS;
  const P = [];
  for (let x = -2.1; x <= 2.1001; x += 0.03) for (let z = -1.2; z <= 1.2001; z += 0.03) {
    if (holeAt(x, z)) continue;
    P.push([x, rimAt(x, z) ? 1.22 : 1.2, z]);
  }
  for (const k of ['cir', 'tri', 'sq']) {
    for (const [x, z] of contourPts(k, 0, 0.01)) for (const y of [1.22, 1.20, 1.17, 1.14, 1.10, 1.06, 1.02, 0.97, 0.92]) P.push([x, y, z]);
    for (const [x, z] of contourPts(k, 0.06, 0.02)) P.push([x, 1.22, z]);
  }
  LIDPTS = P.map((a) => new THREE.Vector3(...a));
  return LIDPTS;
}
// SDF скруглённого куба (ребро 1, радиус 0.18) в локальных координатах тела
function sdBox(v) {
  const h = 0.5 - 0.18;
  const qx = Math.abs(v.x) - h, qy = Math.abs(v.y) - h, qz = Math.abs(v.z) - h;
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0), oz = Math.max(qz, 0);
  return Math.hypot(ox, oy, oz) + Math.min(Math.max(qx, qy, qz), 0) - 0.18;
}
const _inv = new THREE.Matrix4(), _v = new THREE.Vector3();
function minSdfAt(y, dy, near) {
  S.cubeRoot.position.y = y; S.cubeRoot.updateMatrixWorld(true);
  _inv.copy(S.body.matrixWorld).invert();
  let m = Infinity;
  for (const q of near) { _v.set(q.x, q.y + dy, q.z).applyMatrix4(_inv); const d = sdBox(_v); if (d < m) m = d; }
  return m;
}
function nearPts(p) {
  return lidPoints().filter((q) => Math.hypot(q.x - p.x, q.z - p.z) < 1.0);
}
// поднять кубик до касания (возвращает y ≥ y0)
function solveLift(p, f, y0) {
  poseRig({ ...p, y: y0 });
  const dy = ch(LIDDY, f), near = nearPts(p);
  if (!near.length || minSdfAt(y0, dy, near) >= 0) return y0;
  let lo = y0, hi = y0 + 0.05;
  while (minSdfAt(hi, dy, near) < 0 && hi < y0 + 3) { lo = hi; hi += 0.05; }
  for (let i = 0; i < 22; i++) { const mid = (lo + hi) / 2; if (minSdfAt(mid, dy, near) < 0) lo = mid; else hi = mid; }
  return hi;
}
// правило опоры: кубик опускается на крышку/кромки (стартуем с низа куба на 0.60)
function contactY(f) {
  const p = basePose(f); p.y = 0; poseRig(p);
  S.box.setFromObject(S.body, true);
  return solveLift(p, f, 0.60 - S.box.min.y);
}
function resolveY(spec, f) {
  if (spec === 'G') return 1.2 + 0.5 * sy(f);
  if (spec === 'C') return contactY(f);
  return spec;
}
function cubeY(f) {
  if (inFall(f)) return Math.max(fallY(f), 1.2 + 0.5 * sy(f));
  const i = segIndex(Y, f), k = Y[i], n = Y[i + 1], it = k[2];
  if (it === 'G') return 1.2 + 0.5 * sy(f);
  if (it === 'C') return contactY(f) + ch(COFF, f);
  if (it && it.B !== undefined) {
    const u = (f - k[0]) / (n[0] - k[0]);
    return 1.2 + 4 * it.B * u * (1 - u) + 0.5 * sy(f);
  }
  const a = resolveY(k[1], k[0]);
  if (!n || it === 'H') return a;
  const b = resolveY(n[1], n[0]);
  const u = (f - k[0]) / (n[0] - k[0]);
  return a + (b - a) * EASE[it](u);
}
export function cubePose(f) {
  const p = basePose(f);
  p.y = cubeY(f);
  // страховка от проникания в крышку до момента «идеально» (f330); провал в квадрат — без неё
  if (f < 330 || f >= 438) p.y = solveLift(p, f, p.y);
  return p;
}

// ---------------------------------------------------------------- тень §4.5
function shadowParams(f, p) {
  const t = f / FPS;
  let h = Math.max(0, p.y - 1.7), m = 1;
  if (f >= 78 && f <= 81) m = 0.6;
  if (f >= 150 && f <= 182) { h = 0; m = 0.6; }
  if (f >= 330 && f <= 342) { h = 0; m = 1 - (f - 330) / 12; }
  if (f >= 343 && f <= 407) m = 0;
  if (f >= 408 && f <= 437) {
    const u = t - 13.6;
    const h00 = 2 * u ** 3 - 3 * u ** 2 + 1, h10 = u ** 3 - 2 * u ** 2 + u, h01 = -2 * u ** 3 + 3 * u ** 2, h11 = u ** 3 - u ** 2;
    h = h00 * 13 + h10 * -8 + h01 * 6.20 * FALL_K + h11 * -1.615 * FALL_K;
  }
  // доработка QA: тень-твист f408–f11 — функция времени петли u (0…54), а не высоты:
  // темнее и крупнее; f449 → f0 непрерывно (u 41 → 42), на f12 = обычная тень касания
  if (f >= 408 || f < 12) {
    const u = f >= 408 ? f - 408 : f + 42, w = 1 - u / 54;
    const s = clamp(u / 6, 0, 1), fade = s * s * (3 - 2 * s);
    return { r: 0.55 * (1 - 0.7 * w * w), a: 0.45 * (1 - 0.75 * w * w * w) * fade, h };
  }
  const q = 1 - h / 14;
  return { r: 0.55 * clamp(q, 0.20, 1), a: 0.45 * clamp(q, 0.12, 1) * m, h };
}

// ---------------------------------------------------------------- цели взгляда
function gazePoint(name, f, p, camPos) {
  switch (name) {
    case 'HOME': return HOME.clone();
    case 'CIR': return CIR.clone();
    case 'TRI': return TRI.clone();
    case 'SQ': return SQ.clone();
    case 'CAM': return camPos.clone();
    case 'SELF': return new THREE.Vector3(p.x, 1.2, p.z + 0.7);
  }
}
function gazeTarget(f, p, camPos) {
  const i = segIndex(GAZE, f), k = GAZE[i], n = GAZE[i + 1];
  const a = gazePoint(k[1], f, p, camPos);
  if (f < GAZE[0][0] || !n || k[2] === 'H') return a;
  const u = (f - k[0]) / (n[0] - k[0]);
  return a.lerp(gazePoint(n[1], f, p, camPos), EASE[k[2]](u));
}

// ================================================================= применить кадр
const DARK = new THREE.Color(COL.inside);
const BASE = {};
export function setFrame(f) {
  f = ((Math.round(f) % NFRAMES) + NFRAMES) % NFRAMES;
  const cam = cameraPose(f);
  S.camera.position.copy(cam.pos); S.camera.up.set(0, 1, 0);
  S.camera.lookAt(cam.target); S.camera.rotateZ(cam.roll * D2R);
  S.camera.updateMatrixWorld(true);

  // сортер
  const dy = ch(LIDDY, f);
  S.lidGroup.position.y = dy;
  S.rimMats.cir.emissiveIntensity = ch(CIRE, f);
  S.rimMats.tri.emissiveIntensity = 0;
  S.rimMats.sq.emissiveIntensity = ch(SQE, f);
  S.strip.visible = f >= 237 && f < 246;
  S.stripMat.uniforms.uC.value = ch(STRIP_C, f);
  S.stripMat.uniforms.uA.value = ch(STRIP_A, f);

  // кубик
  const p = cubePose(f);
  poseRig(p);
  const top = p.y + 0.5 * p.sy;
  const k = clamp((1.22 - top) / 0.35, 0, 1);
  const visible = (f < 356 || f >= 438) && k < 1;
  S.cubeRoot.visible = visible;
  if (!BASE.cube) for (const n of ['cube', 'white', 'pupil', 'glint', 'brow']) BASE[n] = S[n + 'Mat'].color.clone();
  for (const n of ['cube', 'white', 'pupil', 'glint', 'brow']) S[n + 'Mat'].color.copy(BASE[n]).lerp(DARK, k);

  // глаза
  const lid = ch(LID, f), pS = ch(PUPIL, f), wS = ch(WHITE, f), gS = ch(GLINT, f);
  const brow = ch(BROW, f), browY = ch(BROWY, f);
  const happy = f >= 348 && f < 438;
  const tgt = gazeTarget(f, p, cam.pos);
  for (const e of S.eyes) {
    e.eye.visible = !happy; e.happy.visible = happy;
    e.eye.scale.set(1, 1 - 0.9 * lid, 1);
    e.white.scale.set(0.13 * EYE * wS, 0.13 * EYE * wS, 0.065 * EYE * wS);
    const front = 0.065 * EYE * wS;
    // смещение зрачка к проекции цели на грань (≤ 0.04)
    const local = S.face.worldToLocal(tgt.clone()).sub(e.eye.position);
    const len = local.length() || 1;
    const om = 0.04 * EYE;
    let ox = om * local.x / len, oy = om * local.y / len;
    const ol = Math.hypot(ox, oy); if (ol > om) { ox *= om / ol; oy *= om / ol; }
    const pr = 0.075 * EYE * pS;
    e.pupil.scale.set(pr, pr, 0.03 * EYE);
    e.pupil.position.set(ox, oy, front - 0.02 * EYE);
    const gr = 0.025 * EYE * gS;
    e.glint.scale.set(gr, gr, 0.012 * EYE);
    e.glint.position.set(-0.035 + ox * 0.3, 0.042 + oy * 0.3, front + 0.012 * EYE);
    const isLeft = e.sx < 0;
    const ang = brow + (isLeft ? ch(BROWL_A, f) : 0);
    e.brow.position.set(0.2 * e.sx, 0.33 + EYE * (browY + (isLeft ? ch(BROWL_Y, f) : 0)), 0.5 + 0.02 * EYE);
    // внутренний конец вниз при «+»: правая бровь +θ, левая −θ
    e.brow.rotation.set(0, 0, (e.sx > 0 ? 1 : -1) * ang * D2R);
  }
  S.cubeRoot.updateMatrixWorld(true);

  // контактная тень
  const sp = shadowParams(f, p);
  S.cshadow.visible = sp.a > 0.0005;
  const onHome = f >= 408 && f < 438; // тень-твист: на HOME, кубик ещё скрыт (§4.5)
  S.cshadow.position.set(onHome ? HOME.x : p.x, 1.203 + dy, onHome ? HOME.z : p.z);
  S.cshadow.scale.set(2 * sp.r, 2 * sp.r, 1);
  S.shadowMat.opacity = sp.a;

  // искорки
  SPARKS.forEach((d, i) => {
    const m = S.sparks[i], age = f - d[0], life = d[6];
    if (age < 0 || age > life) { m.visible = false; return; }
    const tau = age / FPS;
    m.position.set(1.35 + d[1] + d[3][0] * tau, 1.25 + d[3][1] * tau - 4.5 * tau * tau, 0.45 + d[2] + d[3][2] * tau);
    let s = 1;
    if (age < 2) s = EASE.EO(age / 2);
    else if (age > 0.6 * life) s = 1 - EASE.EI((age - 0.6 * life) / (0.4 * life));
    m.scale.setScalar(Math.max(1e-4, d[4] * s));
    m.visible = s > 0.001;
  });
  return { f, pose: p, k, visible, lid, shadow: sp, cam };
}

export function render(f) {
  const st = setFrame(f);
  S.renderer.render(S.scene, S.camera);
  return st;
}

// ================================================================= самопроверки
const toPx = (v, cam) => { const q = v.clone().project(cam); return [ (q.x + 1) / 2 * W, (1 - q.y) / 2 * H ]; };
function cubeBoxPx() {
  S.box.setFromObject(S.body, true);
  const b = S.box, xs = [], ys = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) {
    const [px, py] = toPx(new THREE.Vector3(x, y, z), S.camera); xs.push(px); ys.push(py);
  }
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys), minY: b.min.y };
}
// кадрирование, видимость глаз
export function frameReport(f) {
  const st = setFrame(f);
  const xs = [], ys = [];
  for (const x of [-2.1, 2.1]) for (const y of [0, 1.2]) for (const z of [-1.2, 1.2]) {
    const [px, py] = toPx(new THREE.Vector3(x, y, z), S.camera); xs.push(px); ys.push(py);
  }
  const holes = { cir: toPx(CIR, S.camera), tri: toPx(TRI, S.camera), sq: toPx(SQ, S.camera),
    sqRight: toPx(new THREE.Vector3(1.35 + 0.59, 1.22, 0.45 + 0.59), S.camera) };
  const r = { f, sorter: { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }, holes,
    cubeVisible: st.visible, lid: +st.lid.toFixed(2), shadow: { r: +st.shadow.r.toFixed(3), a: +st.shadow.a.toFixed(3) },
    pose: Object.fromEntries(Object.entries(st.pose).map(([k, v]) => [k, +v.toFixed(3)])) };
  if (st.visible) {
    r.cube = cubeBoxPx();
    // лицо к камере: нормаль передней грани vs направление на камеру
    const n = new THREE.Vector3(0, 0, 1).applyQuaternion(S.rot.getWorldQuaternion(new THREE.Quaternion()));
    const c = S.cubeRoot.getWorldPosition(new THREE.Vector3());
    r.faceDot = +n.dot(S.camera.position.clone().sub(c).normalize()).toFixed(3);
    const ec = S.eyes.map((e) => toPx(e.eye.getWorldPosition(new THREE.Vector3()), S.camera).map((v) => Math.round(v)));
    r.eyesPx = ec;
  }
  return r;
}
// проникание в крышку: вершины тела ниже верха крышки вне отверстий
function inTri(x, z, side) {
  // треугольник: центр (0, 0.45), вершина по TRI_DIR
  const R = side / Math.sqrt(3), r = side / (2 * Math.sqrt(3));
  const ax = 0, az = 0.45 + TRI_DIR * R, bx = -side / 2, bz = 0.45 - TRI_DIR * r, cx = side / 2, cz = 0.45 - TRI_DIR * r;
  const s = (px, pz, qx, qz, wx, wz) => (px - wx) * (qz - wz) - (qx - wx) * (pz - wz);
  const d1 = s(x, z, ax, az, bx, bz), d2 = s(x, z, bx, bz, cx, cz), d3 = s(x, z, cx, cz, ax, az);
  const neg = d1 < 0 || d2 < 0 || d3 < 0, pos = d1 > 0 || d2 > 0 || d3 > 0;
  return !(neg && pos);
}
function holeAt(x, z) {
  if (Math.hypot(x + 1.35, z - 0.45) < 0.40) return 'cir';
  if (inTri(x, z, TRI_SIDE)) return 'tri';
  if (Math.abs(x - 1.35) < 0.53 && Math.abs(z - 0.45) < 0.53) return 'sq';
  return null;
}
function rimAt(x, z) {
  return Math.hypot(x + 1.35, z - 0.45) < 0.46 || inTri(x, z, TRI_SIDE + 2 * 0.06 * Math.sqrt(3)) ||
    (Math.abs(x - 1.35) < 0.59 && Math.abs(z - 0.45) < 0.59);
}
export function penetrationScan(f0 = 0, f1 = 449) {
  const out = [], v = new THREE.Vector3();
  const pos = S.body.geometry.attributes.position;
  for (let f = f0; f <= f1; f++) {
    const st = setFrame(f);
    if (!st.visible) continue;
    const dy = ch(LIDDY, f), near = nearPts(st.pose);
    const sdf = near.length ? minSdfAt(st.pose.y, dy, near) : 1;
    let lowest = Infinity, lowXZ = null;
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i); S.body.localToWorld(v);
      if (v.y < lowest) { lowest = v.y; lowXZ = [v.x, v.z]; }
    }
    out.push({ f, pen: +Math.max(0, -sdf).toFixed(4), y: +st.pose.y.toFixed(3), lowest: +lowest.toFixed(3),
      lowXZ: lowXZ.map((a) => +a.toFixed(3)), lowHole: holeAt(...lowXZ) });
  }
  return out;
}

// зонд для подбора: глубина застревания угла в треугольнике при заданной стороне и позе
export function probeStuck(side, rx, ry, rz, syv = 1, dir = 1) {
  TRI_SIDE = side; TRI_DIR = dir; LIDPTS = null;
  const p = { x: 0, z: 0, y: 0, sy: syv, rx, ry, rz, flipX: 0, flipZ: 0 };
  poseRig(p);
  const v = new THREE.Vector3(), pos = S.body.geometry.attributes.position; let lo = Infinity, lx = 0, lz = 0;
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i); S.body.localToWorld(v); if (v.y < lo) { lo = v.y; lx = v.x; lz = v.z; } }
  p.x = -lx; p.z = 0.45 - lz;
  const y = solveLift(p, 150, 0.60 - lo);
  poseRig({ ...p, y });
  let lo2 = Infinity; for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i); S.body.localToWorld(v); lo2 = Math.min(lo2, v.y); }
  const n = new THREE.Vector3(0, 0, 1).applyQuaternion(S.rot.getWorldQuaternion(new THREE.Quaternion()));
  const c = new THREE.Vector3(p.x, y, p.z);
  setFrame(150);
  const fd = n.dot(S.camera.position.clone().sub(c).normalize());
  return { side, rx, ry, rz, x: +p.x.toFixed(3), z: +p.z.toFixed(3), y: +y.toFixed(3), depth: +(1.22 - lo2).toFixed(3), faceDot: +fd.toFixed(2) };
}
export const getState = () => S;
