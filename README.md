# Utsav (उत्सव) — GenAI Event Planning Assistant

> Plan weddings, birthdays and community events with budgets that always add up, timelines that warn you early, vendor checklists, and AI ideas shaped by your traditions.

## Judging criteria → evidence

| Criterion | Evidence (all reproducible with `scripts/check.sh`) |
|---|---|
| **Problem statement alignment** | Every requirement (weddings, birthdays and community events; budgets; timelines; vendor checklists; personalised ideas) is mapped to a feature in the table below. |
| **Code quality** | Modular FastAPI routers and services. Vanilla ES modules with no build step. `ruff` and `eslint` (recommended rules plus `eqeqeq`, `prefer-const` and no unused variables) are clean. Schemas are validated at every boundary. CI runs it all (`.github/workflows/ci.yml`). |
| **Security** | PBKDF2 passwords and hashed session tokens. httpOnly SameSite cookies on the web, bearer tokens in the app, and a CORS allow-list. CSRF Origin check, strict CSP and HSTS. Per-user quotas on AI and WhatsApp calls. WhatsApp webhooks are HMAC-verified. Prompt-injection hardening and model-output validation. See [Security](#security). |
| **Efficiency** | All numbers come from a deterministic engine (no LLM latency on the core plan). Assets are gzipped and served at immutable versioned URLs. AI artwork is generated once and stored. WhatsApp bulk sends run in parallel with a concurrency cap. Offline reads come from IndexedDB in milliseconds. |
| **Testing** | **93 backend tests** (pytest), run on both SQLite and the Firestore emulator, with **96% combined coverage**. Gemini, the image model and the WhatsApp Graph API are mocked at the HTTP layer. Plus **7 frontend unit tests** (`node --test`). |
| **Accessibility** | **axe-core audit: 0 WCAG 2.1 A/AA violations** across the landing page, home, all six plan tabs and the notification panel, on desktop and phone (`npm run test:a11y`). Keyboard-first tabs, labelled controls, live regions, AA contrast enforced even on AI-coloured invite text, reduced motion and forced colours supported. |

## Problem statement → what Utsav does

| Requirement | How Utsav delivers it |
|---|---|
| **Weddings, birthdays, community events** | Three planning profiles, each with its own budget split, vendor list and lead times: 16 wedding tasks, 9 birthday tasks, 12 community tasks (including permits, safety and sanitation). |
| **Describe it in your own words** | Write a free-text brief ("120 guests in Lisbon next June, €60k, grandma uses a wheelchair, vegetarian guests, mehndi night…"). Gemini fills in the form (type, date, guests, budget, currency, city, culture, vibe), adds 3–8 **personalised tasks** a standard checklist would miss, and **re-weights the budget split** toward what matters to you. Everything it returns is validated (known categories only, Contingency kept at 4% or more, shares normalised), and you review it before saving. The brief is the main input for **Ideas** (themes and every idea built around its rituals, venue and audience, aligned with the event's budget categories) and **Invites** (names, venue and flavour taken from it, with blank host/venue/time/RSVP boxes filled only from what it explicitly states). **Ask Utsav** also treats the brief as context, together with the run sheet, invite details and checklist, and its starter questions are built from the plan. It also gives **planner suggestions** and works out budgets from contributions (₹600 × 400 residents = ₹2,40,000). On an existing event, **edit the brief and re-plan**: Gemini re-reads it against the current plan, and you approve each change (details as old → new, tasks added or removed, new budget priorities). Ticks on tasks that survive are kept. Gemini also **designs the budget categories for each event**. A society Karwa Chauth gets *Food*, *Mehndi artists*, *Pooja & rituals* and *Decor* rather than a generic list. It also **writes the whole checklist** (10–20 tasks, filed under the event's own categories plus *Planning*) in place of the generic list for the event type, leaving out anything the brief says is already decided. An offline keyword reader covers the no-AI case. |
| **Any currency** | 20 currencies (INR, USD, EUR, GBP, AED, SGD, AUD, JPY, NGN…). Amounts are formatted per currency, and per-guest benchmarks are scaled to typical local event costs, not raw exchange rates. |
| **Budgets** | **Leave the budget blank and Utsav estimates it** from the guest count, event type and local costs (for example ₹38,000 for a 40-guest birthday). Gemini's own estimate from the brief is accepted only if it falls between 0.5× and 8× a realistic per-guest benchmark, so it can never invent a number. Typed budgets get a live verdict as you type (*too low*, *tight*, *comfortable*, *generous*). The budget is split into whole rupees that sum exactly to the total. You enter spend per category, and Utsav flags overspends and checks your budget per guest against a realistic per-guest benchmark. |
| **Timelines** | Every task is scheduled backwards from the event date using real vendor lead times. Each task is shown as overdue, due soon or upcoming. The whole plan exports to any calendar as **.ics**. |
| **Vendor checklists** | Checklist grouped by category, with vendor bookings tagged. Ticking a task updates progress and the plan health score. |
| **Personalised ideas** | Gemini writes a theme, colour palette, décor, menu, activities, personal touches and greener choices, all tailored to your **tradition, vibe, city and budget per guest**. |
| **Invites & bulk sharing** | Gemini acts as designer and copywriter, producing **three distinct concepts**. Each has its own angle, an original verse, a hashtag, invite and banner copy, an email, a WhatsApp message and a design brief (layout, typography, palette, art direction). It uses only the host, venue, time and RSVP you enter. **AI posters:** Gemini's image model illustrates a full festival-style poster with the text painted in (title, tagline, an icon row of the event's highlights, date/time/venue rows, an RSVP band). Gemini vision then **proof-reads** it against the exact facts; a poster that misspells anything is regenerated (up to 3 tries) and never saved if it can't pass. **Gemini's image model** (`gemini-3.1-flash-image`) also paints custom artwork for the chosen concept, as an invite card (4:5) and a banner (21:9). Utsav lays the text over it in one of four layouts, with frosted panels and scrims for legibility, so names and dates are always spelled exactly. Download as PNG or share to WhatsApp, then bulk-send personalised messages to your guest list (per-guest WhatsApp links, email-all, CSV export, sent tracking). |
| **Day-of run sheet** | In the Timeline tab, Gemini drafts the schedule for the day itself, from setup through each ritual, food and key moments to clean-up. Each step has an owner. Times that depend on sunrise, sunset, moonrise or a local calendar are marked `~` to confirm. You can redraft it at any time, and an offline skeleton covers the no-AI case. |
| **WhatsApp** | **WhatsApp Business Cloud API**: bulk-send the invite (AI poster or card as the image) to the whole guest list, with *sent → delivered → read* receipts, and send yourself the event's most urgent alerts. Without credentials, one-tap `wa.me` links work for every guest and every notification. |
| **Notifications** | A bell in the top bar collects alerts across all your events, ranked **critical / high / medium / low** by urgency. They cover overdue tasks (vendor bookings count as critical), tasks due today or within 3, 7 or 14 days, the event countdown (today, tomorrow, final week, one month), a timeline at risk, overspend in total or by category, categories almost used up, a budget too tight for the guest count, missing theme ideas, a finished checklist and an event that has passed. You can open an alert at the right tab, **share** it as a reminder (system share sheet, or copied to paste into WhatsApp or email), dismiss it, or turn on **desktop alerts** for critical and high items. **Smart alerts from the brief:** Gemini also writes 3–6 reminders specific to the event, such as collecting contributions, confirming moonrise with a local panchang, or securing terrace permissions. Each appears from its own window (days before the event), anything still open on the eve is raised to high, and they're regenerated whenever the brief changes. |
| **Assistant** | "Ask Utsav" answers questions about *your* plan, such as "Can I afford a live band?" or "What should I book this week?". |

## What makes it different

1. **Numbers never come from the LLM.** A deterministic engine (`backend/app/planner.py`) computes every rupee, date and score. Gemini gets the plan as context and is told to quote figures only from it, so a hallucinated price can't reach the user.
2. **Plan Health score (0–100).** Combines how affordable the plan is with how much time is left, and gives notes you can act on: *"Budget works out to ₹1,000 per guest; a wedding typically needs about ₹2,500. Trim the list to 40 guests or add ₹1,50,000."*
3. **Rescue plan.** For a short-notice event, it lists the tasks that are already past their ideal date, longest lead time first, because those vendors get booked out earliest.
4. **What-if panel.** Change the guest count, budget or date and the whole plan is recomputed straight away.
5. **Works without the AI.** With no API key or no network, the app uses curated ideas and answers built from the plan, so a demo never breaks. The header shows `● Gemini` or `● Offline mode`.
6. **Culturally aware.** Ideas adapt to any tradition you enter (Tamil, Catholic, Jewish, Nigerian, Eid, secular…). Amounts use rupee formatting (₹12,34,567) and market-based budget splits.

## Architecture

```
frontend/ (vanilla ES modules, no build)      backend/ (FastAPI)
  main.js   routing + boot                      main.py           app, CSP + security headers, gzip
  auth.js   sign in / register                  app/planner.py    deterministic engine (budget, timeline, health, ICS)
                                                app/notify.py     prioritised alerts derived from the plan
  home.js   event list + create form            app/ai.py         Gemini prompts, output validation, offline fallbacks
  event.js  plan tabs, what-if, chat 
  notify.js bell, alert panel, share, desktop alerts
  invites.js AI invites, canvas designs, bulk WhatsApp/email           app/gemini_client.py  REST client (key in header, never logged)
  api.js / dom.js  fetch + escaping helpers     app/auth.py       PBKDF2 + httpOnly session cookies + login rate limit
                                                app/store.py      SQLite, every query scoped by user_id
                                                app/routers/events.py  CRUD, plan, ideas, ask, calendar.ics
```

## Android & iOS apps: offline-first
The Capacitor apps (`mobile/`) **bundle the whole web app inside the APK/IPA**, so the app opens instantly even with no signal. Earlier builds only pointed a WebView at the server and showed "server not connected" when the network dropped.
- **On-device database:** every plan you open is kept in IndexedDB (`frontend/js/offline.js`). Plans, budgets, checklists, timelines and guest lists open offline. Ticks, spend and guest edits made offline are recomputed on the device (the same task-status rules as the server), queued, and synced in order when the connection returns, with an *Offline · N changes will sync* banner. AI features clearly say they need internet. Signing out wipes the device copy.
- **Auth:** the app gets a bearer token at sign-in (`X-Utsav-Client: native`), because cookies don't cross from the app's origin. The API allows only the app origins via CORS (`UTSAV_APP_ORIGINS`).
- **Build:** the Capacitor project (`mobile/`) is kept outside this repository. Its `npm run sync` copies `frontend/` with the API address and a strict CSP, then `cap sync`, and the APK is built with `./gradlew assembleDebug`.

## Installable PWA (web)
Utsav installs like a native app on Android, iPhone and desktop. It has a home-screen icon, opens full-screen with no browser bars, its top bar is safe for phone notches, and it loads instantly on repeat visits.
- `frontend/manifest.json` sets the name, standalone display, theme colour, icons (including a maskable one) and an "Plan a new event" shortcut.
- `frontend/sw.js` is the service worker. Versioned `/v/<build>/` assets are cache-first (they're immutable), pages are network-first with an offline fallback, and `/api/` is never cached.
- **Install:** on Android/Chrome, use the **⬇ Install app** button in the top bar or the browser menu. On iPhone/Safari, use Share → *Add to Home Screen*.
- Phones need an **HTTPS** deployment (Vercel or Cloud Run) to install; `localhost` only works on the same computer.
- **For the App Store / Play Store:** wrap the deployed app with Capacitor (`npx cap add ios android`). No rewrite is needed.

## WhatsApp Business (Cloud API)
Without credentials, Utsav labels WhatsApp Business **not connected** and uses one-tap `wa.me` links: per guest, copy-all, and *WhatsApp* on every notification. To send directly:

1. In Meta for Developers, create an app with the WhatsApp product. Note the **phone number ID**, a **permanent access token** (system user) and the **app secret**.
2. In WhatsApp Manager, create two templates (category *Utility* or *Marketing*, language `en`):
   - `utsav_invite`, with an **Image** header and this body: `You're invited to {{1}} 🎉` / `{{2}}` / `Date: {{3}}` / `Reply to this message to RSVP.`
   - `utsav_reminder`, with this body: `Utsav reminder for {{1}}: {{2}}`
3. Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN` (see `.env.example`).
4. Point the webhook at `https://<your-host>/api/whatsapp/webhook` (same verify token) and subscribe to `messages`.

**Invites → Send on WhatsApp** uploads the AI poster (or the invite card) once, sends every guest a personalised template in parallel, and shows each guest as *Sent → Delivered → Read* or *Failed*. Guests already reached are skipped on re-send, and webhooks are HMAC-verified and never move a status backwards. **🔔 → Send to my WhatsApp** sends the host that event's five most urgent alerts.

## Security
- **Native app:** bearer tokens are handed out only to the app on request, never to the web page. CORS allows only the app shells. Every cookie-authenticated write from another origin is rejected (CSRF Origin check).
- **Headers:** CSP, HSTS, X-Frame-Options DENY, a Permissions-Policy that turns off camera, microphone, location and payment, COOP and nosniff.
- **Cost and abuse limits:** per-user quotas on AI text (40 per 10 minutes), AI images (15 per 10 minutes) and WhatsApp sends (10 per 10 minutes) return `429` with `Retry-After`.
- **WhatsApp:** the token is only ever sent as a bearer header and never logged. Webhooks need a valid `X-Hub-Signature-256` HMAC and can never move a delivery status backwards.
- **AI posters:** a separate Gemini vision pass proof-reads every poster against the exact facts, and a poster that fails is never saved.
- Passwords use PBKDF2-SHA256 (210k iterations). Sessions are random tokens and only their SHA-256 hash is stored. The session cookie is httpOnly and SameSite=Lax.
- Each user can only reach their own events. Other users' events return 404, so event ids don't leak.
- Login is rate-limited to 5 attempts per minute per email.
- A strict Content-Security-Policy: no inline scripts or styles. All user and model text is HTML-escaped before rendering.
- Prompt-injection hardening: user text goes to the model inside tags and is treated as data. Model JSON is checked against a schema (for example, colours must be hex codes), and anything malformed falls back to curated content.
- Pydantic validates every input: past dates, out-of-range numbers, and unknown task ids or categories are rejected or dropped.

## Accessibility
`npm run test:a11y` drives real Chrome through every view and plan tab, on desktop and phone, and runs **axe-core against WCAG 2.1 A/AA**; it currently reports **zero violations**. Also: skip link, WAI-ARIA tabs with arrow-key navigation, a labelled control for every input, `role="log"` for chat, `role="alert"` for errors, native `<meter>` and `<table>` with a caption, visible focus outlines, `prefers-reduced-motion`, AA colour contrast, a stylesheet for printing the plan, and a layout that works on phones.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env    # add GEMINI_API_KEY (optional)
.venv/bin/uvicorn backend.main:app --port 8101
```
Open http://localhost:8101.

## Tests

```bash
scripts/check.sh                 # everything: ruff, pytest + coverage, eslint, JS tests, axe audit
.venv/bin/python -m pytest -q    # 93 backend tests, offline and deterministic
scripts/test-firestore.sh        # the same suite against the Firestore emulator
npm install && npm test          # frontend unit tests;  npm run lint;  npm run test:a11y
```
The tests cover rupee formatting, exact budget allocation, task status, health scoring, overspend penalties, ICS output, auth, rate limiting, isolation between users, input validation, model-output validation, the Gemini path (mocked) and the offline fallbacks.

## Deploy (Cloud Run): live demo
`PROJECT_ID=<project> deploy/cloudrun.sh` builds the `Dockerfile` with Cloud Build, stores the Gemini key from `.env` in Secret Manager, enables Firestore (native mode, asia-south1) and deploys with `UTSAV_STORE=firestore`, so instances are stateless and data survives redeploys and scaling (0–3 instances). Optional WhatsApp credentials in `.env` are also stored as secrets. It's live at **https://utsav-242709395679.asia-south1.run.app**. Local development and tests use SQLite; `scripts/test-firestore.sh` runs the same suite against the Firestore emulator.

## Deploy (Vercel)
`vercel.json` serves `frontend/` as static files and `api/index.py` as the Python function. Set `GEMINI_API_KEY` in the project's environment variables. There is deliberately no `pyproject.toml`: Vercel's `uv` builder would ignore `requirements.txt` if one existed. Note that SQLite lives in `/tmp` on Vercel, which is temporary; use a managed database for real users.
