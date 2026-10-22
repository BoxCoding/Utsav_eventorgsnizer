// Invites: three AI concepts, AI-painted artwork, and bulk WhatsApp / email sharing.
import { api, imageUrl, whatsappStatus } from './api.js';
import { $, esc, toast } from './dom.js';
import { drawDesign, loadFonts } from './invite-art.js';

const TONES = [['elegant', 'Elegant'], ['fun', 'Fun'], ['formal', 'Formal'], ['minimal', 'Minimal']];
const LAYOUT_NAME = { centered: 'Centred', editorial: 'Editorial', framed: 'Framed', poster: 'Poster' };
const TYPE_NAME = { serif: 'Serif', modern: 'Modern sans', playful: 'Playful', script: 'Script' };

// { event, save, signature, edits, concept, art: Map(key -> version), images: Map(key -> Image), painting }
let ctx = null;
const concept = () => ctx.event.invite.concepts[ctx.concept];

// ── guest list parsing & message personalisation ─────────────────────────
/** "Meera Shah, meera@x.com, +91 98765 43210" -> { name, email, phone } (one guest per line). */
export function parseGuests(text) {
  return text.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
    const parts = line.split(/[,;\t]/).map((p) => p.trim()).filter(Boolean);
    const email = parts.find((p) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p)) || '';
    const phone = parts.find((p) => /^\+?[0-9 ()-]{6,24}$/.test(p)) || '';
    const name = parts.find((p) => p !== email && p !== phone) || email || phone;
    return { name: name.slice(0, 80), email, phone };
  });
}

const firstName = (name) => name.split(/\s+/)[0];
const personalise = (text, guest) => text.replaceAll('{name}', guest ? firstName(guest.name) : 'friends');

function waNumber(phone, countryCode) {
  if (!phone) return '';
  const digits = phone.replace(/\D/g, '');
  return phone.trim().startsWith('+') ? digits : `${countryCode.replace(/\D/g, '')}${digits.replace(/^0+/, '')}`;
}

const waLink = (guest, text, cc) => `https://wa.me/${waNumber(guest.phone, cc)}?text=${encodeURIComponent(personalise(text, guest))}`;
const mailLink = (to, subject, body, bcc = '') => `mailto:${encodeURIComponent(to)}?${bcc ? `bcc=${encodeURIComponent(bcc)}&` : ''}subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

function csvCell(value) {
  let v = String(value ?? '');
  if (/^[=+\-@]/.test(v)) v = `'${v}`; // neutralise spreadsheet formula injection
  return `"${v.replaceAll('"', '""')}"`;
}

// ── rendering ─────────────────────────────────────────────────────────────
function formHtml(event) {
  const d = event.invite?.details || {};
  const tone = d.tone || 'elegant';
  return `
    <form class="invite-form" id="invite-form">
      <div class="tone-row" role="radiogroup" aria-label="Tone">
        ${TONES.map(([v, l]) => `<label class="tone"><input type="radio" name="tone" value="${v}" ${v === tone ? 'checked' : ''}><span>${l}</span></label>`).join('')}
      </div>
      <div class="invite-fields">
        <label>Hosted by <input id="inv-host" maxlength="100" value="${esc(d.host || '')}" placeholder="Asha & Rohan, the Mehta family…"></label>
        <label>Venue <input id="inv-venue" maxlength="150" value="${esc(d.venue || '')}" placeholder="Venue name and area"></label>
        <label>Time <input id="inv-time" maxlength="60" value="${esc(d.time || '')}" placeholder="7:00 pm onwards"></label>
        <label>RSVP <input id="inv-rsvp" maxlength="150" value="${esc(d.rsvp || '')}" placeholder="By 20 Dec to +91 98765 43210"></label>
      </div>
      <button class="btn primary" type="submit" id="invite-btn">✦ ${event.invite ? 'New concepts' : 'Design my invites'}</button>
      <p class="muted small">${event.brief ? 'Leave a box blank and Utsav takes it from your brief. ' : ''}Only details you have given are used. Nothing is invented.</p>
    </form>`;
}

const WA_STATUS = { sent: '✓ Sent', delivered: '✓✓ Delivered', read: '✓✓ Read', failed: '⚠ Failed' };

function waBusinessHtml(guests) {
  const phones = guests.filter((g) => g.phone).length;
  if (!ctx.waConnected) {
    return `<p class="wa-api off small"><span class="dot" aria-hidden="true"></span>WhatsApp Business API not connected. Using one-tap WhatsApp links below.</p>`;
  }
  const pending = guests.filter((g) => g.phone && !['sent', 'delivered', 'read'].includes(g.wa_status)).length;
  return `
    <div class="wa-api on">
      <p class="small"><span class="dot" aria-hidden="true"></span><strong>WhatsApp Business connected.</strong>
        Sends the ${ctx.art.has(`${ctx.concept}-poster`) ? 'AI poster' : 'invite card'} with each guest's personal message, then tracks delivery and reads.</p>
      <button class="btn wa-btn sm" type="button" id="wa-api-send" ${pending && !ctx.waSending ? '' : 'disabled'}>
        ${ctx.waSending ? '<span class="spinner" aria-hidden="true"></span> Sending…' : `📲 Send to ${pending} of ${phones} on WhatsApp`}</button>
    </div>`;
}

function guestsHtml(event) {
  const guests = event.guest_list || [];
  const sent = guests.filter((g) => g.sent_wa || g.sent_email).length;
  const text = guests.map((g) => [g.name, g.email, g.phone].filter(Boolean).join(', ')).join('\n');
  return `
    <section class="inv-section">
      <div class="inv-head">
        <div><h3>Guest list & bulk sending</h3>
          <p class="muted small">One guest per line: name, email and/or phone. Messages are personalised with each first name.</p></div>
        <span class="chip ${sent && sent === guests.length ? 'ok' : ''}">${sent} of ${guests.length} sent</span>
      </div>
      <div class="guest-input">
        <label class="sr-only" for="guest-text">Guest list</label>
        <textarea id="guest-text" rows="5" placeholder="Meera Shah, meera@example.com, +91 98765 43210&#10;Daniel Costa, +351 912 345 678&#10;Priya, priya@example.com">${esc(text)}</textarea>
        <div class="guest-controls">
          <label>Default country code <input id="guest-cc" value="${esc(ctx.edits.cc ?? '+91')}" maxlength="5" inputmode="tel"></label>
          <button class="btn ghost" type="button" id="guest-save">Save guest list</button>
        </div>
      </div>
      ${guests.length ? `
      ${waBusinessHtml(guests)}
      <div class="bulk-bar">
        <button class="btn primary sm" type="button" id="bulk-email">✉ Email all (BCC)</button>
        <button class="btn ghost sm" type="button" id="bulk-wa">Copy all WhatsApp messages</button>
        <button class="btn ghost sm" type="button" id="bulk-csv">Download CSV for mail merge</button>
      </div>
      <ul class="guest-list">
        ${guests.map((g, i) => `
          <li>
            <span class="g-avatar" aria-hidden="true">${esc(g.name.slice(0, 1).toUpperCase())}</span>
            <div class="g-main"><strong>${esc(g.name)}</strong>
              <span class="muted small">${esc([g.email, g.phone].filter(Boolean).join(' · ') || 'No contact')}</span>
              ${g.wa_status ? `<span class="wa-status ${g.wa_status}">${WA_STATUS[g.wa_status]}</span>` : ''}</div>
            <button type="button" class="send wa ${g.sent_wa ? 'sent' : ''}" data-send="wa" data-i="${i}" ${g.phone ? '' : 'disabled'}
              aria-label="WhatsApp ${esc(g.name)}">${g.sent_wa ? '✓ ' : ''}WhatsApp</button>
            <button type="button" class="send em ${g.sent_email ? 'sent' : ''}" data-send="email" data-i="${i}" ${g.email ? '' : 'disabled'}
              aria-label="Email ${esc(g.name)}">${g.sent_email ? '✓ ' : ''}Email</button>
          </li>`).join('')}
      </ul>` : ''}
    </section>`;
}

function conceptsHtml(inv) {
  return `
    <section class="inv-section">
      <div class="inv-head">
        <div><h3>Pick a concept</h3>
          <p class="muted small">${inv.source === 'gemini' ? 'Three directions designed by Gemini' : 'Three starter directions (offline)'}. Each has its own copy, verse, type and colour story.</p></div>
      </div>
      <div class="concepts" role="radiogroup" aria-label="Invite concepts">
        ${inv.concepts.map((c, i) => `
          <button type="button" class="concept ${i === ctx.concept ? 'on' : ''}" role="radio" aria-checked="${i === ctx.concept}" data-concept="${i}">
            <span class="concept-palette">${c.design.palette.map((p) => `<i data-color="${esc(p)}"></i>`).join('')}</span>
            <span class="concept-name type-${c.design.type}">${esc(c.name)}</span>
            <span class="concept-angle">${esc(c.angle)}</span>
            <span class="concept-verse">${esc(c.verse.split('\n').slice(0, 2).join(' / '))}</span>
            <span class="concept-meta">${LAYOUT_NAME[c.design.layout]} · ${TYPE_NAME[c.design.type]} · ${esc(c.hashtag)}</span>
          </button>`).join('')}
      </div>
    </section>`;
}

const FORMATS = ['poster', 'invite', 'banner'];

function isPainted(i = ctx.concept) {
  return FORMATS.every((f) => ctx.art.has(`${i}-${f}`) || (f === 'poster' && ctx.posterFailed.has(i)));
}

function posterHtml(c) {
  const key = `${ctx.concept}-poster`;
  const has = ctx.art.has(key);
  const body = has
    ? `<img id="poster-img" data-src="/api/events/${ctx.event.id}/invite/art/${key}?v=${ctx.art.get(key)}" alt="AI poster: ${esc(ctx.event.name)}, ${esc(c.headline)}">`
    : `<div class="poster-empty">${ctx.painting
      ? '<span class="spinner" aria-hidden="true"></span><p>Gemini is illustrating your poster and proof-reading every detail…</p>'
      : ctx.posterFailed.has(ctx.concept)
        ? '<p>The AI poster could not get every detail exactly right, so it was not used. Your card and banner are exact. Try <b>Repaint</b>.</p>'
        : '<p>A fully illustrated poster with your title, highlights, date, time and venue.</p>'}</div>`;
  return `
    <figure class="design poster-design ${ctx.painting && !has ? 'busy' : ''}">
      ${body}
      <figcaption><span>AI poster · proof-read ${has ? '✓' : ''}</span>
        ${has ? `<span class="d-actions"><button class="btn ghost sm" type="button" data-dl="poster">Download</button>
        <button class="btn ghost sm" type="button" data-share-img="poster">Share</button></span>` : ''}</figcaption>
    </figure>`;
}

function designsHtml() {
  const c = concept();
  const painted = isPainted();
  return `
    <section class="inv-section">
      <div class="inv-head">
        <div><h3>${esc(c.name)}</h3><p class="muted small">${painted ? 'Artwork painted by Gemini.' : 'Preview. Paint custom AI artwork for this concept.'} The poster is illustrated by Gemini and proof-read against your details; the card and banner text is set by Utsav, so it is always exact.</p></div>
        <button type="button" class="btn primary paint-btn" id="paint-btn" ${ctx.painting ? 'disabled' : ''}>
          ${ctx.painting ? '<span class="spinner" aria-hidden="true"></span> Painting artwork…' : painted ? '↻ Repaint artwork' : '🎨 Paint AI artwork'}</button>
      </div>
      <div class="designs">
        ${posterHtml(c)}
        <div class="design-stack">
        <figure class="design invite-design ${ctx.painting ? 'busy' : ''}">
          <canvas id="cv-invite" role="img" aria-label="Invitation card: ${esc(c.headline)}"></canvas>
          <figcaption><span>Invite card · 1080×1350</span>
            <span class="d-actions"><button class="btn ghost sm" type="button" data-dl="invite">Download</button>
            <button class="btn ghost sm" type="button" data-share-img="invite">Share</button></span></figcaption>
        </figure>
        <figure class="design banner-design ${ctx.painting ? 'busy' : ''}">
          <canvas id="cv-banner" role="img" aria-label="Event banner: ${esc(c.banner_headline)}"></canvas>
          <figcaption><span>Banner · 1500×500</span>
            <span class="d-actions"><button class="btn ghost sm" type="button" data-dl="banner">Download</button>
            <button class="btn ghost sm" type="button" data-share-img="banner">Share</button></span></figcaption>
          <blockquote class="verse-card"><p>${esc(c.verse)}</p><cite>${esc(c.hashtag)}</cite></blockquote>
        </figure>
        </div>
      </div>
    </section>`;
}

function messagesHtml() {
  const c = concept();
  const edit = (key, fallback) => esc(ctx.edits[key] ?? fallback);
  return `
    <section class="inv-section messages">
      <div class="msg-card">
        <div class="msg-title"><span class="msg-icon em" aria-hidden="true">✉</span><h3>Email</h3>
          <button type="button" class="link-btn" data-copy-field="email">Copy</button></div>
        <label>Subject <input id="msg-subject" value="${edit('subject', c.email_subject)}"></label>
        <label>Message <textarea id="msg-email" rows="9">${edit('email', c.email_body)}</textarea></label>
      </div>
      <div class="msg-card">
        <div class="msg-title"><span class="msg-icon wa" aria-hidden="true">💬</span><h3>WhatsApp</h3>
          <button type="button" class="link-btn" data-copy-field="wa">Copy</button></div>
        <label>Message <textarea id="msg-wa" rows="9">${edit('wa', c.whatsapp)}</textarea></label>
        <p class="muted small"><code>{name}</code> becomes each guest's first name when you send.</p>
      </div>
    </section>`;
}

function facts() {
  const { event } = ctx;
  const d = event.invite.details;
  return {
    eyebrow: event.name.toUpperCase(), // the message starts with what the event is
    date: new Date(`${event.event_date}T00:00:00`).toLocaleDateString('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    }),
    time: d.time,
    venue: d.venue,
    iso: event.event_date,
  };
}

function loadImage(key) {
  if (ctx.images.has(key)) return ctx.images.get(key);
  const p = new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    imageUrl(`/api/events/${ctx.event.id}/invite/art/${key}?v=${ctx.art.get(key)}`)
      .then((url) => { img.src = url; }, () => resolve(null));
  });
  ctx.images.set(key, p);
  return p;
}

async function drawAll() {
  if (!ctx.event.invite?.concepts?.length) return; // none yet, or a pre-concepts invite
  await loadFonts();
  const c = concept();
  const f = facts();
  for (const fmt of ['invite', 'banner']) {
    const key = `${ctx.concept}-${fmt}`;
    const img = ctx.art.has(key) ? await loadImage(key) : null;
    const canvas = $(`#cv-${fmt}`);
    if (canvas) drawDesign(canvas, fmt, c, f, img);
  }
  for (const el of $('#panel-invites').querySelectorAll('[data-color]')) el.style.background = el.dataset.color;
  const poster = $('#poster-img');
  if (poster) imageUrl(poster.dataset.src).then((url) => { poster.src = url; }, () => {});
}

function renderBody() {
  const { event } = ctx;
  const inv = event.invite;
  $('#panel-invites').innerHTML = `
    <div class="dark-hero invite-hero">
      <div>
        <p class="hero-eyebrow">Invites & sharing · powered by Gemini</p>
        <p class="bh-amount"><strong>Invitations people remember</strong></p>
        <p class="hero-note">Three creative concepts with original verse, custom AI-painted artwork, and ready-to-send email and WhatsApp messages for your whole guest list.</p>
      </div>
    </div>
    ${formHtml(event)}
    ${inv?.concepts?.length ? `${conceptsHtml(inv)}${designsHtml()}${messagesHtml()}${guestsHtml(event)}` : ''}`;
  drawAll();
}

export function renderInvites(event) {
  const signature = JSON.stringify([event.id, event.invite, event.guest_list, event.event_date]);
  if (ctx?.signature === signature) {
    ctx.event = event;
    return; // nothing invite-related changed: keep in-progress edits
  }
  const same = ctx?.event?.id === event.id;
  const sameInvite = same && JSON.stringify(ctx.event.invite) === JSON.stringify(event.invite);
  ctx = {
    ...ctx, event, signature,
    edits: sameInvite ? ctx.edits : {},
    concept: sameInvite ? ctx.concept : 0,
    art: sameInvite ? ctx.art : new Map(),
    images: sameInvite ? ctx.images : new Map(),
    painting: sameInvite ? ctx.painting : false,
    posterFailed: sameInvite ? ctx.posterFailed : new Set(),
  };
  renderBody();
  whatsappStatus().then((on) => {
    if (on !== Boolean(ctx.waConnected)) {
      ctx.waConnected = on;
      renderBody();
    }
  });
  if (event.invite?.concepts && !sameInvite) {
    // Artwork painted in an earlier session is stored server-side.
    api('GET', `/api/events/${event.id}/invite/art`).then(({ art }) => {
      if (ctx.event.id !== event.id) return;
      for (const key of art) ctx.art.set(key, 1);
      if (!isPainted() && !ctx.painting && event.invite.source === 'gemini') paint();
      else if (art.length) renderBody();
    }).catch(() => {});
  }
}

async function paint() {
  const { event } = ctx;
  const idx = ctx.concept;
  ctx.painting = true;
  renderBody();
  ctx.posterFailed.delete(idx);
  const results = await Promise.allSettled(FORMATS.map((format) =>
    api('POST', `/api/events/${event.id}/invite/art`, { concept: idx, format })));
  results.forEach((r, i) => {
    if (r.status === 'fulfilled') {
      const { key } = r.value;
      ctx.art.set(key, (ctx.art.get(key) || 0) + 1);
      ctx.images.delete(key);
    } else if (FORMATS[i] === 'poster') ctx.posterFailed.add(idx); // don't auto-retry it
  });
  ctx.painting = false;
  if (ctx.event.id !== event.id) return;
  const failed = results.find((r) => r.status === 'rejected');
  toast(failed ? failed.reason.message : 'Poster, card and banner painted ✨');
  renderBody();
}

async function designFile(fmt) {
  const name = `${ctx.event.name}-${fmt}`;
  if (fmt !== 'poster') return canvasFile(`#cv-${fmt}`, `${name}.png`);
  const blob = await (await fetch($('#poster-img').src)).blob();
  return new File([blob], `${name}.${blob.type.split('/')[1] || 'png'}`, { type: blob.type });
}

function canvasFile(id, name) {
  return new Promise((resolve) => {
    $(id).toBlob((blob) => resolve(new File([blob], name, { type: 'image/png' })), 'image/png');
  });
}

// ── actions ───────────────────────────────────────────────────────────────
async function sendViaWhatsApp() {
  const { event } = ctx;
  const poster = ctx.art.has(`${ctx.concept}-poster`);
  const body = { message: messages().wa, country_code: $('#guest-cc').value, concept: ctx.concept,
    image: poster ? 'poster' : 'card' };
  if (!poster) body.card_png = $('#cv-invite').toDataURL('image/png').split(',')[1];
  ctx.waSending = true;
  renderBody();
  try {
    const res = await api('POST', `/api/events/${event.id}/whatsapp/invite`, body);
    event.guest_list = res.guest_list;
    toast(res.failed ? `Sent ${res.sent}; ${res.failed} failed: ${res.errors.join('; ')}`
      : `Sent to ${res.sent} guest${res.sent === 1 ? '' : 's'} on WhatsApp ✓`);
  } catch (err) {
    toast(err.message);
  } finally {
    ctx.waSending = false;
    if (ctx.event.id === event.id) renderBody();
  }
}

function messages() {
  return { subject: $('#msg-subject').value, email: $('#msg-email').value, wa: $('#msg-wa').value };
}

async function copy(text, done) {
  try {
    await navigator.clipboard.writeText(text);
    toast(done);
  } catch {
    toast('Copy failed: your browser blocked clipboard access');
  }
}

function markSent(i, field) {
  const guests = ctx.event.guest_list.map((g, n) => (n === i ? { ...g, [field]: true } : g));
  ctx.save({ guest_list: guests });
}

export function bindInvites(save) {
  ctx = { save };
  const panel = $('#panel-invites');
  const editable = { 'msg-subject': 'subject', 'msg-email': 'email', 'msg-wa': 'wa', 'guest-cc': 'cc' };
  panel.addEventListener('input', (e) => {
    if (editable[e.target.id]) ctx.edits[editable[e.target.id]] = e.target.value;
  });
  panel.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#invite-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Designing three concepts…';
    try {
      const { invite } = await api('POST', `/api/events/${ctx.event.id}/invite`, {
        tone: panel.querySelector('input[name="tone"]:checked').value,
        host: $('#inv-host').value.trim(),
        venue: $('#inv-venue').value.trim(),
        time: $('#inv-time').value.trim(),
        rsvp: $('#inv-rsvp').value.trim(),
      });
      ctx.event.invite = invite; // same object as the event view's state
      renderInvites(ctx.event);
      if (invite.source === 'gemini') {
        toast('Three concepts ready. Painting artwork for the first one…');
        paint();
      } else toast('Three concepts ready');
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  });

  panel.addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const { event } = ctx;
    if (btn.dataset.concept) {
      ctx.concept = Number(btn.dataset.concept);
      ctx.edits = { cc: ctx.edits.cc }; // messages follow the chosen concept
      renderBody();
      $(`[data-concept="${ctx.concept}"]`).focus();
      // Show every concept as finished artwork, not a flat preview.
      if (!isPainted() && !ctx.painting && event.invite.source === 'gemini') paint();
    } else if (btn.id === 'paint-btn') {
      paint();
    } else if (btn.dataset.dl) {
      const file = await designFile(btn.dataset.dl);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(file);
      a.download = file.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } else if (btn.dataset.shareImg) {
      const file = await designFile(btn.dataset.shareImg);
      if (navigator.canShare?.({ files: [file] })) {
        navigator.share({ files: [file], text: personalise(messages().wa, null) }).catch(() => {});
      } else toast('Image sharing works on phones. Use Download here, then attach it.');
    } else if (btn.dataset.copyField) {
      const m = messages();
      copy(btn.dataset.copyField === 'email' ? `${m.subject}\n\n${m.email}` : m.wa, 'Message copied');
    } else if (btn.id === 'guest-save') {
      const old = new Map((event.guest_list || []).map((g) => [`${g.name}|${g.email}|${g.phone}`, g]));
      const guests = parseGuests($('#guest-text').value).map((g) => ({
        ...g, ...(old.get(`${g.name}|${g.email}|${g.phone}`) || {}), // keep sent status
      }));
      ctx.save({ guest_list: guests });
      toast(`${guests.length} guest${guests.length === 1 ? '' : 's'} saved`);
    } else if (btn.dataset.send) {
      const i = Number(btn.dataset.i);
      const g = event.guest_list[i];
      const m = messages();
      if (btn.dataset.send === 'wa') {
        window.open(waLink(g, m.wa, $('#guest-cc').value), '_blank', 'noopener');
        markSent(i, 'sent_wa');
      } else {
        window.location.href = mailLink(g.email, personalise(m.subject, g), personalise(m.email, g));
        markSent(i, 'sent_email');
      }
    } else if (btn.id === 'bulk-email') {
      const emails = event.guest_list.filter((g) => g.email).map((g) => g.email);
      const m = messages();
      const link = mailLink('', personalise(m.subject, null), personalise(m.email, null), emails.join(','));
      if (!emails.length) toast('No guest emails yet');
      else if (link.length > 1900) toast('Too many guests for one email link. Use the CSV with your mail-merge tool.');
      else {
        window.location.href = link;
        ctx.save({ guest_list: event.guest_list.map((g) => (g.email ? { ...g, sent_email: true } : g)) });
      }
    } else if (btn.id === 'bulk-wa') {
      const m = messages();
      const cc = $('#guest-cc').value;
      const all = event.guest_list.filter((g) => g.phone)
        .map((g) => `${g.name} (${g.phone}): ${waLink(g, m.wa, cc)}\n${personalise(m.wa, g)}`).join('\n\n');
      copy(all, 'All WhatsApp messages copied, each with its send link');
    } else if (btn.id === 'wa-api-send') {
      sendViaWhatsApp();
    } else if (btn.id === 'bulk-csv') {
      const m = messages();
      const cc = $('#guest-cc').value;
      const rows = [['name', 'email', 'phone', 'email_subject', 'email_body', 'whatsapp_message', 'whatsapp_link']]
        .concat(event.guest_list.map((g) => [g.name, g.email, g.phone, personalise(m.subject, g),
          personalise(m.email, g), personalise(m.wa, g), g.phone ? waLink(g, m.wa, cc) : '']));
      const blob = new Blob([rows.map((r) => r.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${event.name}-guests.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
  });
}
