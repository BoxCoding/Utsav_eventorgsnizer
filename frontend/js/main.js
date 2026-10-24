// Boot + hash routing: #/ (home) and #/event/<id>.
import { NATIVE, api, forgetDevice, syncOffline } from './api.js';
import { bindAuth } from './auth.js';
import { $, showView, toast } from './dom.js';
import { bindEventView, openEvent, showTab } from './event.js';
import { bindEventForm, renderHome } from './home.js';
import { bindNotifications, refreshNotifications } from './notify.js';

let user = null;

function setUser(u) {
  user = u;
  $('#user-box').hidden = !u;
  $('#user-name').textContent = u ? u.name : '';
  $('#greeting').textContent = u ? `Welcome back, ${u.name.split(' ')[0]}` : '';
}

async function route() {
  if (!user) {
    showView('auth-view');
    return;
  }
  refreshNotifications();
  const match = location.hash.match(/^#\/event\/(\d+)(?:\/(\w+))?$/);
  try {
    if (match) {
      await openEvent(Number(match[1]));
      showView('event-view');
      if (match[2]) showTab(match[2]);
    } else {
      await renderHome();
      showView('home-view');
    }
  } catch (err) {
    if (err.status === 404) {
      toast('That event was not found');
      location.hash = '#/';
    } else if (err.status !== 401) {
      toast(err.message);
    }
  }
}

function refreshStatus() {
  api('GET', '/api/health').catch(() => ({ llm: 'unreachable' })).then((health) => {
    const status = $('#ai-status');
    status.textContent = { gemini: '● Gemini', unreachable: '● No connection' }[health.llm] || '● Offline mode';
    status.classList.toggle('ok', health.llm === 'gemini');
    status.classList.toggle('warn', health.llm !== 'gemini');
  });
}

async function boot() {
  bindAuth((u) => {
    setUser(u);
    route();
  });
  bindEventForm((id) => { location.hash = `#/event/${id}`; });
  bindEventView(() => { location.hash = '#/'; });
  bindNotifications();

  $('#logout-btn').addEventListener('click', async () => {
    await api('POST', '/api/auth/logout').catch(() => {}); // offline: the token expires on its own
    await forgetDevice();
    setUser(null);
    location.hash = '#/';
    route();
  });
  window.addEventListener('utsav:unauthorized', () => {
    if (!user) return;
    setUser(null);
    toast('Your session ended — please sign in again');
    route();
  });
  window.addEventListener('hashchange', route);
  window.addEventListener('utsav:connectivity', (/** @type {CustomEvent} */ { detail }) => {
    const bar = $('#offline-bar');
    bar.hidden = detail.online && !detail.pending;
    bar.textContent = detail.online
      ? `Syncing ${detail.pending} change${detail.pending === 1 ? '' : 's'}…`
      : `Offline · showing plans saved on this device${detail.pending ? ` · ${detail.pending} change${detail.pending === 1 ? '' : 's'} will sync` : ''}`;
  });
  window.addEventListener('online', async () => {
    refreshStatus();
    if (await syncOffline()) {
      toast('Back online: your offline changes are saved');
      if (user) route();
    }
  });

  refreshStatus(); // fills in when it can; it must not hold up the first screen
  const session = await api('GET', '/api/auth/session').catch(() => ({ user: null }));
  setUser(session.user);
  if (session.user) await syncOffline();
  $('#boot').remove();
  route();
}

// ── installable app (PWA) ──
document.documentElement.classList.toggle('native', NATIVE);
if ('serviceWorker' in navigator && !NATIVE) { // the app bundles its files already
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
let installPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault(); // show our own button instead of the browser's mini-bar
  installPrompt = e;
  $('#install-btn').hidden = false;
});
$('#install-btn').addEventListener('click', async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $('#install-btn').hidden = true;
});
window.addEventListener('appinstalled', () => { $('#install-btn').hidden = true; toast('Utsav installed'); });

boot();
