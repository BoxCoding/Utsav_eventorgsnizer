// Automated WCAG 2.1 AA audit (axe-core) of every view and plan tab, in real Chrome.
// Run against a local server: uvicorn backend.main:app --port 8101, then npm run test:a11y
// (BASE_URL overrides the address). Exits 1 if any page has a violation.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';

const BASE = process.env.BASE_URL || 'http://localhost:8101';
const axe = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

const browser = await chromium.launch({ channel: 'chrome', headless: true });
// bypassCSP only lets the audit script in; the app's own CSP stays as served.
const context = await browser.newContext({ bypassCSP: true, reducedMotion: 'reduce' });
const page = await context.newPage();
const failures = [];

async function audit(name, width = 1280) {
  await page.setViewportSize({ width, height: 900 });
  await page.waitForTimeout(400);
  await page.evaluate(axe);
  const { violations } = await page.evaluate((tags) => window.axe.run(document, {
    runOnly: { type: 'tag', values: tags },
  }), TAGS);
  const label = `${name}${width < 600 ? ' (phone)' : ''}`;
  console.log(`${violations.length ? '✖' : '✔'} ${label}`);
  for (const v of violations) {
    failures.push(label);
    console.log(`   ${v.impact} · ${v.id}: ${v.help}`);
    for (const node of v.nodes.slice(0, 3)) console.log(`     ${node.target.join(' ')}`);
  }
}

await page.goto(BASE);
await page.waitForSelector('#auth-view:not([hidden])');
await audit('Sign-in / landing');

// A throwaway local account and event, made through the public API.
const email = `a11y-${Date.now()}@example.test`;
await page.evaluate(async (e) => {
  const post = (path, body) => fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then((r) => r.json());
  await post('/api/auth/register', { name: 'Audit', email: e, password: crypto.randomUUID() });
  const date = new Date(Date.now() + 90 * 864e5).toISOString().slice(0, 10);
  const { event } = await post('/api/events', {
    name: 'Audit Wedding', kind: 'wedding', event_date: date, guests: 120, budget: null,
    city: 'Lisbon', currency: 'EUR',
  });
  await post(`/api/events/${event.id}/invite`, { tone: 'elegant', venue: 'Quinta da Regaleira' });
  location.hash = `#/event/${event.id}`;
}, email);
await page.reload();

await page.goto(`${BASE}/#/`);
await page.waitForSelector('#home-view:not([hidden])');
await audit('Home');
await audit('Home', 375);

await page.locator('.event-card').first().click();
await page.waitForSelector('#event-view:not([hidden])');
for (const tab of ['budget', 'timeline', 'checklist', 'ideas', 'invites', 'ask']) {
  await page.click(`#t-${tab}`);
  await page.waitForSelector(`#panel-${tab}:not([hidden])`);
  await audit(`Event · ${tab}`);
}
await audit('Event · ask', 375);
await page.click('#bell');
await audit('Notifications panel');

await browser.close();
if (failures.length) {
  console.log(`\n${new Set(failures).size} page(s) with accessibility violations`);
  process.exit(1);
}
console.log('\nNo WCAG 2.1 A/AA violations found');
