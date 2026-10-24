// On-device database (IndexedDB) for the installed app: every plan opened online is
// kept here, so plans, budgets, checklists and timelines open with no signal. Edits
// made offline (ticks, spend, guest list) are queued and synced in order.
import { todayIso } from './dom.js';

let dbPromise;
function db() {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open('utsav', 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('cache'); // API path -> last response
      req.result.createObjectStore('queue', { autoIncrement: true }); // pending PATCHes
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

async function run(store, mode, fn) {
  const t = (await db()).transaction(store, mode);
  const req = fn(t.objectStore(store));
  return new Promise((resolve, reject) => {
    t.oncomplete = () => resolve(req?.result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

export const cacheGet = (path) => run('cache', 'readonly', (s) => s.get(path)).catch(() => undefined);
export const cachePut = (path, data) => run('cache', 'readwrite', (s) => s.put(data, path)).catch(() => {});
export const enqueue = (item) => run('queue', 'readwrite', (s) => s.add(item));
export const pendingCount = () => run('queue', 'readonly', (s) => s.count()).catch(() => 0);

export async function queued() {
  const keys = await run('queue', 'readonly', (s) => s.getAllKeys());
  const items = await run('queue', 'readonly', (s) => s.getAll());
  return keys.map((key, i) => ({ key, ...items[i] }));
}
export const dequeue = (key) => run('queue', 'readwrite', (s) => s.delete(key));

/** Forget everything on sign-out: the next person on this device sees nothing. */
export async function clearAll() {
  await run('cache', 'readwrite', (s) => s.clear()).catch(() => {});
  await run('queue', 'readwrite', (s) => s.clear()).catch(() => {});
}

// Mirrors planner._status so offline ticks show the same states the server would.
function status(due, today, done) {
  if (done) return 'done';
  if (due < today) return 'late';
  return (Date.parse(due) - Date.parse(today)) / 864e5 <= 14 ? 'soon' : 'upcoming';
}

/** Apply an offline edit to a cached {event, plan} view, as the server would. */
export function applyEdit(view, fields) {
  const event = { ...view.event, ...fields };
  const plan = structuredClone(view.plan);
  const today = todayIso(); // local date, like the server's planner
  const done = new Set(event.done || []);
  for (const t of plan.tasks) t.status = status(t.due, today, done.has(t.id));
  plan.progress = Math.round((100 * plan.tasks.filter((t) => t.status === 'done').length) / plan.tasks.length) / 100;
  const spend = event.spend || {};
  for (const line of plan.budget.lines) {
    line.spent = Math.trunc(spend[line.category] || 0);
    line.remaining = line.planned - line.spent;
  }
  plan.budget.spent = plan.budget.lines.reduce((s, l) => s + l.spent, 0);
  plan.budget.remaining = plan.budget.total - plan.budget.spent;
  return { event, plan, offline: true };
}

/** An offline edit replayed onto the server's current event: only what changed on this
 * device is applied, so ticks or spend entered elsewhere meanwhile are kept. */
export function rebase(server, base, body) {
  const out = { ...body };
  if (body.done) {
    const before = new Set(base.done || []);
    const after = new Set(body.done);
    const done = new Set(server.done || []);
    for (const id of after) if (!before.has(id)) done.add(id);
    for (const id of before) if (!after.has(id)) done.delete(id);
    out.done = [...done];
  }
  if (body.spend) {
    const changed = Object.entries(body.spend).filter(([k, v]) => (base.spend || {})[k] !== v);
    out.spend = { ...(server.spend || {}), ...Object.fromEntries(changed) };
  }
  return out; // guest_list: the device's list wins
}
