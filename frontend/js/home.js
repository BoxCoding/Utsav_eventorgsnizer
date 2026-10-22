// Event list + the "plan a new event" form.
import { api } from './api.js';
import { $, currencyOptions, esc, fmtDate, todayIso, toast } from './dom.js';

const ICON = { wedding: '💍', birthday: '🎂', community: '🏘️' };
const HEALTH_CLASS = { 'On track': 'ok', 'Needs attention': 'warn', 'At risk': 'bad' };

export async function renderHome() {
  $('#ev-date').min = todayIso();
  const list = $('#event-list');
  const { events } = await api('GET', '/api/events');
  list.innerHTML = events.length
    ? events.map((ev) => `
      <li>
        <a class="card event-card" href="#/event/${ev.id}">
          <span class="event-band kind-${ev.kind}">
            <span class="event-icon" aria-hidden="true">${ICON[ev.kind]}</span>
            <span class="days"><strong>${ev.days_left}</strong><span>days to go</span></span>
          </span>
          <span class="event-body">
            <strong>${esc(ev.name)}</strong>
            <span class="muted small">${fmtDate(ev.event_date)} · ${ev.guests} guests</span>
            <progress max="100" value="${Math.round(ev.progress * 100)}"
              aria-label="Checklist progress">${Math.round(ev.progress * 100)}%</progress>
            <span class="event-foot">
              <span class="muted small">${Math.round(ev.progress * 100)}% done</span>
              <span class="chip ${HEALTH_CLASS[ev.health]}">${esc(ev.health)} · ${ev.score}</span>
            </span>
          </span>
        </a>
      </li>`).join('')
    : `<li class="empty"><strong>Your first celebration starts here</strong>
        <span class="muted">Fill in the form below and get a complete plan in seconds.</span></li>`;
}

// Personalisation proposed from the brief, sent with the form on create.
let extras = { custom_tasks: [], split_override: null, skipped: [] };

const FIELD_INPUTS = {
  name: '#ev-name', event_date: '#ev-date', guests: '#ev-guests', budget: '#ev-budget',
  currency: '#ev-currency', city: '#ev-city', tradition: '#ev-tradition', vibe: '#ev-vibe',
};

function showBrief(result) {
  const { fields, custom_tasks: tasks, split, summary, source } = result;
  const skipped = result.skipped || [];
  $(`#event-form input[name="kind"][value="${fields.kind}"]`).checked = true;
  for (const [key, sel] of Object.entries(FIELD_INPUTS)) {
    if (fields[key] != null) {
      $(sel).value = fields[key];
      $(sel).classList.add('filled');
    }
  }
  extras = { custom_tasks: tasks, split_override: split, skipped };
  const missing = ['event_date', 'guests', 'budget'].filter((k) => fields[k] == null);
  const cats = split ? Object.entries(split) : [];
  const box = $('#brief-result');
  box.hidden = false;
  box.innerHTML = `
    <div class="br-head"><strong>✦ Here's what Utsav understood</strong>
      <span class="pill">${source === 'gemini' ? 'Read by Gemini' : 'Offline reading'}</span></div>
    <ul class="br-summary">${summary.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
    ${result.suggestions?.length ? `<div class="br-suggest"><p class="br-label">💡 Utsav suggests</p>
      <ul>${result.suggestions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
    ${tasks.length ? `<p class="br-label">${skipped.length ? `Your checklist: ${tasks.length} tasks written for this event` : `${tasks.length} personalised tasks added to your checklist`}</p>
      <ul class="br-tasks">${tasks.map((t) => `<li><span>${esc(t.title)}</span><small>${esc(t.category)} · ${t.lead_days} days before</small></li>`).join('')}</ul>` : ''}
    ${cats.length ? `<p class="br-label">Budget categories designed for your event</p>
      <div class="br-split">${cats.map(([c, v]) => `<span><b>${Math.round(v * 100)}%</b>${esc(c)}</span>`).join('')}</div>` : ''}

    ${missing.length ? `<p class="br-missing">Please add: ${missing.map((m) => m.replace('_', ' ')).join(', ')}. Then check the details below.</p>`
      : '<p class="br-ok">Details filled in below. Check them (especially the exact date), then build your plan.</p>'}`;
}

export function bindEventForm(onCreated) {
  const form = $('#event-form');
  const error = $('#event-error');
  $('#ev-currency').innerHTML = currencyOptions('INR');
  $('#brief-btn').addEventListener('click', async () => {
    const brief = $('#ev-brief').value.trim();
    if (brief.length < 15) {
      toast('Tell Utsav a little more about your event first');
      return;
    }
    const btn = $('#brief-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Reading your description…';
    try {
      showBrief(await api('POST', '/api/events/brief', { brief }));
      $('#brief-result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '✦ Plan from my description';
    }
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    error.textContent = '';
    if (!$('#ev-name').value.trim() || !$('#ev-date').value) {
      error.textContent = 'Please add a name and a date.';
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = 'Building your plan…';
    try {
      const { event } = await api('POST', '/api/events', {
        name: $('#ev-name').value.trim(),
        kind: form.elements.kind.value,
        event_date: $('#ev-date').value,
        guests: Number($('#ev-guests').value),
        budget: Number($('#ev-budget').value),
        currency: $('#ev-currency').value,
        brief: $('#ev-brief').value.trim(),
        ...extras,
        city: $('#ev-city').value.trim(),
        tradition: $('#ev-tradition').value.trim(),
        vibe: $('#ev-vibe').value.trim(),
      });
      form.reset();
      extras = { custom_tasks: [], split_override: null, skipped: [] };
      $('#brief-result').hidden = true;
      for (const el of form.querySelectorAll('.filled')) el.classList.remove('filled');
      onCreated(event.id);
    } catch (err) {
      error.textContent = err.message;
    } finally {
      button.disabled = false;
      button.textContent = 'Build my plan';
    }
  });
}
