# Pact — Full Redesign Design Spec

**Date:** 2026-06-26
**Status:** Approved (brainstorming). Ready to turn into an implementation plan.
**Context:** Hermes Agentic Business hackathon, local-first / open-source. Builds on the merged Day-1→Tier-4 engine + the Geist `Create` flow. This spec redesigns the **whole app** in the Geist style and defines the **post-creation experience** (backend wiring, Link setup, Hermes agent ties, post-creation surfaces, motivation layer).

---

## 0. Goal & Approved Decisions

Rebuild the app so it is one coherent Geist-styled experience, and design what happens **after** a pact is created. Locked answers from the brainstorm:

| # | Decision | Choice |
|---|---|---|
| 1 | Sequencing | **Plan everything first**, then build the whole new app (Create + post-creation) in one coordinated pass. Nothing is deleted until this plan is approved. |
| 2 | Primary surface | **Co-primary** — a real web dashboard **and** the agent-channel loop, both reading/writing the same FastAPI server truth. |
| 3 | Link timing | **Connect after the first pact** — no card friction inside Create. Once the first pact is sealed and handed to the agent, check whether Link is connected; if not, prompt to connect a funding source. |
| 4 | Motivation | **All four** — streaks & record, agent check-in nudges, live progress visualization, milestones & loss-framing. |
| 5 | Agent depth | **Full** — web photo upload **and** agent-channel proof/coaching/verdict. |
| 6 | App shape | **One living `/pact/:id` surface + a dashboard** (verdict folded into the living pact as a terminal state). |

**Invariants carried forward (unchanged):** the brain is the Hermes **agent** (hybrid broker + `test_llm` fallback), **charge-on-fail** (no escrow — Link can only create a charge), `test_llm`/`test_link` are safe defaults, no real money / email / network moves by default or in tests, local-first (no multi-user auth, no durable token store).

---

## 1. Surface Map (web) — 3 surfaces, down from 5

The app collapses from five Binding-Contract screens (`Home`, `Create`, `Confirm`, `Active`, `Verdict`) to **three** Geist surfaces. `Confirm` is already folded into `Create`. `Home`/`Active`/`Verdict` are removed and their function re-expressed in the new Dashboard + living Pact.

### 1.1 `/` — Dashboard (motivation home + landing)
- **Record band:** current streak, best streak, kept vs. failed — from `profile.py`.
- **Active pacts:** each as a **live progress card** (title, charity stamp, stake, progress ring = valid count / target, days left, on-track / behind). Click → `/pact/:id`.
- **History:** past pacts (kept / donated) with outcome.
- **Link-connect banner:** shown only **after the first pact exists** and Link is not connected. Dismissible per session but reappears until connected.
- **Empty state:** "Make your first pact" → `/create`.

### 1.2 `/create` — Create (exists, Geist)
Deck → pact card (frequency, stake $10–$500, charity wax-stamp chips) → agent pick → seal (= consent) → "handing to {agent}" → agent message → **Open my pact** → `/pact/:id`. On seal we also perform the **handoff** (see §2) and arm the **Link check** (see §3).

### 1.3 `/pact/:id` — The living pact (absorbs Active + Verdict)
One surface that renders by the pact's server status:
- **Active:** progress ring (valid / target, days left, on-track/behind), **photo-proof upload** (token-nonce → image → server judge), the **coaching thread** (agent nudges + user check-ins), **milestone** moments, **loss-framing** line when behind pace, **cancel** (cooling-off / forfeit disclosure).
- **Settling → verdict:** the **wax-stamp verdict** moment (pass / fail), the **single dispute window**, `needs_review` "under review" state, donation status.
- **Donated / kept:** terminal summary → back to dashboard.

> Verdict is a **state** of the living pact, not a separate route. (If we later want the standalone ceremonial verdict page, it's a thin wrapper over the same state — noted as a deferred option.)

### 1.4 Link-connect (focused modal/section)
Reachable from the dashboard banner and the pact prompt. Not a top-level nav item.

---

## 2. Agent-Channel Loop (co-primary)

Reuses existing infrastructure: the reasoning-task **broker**, the coaching **outbox**, the `/pact` Hermes **skill**, and the `pact serve` **HTTP worker**. Both surfaces operate on the same server truth; the web polls (the demo clock drives in demo mode), the agent acts via the API.

- **Handoff on seal:** sealing a pact assigns it to the chosen agent (`Pact.agent`) and **enqueues the first coaching/handoff** message. The agent "receives" the pact and sends the opening line; the Create flow's message card mirrors it.
- **Proof via agent:** the user sends a photo to their agent; the agent calls the **same** `POST /api/pacts/{id}/proofs/image`. Web upload and agent upload land in one proof list — the living-pact progress reflects either source.
- **Nudges:** the scheduler writes due nudges to the outbox (`CoachingMessage.delivered_at`); the agent pulls `GET /api/outbox?owner=`, relays in-channel, then `POST /api/coach/{id}/delivered`. The web pact thread shows the same messages.
- **Verdict:** the agent judges proof against the **frozen rubric** (reasoning task, temp 0) and narrates the verdict in its channel; the web reflects the verdict state. `test_llm` keeps the whole loop working with no live agent connected.

---

## 3. Link Setup / Config (post-first-pact connect)

Realizes decision #3 without contradicting **charge-on-fail / no-escrow** (Link cannot hold funds; "connect" only registers a funding source so a charge *can* fire later).

- **Model:** a per-owner Link account — `{owner, connected: bool, funding_ref: str | None, connected_at}`. Stored in the repository (new small table or a profile field).
- **Trigger:** after the **first** pact is sealed + handed off, the app checks `GET /api/link/status?owner=`. If `connected == false`, surface "Connect Link" (dashboard banner + pact prompt + an agent nudge: *"connect a funding source so your stake is real"*).
- **Connect:** `POST /api/link/connect` is a **safe local-first stub** — registers a test funding reference and sets `connected = true`. It never moves real money; live wiring stays gated behind explicit config like the existing `LinkCliProvider` (which raises in live mode).
- **Settlement check:** the charge-on-fail path checks `link.connected`. Connected → the (test) donation fires through the existing payment provider. Not connected → the pact **stays in the existing `donation_pending` status** with a **"Link required"** prompt (web + agent ask the user to connect) rather than silently dropping the stake or inventing a new status. Once connected, the deferred donation fires through the normal `close_dispute_window` / settle path.

**New endpoints:** `GET /api/link/status?owner=`, `POST /api/link/connect`. **Reused:** the whole settle/donation path.

---

## 4. Motivation Layer (all four)

| Mechanic | Source | Surface |
|---|---|---|
| Streaks & record | `profile.py` (current/best streak, kept/failed, history) | Dashboard record band + history |
| Agent check-in nudges | `coaching.py` (pace-aware, nag-governed) + outbox | Agent channel + pact thread |
| Live progress visualization | derived (valid count / target, days left, on-track) | Progress ring on pact + dashboard cards |
| Milestones & loss-framing | derived from valid count vs. target | Milestone moments at 25/50/75/100% + streak badges; loss-framing line ("$200 and One Tree Planted are one missed day away") when behind pace |

Milestones and pace/on-track are **derived read-model fields** (no new persistence needed beyond what proofs already give us).

---

## 5. Backend Additions (most is reuse)

**New:**
- `link.py` — Link account model + `status`/`connect` + the settlement `connected` check.
- API: `GET /api/link/status`, `POST /api/link/connect`.
- Pact **read-model enrichment** (in `api`/`packet`): `valid_count`, `target`, `pct`, `days_left`, `on_track`, `milestone` — so both surfaces render progress/motivation without recomputing.
- Seal → **enqueue handoff / first coaching** (wire into `create_pact_structured` / confirm).

**Reused as-is:** `GET /api/pacts?owner=` (already exists — `list_pacts`), proofs/image upload, proofs list, outbox, profile, settle/dispute/cancel, scheduler, broker, charities.

---

## 6. Representative Data Flow — "log proof"

1. User submits a photo (web upload **or** their agent) → `POST /api/pacts/{id}/proofs/image` (token nonce verified, EXIF-stripped, pHash deduped, server-time distinct-day bucket).
2. Proof judged against the frozen rubric (agent reasoning task; `test_llm` fallback).
3. Proof list + `valid_count` update on the server.
4. Web living-pact **progress ring advances**; the agent can narrate ("3 of 5 — nice").
5. **Milestone check:** if a threshold (25/50/75/100%) was crossed, fire the milestone moment (web) + optional agent congrats.

---

## 7. Scope (local-first, hackathon)

**In:** all 3 web surfaces (dashboard + living pact + create), the agent loop on the hybrid broker with `test_llm` fallback, the Link-connect **stub**, all 4 motivation mechanics, an updated demo harness (seed pacts that exercise active / behind / verdict / donated + the Link-connect prompt).

**Out / gated (never auto-run):** real money movement (`LinkCliProvider` live), real card collection / KYC, multi-user auth & accounts, durable/multi-worker token store, artifact TTL deletion. Real Link/agent wiring stays behind explicit config + human action.

---

## 8. Testing

**Backend (keep the 383 green, add):**
- Link: `status` defaults to not-connected; `connect` sets connected; settle **checks `connected`** (connected → donation fires; not → "needs Link" state, no silent drop).
- Read-model: milestone/pace derivation (valid/target → pct, on_track, milestone thresholds).
- Handoff: sealing enqueues the first coaching/handoff for the assigned agent.

**Web:** `npm run build` clean; browser-verify the dashboard (record + live cards + Link banner), the living pact through its states (active → proof → verdict → donated/kept), the Link-connect prompt, and a milestone moment.

---

## 9. Component Boundaries (isolation)

**Web:** `screens/Dashboard.tsx`, `screens/Pact.tsx` (lifecycle sub-states), `components/LinkConnect.tsx`, `components/ProgressRing.tsx`, `components/CoachThread.tsx`, plus small motivation bits. Extend the `--pc-*` Geist tokens / `create.css` patterns into a shared `geist.css`. Old `Home.tsx`/`Confirm.tsx`/`Active.tsx`/`Verdict.tsx` removed; `main.tsx` routes updated to `/`, `/create`, `/pact/:id`.

**Backend:** `link.py` stays focused (account + status/connect + settlement check). Read-model enrichment lives in `api`/`packet`. Everything else is reused.

---

## 10. Build Order (for the plan)

1. **Backend foundation** — `link.py` + endpoints + settlement check; read-model enrichment; handoff-on-seal. (Tests first.)
2. **Web shell & routing** — strip to 3 routes, shared `geist.css`, shared components (`ProgressRing`, `CoachThread`, `LinkConnect`).
3. **Dashboard** — record band, live cards, history, Link banner.
4. **Living pact** — active (progress + proof + thread + milestones + loss-framing + cancel) → verdict/dispute/needs_review → donated/kept.
5. **Agent loop polish** — handoff message, nudges in-thread, proof-via-agent path, verdict narration (skill/worker).
6. **Demo harness** — seed states + Link-prompt; browser-verify; keep suite green; merge.
