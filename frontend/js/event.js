// Event plan view: health, what-if, budget, timeline, checklist, ideas, assistant.
import { api } from './api.js';
import { $, currencyOptions, debounce, esc, fmtDate, money, setupTabs, todayIso, toast } from './dom.js';
import { bindIdeas, renderIdeas } from './ideas.js';
import { bindInvites, renderInvites } from './invites.js';
import { renderBudget, renderChecklist, renderTimeline } from './panels.js';
import { bindBriefCard, renderBriefCard } from './replan.js';

const KIND = { wedding: 'Wedding', birthday: 'Birthday', community: 'Community event' };

let state = null; // { event, plan }
let selectTab = null;
let checkFilter = 'all';
let chat = []; // [{ role: 'user'|'model', content }]

// ── rendering ──────────────────────────────────────────────────────────
function renderHeader() {
  const { event, plan } = state;
  $('#ev-title').textContent = event.name;
  const where = event.city ? ` · ${event.city}` : '';
  const extra = [event.tradition, event.vibe].filter(Boolean).join(' · ');
  $('#event-hero').className = `event-hero kind-${event.kind}`;
  $('#ev-kind').textContent = KIND[event.kind];
  $('#ev-meta').textContent =
    `${fmtDate(event.event_date)}${where} · ${event.guests} guests${extra ? ` · ${extra}` : ''}`;
  $('#ev-days').textContent = plan.days_left;
  $('#ev-days-label').textContent =
    plan.days_left === 0 ? "It's today!" : `day${plan.days_left === 1 ? '' : 's'} to go`;
  $('#ics-link').href = `/api/events/${event.id}/calendar.ics`;
  $('#wi-guests').value = event.guests;
  $('#wi-budget').value = event.budget;
  $('#wi-currency').innerHTML = currencyOptions(event.currency);
  $('#wi-date').value = event.event_date;
  $('#wi-date').min = todayIso();
}

function renderHealth() {
  const { score, label, notes } = state.plan.health;
  const cls = score >= 80 ? 'ok' : score >= 55 ? 'warn' : 'bad';
  const circumference = 2 * Math.PI * 42;
  $('#health-card').innerHTML = `
    <svg class="ring ${cls}" viewBox="0 0 100 100" role="img" aria-label="Plan health ${score} out of 100">
      <circle cx="50" cy="50" r="42" class="track"/>
      <circle cx="50" cy="50" r="42" class="value" stroke-dasharray="${(score / 100) * circumference} ${circumference}"/>
      <text x="50" y="54" text-anchor="middle">${score}</text>
      <text x="50" y="68" text-anchor="middle" class="ring-sub">OF 100</text>
    </svg>
    <div>
      <h2>Plan health: <span class="chip ${cls}">${esc(label)}</span></h2>
      <ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
      <p class="muted small">${Math.round(state.plan.progress * 100)}% of the checklist done</p>
    </div>`;
}

// Model replies may use light markdown; show bullets/bold as plain text.
const plain = (text) => text.replace(/^\s*[*-]\s+/gm, '• ').replace(/\*\*(.+?)\*\*/g, '$1');

const AVATAR = '<span class="chat-avatar sm" aria-hidden="true">✦</span>';
const bubble = (role, html) => `<div class="msg-row ${role}">${role === 'model' ? AVATAR : ''}<p class="bubble ${role}">${html}</p></div>`;

function renderChat() {
  $('#chat-log').innerHTML = chat.length
    ? chat.map((m) => bubble(m.role, esc(plain(m.content)))).join('')
    : bubble('model', `Hi! I know everything in <strong>${esc(state.event.name)}</strong>'s plan. Ask me about the budget, what to book next, or ideas for the day.`);
  $('#chat-suggestions').classList.toggle('compact', chat.length > 0);
  $('#chat-log').scrollTop = $('#chat-log').scrollHeight;
}

function renderAskContext() {
  const { plan, event } = state;
  const open = plan.tasks.filter((t) => t.status !== 'done').length;
  const facts = [
    ['💰', `${money(plan.budget.remaining, plan.budget.currency)} left`],
    ['✅', `${open} open tasks`],
    ['⏳', `${plan.days_left} days to go`],
    ...(event.ideas ? [['✨', event.ideas.theme]] : []),
  ];
  $('#ask-context').innerHTML = facts.map(([i, t]) => `<span><span aria-hidden="true">${i}</span> ${esc(t)}</span>`).join('');
  renderSuggestions();
}

const clip = (text, n = 48) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

/** Starter questions built from this plan, so they fit the event rather than any event. */
function renderSuggestions() {
  const { plan, event } = state;
  const lines = plan.budget.lines.filter((l) => l.category !== 'Contingency');
  const biggest = lines.reduce((a, b) => (b.planned > a.planned ? b : a), lines[0]);
  const urgent = plan.tasks.find((t) => t.status === 'late') || plan.tasks.find((t) => t.status === 'soon');
  const qs = [
    urgent && ['🗓️', urgent.status === 'late'
      ? `"${clip(urgent.title)}" is overdue. What should I do?`
      : `How do I get "${clip(urgent.title)}" done in time?`],
    biggest && ['💰', `How should I spend the ${money(biggest.planned, plan.budget.currency)} ${biggest.category} budget?`],
    event.run_sheet ? ['🕒', 'Walk me through the day-of schedule'] : ['📋', 'What should I book this week?'],
    event.brief ? ['💡', 'What am I missing for this event?'] : ['💡', 'Where can I save money?'],
  ].filter(Boolean);
  $('#chat-suggestions').innerHTML = qs.map(([icon, q]) => `
    <button type="button" class="chip-btn" data-q="${esc(q)}"><span aria-hidden="true">${icon}</span><span>${esc(q)}</span></button>`).join('');
}

function renderAll() {
  const focusedId = document.activeElement?.id;
  renderHeader();
  renderHealth();
  renderBriefCard(state.event);
  renderBudget($('#panel-budget'), state.plan);
  renderTimeline($('#panel-timeline'), state.event, state.plan);
  renderChecklist($('#panel-checklist'), state.plan, checkFilter);
  renderAskContext();
  renderIdeas(state.event);
  renderInvites(state.event);
  if (focusedId) document.getElementById(focusedId)?.focus();
}

// ── actions ────────────────────────────────────────────────────────────
/** PATCH the event and re-render; resolves to true on success. */
async function save(fields) {
  try {
    state = await api('PATCH', `/api/events/${state.event.id}`, fields);
    renderAll();
    window.dispatchEvent(new CustomEvent('utsav:changed'));
    if ('brief' in fields) ensureBriefAlerts(state.event);
    return true;
  } catch (err) {
    toast(err.message);
    renderAll(); // snap inputs back to saved values
    return false;
  }
}

const saveWhatIf = debounce(() => {
  const guests = Number($('#wi-guests').value);
  const budget = Number($('#wi-budget').value);
  const date = $('#wi-date').value;
  const currency = $('#wi-currency').value;
  if (guests >= 1 && budget >= 100 && date) save({ guests, budget, event_date: date, currency });
}, 400);

async function generateIdeas(button) {
  button.disabled = true;
  button.textContent = '✨ Dreaming up ideas…';
  try {
    const { ideas } = await api('POST', `/api/events/${state.event.id}/ideas`);
    state.event.ideas = ideas;
    renderIdeas(state.event);
    window.dispatchEvent(new CustomEvent('utsav:changed'));
    $('#ideas-btn').focus();
  } catch (err) {
    toast(err.message);
    button.disabled = false;
  }
}

async function ask(question) {
  chat.push({ role: 'user', content: question });
  renderChat();
  $('#chat-typing').innerHTML = `<div class="msg-row model">${AVATAR}<span class="dots"><span class="sr-only">Utsav is thinking</span><i></i><i></i><i></i></span></div>`;
  try {
    const history = chat.slice(-7, -1);
    const { answer } = await api('POST', `/api/events/${state.event.id}/ask`, { question, history });
    chat.push({ role: 'model', content: answer });
  } catch (err) {
    chat.push({ role: 'model', content: `Sorry — ${err.message}` });
  } finally {
    $('#chat-typing').innerHTML = '';
    renderChat();
  }
}

/** Tick or untick one task by id (a filter may hide others, so never rebuild from the DOM). */
function setDone(id, on) {
  const done = new Set(state.event.done);
  if (on) done.add(id);
  else done.delete(id);
  save({ done: [...done] });
}

async function draftRunSheet(btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Drafting the day…';
  try {
    const { run_sheet: sheet } = await api('POST', `/api/events/${state.event.id}/runsheet`);
    state.event.run_sheet = sheet;
    renderTimeline($('#panel-timeline'), state.event, state.plan);
    $('#runsheet-btn').focus();
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
  }
}

function bindPlanPanels() {
  $('#panel-budget').addEventListener('change', (e) => {
    if (!e.target.classList.contains('spend')) return;
    const spend = {};
    for (const input of $('#panel-budget').querySelectorAll('.spend')) {
      spend[input.dataset.category] = Math.max(0, Math.round(Number(input.value) || 0));
    }
    save({ spend });
  });
  $('#panel-timeline').addEventListener('click', (e) => {
    if (e.target.id === 'runsheet-btn') {
      draftRunSheet(e.target);
      return;
    }
    const id = e.target.closest('[data-toggle]')?.dataset.toggle;
    if (id) setDone(id, !state.event.done.includes(id));
  });
  $('#panel-checklist').addEventListener('change', (e) => {
    if (e.target.dataset.task) setDone(e.target.dataset.task, e.target.checked);
  });
  $('#panel-checklist').addEventListener('click', (e) => {
    const f = e.target.closest('[data-cfilter]')?.dataset.cfilter;
    if (!f) return;
    checkFilter = f;
    renderChecklist($('#panel-checklist'), state.plan, checkFilter);
    $(`[data-cfilter="${f}"]`).focus();
  });
  for (const id of ['#wi-guests', '#wi-budget', '#wi-date', '#wi-currency']) $(id).addEventListener('change', saveWhatIf);
}

function bindChat() {
  $('#chat-suggestions').addEventListener('click', (e) => {
    const q = e.target.closest('.chip-btn')?.dataset.q;
    if (q) ask(q);
  });
  $('#chat-clear').addEventListener('click', () => {
    chat = [];
    renderChat();
    $('#chat-input').focus();
  });
  $('#chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const q = $('#chat-input').value.trim();
    if (!q) return;
    $('#chat-input').value = '';
    ask(q);
  });
}

function bindHeaderActions(onDeleted) {
  $('#print-btn').addEventListener('click', () => window.print());
  $('#delete-btn').addEventListener('click', async () => {
    if (!window.confirm(`Delete "${state.event.name}"? This cannot be undone.`)) return;
    await api('DELETE', `/api/events/${state.event.id}`);
    toast('Event deleted');
    onDeleted();
  });
}

export function bindEventView(onDeleted) {
  const phone = window.matchMedia('(max-width: 640px)');
  selectTab = setupTabs($('#plan-tabs'), (tab) => {
    // With the bar fixed at the bottom, bring the chosen section's top into view.
    if (phone.matches) document.getElementById(tab.getAttribute('aria-controls')).scrollIntoView({ block: 'start' });
  });
  bindPlanPanels();
  bindChat();
  bindHeaderActions(onDeleted);
  bindIdeas(generateIdeas);
  bindInvites(save);
  bindBriefCard(save);
}

/** Jump to a plan section, e.g. from a notification. */
export function showTab(name) {
  const tab = document.getElementById(`t-${name}`);
  if (tab) {
    selectTab(tab);
    document.getElementById(tab.getAttribute('aria-controls')).scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

/** Smart alerts are written once per brief; (re)generate them in the background when the
 * brief is new or has changed, then refresh the bell. */
function ensureBriefAlerts(event) {
  if (!event.brief || event.brief_alerts?.brief === event.brief) return;
  api('POST', `/api/events/${event.id}/alerts`).then(({ brief_alerts: alerts }) => {
    if (state?.event.id === event.id) state.event.brief_alerts = alerts;
    window.dispatchEvent(new CustomEvent('utsav:changed'));
  }).catch(() => {}); // the rule-based alerts still work without them
}

export async function openEvent(id) {
  if (state?.event.id !== id) chat = [];
  state = await api('GET', `/api/events/${id}`);
  renderAll();
  renderChat();
  ensureBriefAlerts(state.event);
}
