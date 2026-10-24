// End-to-end functional test: the main user journey in real Chrome, start to finish.
// Run against a server in offline-AI mode (deterministic, no Gemini cost), e.g.
//   UTSAV_OFFLINE=1 UTSAV_DB=/tmp/e2e.db uvicorn backend.main:app --port 8104
//   BASE_URL=http://localhost:8104 npm run test:e2e
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';

const BASE = process.env.BASE_URL || 'http://localhost:8104';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
// Behave like the installed app (display-mode: standalone) so the offline layer is on.
await context.addInitScript(() => {
  const real = window.matchMedia.bind(window);
  window.matchMedia = (q) => (q.includes('display-mode: standalone')
    ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : real(q));
});
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
let failed = 0;

async function step(name, fn) {
  try {
    await fn();
    console.log(`✔ ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`✖ ${name}\n   ${err.message.split('\n')[0]}`);
  }
}
const text = (sel) => page.locator(sel).innerText();
const server = async (path) => (await page.request.get(`${BASE}${path}`)).json(); // shares the session cookie
let eventId;

await page.goto(BASE);
await page.waitForSelector('#auth-view:not([hidden])');

await step('sign-up rejects a short password before sending it', async () => {
  await page.click('#tab-register');
  await page.fill('#reg-name', 'E2E Tester');
  await page.fill('#reg-email', `e2e-${Date.now()}@example.com`);
  await page.fill('#reg-password', 'abc123');
  await page.click('#register-form button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#auth-error').textContent.includes('8 characters'));
});

await step('sign-up rejects an invalid email with a readable message', async () => {
  const email = await page.inputValue('#reg-email');
  await page.fill('#reg-email', 'e2e@example');
  await page.fill('#reg-password', 'e2e-pass-2026');
  await page.click('#register-form button[type=submit]');
  await page.waitForFunction(() => document.querySelector('#auth-error').textContent === 'Please enter a valid email.');
  await page.fill('#reg-email', email);
});

await step('valid sign-up lands on the home screen', async () => {
  await page.click('#register-form button[type=submit]');
  await page.waitForSelector('#home-view:not([hidden])');
  assert.match(await text('#greeting'), /Welcome back, E2E/);
});

await step('an unrealistic budget is flagged live', async () => {
  await page.fill('#ev-guests', '150');
  await page.fill('#ev-budget', '50000');
  await page.waitForFunction(() => /low/i.test(document.querySelector('#budget-hint').textContent), null, { timeout: 5000 });
});

await step('a blank budget is estimated, not defaulted', async () => {
  await page.fill('#ev-budget', '');
  await page.fill('#ev-name', 'E2E Lisbon Wedding');
  await page.fill('#ev-date', '2027-06-12');
  await page.fill('#ev-guests', '120');
  await page.selectOption('#ev-currency', 'EUR');
  await page.fill('#ev-city', 'Lisbon');
  await page.click('#event-form button[type=submit]');
  await page.waitForSelector('#event-view:not([hidden])');
  eventId = Number(page.url().match(/event\/(\d+)/)[1]);
  const { event } = await server(`/api/events/${eventId}`);
  assert.ok(event.budget > 0 && event.currency === 'EUR', `budget ${event.budget} ${event.currency}`);
  assert.match(event.budget_note, /Estimated by Utsav/);
});

await step('ticking a task saves it and updates progress', async () => {
  await page.click('#t-checklist');
  await page.locator('#panel-checklist .check-box').first().click();
  await page.waitForFunction(() => !/^0% of/.test(document.querySelector('#health-card').innerText.match(/\d+% of the checklist done/)?.[0] || '0% of'));
  assert.equal((await server(`/api/events/${eventId}`)).event.done.length, 1);
});

await step('what-if: changing the guest count recomputes the plan on the server', async () => {
  await page.fill('#wi-guests', '200');
  await page.locator('#wi-guests').press('Tab');
  await page.waitForFunction(async (id) => (await (await fetch(`/api/events/${id}`)).json()).event.guests === 200, eventId);
  await page.fill('#wi-guests', '120');
  await page.locator('#wi-guests').press('Tab');
});

await step('invites: three concepts using only the details given', async () => {
  await page.click('#t-invites');
  await page.fill('#inv-venue', 'Quinta da Regaleira');
  await page.fill('#inv-time', '6:30 pm');
  await page.click('#invite-btn');
  await page.waitForSelector('.concepts');
  assert.equal(await page.locator('.concept').count(), 3);
  assert.match(await page.inputValue('#msg-wa'), /Quinta da Regaleira/);
});

await step('Ask Utsav answers from the plan', async () => {
  await page.click('#t-ask');
  await page.fill('#chat-input', 'How is my budget looking?');
  await page.press('#chat-input', 'Enter');
  await page.waitForFunction(() => {
    const rows = document.querySelectorAll('#chat-log .msg-row');
    return rows.length > 1 && rows[rows.length - 1].classList.contains('model') && !document.querySelector('#chat-typing').children.length;
  });
  assert.match(await page.locator('#chat-log .msg-row.model').last().innerText(), /€/);
});

await step('offline: a tick is queued on the device, then synced when back online', async () => {
  await page.click('#t-checklist');
  await context.setOffline(true);
  await page.locator('#panel-checklist .check-box:not(:checked)').first().click();
  await page.waitForFunction(() => /1 change will sync/.test(document.querySelector('#offline-bar').textContent));
  assert.equal((await server(`/api/events/${eventId}`)).event.done.length, 1, 'not on the server yet');
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await page.waitForSelector('#offline-bar', { state: 'hidden' });
  assert.equal((await server(`/api/events/${eventId}`)).event.done.length, 2, 'synced');
});

await step('sign-out clears the session', async () => {
  await page.click('#logout-btn');
  await page.waitForSelector('#auth-view:not([hidden])');
  assert.equal((await page.request.get(`${BASE}/api/auth/me`)).status(), 401);
});

await step('no uncaught JavaScript errors during the journey', async () => {
  assert.deepEqual(errors, []);
});

await browser.close();
console.log(failed ? `\n${failed} step(s) failed` : '\nAll journeys passed');
process.exit(failed ? 1 : 0);
