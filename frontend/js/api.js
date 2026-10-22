// Fetch wrapper. The web app is same-origin with the httpOnly session cookie. The native
// app (assets bundled in the APK, <meta name="utsav-api">) calls the API cross-origin with
// a bearer token, and keeps an on-device copy of every plan so it works offline.
import * as offline from './offline.js';

export const API_BASE = document.querySelector('meta[name="utsav-api"]')?.content || '';
export const NATIVE = Boolean(API_BASE);
const OFFLINE_FIRST = NATIVE || matchMedia('(display-mode: standalone)').matches;
const TOKEN_KEY = 'utsav:token';
const EVENT_PATH = /^\/api\/events\/\d+$/;
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

export async function api(method, path, body) {
  if (!OFFLINE_FIRST) return request(method, path, body);
  try {
    const data = await request(method, path, body);
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
    } else if ((method === 'GET' && path !== '/api/health') || (method === 'PATCH' && EVENT_PATH.test(path))) {
      offline.cachePut(path, data); // a PATCH answers with the same view as the GET
    }
    connectivity(true);
    return data;
  } catch (err) {
    if (err.status !== 0) throw err;
    connectivity(false);
    if (method === 'GET' && path !== '/api/health') { // health must reflect the live server
      const saved = await offline.cacheGet(path);
      if (saved) return saved;
      throw new ApiError(0, "You're offline, and this hasn't been opened on this device yet.");
    }
    if (method === 'PATCH' && EVENT_PATH.test(path) && Object.keys(body).every((k) => OFFLINE_FIELDS.has(k))) {
      const saved = await offline.cacheGet(path);
      if (saved) {
        await offline.enqueue({ path, body });
        const view = offline.applyEdit(saved, body);
        await offline.cachePut(path, view);
        connectivity(false);
        return view;
      }
    }
    throw new ApiError(0, "You're offline. Your plan is saved on this device; this action needs internet.");
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
      offline.cachePut(item.path, await request('PATCH', item.path, item.body));
    } catch (err) {
      if (err.status === 0) break; // still offline: keep the rest queued
      // 4xx: the event changed or was deleted elsewhere; this edit can't apply any more
    }
    await offline.dequeue(item.key);
    sent += 1;
  }
  connectivity(navigator.onLine);
  return sent;
}

/** URL for an authenticated image: same-origin path on the web, a blob URL in the app. */
const blobs = new Map();
export function imageUrl(path) {
  if (!NATIVE) return Promise.resolve(path);
  if (!blobs.has(path)) {
    blobs.set(path, fetch(API_BASE + path, { headers: headers() })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => URL.createObjectURL(b))
      .catch((e) => { blobs.delete(path); throw e; }));
  }
  return blobs.get(path);
}

// WhatsApp Business Cloud API connected on the server? Asked once per page load.
let waPromise;
export function whatsappStatus() {
  waPromise ??= api('GET', '/api/whatsapp/status').then((r) => r.connected).catch(() => false);
  return waPromise;
}
