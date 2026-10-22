// Small DOM helpers shared by every view.

export const $ = (sel, root = document) => root.querySelector(sel);

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
/** Escape any user- or model-supplied text before it goes into innerHTML. */
export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const CURRENCIES = [
  ['INR', 'Indian rupee'], ['USD', 'US dollar'], ['EUR', 'Euro'], ['GBP', 'British pound'],
  ['AED', 'UAE dirham'], ['SAR', 'Saudi riyal'], ['SGD', 'Singapore dollar'], ['AUD', 'Australian dollar'],
  ['CAD', 'Canadian dollar'], ['NZD', 'New Zealand dollar'], ['JPY', 'Japanese yen'], ['CHF', 'Swiss franc'],
  ['ZAR', 'South African rand'], ['NGN', 'Nigerian naira'], ['KES', 'Kenyan shilling'], ['BRL', 'Brazilian real'],
  ['MXN', 'Mexican peso'], ['LKR', 'Sri Lankan rupee'], ['NPR', 'Nepalese rupee'], ['BDT', 'Bangladeshi taka'],
];
export const currencyOptions = (selected = 'INR') => CURRENCIES
  .map(([code, name]) => `<option value="${code}" ${code === selected ? 'selected' : ''}>${code} · ${name}</option>`).join('');

const formatters = new Map();
/** Whole-unit amount in the event's currency (Indian digit grouping for INR). */
export function money(n, currency = 'INR') {
  if (!formatters.has(currency)) {
    formatters.set(currency, new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en', {
      style: 'currency', currency, maximumFractionDigits: 0,
    }));
  }
  return formatters.get(currency).format(n);
}

/** "€", "$", "₹", "AED"… for input prefixes. */
export const currencySymbol = (currency) => new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en', {
  style: 'currency', currency,
}).formatToParts(0).find((p) => p.type === 'currency')?.value || currency;

export const fmtDate = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric',
  });

export const todayIso = () => new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD, local

export function showView(id) {
  for (const view of document.querySelectorAll('.view')) view.hidden = view.id !== id;
  $('#main-content').focus({ preventScroll: true });
}

let toastTimer;
export function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

/** WAI-ARIA tabs: click + arrow keys; calls onSelect(tabButton). */
export function setupTabs(tablist, onSelect) {
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  const select = (tab) => {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    }
    onSelect?.(tab);
  };
  tablist.addEventListener('click', (e) => {
    const tab = e.target.closest('[role="tab"]');
    if (tab) select(tab);
  });
  tablist.addEventListener('keydown', (e) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    const next = tabs[(tabs.indexOf(document.activeElement) + step + tabs.length) % tabs.length];
    next.focus();
    select(next);
  });
  return select;
}

/** Debounce for inputs that save to the server. */
export function debounce(fn, ms = 500) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
