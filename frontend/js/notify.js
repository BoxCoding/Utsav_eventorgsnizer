// Notification centre: bell + panel, read state, share, and opt-in desktop alerts.
import { api } from './api.js';
import { $, esc, toast } from './dom.js';

const URGENT = new Set(['critical', 'high']);
const REFRESH_MS = 5 * 60 * 1000;

let items = [];
let filter = 'all';
let showRead = false;

// Read/pushed ids are per-viewer conveniences: browser storage, failure-tolerant.
function loadSet(key) {
  try {
    return new Set(JSON.parse(localStorage.getItem(key) || '[]'));
  } catch {
    return new Set();
  }
}
function saveSet(key, set) {
  try {
    localStorage.setItem(key, JSON.stringify([...set].slice(-500)));
  } catch { /* storage unavailable: state lasts for this page only */ }
}
const read = loadSet('utsav:read');
const pushed = loadSet('utsav:pushed');

function when(n) {
  if (n.due_in == null) return '';
  if (n.due_in < 0) return `${-n.due_in}d overdue`;
  if (n.due_in === 0) return 'Today';
  return `In ${n.due_in}d`;
}

function render() {
  const unread = items.filter((n) => !read.has(n.id));
  const count = $('#bell-count');
  count.hidden = unread.length === 0;
  count.textContent = unread.length > 99 ? '99+' : unread.length;
  count.classList.toggle('urgent', unread.some((n) => URGENT.has(n.priority)));
  $('#bell').setAttribute('aria-label', `Notifications, ${unread.length} unread`);

  const visible = items.filter((n) => (filter === 'all' || n.priority === filter)
    && (showRead || !read.has(n.id)));
  $('#notif-show-read').textContent = showRead ? 'Hide dismissed' : 'Show dismissed';
  $('#notif-list').innerHTML = visible.length
    ? visible.map((n) => `
      <li class="notif ${n.priority} ${read.has(n.id) ? 'read' : ''}">
        <div class="notif-top">
          <span class="prio ${n.priority}">${n.priority}</span>
          <span class="muted small">${esc(n.event_name)}${when(n) ? ` · ${when(n)}` : ''}</span>
          ${n.source === 'brief' ? '<span class="tag brief">✦ from your brief</span>' : ''}
        </div>
        <strong>${esc(n.title)}</strong>
        <p>${esc(n.message)}</p>
        <div class="notif-actions">
          <button type="button" class="link-btn" data-act="open" data-id="${esc(n.id)}">Open</button>
          <button type="button" class="link-btn" data-act="share" data-id="${esc(n.id)}">Share</button>
          ${read.has(n.id) ? '' : `<button type="button" class="link-btn" data-act="dismiss" data-id="${esc(n.id)}">Dismiss</button>`}
        </div>
      </li>`).join('')
    : '<li class="notif-empty muted">You\'re all caught up.</li>';
}

function pushDesktop() {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  for (const n of items) {
    if (!URGENT.has(n.priority) || read.has(n.id) || pushed.has(n.id)) continue;
    const note = new Notification(`${n.priority === 'critical' ? '⚠ ' : ''}${n.title}`, {
      body: `${n.event_name}: ${n.message}`, tag: n.id,
    });
    note.onclick = () => { window.focus(); open(n); };
    pushed.add(n.id);
  }
  saveSet('utsav:pushed', pushed);
}

function syncDesktopButton() {
  const btn = $('#notif-desktop');
  if (!('Notification' in window)) {
    btn.hidden = true;
  } else if (Notification.permission === 'granted') {
    btn.textContent = 'Desktop alerts on';
    btn.disabled = true;
  } else if (Notification.permission === 'denied') {
    btn.textContent = 'Desktop alerts blocked in browser';
    btn.disabled = true;
  }
}

function setOpen(open) {
  $('#notif-panel').hidden = !open;
  $('#bell').setAttribute('aria-expanded', String(open));
  if (open) $('#notif-panel').querySelector('button')?.focus();
}

function open(n) {
  read.add(n.id);
  saveSet('utsav:read', read);
  setOpen(false);
  location.hash = `#/event/${n.event_id}/${n.tab}`;
  render();
}

async function share(n) {
  const text = `${n.title}: ${n.message} (${n.event_name}, via Utsav)`;
  try {
    if (navigator.share) {
      await navigator.share({ title: 'Utsav reminder', text });
    } else {
      await navigator.clipboard.writeText(text);
      toast('Reminder copied — paste it into WhatsApp, email or chat');
    }
  } catch (err) {
    if (err?.name !== 'AbortError') toast('Could not share this reminder');
  }
}

export async function refreshNotifications() {
  if ($('#user-box').hidden) return; // signed out
  try {
    ({ notifications: items } = await api('GET', '/api/notifications'));
  } catch {
    return; // signed out or offline: keep the last known list
  }
  render();
  pushDesktop();
}

export function bindNotifications() {
  syncDesktopButton();
  $('#bell').addEventListener('click', () => setOpen($('#notif-panel').hidden));
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.notif-wrap')) setOpen(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#notif-panel').hidden) {
      setOpen(false);
      $('#bell').focus();
    }
  });
  $('#notif-panel').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.dataset.filter) {
      filter = btn.dataset.filter;
      for (const b of $('#notif-panel').querySelectorAll('.filter')) {
        b.classList.toggle('on', b === btn);
        b.setAttribute('aria-pressed', String(b === btn));
      }
      render();
      return;
    }
    const n = items.find((x) => x.id === btn.dataset.id);
    if (btn.dataset.act === 'open' && n) open(n);
    if (btn.dataset.act === 'share' && n) share(n);
    if (btn.dataset.act === 'dismiss' && n) {
      read.add(n.id);
      saveSet('utsav:read', read);
      render();
    }
  });
  $('#notif-read-all').addEventListener('click', () => {
    for (const n of items) read.add(n.id);
    saveSet('utsav:read', read);
    render();
  });
  $('#notif-show-read').addEventListener('click', () => {
    showRead = !showRead;
    render();
  });
  $('#notif-desktop').addEventListener('click', async () => {
    await Notification.requestPermission();
    syncDesktopButton();
    pushDesktop();
  });
  // Plan edits (checklist, spend, what-if) change which alerts apply.
  window.addEventListener('utsav:changed', refreshNotifications);
  setInterval(refreshNotifications, REFRESH_MS);
}
