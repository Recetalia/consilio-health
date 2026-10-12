// Videos demo de Consilio sobre PRE (consiliopre). Método de la skill demo-video:
// Playwright (playwright-core + Chrome instalado) + screencast CDP + ffmpeg.
//   cd docs/demos && npm i && DEMO_TOKEN=$(cat ~/.config/consilio-demo/key) node grabar.mjs [1 2 ...|todos]
// La API key de PRE va a localStorage (consilio_api_key): nunca aparece en pantalla ni en este archivo.
// Ningún video crea datos: Consilio no guarda recetas ni pacientes.
import { chromium } from 'playwright-core';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// ───────────── CONFIGURAR ─────────────
const URL = process.env.DEMO_URL || 'https://consiliopre.medicinainteligente.ai/';
const KEY = process.env.DEMO_TOKEN || '';          // secreto: nunca en el archivo ni en pantalla
const TOKEN_LS = process.env.DEMO_TOKEN_LS || 'consilio_api_key';  // clave de localStorage donde la app guarda el token ('' = no usa)
const OUT = process.env.DEMO_OUT || path.join(os.homedir(), 'Desktop/demo-consilio');
const W = 1440, H = 900;
const MARCA = {
  fondo: '#14213a',               // fondo de cartelas
  leyenda: 'rgba(20,33,58,.95)',  // fondo de leyendas
  acento: '#a15872',              // borde de leyenda, resaltado, anillo del click
  resalte: '#f3c6d6',             // <b> en leyendas y kicker de cartela
  logo: 'https://consiliopre.medicinainteligente.ai/ui/isotipo-blanco.svg',
  pie: 'Consilio · medicinainteligente.ai',
};
fs.mkdirSync(OUT, { recursive: true });

// ───────────────────────── capas de la demo (cursor, leyenda, cartela, resaltado) ─────────────────────────
function capas(MARCA) {
  const install = () => {
    if (document.getElementById('__demo_cursor')) return;
    const st = document.createElement('style');
    st.textContent = `
      #__demo_cursor{position:fixed;left:720px;top:450px;width:0;height:0;z-index:2147483647;pointer-events:none;
        transition:left .6s cubic-bezier(.4,0,.2,1),top .6s cubic-bezier(.4,0,.2,1)}
      #__demo_cursor svg{position:absolute;left:-3px;top:-2px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}
      #__demo_cursor .ring{position:absolute;left:-16px;top:-16px;width:32px;height:32px;border-radius:50%;
        background:rgba(161,88,114,.30);border:2px solid rgba(127,63,88,.7);opacity:0;transform:scale(.3)}
      #__demo_cursor .ring.on{animation:__demo_pulse .5s ease-out}
      @keyframes __demo_pulse{0%{opacity:.95;transform:scale(.3)}100%{opacity:0;transform:scale(1.6)}}
      #__demo_cap{position:fixed;left:50%;bottom:34px;transform:translate(-50%,12px);max-width:1120px;width:max-content;
        z-index:2147483646;pointer-events:none;opacity:0;transition:opacity .35s ease,transform .35s ease;
        background:${MARCA.leyenda};color:#fff;border-radius:14px;padding:16px 26px 17px;
        box-shadow:0 10px 30px rgba(20,33,58,.35);border-left:6px solid ${MARCA.acento};
        font:500 24px/1.38 Manrope,Inter,system-ui,sans-serif;letter-spacing:.005em}
      #__demo_cap.on{opacity:1;transform:translate(-50%,0)}
      #__demo_cap b{color:${MARCA.resalte};font-weight:700}
      #__demo_cap code{font:600 21px ui-monospace,Menlo,monospace;color:#ffd9e6;background:rgba(255,255,255,.09);
        padding:1px 7px;border-radius:6px}
      #__demo_card{position:fixed;inset:0;z-index:2147483645;background:${MARCA.fondo};color:#fff;display:flex;
        flex-direction:column;justify-content:center;padding:0 150px;opacity:0;pointer-events:none;transition:opacity .6s ease;
        font-family:Manrope,Inter,system-ui,sans-serif}
      #__demo_card.on{opacity:1}
      #__demo_card img{width:88px;margin-bottom:46px}
      #__demo_card .k{color:${MARCA.resalte};font-weight:700;font-size:22px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:18px}
      #__demo_card .t{font-size:58px;font-weight:700;line-height:1.12;max-width:1100px}
      #__demo_card .bar{width:96px;height:6px;background:${MARCA.acento};border-radius:3px;margin:34px 0 30px}
      #__demo_card .s{font-size:27px;line-height:1.5;color:#d7dceb;max-width:1050px}
      #__demo_card .p{position:absolute;bottom:56px;left:150px;font-size:20px;color:#9fa9c4}
      .__demo_hl{outline:4px solid ${MARCA.acento} !important;outline-offset:5px !important;border-radius:8px;
        box-shadow:0 0 0 12px rgba(161,88,114,.16) !important;transition:outline-color .3s}`;
    document.head.appendChild(st);
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = `<div class="ring"></div><svg width="22" height="28" viewBox="0 0 22 28">
      <path d="M2 2 L2 22 L7.2 17.2 L10.6 25 L14 23.6 L10.7 15.9 L17.6 15.9 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    document.body.appendChild(c);
    const cap = document.createElement('div'); cap.id = '__demo_cap'; document.body.appendChild(cap);
    const card = document.createElement('div'); card.id = '__demo_card'; document.body.appendChild(card);
    window.__cap = (html) => {
      if (!html) { cap.classList.remove('on'); return; }
      const poner = () => { cap.innerHTML = html; cap.classList.add('on'); };
      if (cap.classList.contains('on')) { cap.classList.remove('on'); setTimeout(poner, 380); } else poner();
    };
    window.__card = (k, t, s) => {
      card.innerHTML = (MARCA.logo ? `<img src="${MARCA.logo}" alt="">` : "") + `<div class="k">${k}</div><div class="t">${t}</div>` +
        `<div class="bar"></div><div class="s">${s || ''}</div><div class="p">${MARCA.pie}</div>`;
      card.classList.add('on'); c.style.visibility = 'hidden';
    };
    window.__uncard = () => { card.classList.remove('on'); c.style.visibility = 'visible'; };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
}

// ───────────────────────── grabación ─────────────────────────
async function grabar(nombre, guion, url = URL) {
  const RAW = path.join(os.tmpdir(), 'demo-raw-' + nombre);
  fs.rmSync(RAW, { recursive: true, force: true }); fs.mkdirSync(RAW, { recursive: true });
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true,
    args: ['--hide-scrollbars', '--font-render-hinting=none'],
  });
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, colorScheme: 'light', locale: 'es-UY' });
  if (TOKEN_LS && KEY) await ctx.addInitScript(([c, k]) => { try { localStorage.setItem(c, k); } catch {} }, [TOKEN_LS, KEY]);
  await ctx.addInitScript(capas, MARCA);
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new globalThis.URL(URL).origin });
  const page = await ctx.newPage();
  page.setDefaultTimeout(60000);
  page.on('dialog', (d) => d.dismiss());

  // Screencast por página; sólo cuentan los cuadros de la página activa (para el PDF que abre otra pestaña).
  const frames = []; let n = 0; let activa = page; let grabando = false; let cdpPagina = null;
  async function filmar(p) {
    const cdp = await ctx.newCDPSession(p);
    cdp.on('Page.screencastFrame', async (f) => {
      if (grabando && activa === p) {
        const file = path.join(RAW, `f${String(++n).padStart(6, '0')}.jpg`);
        fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
        frames.push({ file, ts: f.metadata.timestamp });
      }
      try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch {}
    });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 95, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
    return cdp;
  }

  const wait = (ms) => page.waitForTimeout(ms);
  async function scrollToY(y, ms = 900, p = page) {
    await p.evaluate(([y, ms]) => new Promise((res) => {
      const max = document.documentElement.scrollHeight - innerHeight;
      const from = scrollY, to = Math.max(0, Math.min(max, y)), t0 = performance.now();
      if (Math.abs(to - from) < 2) return res();
      const step = (t) => {
        const q = Math.min(1, (t - t0) / ms), e = q < .5 ? 2 * q * q : 1 - Math.pow(-2 * q + 2, 2) / 2;
        scrollTo(0, from + (to - from) * e); q < 1 ? requestAnimationFrame(step) : res();
      };
      requestAnimationFrame(step);
    }), [y, ms]);
    await p.waitForTimeout(150);
  }
  const L = (x) => (typeof x === 'string' ? page.locator(x).first() : x);
  async function scrollToEl(loc, offset = 140, ms = 1000) {
    const y = await L(loc).evaluate((el, off) => el.getBoundingClientRect().top + scrollY - off, offset);
    await scrollToY(y, ms);
  }
  async function ensureVisible(loc) {
    const r = await loc.boundingBox(); if (!r) return;
    if (r.y < 90 || r.y + r.height > H - 170) {
      const cur = await page.evaluate(() => scrollY);
      await scrollToY(cur + r.y - H * 0.35, 750);
    }
  }
  async function cursorA(x, y) {
    await page.evaluate(([x, y]) => { const c = document.getElementById('__demo_cursor'); c.style.left = x + 'px'; c.style.top = y + 'px'; }, [x, y]);
    await page.mouse.move(x, y, { steps: 10 });
    await wait(650);
  }
  async function moveTo(loc, { dx = 0.5, dy = 0.5 } = {}) {
    loc = L(loc); await ensureVisible(loc);
    const r = await loc.boundingBox();
    const x = Math.round(r.x + r.width * dx), y = Math.round(r.y + r.height * dy);
    await cursorA(x, y); return { x, y };
  }
  async function pulse() {
    await page.evaluate(() => { const r = document.querySelector('#__demo_cursor .ring'); r.classList.remove('on'); void r.offsetWidth; r.classList.add('on'); });
    await wait(200);
  }
  async function click(loc, opts) {
    const { x, y } = await moveTo(loc, opts); await pulse();
    await page.mouse.click(x, y); await wait(400);
  }
  async function escribir(loc, texto, delay = 55) {
    loc = L(loc); await click(loc); await loc.fill(''); await wait(150);
    await page.keyboard.type(texto, { delay }); await wait(250);
  }
  // Leyenda: tiempo de lectura proporcional al largo (mín. 2,8 s).
  async function cap(html, extra = 0) {
    await page.evaluate((h) => window.__cap(h), html);
    const largo = html.replace(/<[^>]+>/g, '').length;
    await wait(Math.max(2800, largo * 62) + extra);
  }
  const sinCap = () => page.evaluate(() => window.__cap(''));
  const hl = (loc) => L(loc).evaluate((el) => el.classList.add('__demo_hl'));
  const sinHl = () => page.evaluate(() => document.querySelectorAll('.__demo_hl').forEach((e) => e.classList.remove('__demo_hl')));
  // La grabación arranca con la primera cartela ya puesta (sin fundido): el video abre en la
  // diapositiva y no en la pantalla de la app.
  let t0 = null;
  async function arrancar() {
    if (grabando) return;
    grabando = true; t0 = Date.now() / 1000;
    // Fuerza un cuadro nuevo: el screencast sólo emite cuando algo se repinta.
    await page.evaluate(() => { const c = document.getElementById('__demo_card'); c.style.backgroundColor = '#14213b';
      requestAnimationFrame(() => requestAnimationFrame(() => { c.style.backgroundColor = ''; })); });
  }
  async function cartela(k, t, s, ms = 5200) {
    if (!grabando) {
      await page.evaluate(([k, t, s]) => { const c = document.getElementById('__demo_card'); c.style.transition = 'none';
        window.__card(k, t, s); void c.offsetWidth; c.style.transition = ''; }, [k, t, s]);
      await wait(400);
      await arrancar();
    } else {
      await page.evaluate(([k, t, s]) => window.__card(k, t, s), [k, t, s]);
    }
    await wait(ms);
  }
  const sinCartela = async () => { await page.evaluate(() => window.__uncard()); await wait(700); };
  // Desplaza un <pre> (suave) hasta la línea que contiene `aguja`.
  async function scrollPre(loc, aguja, ms = 1400) {
    await L(loc).evaluate((pre, [aguja, ms]) => new Promise((res) => {
      const lineas = pre.textContent.split('\n');
      const i = Math.max(0, lineas.findIndex((l) => l.includes(aguja)));
      const lh = parseFloat(getComputedStyle(pre).lineHeight) || 18;
      const to = Math.max(0, i * lh - pre.clientHeight * 0.35), from = pre.scrollTop, t0 = performance.now();
      const step = (t) => {
        const q = Math.min(1, (t - t0) / ms), e = q < .5 ? 2 * q * q : 1 - Math.pow(-2 * q + 2, 2) / 2;
        pre.scrollTop = from + (to - from) * e; q < 1 ? requestAnimationFrame(step) : res();
      };
      requestAnimationFrame(step);
    }), [aguja, ms]);
    await wait(300);
  }
  // Abre el PDF (otra pestaña), lo muestra y vuelve.
  async function verPdf(loc, ms = 6500) {
    loc = L(loc); const { x, y } = await moveTo(loc); await pulse();
    const [pop] = await Promise.all([ctx.waitForEvent('page'), page.mouse.click(x, y)]);
    const cdpPop = await filmar(pop);
    activa = pop; await pop.bringToFront();
    await pop.waitForLoadState('load').catch(() => {});
    await pop.waitForTimeout(ms);
    activa = page; await cdpPop.send('Page.stopScreencast').catch(() => {});
    await pop.close(); await page.bringToFront();
    // Al cerrar la otra pestaña el screencast queda en 1440×813: se reponen las métricas y se reinicia.
    await cdpPagina.send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    await cdpPagina.send('Page.stopScreencast');
    await cdpPagina.send('Page.startScreencast', { format: 'jpeg', quality: 95, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
    await cursorA(x + 3, y + 2); // fuerza un cuadro nuevo de la página
  }

  const h = { page, ctx, wait, scrollToY, scrollToEl, moveTo, cursorA, click, escribir, cap, sinCap, hl, sinHl,
              cartela, sinCartela, scrollPre, verPdf, L };

  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForSelector('#__demo_cursor', { state: 'attached' });
  const cdp = await filmar(page); cdpPagina = cdp;
  await wait(300);
  await guion(h);
  await arrancar(); // por si un guion no abre con cartela
  const t1 = Date.now() / 1000;
  grabando = false;
  await cdp.send('Page.stopScreencast').catch(() => {});
  await ctx.close(); await browser.close();

  // Concat: cada cuadro dura hasta el siguiente; el primero arranca en t0.
  const fr = frames.filter((f) => f.ts <= t1);
  let list = '';
  fr.forEach((f, i) => {
    const desde = i === 0 ? Math.min(f.ts, t0) : f.ts;
    const hasta = i + 1 < fr.length ? fr[i + 1].ts : t1;
    list += `file '${f.file}'\nduration ${Math.max(0.001, hasta - desde).toFixed(4)}\n`;
  });
  list += `file '${fr[fr.length - 1].file}'\n`;
  const listFile = path.join(RAW, 'frames.txt'); fs.writeFileSync(listFile, list);
  const mp4 = path.join(OUT, nombre + '.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', listFile,
    '-vf', `fps=30,scale=${W}:${H}:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-r', '30',
    '-movflags', '+faststart', '-an', mp4], { stdio: 'inherit' });
  fs.rmSync(RAW, { recursive: true, force: true });
  console.log(`listo ${mp4} (${(t1 - t0).toFixed(1)} s, ${fr.length} cuadros)`);
}

// ───────────── GUIONES (uno por video) ─────────────
// h = { page, ctx, wait, click, escribir, moveTo, cursorA, scrollToY, scrollToEl, cap, sinCap,
//       hl, sinHl, cartela, sinCartela, scrollPre, verPdf, L }
// Cada leyenda se verificó contra PRE (UI y API) el 2026-10-09.
const CIERRE = ['Consilio', 'Seguridad en la prescripción',
  'Escribinos a <b>hello@medicinainteligente.ai</b>'];

const tarjeta = (h, texto) => h.page.locator('#results article.finding', { hasText: texto }).first();

async function agregarMed(h, q, delay = 75) {
  const { page, escribir, click, wait } = h;
  await escribir('#q', q, delay);
  await page.waitForSelector('#suggestions li', { state: 'visible' });
  await wait(500);
  await click('#suggestions li');
  await wait(300);
}

async function consultar(h) {
  const { page, click, wait } = h;
  await click('#check');
  await page.locator('#results article.finding:visible, #results .empty-state:visible').first().waitFor({ timeout: 60000 });
  await wait(900);
}

async function mostrarTarjeta(h, texto, leyenda, extra = 0, offset = 220) {
  const t = tarjeta(h, texto);
  await h.scrollToEl(t, offset, 900);
  await h.hl(t);
  await h.cap(leyenda, extra);
  await h.sinHl();
}

// ───────────── 1 · Interacciones ─────────────
async function video1(h) {
  const { page, cap, sinCap, hl, sinHl, cartela, sinCartela, wait, scrollToY } = h;
  await cartela('Demo 1 · Interacciones', 'Interacciones entre los medicamentos de una receta',
    'Escribís los principios activos y Consilio cruza todas las combinaciones: gravedad, qué hacer y de qué fuente sale cada alerta.');
  await sinCartela();
  await cap('Escribimos el principio activo. El autocompletado lo reconoce en castellano y muestra su identificador <b>RxCUI</b>.', -1200);
  await h.escribir('#q', 'warfarina', 90);
  await page.waitForSelector('#suggestions li', { state: 'visible' });
  await hl('#suggestions');
  await wait(2200);
  await sinHl();
  await h.click('#suggestions li');
  await cap('Agregamos ibuprofeno, simvastatina y claritromicina.', -1400);
  for (const m of ['ibuprofeno', 'simvastatina', 'claritromicina']) await agregarMed(h, m, 65);
  await hl('#resumen-cruce');
  await cap('Con cuatro medicamentos son <b>6 combinaciones</b>: Consilio las cruza todas entre sí.');
  await sinHl();
  await consultar(h);
  await mostrarTarjeta(h, 'Warfarina + Ibuprofeno',
    '<b>Warfarina + ibuprofeno: grave.</b> Explica el riesgo, dice <b>qué hacer</b> y cita la fuente: el texto de la AEMPS, la gravedad de DDInter.', 800);
  await mostrarTarjeta(h, 'Simvastatina + Claritromicina',
    '<b>Simvastatina + claritromicina:</b> asociación contraindicada, por riesgo de miopatía y rabdomiólisis.', 300);
  await mostrarTarjeta(h, 'Warfarina + Claritromicina',
    'Si la fuente registra el par pero no explica el mecanismo, Consilio lo dice. <b>No inventa la explicación.</b>', 300);
  await mostrarTarjeta(h, 'Ibuprofeno + Simvastatina',
    '<b>Revisar:</b> la interacción está registrada pero sin gravedad asignada. Hay que mirar el prospecto.', 200);
  await sinCap();
  await scrollToY(0, 1000);
  await cap('Todo en segundos y sin guardar la receta: Consilio <b>no almacena</b> recetas ni datos de pacientes.', 200);
  await sinCap();
  await cartela(...CIERRE, 4500);
}

// ───────────── 2 · Duplicidad terapéutica ─────────────
async function video2(h) {
  const { page, click, cap, sinCap, hl, sinHl, cartela, sinCartela, wait, scrollToY } = h;
  await cartela('Demo 2 · Duplicidad terapéutica', 'Dos medicamentos que hacen lo mismo',
    'Consilio detecta dos fármacos de la misma clase terapéutica (ATC, AEMPS). Y cuando la combinación es tratamiento estándar, no alerta y explica por qué.');
  await sinCartela();
  await cap('Un paciente con <b>omeprazol</b> y además <b>pantoprazol</b>: dos protectores gástricos.', -1000);
  for (const m of ['omeprazol', 'pantoprazol']) await agregarMed(h, m);
  await consultar(h);
  await mostrarTarjeta(h, 'Duplicidad de clase',
    'Los dos son <b>inhibidores de la bomba de protones</b> (grupo ATC <code>A02BC</code>). El máximo sin alerta es uno.', 600);
  await sinCap();
  await scrollToY(0, 900);
  await click('#clear'); await wait(700);
  await cap('Ahora <b>hidrocortisona + fludrocortisona</b>, el tratamiento de la insuficiencia suprarrenal (Addison).', -800);
  await agregarMed(h, 'hidrocortisona');
  await agregarMed(h, 'fludro');
  await consultar(h);
  const sup = page.locator('details.suprimidas').first();
  await h.scrollToEl(sup, 220, 900);
  await click(sup.locator('summary')); await wait(700);
  await hl(sup);
  await cap('Son de la misma clase, pero <b>no se alerta</b>: es una excepción curada. Igual se muestra, con el motivo y la referencia.', 900);
  await sinHl();
  await mostrarTarjeta(h, 'Mineralocorticoides',
    'Y declara su estado: la excepción está <b>pendiente de validación farmacéutica</b>.', 0);
  const vacio = page.locator('#results .empty-state', { hasText: 'sin interacción documentada' }).first();
  await hl(vacio);
  await cap('El silencio nunca significa «sin riesgo»: que no haya una interacción documentada <b>no quiere decir que no exista</b>.', 600);
  await sinHl(); await sinCap();
  await cartela(...CIERRE, 4500);
}

// ───────────── 3 · Perfil del paciente (ejemplo) ─────────────
async function video3(h) {
  const { page, click, cap, sinCap, hl, sinHl, cartela, sinCartela, wait, scrollToY, scrollToEl } = h;
  await cartela('Demo 3 · Perfil del paciente', 'Los medicamentos contra el paciente',
    'Edad, sexo, embarazo, función renal y hepática, alergias y patologías CIE-10. Consilio cruza cada medicamento contra ese perfil.');
  await sinCartela();
  await hl('#btn-ejemplo-paciente');
  await cap('«Ejemplo con paciente»: una mujer de <b>78 años</b> con enfermedad renal crónica, una alergia y cinco medicamentos.', -600);
  await sinHl();
  await click('#btn-ejemplo-paciente');
  await page.waitForSelector('#results article.finding', { state: 'visible', timeout: 60000 });
  await wait(800);
  await scrollToY(0, 900);
  await hl('#aviso-edad');
  await cap('Desde los 65 años se aplican los <b>criterios de prescripción en el anciano</b> de la AEMPS.');
  await sinHl();
  await hl(page.locator('#renal').locator('xpath=..'));
  await cap('Función renal: <b>alterada, grave</b>.', -800);
  await sinHl();
  await scrollToEl('#chips-alergias', 300, 800);
  await hl('#chips-alergias');
  await cap('Alergia declarada: <b>amoxicilina</b>. Se compara el fármaco exacto; no infiere reactividad cruzada por clase.', 200);
  await sinHl();
  await hl('#chips-patologias');
  await cap('Patologías por código <b>CIE-10</b>: <code>N18.5</code>, enfermedad renal crónica estadio 5.');
  await sinHl();
  await hl('#chips');
  await cap('Y los cinco medicamentos: metformina, diazepam, lorazepam, amoxicilina e ibuprofeno.', -400);
  await sinHl();
  await mostrarTarjeta(h, 'Alergia declarada',
    'A la derecha, lo que cruza con el paciente. La amoxicilina está recetada y es <b>alérgica</b> a ella.', 300, 260);
  await mostrarTarjeta(h, 'Insuficiencia renal',
    '<b>Metformina, contraindicada</b> en insuficiencia renal (fuente MED-RT), a partir del código N18.5.', 300, 260);
  await mostrarTarjeta(h, 'Pacientes tratados con fármacos que aumentan el riesgo de caídas',
    'Diazepam en mayor de 65: <b>verificar</b> si aplica. Dice en qué situación y qué hacer, con el criterio de la AEMPS.', 800, 200);
  await mostrarTarjeta(h, 'Derivados de la benzodiazepina',
    'Y del lado de los medicamentos, la duplicidad: <b>diazepam + lorazepam</b>, dos benzodiacepinas.', 300, 300);
  await sinCap();
  await cartela(...CIERRE, 4500);
}

// ───────────── 4 · Embarazo y función hepática ─────────────
async function video4(h) {
  const { page, click, cap, sinCap, hl, sinHl, cartela, sinCartela, wait, moveTo, escribir } = h;
  await cartela('Demo 4 · Embarazo y función hepática', 'Un perfil cargado a mano',
    'Cada dato del paciente suma controles. Acá: una paciente embarazada y con la función hepática alterada.');
  await sinCartela();
  await cap('Tres medicamentos: <b>enalapril</b>, <b>warfarina</b> y <b>paracetamol</b>.', -1200);
  for (const m of ['enalapril', 'warfarina', 'paracetamol']) await agregarMed(h, m, 65);
  await cap('En el perfil: mujer de 31 años, embarazada de 20 semanas.', -1200);
  await moveTo('#sexo'); await page.selectOption('#sexo', 'F'); await wait(500);
  await escribir('#edad', '31', 120);
  await click('#embarazo'); await wait(400);
  await moveTo('#semanas'); await page.selectOption('#semanas', { label: 'semana 20' }); await wait(600);
  await hl('#gestacion');
  await cap('Embarazo y semana de gestación; también se puede marcar <b>lactancia</b>.', -400);
  await sinHl();
  await moveTo('#hepatica'); await page.selectOption('#hepatica', 'alterada'); await wait(500);
  await hl(page.locator('#hepatica').locator('xpath=..'));
  await cap('Y la función hepática, <b>alterada</b>.', -900);
  await sinHl();
  await consultar(h);
  await mostrarTarjeta(h, 'Embarazo', '<b>Enalapril, contraindicado en el embarazo</b> (fuente MED-RT).', 0, 260);
  const warf = page.locator('#results article.finding', { hasText: 'Warfarina' }).filter({ hasText: 'Embarazo' }).first();
  await h.scrollToEl(warf, 260, 800); await hl(warf);
  await cap('<b>Warfarina</b>, también contraindicada en el embarazo…', -600);
  await sinHl();
  const warfH = page.locator('#results article.finding', { hasText: 'Warfarina' }).filter({ hasText: 'Enfermedad hepática' }).first();
  await hl(warfH);
  await cap('…y en la enfermedad hepática, igual que el <b>paracetamol</b>.', -600);
  await sinHl();
  const parac = page.locator('#results article.finding', { hasText: 'Paracetamol' }).filter({ hasText: 'Enfermedad hepática' }).first();
  await hl(parac); await wait(1600); await sinHl();
  await mostrarTarjeta(h, 'Warfarina + Paracetamol',
    'Y entre ellos, la interacción <b>warfarina + paracetamol</b>, moderada según DDInter.', 0, 260);
  await sinCap();
  await cartela(...CIERRE, 4500);
}

// ───────────── 5 · Resultados y transparencia ─────────────
async function video5(h) {
  const { page, click, cap, sinCap, hl, sinHl, cartela, sinCartela, wait, scrollToY, scrollToEl, escribir, moveTo } = h;
  await cartela('Demo 5 · Resultados y transparencia', 'Filtrar, compartir y saber de dónde sale cada alerta',
    'Filtros por gravedad, fuente y texto; resumen para copiar o imprimir; y un panel que muestra cada fuente, su licencia y su fecha.');
  await sinCartela();
  await click('#btn-ejemplo');
  await page.waitForSelector('#results article.finding', { state: 'visible', timeout: 60000 });
  await wait(800);
  await scrollToEl('#filtros', 120, 1000);
  await hl('#f-sev-grupo'); await hl('#f-fuente-grupo');
  await cap('Arriba de los resultados, cuántas alertas hay de cada <b>gravedad</b> y de cada <b>fuente</b>.');
  await sinHl();
  await cap('Un click y quedan sólo las <b>graves</b>.', -1800);
  await click('#f-sev [data-sev="major"]'); await wait(2200);
  await click('#f-sev [data-sev="major"]'); await wait(600);
  await escribir('#f-texto', 'hemorragia', 110); await wait(900);
  await cap('O se busca por texto: «hemorragia» encuentra <b>warfarina + ibuprofeno</b>.', -300);
  await click('#f-reset'); await wait(700);
  await hl('#btn-copiar'); await hl('#btn-imprimir');
  await cap('El resumen se <b>copia</b> para pegarlo en la historia clínica, o se <b>imprime</b>.', -400);
  await sinHl();
  await click('#btn-copiar'); await wait(1800);
  await sinCap();
  await scrollToY(0, 900);
  await click('#btn-ayuda'); await wait(900);
  await hl('#ayuda');
  await cap('«¿Qué evalúa?» explica qué cruza, cómo leer la gravedad y qué <b>no</b> hace: no controla dosis y <b>no decide</b>.', 600);
  await sinHl();
  await click('#btn-ayuda'); await wait(500);
  await click('#btn-datos'); await wait(1200);
  await scrollToY(0, 700);
  await cap('<b>Transparencia</b>: de dónde sale cada alerta, con cifras vivas de la base.', -600);
  await hl('#datos-stats');
  await cap('Pares con interacción registrada, fármacos, clases de duplicidad, criterios en el anciano y alertas fármaco-patología.', 200);
  await sinHl();
  await scrollToEl('#datos-fuentes', 120, 1200);
  await hl('#datos-fuentes');
  await cap('Cada fuente con lo que aporta, su <b>licencia</b> y su <b>fecha de actualización</b>: DDInter, AEMPS, openFDA, MED-RT, RxNorm, DNMA.', 900);
  await sinHl();
  await scrollToEl('#datos-fuentes', -300, 1400);
  await wait(2500);
  await click('#btn-cerrar-datos'); await wait(700);
  await scrollToY(0, 800);
  await cap('Y la interfaz está en castellano y en <b>inglés</b>.', -900);
  await click('#lang-switch button[data-lang=en]'); await wait(1500);
  await scrollToEl('#results', 120, 1100);
  await wait(2500);
  await scrollToY(0, 800);
  await click('#lang-switch button[data-lang=es]'); await wait(800);
  await sinCap();
  await cartela(...CIERRE, 4500);
}

// ───────────── 6 · Extra: lo mismo por la API ─────────────
// Las salidas son respuestas reales de PRE (api/oN.txt) pasadas por el mismo jq que se ve en pantalla.
const API_DIR = path.join(path.dirname(new globalThis.URL(import.meta.url).pathname), 'api');
const salida = (n) => fs.readFileSync(path.join(API_DIR, `o${n}.txt`), 'utf8');
async function video6(h) {
  const { page, cap, sinCap, cartela, sinCartela, wait } = h;
  const t = (cmd, ms) => page.evaluate(([c, m]) => window.__tipear(c, m), [cmd, ms || 26]);
  const o = (txt, ms) => page.evaluate(([x, m]) => window.__salida(x, m), [txt, ms || 40]);
  const com = (x) => page.evaluate((y) => window.__comentario(y), x);
  const blanco = () => page.evaluate(() => window.__blanco());
  await page.evaluate(() => { document.getElementById('__demo_cursor').style.display = 'none'; });
  await cartela('Extra · Para integradores', 'Lo mismo, por la API',
    'Todo lo que se vio en la web es una llamada HTTP con JSON. Así lo integra tu sistema de receta electrónica, con su API key.');
  await sinCartela();
  await com('# CONSILIO_API_KEY tiene la API key de tu institución (no se muestra)');
  await t('export CONSILIO=https://consiliopre.medicinainteligente.ai');
  await blanco();
  await cap('<b>1 · Interacciones</b>: la lista de principios activos de la receta.', -1500);
  await com('# 1. Interacciones entre los medicamentos de la receta');
  await t('curl -s -X POST "$CONSILIO/interactions" -H "X-API-Key: $CONSILIO_API_KEY" \\\n-H "Content-Type: application/json" \\\n-d \'{"drugs":["warfarina","ibuprofeno","simvastatina","claritromicina"]}\' \\\n| jq -c \'.interactions[] | {par: "\\(.drug_a) + \\(.drug_b)", severity, source}\'');
  await wait(800); await o(salida(1), 90);
  await cap('Cada par con su gravedad (<code>major</code>, <code>minor</code>, <code>unknown</code> = revisar) y su fuente.', 300);
  await sinCap();
  await blanco();
  await com('# La misma llamada devuelve las duplicidades');
  await t('curl -s -X POST "$CONSILIO/interactions" -H "X-API-Key: $CONSILIO_API_KEY" \\\n-H "Content-Type: application/json" -d \'{"drugs":["omeprazol","pantoprazol"]}\' \\\n| jq \'.duplicities[] | {layer, class_id, class_desc, products}\'');
  await wait(800); await o(salida(2), 60);
  await cap('<b>Duplicidad de clase</b>: grupo ATC <code>A02BC</code>, inhibidores de la bomba de protones.', 200);
  await sinCap();
  await page.evaluate(() => window.__limpiar());
  await cap('<b>2 · Contra el paciente</b>: los medicamentos más el perfil.', -1500);
  await com('# 2. Medicamentos contra el perfil del paciente');
  await t('curl -s -X POST "$CONSILIO/contraindications" -H "X-API-Key: $CONSILIO_API_KEY" \\\n-H "Content-Type: application/json" \\\n-d \'{"drugs":["metformina","amoxicilina","diazepam"],\n"profile":{"sexo":"F","edad":78,"funcion_renal":"grave","alergias":["amoxicilina"],"patologias_mesh":[]}}\' \\\n| jq \'{contraindicado: [.contraindications[] | "\\(.drug_input) — \\(.condition) (\\(.source))"],\nalergia: [.allergies[] | .drug_input], anciano: [.geriatric[] | .drug]}\'');
  await wait(800); await o(salida(3), 70);
  await cap('Contraindicación por insuficiencia renal, la alergia y el criterio en el anciano. Cada uno en su lista.', 300);
  await sinCap();
  await blanco();
  await com('# El autocompletado de la web es esta búsqueda');
  await t('curl -s "$CONSILIO/drugs/search?q=amoxi&limit=3" -H "X-API-Key: $CONSILIO_API_KEY" \\\n| jq -c \'.results[] | {name_es, name, rxcui}\'');
  await wait(800); await o(salida(4), 90);
  await cap('Nombre en castellano, nombre canónico y <b>RxCUI</b>. La documentación completa está en <code>/docs</code> (OpenAPI).', 600);
  await sinCap();
  await cartela(...CIERRE, 4500);
}

const VIDEOS = {
  1: ['1-interacciones', video1],
  2: ['2-duplicidad-terapeutica', video2],
  3: ['3-perfil-del-paciente', video3],
  4: ['4-embarazo-y-funcion-hepatica', video4],
  5: ['5-resultados-y-transparencia', video5],
  6: ['6-extra-api-para-integradores', video6, 'file://' + path.join(API_DIR, 'terminal.html')],
};
const cuales = process.argv[2] === 'todos' || !process.argv[2] ? Object.keys(VIDEOS) : process.argv.slice(2);
for (const k of cuales) { const [nombre, fn, url] = VIDEOS[k]; await grabar(nombre, fn, url); }
