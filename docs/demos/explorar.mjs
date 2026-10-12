// Pasada exploratoria de Consilio: capturas de cada pantalla antes de guionar.
//   DEMO_TOKEN=$(cat ~/.config/consilio-demo/key) node explorar.mjs   → /tmp/demo-explorar
import { chromium } from 'playwright-core';
import fs from 'node:fs';
const URL = process.env.DEMO_URL || 'https://consiliopre.medicinainteligente.ai/', KEY = process.env.DEMO_TOKEN || '';
const OUT = process.env.OUT || '/tmp/demo-explorar'; fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'es-UY', colorScheme: 'light' });
await ctx.addInitScript((k) => { try { localStorage.setItem('consilio_api_key', k); } catch {} }, KEY);
const page = await ctx.newPage();
page.on('dialog', (d) => d.dismiss());
const shot = (n, full = true) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: full });
const txt = async (sel) => (await page.locator(sel).innerText()).slice(0, 3000);
await page.goto(URL, { waitUntil: 'networkidle' });
await shot('00-inicio');
console.log('botones:', await page.locator('button:visible').allTextContents());

// 1 · ejemplo de interacciones
await page.click('#btn-ejemplo'); await page.waitForTimeout(4000);
await shot('01-ejemplo');
console.log('--- RESULTADOS EJEMPLO ---\n', await txt('#results'));

// 2 · duplicidad
await page.click('#clear'); await page.waitForTimeout(800);
for (const q of ['omeprazol', 'pantoprazol', 'paracetamol']) {
  await page.fill('#q', q); await page.waitForTimeout(1200);
  console.log(`sugerencias ${q}:`, (await page.locator('#suggestions').innerText()).slice(0, 300));
  await page.locator('#suggestions li, #suggestions [role=option], #suggestions > *').first().click(); await page.waitForTimeout(500);
}
await shot('02-chips');
await page.click('#check'); await page.waitForTimeout(4000);
await shot('02-duplicidad');
console.log('--- DUPLICIDAD ---\n', await txt('#results'));

// 3 · ejemplo con paciente
await page.click('#clear'); await page.waitForTimeout(800);
await page.click('#btn-ejemplo-paciente'); await page.waitForTimeout(5000);
await shot('03-paciente');
console.log('--- PACIENTE ---\n', await txt('#results'));
console.log('perfil:', (await page.locator('#cnt-perfil').innerText().catch(() => '')).slice(0, 200));

// 4 · datos, ayuda, idioma
await page.click('#btn-datos'); await page.waitForTimeout(2500); await shot('04-datos', false);
console.log('--- DATOS ---\n', await txt('#datos'));
await page.click('#btn-cerrar-datos'); await page.waitForTimeout(500);
await page.click('#btn-ayuda'); await page.waitForTimeout(1000); await shot('05-ayuda', false);
await page.click('#lang-switch button[data-lang=en]'); await page.waitForTimeout(1500); await shot('06-en', false);
await browser.close();
