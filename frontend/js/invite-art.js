// Canvas renderer for invite cards and banners: AI artwork (or a procedural fallback)
// + typography laid out per the concept's design brief. Text is drawn here, not by the
// image model, so names, dates and venues are always spelled exactly right.

export const SIZES = { invite: [1080, 1350], banner: [1500, 500] };

const HEAD = {
  serif: (s) => `700 ${s}px 'Playfair Display', Georgia, serif`,
  modern: (s) => `800 ${s}px Inter, system-ui, sans-serif`,
  playful: (s) => `600 ${s}px Fredoka, 'Trebuchet MS', sans-serif`,
  script: (s) => `400 ${Math.round(s * 1.3)}px 'Great Vibes', 'Brush Script MT', cursive`,
};
const VERSE = (s) => `italic 500 ${s}px 'Cormorant Garamond', Georgia, serif`;
const SANS = (w) => (s) => `${w} ${s}px Inter, system-ui, sans-serif`;

export async function loadFonts() {
  const specs = ["700 40px 'Playfair Display'", '800 40px Inter', '600 40px Fredoka',
    "400 40px 'Great Vibes'", "italic 500 40px 'Cormorant Garamond'", '400 40px Inter'];
  await Promise.all(specs.map((f) => document.fonts.load(f).catch(() => {})));
}

function wrap(g, text, maxWidth) {
  const out = [];
  for (const para of String(text).split('\n')) {
    let line = '';
    for (const word of para.split(/\s+/).filter(Boolean)) {
      const test = line ? `${line} ${word}` : word;
      if (g.measureText(test).width > maxWidth && line) {
        out.push(line);
        line = word;
      } else line = test;
    }
    if (line) out.push(line);
  }
  return out;
}

/** Measure (and optionally draw) a text block, shrinking until it fits maxLines. Returns height. */
function block(g, text, o, draw = true) {
  if (!text) return 0;
  let s = o.size;
  let lines;
  do {
    g.font = o.font(s);
    lines = wrap(g, text, o.width);
    if (lines.length <= o.maxLines) break;
    s -= 2;
  } while (s > (o.min || 18));
  lines = lines.slice(0, o.maxLines);
  const step = s * (o.lh || 1.2);
  if (draw) {
    g.font = o.font(s);
    g.fillStyle = o.color;
    g.textAlign = o.align;
    if ('letterSpacing' in g) g.letterSpacing = o.spacing || '0px';
    lines.forEach((l, i) => g.fillText(l, o.x, o.y + step * i + s * 0.95));
    if ('letterSpacing' in g) g.letterSpacing = '0px';
  }
  return step * lines.length;
}

/** Lay out blocks top-down from y, with gaps; returns the end y. */
function stack(g, items, x, y, width, align, draw = true) {
  let cursor = y;
  for (const it of items) {
    if (!it || !it.text) continue;
    cursor += it.gap ?? 0;
    cursor += block(g, it.text, { ...it, x, y: cursor, width: it.width || width, align }, draw);
  }
  return cursor;
}

const stackHeight = (g, items, width) => stack(g, items, 0, 0, width, 'left', false);

function cover(g, img, w, h) {
  const r = Math.max(w / img.width, h / img.height);
  const dw = img.width * r;
  const dh = img.height * r;
  g.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
}

function hexA(hex, alpha) {
  const a = Math.round(alpha * 255).toString(16).padStart(2, '0');
  return `${hex}${a}`;
}

/** Procedural backdrop when no AI artwork exists yet: glowing palette blobs. */
function proceduralBg(g, w, h, palette, light) {
  g.fillStyle = light ? '#121216' : '#fbf8f3';
  g.fillRect(0, 0, w, h);
  const spots = [[0.12, 0.08], [0.92, 0.22], [0.5, 1.02], [0.06, 0.82], [0.9, 0.9]];
  spots.forEach(([px, py], i) => {
    const c = palette[i % palette.length];
    const rg = g.createRadialGradient(w * px, h * py, 0, w * px, h * py, Math.max(w, h) * 0.5);
    rg.addColorStop(0, hexA(c, light ? 0.7 : 0.45));
    rg.addColorStop(1, hexA(c, 0));
    g.fillStyle = rg;
    g.fillRect(0, 0, w, h);
  });
}

function paintBackground(g, w, h, design, image) {
  if (image) cover(g, image, w, h);
  else proceduralBg(g, w, h, design.palette, design.text_tone === 'light');
}

/** Frosted panel behind text: blurred copy of the background plus a tint. */
function frost(g, rect, radius, tint, redraw) {
  g.save();
  g.beginPath();
  g.roundRect(rect.x, rect.y, rect.w, rect.h, radius);
  g.clip();
  if ('filter' in g) {
    g.filter = 'blur(22px)';
    redraw();
    g.filter = 'none';
  }
  g.fillStyle = tint;
  g.fillRect(rect.x, rect.y, rect.w, rect.h);
  g.restore();
}

function linear(g, x0, y0, x1, y1, stops) {
  const lg = g.createLinearGradient(x0, y0, x1, y1);
  for (const [at, color] of stops) lg.addColorStop(at, color);
  return lg;
}

// ── colour helpers: keep accents readable on the text panel (WCAG AA 4.5:1) ──
export const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const toHex = (c) => `#${c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;
const lum = (c) => {
  const [r, g, b] = c.map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };

/** Shift a palette colour toward white (on dark panels) or black (on light) until readable. */
export function readable(hex, light) {
  const base = rgb(hex);
  const panel = light ? [20, 20, 26] : [255, 250, 243];
  const toward = light ? [255, 255, 255] : [0, 0, 0];
  for (let t = 0; t <= 1.001; t += 0.05) {
    const c = base.map((v, i) => v + (toward[i] - v) * t);
    if (contrast(c, panel) >= 4.5) return toHex(c);
  }
  return light ? '#ffffff' : '#1c1917';
}

/** Small ornamental divider: lines with a diamond and two dots. */
function ornament(g, x, y, color, width = 90) {
  g.save();
  g.strokeStyle = color;
  g.fillStyle = color;
  g.lineWidth = 2;
  g.beginPath();
  g.moveTo(x - width, y); g.lineTo(x - 16, y);
  g.moveTo(x + 16, y); g.lineTo(x + width, y);
  g.stroke();
  g.beginPath();
  g.moveTo(x, y - 9); g.lineTo(x + 9, y); g.lineTo(x, y + 9); g.lineTo(x - 9, y);
  g.closePath(); g.fill();
  for (const dx of [-width - 8, width + 8]) { g.beginPath(); g.arc(x + dx, y, 3, 0, Math.PI * 2); g.fill(); }
  g.restore();
}

/** Hashtag in a rounded pill so it never disappears into the artwork. */
function pill(g, text, x, y, align, light, accent) {
  if (!text) return 0;
  g.font = SANS(700)(26);
  const w = g.measureText(text).width + 40;
  const left = align === 'center' ? x - w / 2 : x;
  g.save();
  g.shadowColor = 'transparent';
  g.fillStyle = light ? 'rgba(255,255,255,0.16)' : hexA(accent, 0.12);
  g.strokeStyle = light ? 'rgba(255,255,255,0.45)' : hexA(accent, 0.5);
  g.lineWidth = 1.5;
  g.beginPath(); g.roundRect(left, y, w, 46, 23); g.fill(); g.stroke();
  g.fillStyle = light ? '#ffffff' : accent;
  g.textAlign = 'center';
  if ('letterSpacing' in g) g.letterSpacing = '1px';
  g.fillText(text, left + w / 2, y + 32);
  if ('letterSpacing' in g) g.letterSpacing = '0px';
  g.restore();
  return 46;
}

export function drawDesign(canvas, fmt, concept, facts, image) {
  const [w, h] = SIZES[fmt];
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext('2d');
  const d = concept.design;
  const light = d.text_tone === 'light';
  const ink = light ? '#ffffff' : '#1c1917';
  const soft = light ? 'rgba(255,255,255,0.9)' : '#3f3a36';
  const tint = (a) => (light ? `rgba(14,14,18,${a})` : `rgba(255,250,243,${a})`);
  const accent = readable(d.palette[0], light);
  const accent2 = readable(d.palette[1] || d.palette[0], light);
  const head = HEAD[d.type] || HEAD.serif;
  const redraw = () => paintBackground(g, w, h, d, image);
  redraw();

  // Headline in a foil-like gradient (accent → ink), still high contrast at every stop.
  const foil = (y, height) => {
    const gr = g.createLinearGradient(0, y, 0, y + height);
    gr.addColorStop(0, light ? '#ffffff' : ink);
    gr.addColorStop(1, accent);
    return gr;
  };
  const shadowOn = () => { if (light) { g.shadowColor = 'rgba(0,0,0,0.45)'; g.shadowBlur = 14; } };
  const eyebrow = (size) => ({ text: facts.eyebrow, font: SANS(700), size, color: accent2, maxLines: 2, lh: 1.25, spacing: '5px' });
  const info = [
    { text: `🗓  ${facts.date}`, font: SANS(700), size: 36, maxLines: 2, color: ink, gap: 34 },
    facts.time && { text: `⏰  ${facts.time}`, font: SANS(500), size: 31, maxLines: 1, color: soft, gap: 12 },
    facts.venue && { text: `📍  ${facts.venue}`, font: SANS(500), size: 31, maxLines: 2, color: soft, gap: 12 },
    { text: concept.rsvp_line, font: SANS(600), size: 25, maxLines: 2, color: ink, gap: 30 },
  ].filter(Boolean);

  if (fmt === 'banner') {
    g.fillStyle = linear(g, 0, 0, w * 0.78, 0, [[0, tint(0.88)], [0.62, tint(0.6)], [1, tint(0)]]);
    g.fillRect(0, 0, w, h);
    shadowOn();
    const width = w * 0.6;
    const when = [facts.date.replace(/^\w+, /, ''), facts.time, facts.venue].filter(Boolean).join('  ·  ');
    const items = [
      eyebrow(22),
      { text: concept.banner_headline, font: head, size: 80, maxLines: 2, lh: 1.06, color: foil(150, 180), gap: 14 },
      { text: concept.banner_subline, font: SANS(500), size: 30, maxLines: 2, color: soft, gap: 12 },
      { text: when, font: SANS(700), size: 24, maxLines: 1, color: ink, gap: 18 },
    ];
    const top = (h - stackHeight(g, items, width) - 64) / 2;
    const end = stack(g, items, 110, top, width, 'left');
    pill(g, concept.hashtag, 110, end + 18, 'left', light, accent);
    g.shadowColor = 'transparent';
    // date badge
    const bx = w - 320;
    frost(g, { x: bx, y: 105, w: 220, h: 290 }, 28, tint(0.62), redraw);
    g.strokeStyle = light ? 'rgba(255,255,255,0.4)' : hexA(accent, 0.55);
    g.lineWidth = 2;
    g.beginPath(); g.roundRect(bx + 10, 115, 200, 270, 22); g.stroke();
    const dt = new Date(`${facts.iso}T00:00:00`);
    stack(g, [
      { text: dt.toLocaleDateString('en-GB', { weekday: 'short' }).toUpperCase(), font: SANS(700), size: 24, maxLines: 1, color: accent2, spacing: '4px' },
      { text: String(dt.getDate()), font: head, size: 120, maxLines: 1, color: ink, gap: 2 },
      { text: dt.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' }).toUpperCase(), font: SANS(700), size: 22, maxLines: 1, color: soft, gap: 4, spacing: '2px' },
    ], bx + 110, 140, 200, 'center');
    return;
  }

  const verse = { text: concept.verse, font: VERSE, size: 38, maxLines: 4, lh: 1.32, color: soft, gap: 30 };
  const headline = { text: concept.headline, font: head, size: 100, maxLines: 3, lh: 1.05, color: null, gap: 22 };
  const subline = { text: concept.subline, font: SANS(500), size: 34, maxLines: 2, color: soft, gap: 16 };

  if (d.layout === 'editorial') {
    const x = 100;
    const width = w - 200;
    const items = [eyebrow(24), headline, subline, verse, ...info];
    const total = stackHeight(g, items, width) + 70;
    const y = h - 100 - total;
    // Shade from just above the text block, so busy artwork never sits behind the words.
    const fade = Math.max(0, y - 160);
    g.fillStyle = linear(g, 0, fade, 0, h, [[0, tint(0)], [0.18, tint(0.82)], [1, tint(0.94)]]);
    g.fillRect(0, fade, w, h - fade);
    shadowOn();
    headline.color = foil(y, 360);
    const end = stack(g, items, x, y, width, 'left');
    pill(g, concept.hashtag, x, end + 22, 'left', light, accent);
  } else if (d.layout === 'poster') {
    // Covers headline and verse fully; artwork shows through below and around the edges.
    g.fillStyle = linear(g, 0, 0, 0, h * 0.82, [[0, tint(0.92)], [0.78, tint(0.88)], [1, tint(0)]]);
    g.fillRect(0, 0, w, h);
    shadowOn();
    const width = w - 180;
    headline.color = foil(120, 420);
    const end = stack(g, [eyebrow(26), { ...headline, size: 124 }, subline], w / 2, 110, width, 'center');
    ornament(g, w / 2, end + 34, accent);
    stack(g, [{ ...verse, size: 34, gap: 60 }], w / 2, end, width, 'center');
    g.shadowColor = 'transparent';
    const barH = 360;
    frost(g, { x: 60, y: h - barH - 60, w: w - 120, h: barH }, 32, tint(0.8), redraw);
    shadowOn();
    const bottom = info.map((it, i) => ({ ...it, gap: i === 0 ? 0 : it.gap * 0.6 }));
    const bh = stackHeight(g, bottom, w - 240) + 64;
    const bend = stack(g, bottom, w / 2, h - 60 - barH + (barH - bh) / 2, w - 240, 'center');
    pill(g, concept.hashtag, w / 2, bend + 16, 'center', light, accent);
  } else {
    // centered and framed: a centred stack; framed adds a frosted panel with a fine border.
    const width = w - (d.layout === 'framed' ? 300 : 220);
    const items = [eyebrow(24), headline, subline, verse, ...info];
    const total = stackHeight(g, items, width) + 120;
    const y = Math.max(70, (h - total) / 2);
    if (d.layout === 'framed') {
      frost(g, { x: 90, y: y - 60, w: w - 180, h: total + 120 }, 36, tint(0.7), redraw);
      g.strokeStyle = light ? 'rgba(255,255,255,0.4)' : hexA(accent, 0.6);
      g.lineWidth = 2;
      g.beginPath(); g.roundRect(108, y - 42, w - 216, total + 84, 28); g.stroke();
    } else {
      const rg = g.createRadialGradient(w / 2, h / 2, 60, w / 2, h / 2, h * 0.64);
      rg.addColorStop(0, tint(0.8));
      rg.addColorStop(1, tint(0.15));
      g.fillStyle = rg;
      g.fillRect(0, 0, w, h);
    }
    shadowOn();
    headline.color = foil(y + 60, 340);
    const end = stack(g, [eyebrow(24), headline, subline], w / 2, y, width, 'center');
    ornament(g, w / 2, end + 34, accent);
    const end2 = stack(g, [{ ...verse, gap: 60 }, ...info], w / 2, end, width, 'center');
    pill(g, concept.hashtag, w / 2, end2 + 24, 'center', light, accent);
  }
  g.shadowColor = 'transparent';
}
