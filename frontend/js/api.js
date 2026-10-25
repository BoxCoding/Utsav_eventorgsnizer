// Fetch wrapper. The web app is same-origin with the httpOnly session cookie. The native
// app (assets bundled in the APK, <meta name="utsav-api">) calls the API cross-origin with
// a bearer token, and keeps an on-device copy of every plan so it works offline.
import * as offline from './offline.js';

export const API_BASE = document.querySelector('meta[name="utsav-api"]')?.getAttribute('content') || '';
export const NATIVE = Boolean(API_BASE);
const OFFLINE_FIRST = NATIVE || matchMedia('(display-mode: standalone)').matches;
const TOKEN_KEY = 'utsav:token';
const EVENT_PATH = /^\/api\/events\/\d+$/;
// Live answers about the server itself: never served from the device copy.
const LIVE_ONLY = new Set(['/api/health', '/api/whatsapp/status']);
// Edits that can be applied and recomputed on the device; the rest need the server.
const OFFLINE_FIELDS = new Set(['done', 'spend', 'guest_list']);

function token() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
function setToken(value) {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable: signed in for this session only */ }
}

function headers(body) {
  const h = body ? { 'Content-Type': 'application/json' } : {};
  if (NATIVE) {
    h['X-Utsav-Client'] = 'native';
    if (token()) h.Authorization = `Bearer ${token()}`;
  }
  return h;
}

function connectivity(online) {
  offline.pendingCount().then((pending) => window.dispatchEvent(
    new CustomEvent('utsav:connectivity', { detail: { online, pending } })));
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailMessage(detail) {
  if (Array.isArray(detail)) {
    // FastAPI validation errors: show the first one in plain words.
    const first = detail[0] ?? {};
    const field = (first.loc ?? []).slice(-1)[0];
    // A regex in a message means nothing to a person: say what's wrong instead.
    if (first.type === 'string_pattern_mismatch') return `Please enter a valid ${field || 'value'}.`;
    return `${field ? `${field}: ` : ''}${(first.msg ?? 'invalid input').replace(/^Value error, /, '')}`;
  }
  return detail || 'Something went wrong';
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method,
      credentials: NATIVE ? 'omit' : 'same-origin',
      headers: headers(body),
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the server — check your connection.');
  }
  if (res.status === 401) window.dispatchEvent(new CustomEvent('utsav:unauthorized'));
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detailMessage(data.detail));
  return data;
}

const cacheable = (method, path) =>
  (method === 'GET' && !LIVE_ONLY.has(path)) || (method === 'PATCH' && EVENT_PATH.test(path));

/** Remember what an online answer means for this device: token, session, offline copy. */
async function rememberOnline(method, path, data) {
  if (data?.token) {
    setToken(data.token);
    delete data.token;
  }
  // Opening the app offline right after signing in must find the user, not the
  // signed-out session that was cached when the app first started.
  if (data?.user && path.startsWith('/api/auth/')) offline.cachePut('/api/auth/session', { user: data.user });
  if (path === '/api/auth/logout') {
    setToken(null);
    await offline.clearAll();
  } else if (cacheable(method, path)) {
    offline.cachePut(path, data); // a PATCH answers with the same view as the GET
  }
}

/** With no network: serve reads from the device, and queue edits it can apply itself. */
async function answerOffline(method, path, body) {
  if (method === 'GET' && !LIVE_ONLY.has(path)) {
    const saved = await offline.cacheGet(path);
    if (saved) return saved;
    throw new ApiError(0, "You're offline, and this hasn't been opened on this device yet.");
  }
  const queueable = method === 'PATCH' && EVENT_PATH.test(path)
    && Object.keys(body).every((k) => OFFLINE_FIELDS.has(k));
  const saved = queueable && await offline.cacheGet(path);
  if (!saved) throw new ApiError(0, "You're offline. Your plan is saved on this device; this action needs internet.");
  await offline.enqueue({ path, body, base: { done: saved.event.done, spend: saved.event.spend } });
  const view = offline.applyEdit(saved, body);
  await offline.cachePut(path, view);
  connectivity(false);
  return view;
}

export async function api(method, path, body) {
  if (!OFFLINE_FIRST) return request(method, path, body);
  try {
    const data = await request(method, path, body);
    await rememberOnline(method, path, data);
    connectivity(true);
    return data;
  } catch (err) {
    if (err.status !== 0) throw err;
    connectivity(false);
    return answerOffline(method, path, body);
  }
}

/** Sign-out on this device, even with no signal: drop the token and the offline copy. */
export async function forgetDevice() {
  setToken(null);
  await offline.clearAll();
}

/** Send edits made offline, oldest first. Stops at the first network failure. */
export async function syncOffline() {
  if (!OFFLINE_FIRST) return 0;
  let sent = 0;
  for (const item of await offline.queued().catch(() => [])) {
    try {
      const body = item.base ? offline.rebase((await request('GET', item.path)).event, item.base, item.body) : item.body;
      offline.cachePut(item.path, await request('PATCH', item.path, body));
    } catch (err) {
      // Offline, or signed out (session expired): keep the edits until the next sign-in.
      if (err.status === 0 || err.status === 401) break;
      // other 4xx: the event was deleted or changed shape elsewhere; this edit can't apply
    }
    await offline.dequeue(item.key);
    sent += 1;
  }
  connectivity(navigator.onLine);
  return sent;
}

/** URL for an authenticated image: same-origin path on the web, a blob URL in the app. */
const blobs = new Map(); // image path without ?v= -> { path, url }
export function imageUrl(path) {
  if (!NATIVE) return Promise.resolve(path);
  const key = path.split('?')[0];
  const held = blobs.get(key);
  if (held?.path === path) return held.url;
  if (held) held.url.then((u) => URL.revokeObjectURL(u), () => {}); // repainted: free the old one
  const url = fetch(API_BASE + path, { headers: headers() })
    .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
    .then((b) => URL.createObjectURL(b));
  url.catch(() => blobs.delete(key));
  blobs.set(key, { path, url });
  return url;
}

// WhatsApp Business Cloud API connected on the server? Asked once per page load.
let waPromise;
export function whatsappStatus() {
  waPromise ??= api('GET', '/api/whatsapp/status').then((r) => r.connected).catch(() => false);
  return waPromise;
}
