#!/usr/bin/env node
// Рендер кадров сцены в PNG 1080×1920 (headless Chromium + SwiftShader WebGL2, three.js локально).
// Использование:
//   node render.js --frames 0,12,78 [--out DIR]       список кадров
//   node render.js --range 0-449 [--out DIR]          диапазон
//   node render.js --report 0,12,78                   JSON: кадрирование/глаза/тень (без PNG)
//   node render.js --scan                             JSON: проверка проникания кубика в крышку
// По умолчанию --out = render/frames, имена f_%04d.png.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const HERE = __dirname;
const THREE_DIR = path.join(HERE, 'node_modules', 'three');
const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const parseList = (s) => s.split(',').flatMap((p) => {
  if (p.includes('-')) { const [a, b] = p.split('-').map(Number); return Array.from({ length: b - a + 1 }, (_, i) => a + i); }
  return [Number(p)];
});

const MIME = { '.js': 'text/javascript', '.html': 'text/html', '.json': 'application/json' };
function serve() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const u = decodeURIComponent(req.url.split('?')[0]);
      let file = null;
      if (u === '/' || u === '/index.html') file = path.join(HERE, 'index.html');
      else if (u.startsWith('/render/')) file = path.join(HERE, u.slice(8));
      else if (u.startsWith('/three/')) file = path.join(THREE_DIR, u.slice(7));
      if (!file || !file.startsWith(HERE) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv));
  });
}

(async () => {
  const srv = await serve();
  const port = srv.address().port;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error('[page]', m.text()); });
  page.on('pageerror', (e) => console.error('[pageerror]', e.message));
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.waitForFunction('window.ready === true', null, { timeout: 60000 });

  if (args.includes('--scan')) {
    const r = await page.evaluate(() => window.SC.penetrationScan(0, 449));
    console.log(JSON.stringify(r));
  } else if (opt('--report')) {
    const r = await page.evaluate((fr) => fr.map((f) => window.SC.frameReport(f)), parseList(opt('--report')));
    console.log(JSON.stringify(r, null, 1));
  } else {
    const frames = opt('--frames') ? parseList(opt('--frames')) : parseList(opt('--range') || '0-449');
    const out = path.resolve(opt('--out') || path.join(HERE, 'frames'));
    fs.mkdirSync(out, { recursive: true });
    const times = [];
    for (const f of frames) {
      const t0 = Date.now();
      const url = await page.evaluate((n) => window.renderFrame(n), f);
      fs.writeFileSync(path.join(out, `f_${String(f).padStart(4, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
      times.push(Date.now() - t0);
      console.log(`frame ${f}: ${times[times.length - 1]} ms`);
    }
    const avg = times.reduce((a, b) => a + b, 0) / times.length;
    console.log(`TIMING frames=${frames.length} avg_ms=${avg.toFixed(0)} first_ms=${times[0]} est_450_min=${(avg * 450 / 60000).toFixed(1)}`);
  }
  await browser.close();
  srv.close();
})().catch((e) => { console.error(e); process.exit(1); });
