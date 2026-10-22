// Unit tests for the frontend's pure logic. Run: npm test (node --test, no browser needed).
import assert from 'node:assert/strict';
import { test } from 'node:test';

// api.js reads a <meta> at import time; give it the bare minimum of a page.
globalThis.document = { querySelector: () => null };
globalThis.matchMedia = () => ({ matches: false });

const { esc, money } = await import('../../frontend/js/dom.js');
const { parseGuests, csvCell, waLink } = await import('../../frontend/js/invites.js');
const { applyEdit } = await import('../../frontend/js/offline.js');
const { readable, contrast, rgb } = await import('../../frontend/js/invite-art.js');

test('esc neutralises every HTML-significant character', () => {
  assert.equal(esc(`<img src=x onerror="a('b')">&`), '&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;');
  assert.equal(esc(null), '');
});

test('money uses Indian grouping for rupees and local symbols elsewhere', () => {
  assert.equal(money(1234567), '₹12,34,567');
  assert.equal(money(60000, 'EUR'), '€60,000');
});

test('parseGuests reads name, email and phone in any order', () => {
  assert.deepEqual(parseGuests('Meera Shah, meera@example.com, +91 98765 43210\n\n+351 912 345 678; Daniel'), [
    { name: 'Meera Shah', email: 'meera@example.com', phone: '+91 98765 43210' },
    { name: 'Daniel', email: '', phone: '+351 912 345 678' },
  ]);
});

test('csvCell blocks spreadsheet formula injection and escapes quotes', () => {
  assert.equal(csvCell('=HYPERLINK("x")'), `"'=HYPERLINK(""x"")"`);
  assert.equal(csvCell('Meera'), '"Meera"');
});

test('waLink adds the default country code to local numbers only', () => {
  assert.equal(waLink({ name: 'Meera Shah', phone: '098765 43210' }, 'Hi {name}', '+91'),
    'https://wa.me/919876543210?text=Hi%20Meera');
  assert.match(waLink({ name: 'Tom', phone: '+44 7700 900123' }, 'Hi', '+91'), /wa\.me\/447700900123\?/);
});

test('invite accent colours always reach WCAG AA contrast on their panel', () => {
  for (const hex of ['#fde047', '#7c3aed', '#ffffff', '#111111', '#f59e0b']) {
    assert.ok(contrast(rgb(readable(hex, true)), [20, 20, 26]) >= 4.5, `${hex} on dark`);
    assert.ok(contrast(rgb(readable(hex, false)), [255, 250, 243]) >= 4.5, `${hex} on light`);
  }
});

test('offline edits recompute ticks, progress and spend without touching the original', () => {
  const view = {
    event: { id: 1, done: [], spend: {} },
    plan: {
      progress: 0,
      tasks: [
        { id: 'venue', due: '2000-01-01', status: 'late' },
        { id: 'cake', due: '2999-01-01', status: 'upcoming' },
      ],
      budget: { total: 1000, spent: 0, remaining: 1000,
        lines: [{ category: 'Food', planned: 600, spent: 0, remaining: 600 },
          { category: 'Decor', planned: 400, spent: 0, remaining: 400 }] },
    },
  };
  const out = applyEdit(view, { done: ['venue'], spend: { Food: 650.9 } });
  assert.equal(out.plan.tasks[0].status, 'done');
  assert.equal(out.plan.tasks[1].status, 'upcoming');
  assert.equal(out.plan.progress, 0.5);
  assert.deepEqual(out.plan.budget.lines[0], { category: 'Food', planned: 600, spent: 650, remaining: -50 });
  assert.equal(out.plan.budget.remaining, 350);
  assert.equal(view.plan.tasks[0].status, 'late'); // cached copy untouched until saved
  assert.equal(out.offline, true);
});
