# Pact App Shell Redesign — Design Spec

Date: 2026-06-27
Status: Approved (sections 1–7), executing on a feature branch (`feat/app-shell-redesign`).
Source mockup: `~/Desktop/pact-agentic-accountability-app 3/project/pact App.dc.html` (Claude Design `.dc.html`).
Direction: adopt the Geist/Caveat system app-wide (the queued follow-up to the Create redesign).

## 0. Goal & constraints

Port the mockup's unified **app shell** into the React/TS SPA: a persistent left sidebar, a 3D
carousel Home, and a single status-driven per-pact Detail view that folds in every lifecycle
stage, plus the submit-evidence sheet, coach chat pane, Link donation flow, and decline modal.

Hard constraints:
- **Do NOT touch the Create or Landing screens.** `Landing.tsx`, `landing.css`, `Create.tsx`,
  `create.css` stay byte-identical. The only router change is wrapping the *in-app* routes in the
  new shell; Landing (`/`) and Create (`/create`) remain full-bleed.
- Money invariants hold: real Link money movement stays behind the existing `payment.py` provider
  gate (`TestLinkProvider` safe default; `LinkCliProvider` gated/dry-run, never auto-fires).
- Keep the demo-clock machinery (`DemoContext` / FixedClock sync) working.

## 1. Routing & app shell

New `AppShell` layout component:
- Persistent left **sidebar**: `pact` mark, nav (Home / Coach / Charities / Settings) with
  active-route highlight, profile footer (owner + live active-pact count).
- **Nag banner** across the top of main when any pact is `donation_pending` → links to that pact's
  donation resolution.
- Main `<Outlet>`.
- A dev **States / Demo menu** (bottom-left, gated to demo-clock mode) that absorbs today's
  `demobar` clock controls (Seed / Advance / Reset) and adds quick jumps for verification.

Router (`main.tsx`):
- `/` → `Landing` (no shell)
- `/create` → `Create` (no shell)
- `AppShell` element wrapping children: `/dashboard` (Home), `/pact/:pactId` (Detail),
  `/coach`, `/charities`, `/settings`.

`App.tsx` keeps the `DemoContext` provider (clock sync, `bump`/`signalChange`); its demobar JSX
moves into the shell's States/Demo menu.

## 2. Home (`/dashboard`, replaces `Dashboard.tsx`)

- Greeting eyebrow (time-of-day) + a **data-derived headline** (driven by the nearest at-risk /
  near-complete active pact; safe fallback when none).
- **5-stat row**: current streak, best streak (from `profile`); **win rate** = `kept/(kept+failed)`;
  **active pacts** = count of non-terminal; **donated total** = Σ `stake_amount_cents` over pacts
  with status `donated`. Win rate + donated are **derived client-side** (no backend change).
- **3D carousel** of active pact cards (charcoal card) + a trailing "New pact" card → `/create`.
  Hand-rolled (no new dependency) mirroring `Create.tsx`'s transform math: drag, tilt, prev/next
  arrows, click-to-open, keyboard operable, `prefers-reduced-motion` aware.
- **Past-pacts ledger**: kept/missed icon, title, destination (kept → "stake returned"; missed →
  "Donated · {charity}"), when, stake. From settled pacts.

## 3. Per-pact Detail (`/pact/:pactId`, replaces `Pact.tsx`)

One `PactDetail` switches on `pact.status` into sub-views. Topbar: back, charity/goal icon, title,
cadence line ("{days_per_week} days a week · Week N of M"), status pill, overflow.

| Sub-view | Status |
|---|---|
| Active | `active`, `evaluating` |
| Under review | `needs_review` |
| Verdict · kept | `succeeded`, `canceled_release` |
| Verdict · failed | `failed` |
| Donation due | `donation_pending` |
| Donated (terminal) | `donated`, `donation_failed` |
| Declined (terminal) | `donation_declined`, `canceled_forfeit` |

- **Active**: charcoal hero card (icon, on-track pill, title, cadence, "this week" bars, on-the-line
  $, streak, No.) + light right column (data-derived headline, "Submit today's proof" → Submit
  sheet, at-risk/goes-to chips, Cancel, Hermes coach strip → Coach pane).
- **Under review**: amber clock, proof thumbnail, submitted→under review→decision progress.
- **Verdict**: `WaxSeal` (kept/failed) + headline/body + actions (kept → start next / raise stakes;
  failed → resolve donation) + dispute-window strip (`dispute()`), gated to `dispute_window` open.
- **Donation due / Donated / Declined**: see §5.

**Cadence "Week N of M / this week"**: read from new stored `days_per_week`/`weeks` (§6). Week
number N = `min(weeks, ceil((now − created_at)/7d))`; "this week" valid count = proofs whose
`received_at` falls in the current 7-day window; week target = `days_per_week`.

## 4. Overlays (shared, mounted in shell or detail)

- **Submit-Evidence sheet** (slide-in right):
  - `nonce`: `POST proof-token` → show code + expiry countdown.
  - `capture`: file input (camera/upload) + preview, "code visible" hint.
  - `judging`: `POST proofs/image` (real multipart, server pHash + judge) with scan animation.
  - `result`: `pass` (status `passed`) / `fail` (`failed`) / `review` (`ambiguous`). Dev-only
    Pass/Fail/Review simulator buttons gated to demo mode.
- **Coach chat pane** (slide-in right): reuses `CoachThread`; `GET/POST coach`; shows coaching log.
- **Decline-confirm modal**: confirm → `POST decline`.
- **Link payment + approval-wait modal**: see §5.

All overlays: ESC to close, backdrop click to close, focus trap + restore, reduced-motion aware.

## 5. Link donation flow (two-phase: confirm → approve-in-app → monitor → donated)

`donation_pending` Detail sub-view → "Approve in Link" opens the **Link modal**:
1. Modal shows amount + method → **Confirm $X** → web calls
   `POST /api/pacts/{id}/donation/initiate`.
2. Backend creates a spend-request via the configured payment provider (test-safe), sets
   `stake_state = executing`, returns `{ state: "awaiting_approval", spend_request_id }`.
3. Modal flips to **"Approve in your Link app — we're watching for it"** + spinner; web polls
   `GET /api/pacts/{id}/donation/status` (~1.5s).
4. On approval the backend finalizes the donation (existing settle/donation path) →
   `status = donated`, `stake_state = executed`; web shows the **Donated** terminal sub-view +
   receipt. Decline at any point → decline modal → `donation_declined`.

Safety: in demo / `test_link` mode the provider auto-approves after a short delay (or via a dev
"simulate approval" control) so the whole flow is demoable with no real money. `LinkCliProvider`
stays gated and never auto-fires. The donation fires **once** (idempotent), preserving the
single-fire money invariant.

Backend additions (test-safe):
- `POST /api/pacts/{id}/donation/initiate` → creates the spend request, moves to awaiting.
- `GET /api/pacts/{id}/donation/status` → `{ state, status, stake_state, spend_request_id }`
  where `state ∈ {idle, awaiting_approval, approved, donated, declined, error}`.

## 6. Backend changes (additive, no Create/Landing impact)

- **`Pact` model**: add `days_per_week: int | None` and `weeks: int | None`. Persist them in
  `create_pact_structured` (it already *receives* both args). Expose in API responses + `types.ts`.
- **Backfill**: on repository load (or one-time migration), derive missing values for existing rows:
  `weeks = max(1, round((deadline_at − created_at)/7d))`, `days_per_week = max(1, round(target_count/weeks))`.
  Apply the same to demo seeds.
- **Donation-monitor endpoints** (§5), test-safe, single-fire.
- **Demo seeds**: ensure a `needs_review` and a `donation_pending` pact exist (in addition to
  WIN/FAIL/LIVE) so every Detail sub-view is reachable in the demo.
- Win rate / total donated: **no backend change** (client-derived).

## 7. Tokens, files, testing

New `--pc-*` tokens (in `styles.css`): `--pc-accent` `#B0432A`, `--pc-amber` `#B8862F`,
`--pc-kept` `#2F7A55`, `--pc-ivory` `#F6F5F2`. (Existing `--pc-card` `#16150F`, `--pc-on-card*`,
`--pc-green` reused.)

New files (CSS scoped like `create.css`, e.g. `app.css` or split `shell/home/detail`):
`components/AppShell.tsx` (+ Sidebar, NagBanner, StatesMenu), `screens/Home.tsx` (carousel +
ledger), `screens/PactDetail.tsx` (+ status sub-views), overlay components (`SubmitSheet`,
`CoachPane`, `LinkModal`, `DeclineModal`), and `screens/Coach.tsx`, `screens/Charities.tsx`,
`screens/Settings.tsx`. Reuse `WaxSeal` / `ProgressRing` / `CoachThread`. Delete/retire
`Dashboard.tsx` + `Pact.tsx` after parity (kept in git history).

Testing:
- Backend: unit tests for new model fields, backfill derivation, and the two donation-monitor
  endpoints (awaiting → approved → donated single-fire; decline path). Full suite stays green.
- Frontend: `tsc`/`vite build` clean.
- Browser: verify every Home + Detail sub-view + every overlay via the States/Demo menu and the
  demo seeds (WIN/FAIL/LIVE + needs_review + donation_pending).

## 8. Out of scope (this pass)

Multi-user auth, real Link wiring (stays gated), durable token store, the "create your own" 6th
card flow, restyling Landing/Create.
