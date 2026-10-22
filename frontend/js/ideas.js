// Ideas mood board: themed hero, copyable palette, saveable idea cards, share.
import { $, esc, toast } from './dom.js';

const SECTIONS = [
  ['decor', 'Decor', 'M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z'],
  ['food', 'Food & drink', 'M7 2v9M4 2v5a3 3 0 0 0 6 0V2M7 11v11M17 2c-2 1.5-3 4-3 7h3v13'],
  ['activities', 'Activities', 'M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zm12-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0z'],
  ['personal_touches', 'Personal touches', 'M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 12 5a5.5 5.5 0 0 0-10 3.5c0 2.3 1.5 4 3 5.5l7 7z'],
  ['sustainability', 'Greener choices', 'M11 20A7 7 0 0 1 4 13c0-6 7-10 16-10 0 9-4 16-10 16zM4 21c3-4 6-7 10-9'],
];
const FALLBACK_COLORS = ['#7c3aed', '#db2777', '#f97316', '#14b8a6'];

const icon = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="${d}"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// Saved ideas are a per-viewer shortlist: browser storage, failure-tolerant.
const favKey = (id) => `utsav:fav:${id}`;
function loadFavs(id) {
  try {
    return new Set(JSON.parse(localStorage.getItem(favKey(id)) || '[]'));
  } catch {
    return new Set();
  }
}
function saveFavs(id, favs) {
  try {
    localStorage.setItem(favKey(id), JSON.stringify([...favs]));
  } catch { /* storage unavailable: shortlist lasts for this page only */ }
}

let current = null; // { event, favs, savedOnly }

function colorsOf(ideas) {
  return ideas.palette.length ? ideas.palette : FALLBACK_COLORS;
}

function heroHtml(event, ideas, favs) {
  const total = SECTIONS.reduce((n, [k]) => n + (ideas[k]?.length || 0), 0);
  return `
    <div class="mood-hero">
      ${colorsOf(ideas).slice(0, 4).map((c, i) => `<span class="blob b${i}" data-color="${esc(c)}"></span>`).join('')}
      <div class="mood-content">
        <p class="mood-eyebrow">✦ Your theme · ${ideas.source === 'gemini' ? `designed by Gemini${event.brief ? ' from your brief' : ''}` : 'curated offline'}</p>
        <h2>${esc(ideas.theme)}</h2>
        <p class="mood-tagline">${esc(ideas.tagline)}</p>
        <div class="mood-palette" role="group" aria-label="Colour palette, click to copy">
          ${ideas.palette.map((c) => `
            <button type="button" class="swatch-chip" data-copy="${esc(c)}" aria-label="Copy colour ${esc(c)}">
              <span class="swatch-dot" data-color="${esc(c)}"></span>${esc(c.toUpperCase())}
            </button>`).join('')}
        </div>
        <div class="mood-stats">
          <span><strong>${total}</strong> ideas</span>
          <span><strong id="fav-count">${favs.size}</strong> saved</span>
          <span><strong>${event.guests}</strong> guests</span>
        </div>
        <div class="mood-actions">
          <button class="btn light sm" id="ideas-btn" type="button">↻ New ideas</button>
          <button class="btn glass sm" id="ideas-share" type="button">Share mood board</button>
          <button class="btn glass sm" id="ideas-saved" type="button" aria-pressed="${current.savedOnly}">
            ♥ Saved only</button>
        </div>
      </div>
    </div>`;
}

function cardsHtml(ideas, favs) {
  return SECTIONS.filter(([k]) => ideas[k]?.length).map(([k, title, path], i) => {
    const items = ideas[k].filter((x) => !current.savedOnly || favs.has(x));
    if (!items.length) return '';
    return `
      <section class="idea-card" data-color="${esc(colorsOf(ideas)[i % colorsOf(ideas).length])}">
        <header>
          <span class="idea-icon">${icon(path)}</span>
          <h3>${title}</h3>
          <span class="idea-count">${items.length}</span>
        </header>
        <ol>
          ${items.map((x, n) => `
            <li>
              <span class="idea-num" aria-hidden="true">${n + 1}</span>
              <span class="idea-text">${esc(x)}</span>
              <button type="button" class="heart" data-fav="${esc(x)}" aria-pressed="${favs.has(x)}"
                aria-label="${favs.has(x) ? 'Remove from saved' : 'Save idea'}">♥</button>
            </li>`).join('')}
        </ol>
      </section>`;
  }).join('') || '<p class="muted empty-saved">No saved ideas yet. Tap ♥ on the ideas you love.</p>';
}

export function renderIdeas(event) {
  const panel = $('#panel-ideas');
  const ideas = event.ideas;
  if (current?.event.id !== event.id) current = { event, favs: loadFavs(event.id), savedOnly: false };
  current.event = event;
  if (!ideas) {
    panel.innerHTML = `
      <div class="empty-ideas">
        <span class="big" aria-hidden="true">✦</span>
        <h2>Ideas made for ${esc(event.name)}</h2>
        <p>Get a theme, colour palette, menu, activities and personal touches designed for
          <strong>${esc(event.name)}</strong>, shaped by your tradition, vibe and budget.</p>
        <button class="btn primary" id="ideas-btn" type="button">✨ Generate ideas</button>
      </div>`;
    return;
  }
  panel.innerHTML = `${heroHtml(event, ideas, current.favs)}<div class="idea-grid">${cardsHtml(ideas, current.favs)}</div>`;
  // CSP forbids inline style attributes; CSSOM assignment is allowed (values are validated hex).
  for (const el of panel.querySelectorAll('.blob, .swatch-dot')) el.style.background = el.dataset.color;
  for (const el of panel.querySelectorAll('.idea-card')) el.style.setProperty('--c', el.dataset.color);
}

async function shareBoard() {
  const { event } = current;
  const { ideas } = event;
  const picks = SECTIONS.filter(([k]) => ideas[k]?.length)
    .map(([k, title]) => `${title}: ${[...current.favs].find((f) => ideas[k].includes(f)) || ideas[k][0]}`);
  const text = `${ideas.theme} for ${event.name}\n${ideas.tagline}\n\n${picks.join('\n')}\n\nPlanned with Utsav`;
  try {
    if (navigator.share) await navigator.share({ title: ideas.theme, text });
    else {
      await navigator.clipboard.writeText(text);
      toast('Mood board copied, ready to paste anywhere');
    }
  } catch (err) {
    if (err?.name !== 'AbortError') toast('Could not share the mood board');
  }
}

export function bindIdeas(onGenerate) {
  $('#panel-ideas').addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn || !current) return;
    if (btn.id === 'ideas-btn') onGenerate(btn);
    else if (btn.id === 'ideas-share') shareBoard();
    else if (btn.id === 'ideas-saved') {
      current.savedOnly = !current.savedOnly;
      renderIdeas(current.event);
      $('#ideas-saved').focus();
    } else if (btn.dataset.copy) {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
        toast(`Copied ${btn.dataset.copy.toUpperCase()}`);
      } catch {
        toast(btn.dataset.copy.toUpperCase());
      }
    } else if (btn.dataset.fav != null) {
      const idea = btn.dataset.fav;
      const { favs } = current;
      if (favs.has(idea)) favs.delete(idea);
      else favs.add(idea);
      saveFavs(current.event.id, favs);
      btn.setAttribute('aria-pressed', String(favs.has(idea)));
      btn.setAttribute('aria-label', favs.has(idea) ? 'Remove from saved' : 'Save idea');
      btn.classList.toggle('pop', favs.has(idea));
      $('#fav-count').textContent = favs.size;
      if (current.savedOnly) renderIdeas(current.event);
    }
  });
}
