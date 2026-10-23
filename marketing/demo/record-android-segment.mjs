// Records android-segment.html (phone clip + timed captions) as a 1280x800 video segment.
import { readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright-core';

const here = dirname(fileURLToPath(import.meta.url));
const marks = JSON.parse(readFileSync(join(here, 'raw', 'offline-marks.json'), 'utf8'));
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 },
  recordVideo: { dir: join(here, 'raw'), size: { width: 1280, height: 800 } } });
const page = await context.newPage();
const t0 = Date.now();
const url = pathToFileURL(join(here, 'android-segment.html'));
url.searchParams.set('marks', JSON.stringify(marks));
await page.goto(url.href);
await page.waitForFunction(() => document.getElementById('v').readyState >= 3);
await page.waitForTimeout(800);
const start = (Date.now() - t0) / 1000;
await page.evaluate(() => window.startClip());
await page.waitForFunction(() => document.getElementById('v').ended, null, { timeout: 120000 });
await page.waitForTimeout(4000);
const video = page.video();
await context.close();
await browser.close();
renameSync(await video.path(), join(here, 'raw', 'android-segment.webm'));
writeFileSync(join(here, 'raw', 'android-segment.json'), JSON.stringify({ start }));
console.log('android segment recorded, clip starts at', start.toFixed(2), 's');
