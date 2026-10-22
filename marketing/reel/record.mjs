// Record reel.html to MP4 (H.264 + AAC) with headless Chrome.
// Usage: node record.mjs [--lang en|hi] [--music 0..2] [--limit seconds] [--out file.mp4]
//   --lang   en (Rishi, English captions) or hi (Lekha, Hindi captions)    default en
//   --music  background music level: 0 = off, 1 = default, 2 = loudest  default 1
//   --limit  record only the first N seconds (writes reel-test.mp4)
// Drives the installed Google Chrome (channel: chrome), so no browser download is needed.
import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const dir = dirname(fileURLToPath(import.meta.url));
const A = `${dir}/assets`;
const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i > -1 ? process.argv[i + 1] : fallback; };
const LANG = arg('lang', 'en') === 'hi' ? 'hi' : 'en';
const MUSIC = Math.max(0, Math.min(2, Number(arg('music', 1))));
const LIMIT = Number(arg('limit', 0)) || 0;
const VO = LANG === 'hi' ? `${A}/hi` : A;
const dataUrl = (p, type) => `data:${type};base64,${readFileSync(p).toString('base64')}`;
const assets = {};
for (const f of readdirSync(A).filter((f) => f.endsWith('.png'))) assets[f.replace('.png', '')] = dataUrl(`${A}/${f}`, 'image/png');
assets.icon = dataUrl(`${dir}/../../frontend/icons/icon-512.png`, 'image/png');
const voice = [1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => ({ src: dataUrl(`${VO}/vo${i}.wav`, 'audio/wav'),
  duration: parseFloat(execSync(`afinfo "${VO}/vo${i}.wav" | awk '/estimated duration/{print $3}'`).toString()) }));
const out = arg('out', LIMIT ? `${dir}/reel-test.mp4` : `${dir}/utsav-reel${LANG === 'hi' ? '-hi' : ''}.mp4`);
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage({ viewport: { width: 540, height: 960 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto(`file://${dir}/reel.html`);
await page.evaluate(([a, v, lang, music]) => { window.ASSETS = a; window.VOICE = v; window.LANG = lang; window.MUSIC_LEVEL = music; }, [assets, voice, LANG, MUSIC]);
const res = await page.evaluate((l) => window.record(l), LIMIT);
writeFileSync(out, Buffer.from(res.b64, 'base64'));
console.log(`${out} | lang ${LANG} | music ${MUSIC} | ${res.mime} | ${res.total.toFixed(1)}s | log ${JSON.stringify(await page.evaluate(() => window.LOG))} | errors ${JSON.stringify(errors)}`);
await browser.close();
