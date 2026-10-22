// "Your brief" card: edit the free-text brief and re-plan the event from it.
// Gemini re-reads the brief (event type stays fixed); the user picks which changes to apply.
import { api } from './api.js';
import { $, esc, fmtDate, money, toast } from './dom.js';

const LABELS = {
  name: 'Name', event_date: 'Date', guests: 'Guests', budget: 'Budget', currency: 'Currency',
  city: 'City', tradition: 'Tradition', vibe: 'Vibe',
};

let ctx = { event: null, save: null, proposal: null, signature: null };

function show(key, value, currency) {
  if (value == null || value === '') return '—';
  if (key === 'event_date') return fmtDate(value);
  if (key === 'budget') return money(value, currency);
  return String(value);
}

export function renderBriefCard(event) {
  ctx.event = event;
  const signature = `${event.id}|${event.brief}`;
  if (ctx.signature === signature) return; // keep in-progress edits and preview
  ctx.signature = signature;
  ctx.proposal = null;
  const count = (event.custom_tasks || []).length;
  $('#brief-edit').value = event.brief || '';
  $('#brief-sub').textContent = event.brief
    ? `${count} personalised task${count === 1 ? '' : 's'} from your words`
    : 'Describe the event in your own words to personalise this plan';
  $('#replan-preview').hidden = true;
}

function showPreview(result) {
  const { event } = ctx;
  ctx.proposal = result;
  const currency = result.fields.currency || event.currency;
  const changes = Object.entries(result.fields)
    .filter(([k, v]) => k in LABELS && v != null && String(v) !== String(event[k] ?? ''));
  const oldTitles = new Set((event.custom_tasks || []).map((t) => t.title));
  const newTitles = new Set(result.custom_tasks.map((t) => t.title));
  const added = result.custom_tasks.filter((t) => !oldTitles.has(t.title));
  const removed = (event.custom_tasks || []).filter((t) => !newTitles.has(t.title));
  const oldCats = new Set(Object.keys(ctx.event.split_override || {}));
  const cats = result.split ? Object.entries(result.split) : [];
  const newCats = new Set(cats.map(([c]) => c));
  const droppedCats = [...oldCats].filter((c) => !newCats.has(c));
  const oldSkip = new Set(event.skipped || []);
  const newSkip = (result.skipped || []).filter((id) => !oldSkip.has(id));
  const box = $('#replan-preview');
  box.hidden = false;
  box.innerHTML = `
    <div class="br-head"><strong>✦ Proposed changes</strong>
      <span class="pill">${result.source === 'gemini' ? 'Read by Gemini' : 'Offline reading'}</span></div>
    ${result.summary.length ? `<ul class="br-summary">${result.summary.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${result.suggestions?.length ? `<div class="br-suggest"><p class="br-label">💡 Utsav suggests</p>
      <ul>${result.suggestions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
    ${changes.length ? `<p class="br-label">Event details</p>
      <ul class="rp-changes">${changes.map(([k, v]) => `
        <li><label><input type="checkbox" data-field="${k}" checked>
          <span class="rp-field">${LABELS[k]}</span>
          <span class="rp-old">${esc(show(k, event[k], event.currency))}</span>
          <span aria-hidden="true">→</span><span class="sr-only">to</span>
          <span class="rp-new">${esc(show(k, v, currency))}</span></label></li>`).join('')}
      </ul>` : '<p class="muted small">No changes to the event details.</p>'}
    ${added.length || removed.length ? `<p class="br-label">Personalised tasks</p>
      <ul class="rp-tasks">
        ${added.map((t) => `<li class="add"><b aria-label="added">+</b> ${esc(t.title)} <small>${esc(t.category)} · ${t.lead_days} days before</small></li>`).join('')}
        ${removed.map((t) => `<li class="rm"><b aria-label="removed">−</b> ${esc(t.title)}</li>`).join('')}
      </ul>` : ''}
    ${cats.length ? `<p class="br-label">Budget categories</p>
      <div class="br-split">${cats.map(([c, v]) => `<span class="${oldCats.size && !oldCats.has(c) ? 'new' : ''}"><b>${Math.round(v * 100)}%</b>${esc(c)}</span>`).join('')}
        ${droppedCats.map((c) => `<span class="gone">${esc(c)}</span>`).join('')}</div>
      ${droppedCats.length ? '<p class="muted small">Spend recorded on removed categories will be cleared.</p>' : ''}` : ''}
    ${newSkip.length > 5 ? `<p class="br-label">Checklist</p>
      <p class="muted small">The generic ${esc(ctx.event.kind)} checklist (${newSkip.length} tasks) is replaced by the ${result.custom_tasks.length} tasks above, written for this event. Ticks on removed tasks are cleared.</p>`
    : newSkip.length ? `<p class="br-label">Standard tasks to drop</p>
      <div class="br-skip">${newSkip.map((id) => `<span>${esc(id.replaceAll('-', ' '))}</span>`).join('')}</div>` : ''}
    <div class="rp-actions">
      <button type="button" class="btn primary" id="replan-apply">Apply changes</button>
      <button type="button" class="btn ghost" id="replan-cancel">Cancel</button>
    </div>`;
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function apply() {
  const { proposal } = ctx;
  const fields = { brief: $('#brief-edit').value.trim(), custom_tasks: proposal.custom_tasks };
  if (proposal.split) fields.split_override = proposal.split;
  if (proposal.skipped) fields.skipped = proposal.skipped;
  for (const box of $('#replan-preview').querySelectorAll('input[data-field]:checked')) {
    fields[box.dataset.field] = proposal.fields[box.dataset.field];
  }
  if (await ctx.save(fields)) {
    ctx.signature = null; // show the card fresh from the saved event
    renderBriefCard(ctx.event);
    toast('Plan updated from your brief');
  }
}

export function bindBriefCard(save) {
  ctx.save = save;
  $('#replan-btn').addEventListener('click', async () => {
    const brief = $('#brief-edit').value.trim();
    if (brief.length < 15) {
      toast('Tell Utsav a little more about your event first');
      return;
    }
    const btn = $('#replan-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Re-reading your brief…';
    try {
      showPreview(await api('POST', `/api/events/${ctx.event.id}/replan`, { brief }));
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '✦ Re-plan from brief';
    }
  });
  $('#replan-preview').addEventListener('click', (e) => {
    if (e.target.id === 'replan-apply') apply();
    if (e.target.id === 'replan-cancel') {
      ctx.proposal = null;
      $('#replan-preview').hidden = true;
    }
  });
}
