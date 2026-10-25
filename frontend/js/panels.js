// Budget and Timeline panels. Pure rendering from the computed plan; event.js wires the actions.
import { currencySymbol, esc, fmtDate, money, todayIso } from './dom.js';

// Category colours; Contingency (always last) stays neutral.
const SLICE = ['#7c3aed', '#db2777', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#a855f7'];
const sliceColor = (i, n) => (i === n - 1 ? '#a1a1aa' : SLICE[i % SLICE.length]);
let currency = 'INR'; // set per render from the plan
let aiChecklist = false; // whole checklist written by AI: no per-task brief tag
const inr = (n) => money(n, currency);
const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);

/** Apply data-* driven colours/widths: CSP forbids inline style attributes, CSSOM is allowed. */
function paint(root) {
  for (const el of root.querySelectorAll('[data-color]')) el.style.setProperty('--c', el.dataset.color);
  for (const el of root.querySelectorAll('[data-w]')) el.style.width = `${el.dataset.w}%`;
}

function donut(lines, total, spentPct) {
  const C = 2 * Math.PI * 80;
  let offset = 0;
  const arcs = lines.map((line, i) => {
    const len = (line.planned / total) * C;
    const arc = `<circle cx="100" cy="100" r="80" stroke="${sliceColor(i, lines.length)}"
      stroke-dasharray="${Math.max(len - 3, 0)} ${C}" stroke-dashoffset="${-offset}"
      transform="rotate(-90 100 100)"><title>${esc(line.category)}: ${inr(line.planned)}</title></circle>`;
    offset += len;
    return arc;
  }).join('');
  return `
    <svg class="donut" viewBox="0 0 200 200" role="img" aria-label="Budget split across ${lines.length} categories, ${spentPct}% spent">
      ${arcs}
      <text x="100" y="102" text-anchor="middle" class="donut-big">${spentPct}%</text>
      <text x="100" y="122" text-anchor="middle" class="donut-sub">SPENT</text>
    </svg>`;
}

function lineStatus(line) {
  if (line.remaining < 0) return ['bad', `Over by ${inr(-line.remaining)}`];
  if (line.planned && line.spent >= 0.9 * line.planned) return ['warn', 'Almost used'];
  if (line.spent > 0) return ['ok', 'On plan'];
  return ['', 'Not started'];
}

function categoryCard(line, i, count) {
  const [cls, label] = lineStatus(line);
  const used = pct(line.spent, line.planned);
  return `
      <article class="cat-card ${line.remaining < 0 ? 'over' : ''}" data-color="${sliceColor(i, count)}">
        <header>
          <span class="cat-dot" aria-hidden="true"></span>
          <h3>${esc(line.category)}</h3>
          <span class="chip ${cls}">${label}</span>
        </header>
        <div class="cat-nums">
          <div><span>Planned</span><strong>${inr(line.planned)}</strong></div>
          <div><span>Left</span><strong class="${line.remaining < 0 ? 'neg' : ''}">${inr(line.remaining)}</strong></div>
          <div><span>Used</span><strong>${used}%</strong></div>
        </div>
        <div class="bar" role="progressbar" aria-label="${esc(line.category)} used" aria-valuemin="0"
          aria-valuemax="100" aria-valuenow="${Math.min(used, 100)}"><span class="fill" data-w="${Math.min(used, 100)}"></span></div>
        <label class="spend-field">Spent so far
          <span class="money"><span aria-hidden="true">${esc(currencySymbol(currency))}</span>
            <input id="spend-${i}" class="spend" data-category="${esc(line.category)}" type="number"
              min="0" step="500" value="${line.spent || ''}" placeholder="0" inputmode="numeric"></span>
        </label>
      </article>`;
}

export function renderBudget(panel, plan) {
  const b = plan.budget;
  currency = b.currency;
  const spentPct = pct(b.spent, b.total);
  const over = b.lines.filter((l) => l.remaining < 0 && l.category !== 'Contingency').length;
  const perGuestDelta = b.per_guest - b.benchmark_per_guest;
  const cards = b.lines.map((line, i) => categoryCard(line, i, b.lines.length)).join('');

  panel.innerHTML = `
    <div class="dark-hero budget-hero">
      <div class="bh-main">
        <p class="hero-eyebrow">Budget overview</p>
        <p class="bh-amount"><strong>${inr(b.spent)}</strong> <span>spent of ${inr(b.total)}</span></p>
        <div class="bar big" role="progressbar" aria-label="Total budget used" aria-valuemin="0" aria-valuemax="100"
          aria-valuenow="${Math.min(spentPct, 100)}"><span class="fill ${b.remaining < 0 ? 'over' : ''}" data-w="${Math.min(spentPct, 100)}"></span></div>
        <div class="hero-stats">
          <div><strong class="${b.remaining < 0 ? 'neg-light' : ''}">${inr(b.remaining)}</strong><span>remaining</span></div>
          <div><strong>${inr(b.per_guest)}</strong><span>per guest · ${perGuestDelta >= 0 ? `${inr(perGuestDelta)} above` : `${inr(-perGuestDelta)} below`} typical</span></div>
          <div><strong>${over}</strong><span>categor${over === 1 ? 'y' : 'ies'} over plan</span></div>
        </div>
      </div>
      ${donut(b.lines, b.total, spentPct)}
    </div>
    <div class="legend" aria-hidden="true">
      ${b.lines.map((l, i) => `<span data-color="${sliceColor(i, b.lines.length)}"><i></i>${esc(l.category)} · ${pct(l.planned, b.total)}%</span>`).join('')}
    </div>
    <div class="cat-grid">${cards}</div>
    ${b.note ? `<p class="budget-note">✦ ${esc(b.note)}</p>` : ''}
    <p class="muted small">Enter what you've spent or committed. Utsav flags overspends and re-scores
      the plan. ${b.designed ? '✦ Categories and shares were designed from your brief' : 'Splits follow typical market costs'};
      Contingency absorbs surprises.</p>`;
  paint(panel);
}

const STATUS = {
  done: ['ok', 'Done'], late: ['bad', 'Overdue'], soon: ['warn', 'Due soon'], upcoming: ['', 'Upcoming'],
};

function taskItem(t) {
  const d = new Date(`${t.due}T00:00:00`);
  const [cls, text] = STATUS[t.status];
  const done = t.status === 'done';
  return `
    <li class="tl-item ${t.status}">
      <time class="tl-date" datetime="${t.due}">
        <strong>${d.getDate()}</strong><span>${d.toLocaleDateString('en-GB', { month: 'short' })}</span>
      </time>
      <div class="tl-body">
        <span class="tl-title">${esc(t.title)}</span>
        <span class="tl-meta">${t.custom && !aiChecklist ? '<span class="tag">✦ from your brief</span> ' : ''}${esc(t.category)}${t.vendor ? ' · vendor booking' : ''} · ideally ${t.lead_days} days ahead</span>
      </div>
      <span class="chip ${cls}">${text}</span>
      <button type="button" class="tick" data-toggle="${t.id}" aria-pressed="${done}"
        aria-label="${done ? 'Mark not done' : 'Mark done'}: ${esc(t.title)}">✓</button>
    </li>`;
}

function runSheetHtml(event) {
  const sheet = event.run_sheet;
  const head = `
    <div class="rs-head">
      <div><h3>🗓️ Day-of run sheet · ${fmtDate(event.event_date)}</h3>
        <p class="muted small">${sheet ? `${sheet.source === 'gemini' ? 'Drafted by Gemini for this event' : 'Generic draft (offline)'}. Times marked ~ depend on local sunrise, sunset or moonrise: confirm them.`
          : 'Let AI draft the schedule for the day itself: setup, rituals, food, key moments and clean-up.'}</p></div>
      <button type="button" class="btn ${sheet ? 'ghost' : 'primary'} sm" id="runsheet-btn">${sheet ? '↻ Redraft' : '✦ Draft with AI'}</button>
    </div>`;
  if (!sheet) return `<section class="run-sheet">${head}</section>`;
  return `
    <section class="run-sheet">${head}
      <ol class="rs-list">${sheet.items.map((it) => `
        <li>
          <span class="rs-time">${esc(it.time)}</span>
          <div class="rs-body"><strong>${esc(it.title)}</strong>
            ${it.detail ? `<span class="muted small">${esc(it.detail)}</span>` : ''}</div>
          ${it.owner ? `<span class="rs-owner">${esc(it.owner)}</span>` : ''}
        </li>`).join('')}
      </ol>
    </section>`;
}

export function renderTimeline(panel, event, plan) {
  const { tasks, rescue } = plan;
  aiChecklist = plan.ai_checklist;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const count = (s) => tasks.filter((t) => t.status === s).length;
  const done = count('done');
  const today = todayIso();

  panel.innerHTML = `
    <div class="dark-hero tl-hero">
      <div>
        <p class="hero-eyebrow">Timeline</p>
        <p class="bh-amount"><strong>${plan.days_left}</strong> <span>days until ${esc(event.name)}</span></p>
        <div class="bar big" role="progressbar" aria-label="Tasks done" aria-valuemin="0" aria-valuemax="100"
          aria-valuenow="${pct(done, tasks.length)}"><span class="fill done" data-w="${pct(done, tasks.length)}"></span></div>
        <p class="hero-note">${done} of ${tasks.length} tasks done</p>
      </div>
      <div class="status-tiles">
        <div class="tile bad"><strong>${count('late')}</strong><span>Overdue</span></div>
        <div class="tile warn"><strong>${count('soon')}</strong><span>Due soon</span></div>
        <div class="tile"><strong>${count('upcoming')}</strong><span>Upcoming</span></div>
        <div class="tile ok"><strong>${done}</strong><span>Done</span></div>
      </div>
    </div>
    ${rescueHtml(rescue, byId)}
    <div class="tl">${monthGroupsHtml(tasks, today)}
      ${runSheetHtml(event)}
      <div class="tl-finale">
        <span class="finale-icon" aria-hidden="true">🎉</span>
        <div><strong>${esc(event.name)}</strong><span>${fmtDate(event.event_date)} · the big day</span></div>
      </div>
    </div>`;
  paint(panel);
}

function rescueHtml(rescue, byId) {
  if (!rescue.length) return '';
  return `
    <div class="rescue-card" role="note">
      <div class="rescue-head">
        <span class="rescue-icon" aria-hidden="true">⚡</span>
        <div><h3>Rescue plan</h3>
          <p>These are past their ideal booking window. Tackle them in this order this week:
            longest lead time first, because those vendors book out earliest.</p></div>
      </div>
      <ol class="rescue-steps">${rescue.map((id, i) => `
        <li><span class="step">${i + 1}</span><span class="rescue-title">${esc(byId[id].title)}</span>
          <button type="button" class="btn ghost sm" data-toggle="${id}" aria-pressed="false">Mark done</button></li>`).join('')}
      </ol>
    </div>`;
}

/** Tasks grouped by month, with a "Today" marker between past and future items. */
function monthGroupsHtml(tasks, today) {
  let groups = '';
  let month = '';
  let markerPlaced = false;
  for (const t of tasks) {
    const m = new Date(`${t.due}T00:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    if (m !== month) {
      groups += `${month ? '</ol>' : ''}<h3 class="tl-month">${m}</h3><ol class="tl-list">`;
      month = m;
    }
    if (!markerPlaced && t.due >= today) {
      groups += `<li class="tl-today" aria-label="Today"><span>Today · ${fmtDate(today)}</span></li>`;
      markerPlaced = true;
    }
    groups += taskItem(t);
  }
  return `${groups}</ol>`;
}

const CHECK_FILTERS = [['all', 'All'], ['open', 'To do'], ['vendor', 'Vendor bookings'], ['late', 'Overdue'], ['done', 'Done']];
const keep = {
  all: () => true,
  open: (t) => t.status !== 'done',
  vendor: (t) => t.vendor,
  late: (t) => t.status === 'late',
  done: (t) => t.status === 'done',
};

export function renderChecklist(panel, plan, filter) {
  const { tasks } = plan;
  aiChecklist = plan.ai_checklist;
  const done = tasks.filter((t) => t.status === 'done').length;
  const vendors = tasks.filter((t) => t.vendor);
  const booked = vendors.filter((t) => t.status === 'done').length;
  const late = tasks.filter((t) => t.status === 'late').length;
  const progress = pct(done, tasks.length);
  const C = 2 * Math.PI * 42;

  const cats = new Map(); // category -> tasks (Map.groupBy is too new for older Safari)
  for (const t of tasks) cats.set(t.category, [...(cats.get(t.category) || []), t]);
  const groups = [...cats].map(([cat, all], i) => checkGroupHtml(cat, all, i, filter)).join('');

  panel.innerHTML = `
    <div class="dark-hero check-hero">
      <div class="check-hero-main">
        <svg class="ring light" viewBox="0 0 100 100" role="img" aria-label="${progress}% of tasks done">
          <circle cx="50" cy="50" r="42" class="track"/>
          <circle cx="50" cy="50" r="42" class="value" stroke-dasharray="${(progress / 100) * C} ${C}"/>
          <text x="50" y="56" text-anchor="middle">${progress}%</text>
        </svg>
        <div>
          <p class="hero-eyebrow">Vendor checklist</p>
          <p class="bh-amount"><strong>${done}/${tasks.length}</strong> <span>tasks complete</span></p>
          <p class="hero-note">${late ? `${late} overdue. Start with the vendor bookings.` : 'Nothing overdue. Nice work!'}</p>
          ${aiChecklist ? '<p class="hero-note ai-note">✦ Checklist written by AI for this event</p>' : ''}
        </div>
      </div>
      <div class="status-tiles">
        <div class="tile ok"><strong>${booked}/${vendors.length}</strong><span>Vendors booked</span></div>
        <div class="tile bad"><strong>${late}</strong><span>Overdue</span></div>
      </div>
    </div>
    <div class="check-filters" role="group" aria-label="Filter tasks">
      ${CHECK_FILTERS.map(([v, l]) => `<button type="button" class="filter ${v === filter ? 'on' : ''}" data-cfilter="${v}" aria-pressed="${v === filter}">${l}</button>`).join('')}
    </div>
    <div class="check-grid">${groups || '<p class="muted empty-saved">Nothing here. Try another filter.</p>'}</div>`;
  paint(panel);
}

function checkRow(t) {
  const [cls, text] = STATUS[t.status];
  return `
    <label class="check-row ${t.status}">
      <input type="checkbox" class="check-box" id="chk-${t.id}" data-task="${t.id}" ${t.status === 'done' ? 'checked' : ''}>
      <span class="check-text">
        <span class="check-title">${esc(t.title)}${t.vendor ? '<span class="tag">vendor</span>' : ''}${t.custom && !aiChecklist ? '<span class="tag brief">✦ your brief</span>' : ''}</span>
        <span class="muted small">by ${fmtDate(t.due)}</span>
      </span>
      <span class="chip ${cls}">${text}</span>
    </label>`;
}

function checkGroupHtml(cat, all, i, filter) {
  const items = all.filter(keep[filter]);
  if (!items.length) return '';
  const catDone = all.filter((t) => t.status === 'done').length;
  return `
      <fieldset class="check-card" data-color="${SLICE[i % SLICE.length]}">
        <legend class="sr-only">${esc(cat)}</legend>
        <header>
          <span class="cat-dot" aria-hidden="true"></span>
          <h3>${esc(cat)}</h3>
          <span class="check-count">${catDone}/${all.length}</span>
        </header>
        <div class="bar" aria-hidden="true"><span class="fill" data-w="${pct(catDone, all.length)}"></span></div>
        ${items.map(checkRow).join('')}
      </fieldset>`;
}
