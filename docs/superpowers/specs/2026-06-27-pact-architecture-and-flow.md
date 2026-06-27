# Pact — Architecture & Flow Spec (consolidated)

**Date:** 2026-06-27
**Status:** Decisions locked (UI paused to nail backend + integration). This is the contract the rebuilt UI is built against.
**Supersedes/extends:** the payment model here overrides any "schedule at creation / pre-auth" idea — **not possible on Link** (see §6). Builds on `2026-06-24-pact-design.md` and `2026-06-26-pact-redesign-design.md`.

---

## 1. The one idea

There is only ever **one pact, in one backend.** It can be created through **two front doors**, and after creation they are identical. The user's **agent is the brain** (coaches + judges proof); the **backend owns the money + charity**. The agent never touches Link. The agent always **pulls** work from the backend — nothing is pushed into it — which is what makes the web path non-intrusive.

**Locked decisions (this session):**
- **Bring-your-own-agent** — no hosted default. The brain is always the user's agent.
- **Two creation doors** — the `/pact` agent skill, and the web UI. Same backend pact.
- **Stake = charge-on-fail, human-approved at the deadline.** Link cannot pre-auth/schedule/hold. "Connect Link" = readiness only.
- **Teeth = streak/record loss + agent pressure at the deadline** (verdict packet / accountability-partner deferred).
- **Agents** = Hermes, Claude Code, custom MCP; **nemoclaw = "coming soon" icon, not wired.**

---

## 2. Backend storage (source of truth)

SQLite (single file), one row-per-entity as JSON in a `data` column. Tables: `pacts`, `proofs`, `tasks` (reasoning), `verdicts`, `profiles`, `link_accounts`, `coaching_messages`.

| Entity | Holds | Key fields |
|---|---|---|
| **Pact** | the commitment | `id, owner, title, goal, deadline_at, target_count, distinct_days, stake_amount_cents, charity_id, charity_url, agent, rubric, status, stake_state, spend_request_id, dispute_window_closes_at` |
| **Proof** | one piece of evidence | `id, pact_id, modality, received_at, day_bucket, token_ok, phash, status, judge_reason` |
| **Verdict** | settlement outcome | `pact_id, status, valid_proof_count, target_count, summary, payment_action, payment_ref` |
| **Profile** | the track record | `owner, current_streak, best_streak, kept, failed, history[]` |
| **LinkAccount** | funding readiness | `owner, connected, funding_ref, connected_at` |
| **CoachingMessage** | the thread + outbox | `id, pact_id, direction, trigger, body, sent_at, delivered_at` |
| **ReasoningTask** | website→agent work item | `id, pact_id, type, required_capability, input, status, result, claimed_by` |

**Lifecycle state machine** (`status`):
`draft → active → evaluating → {succeeded | failed | needs_review}`; on `failed` a **dispute window** opens (`dispute_window_closes_at`); when it closes with a real shortfall → `donation_pending → donated` (or `donation_failed/declined`); voluntary exits → `canceled_release` (cooling-off) / `canceled_forfeit`. **No money moves before `donation_pending`.** `donation_pending` also parks a pact whose owner hasn't connected Link, and fires once they do.

**Concurrency note:** one shared sqlite connection accessed from FastAPI's threadpool. The redesigned UI fires several reads in parallel per page, which races the shared cursor (intermittent 404/500). Fix in progress: serialize **all** access (reads too) behind one `RLock` — `repository.py` has `_one/_all` helpers added; the read methods still need to route through them. **Finish this when we resume building.**

---

## 3. The two creation doors

**A · Agent door (the agentic way).** The user is inside their agent and says *"help me work out more."* The `/pact` skill triggers, reasons the draft + **frozen rubric inline**, and POSTs it to the backend (`/api/pacts/draft` → `/api/pacts` confirm, or the structured path). Because the agent that created it is already connected, it just keeps coaching/judging. Lowest friction for people who live in their agent.

**B · Web door (pact.com).** The deck/Create flow collects goal → frequency → stake → charity → agent → seal, and writes the pact via `POST /api/pacts/create` (already active). The UI **cannot reason**, so judging/coaching is delegated to the user's agent via the broker (§4).

After either door: same pact, same rubric, same `owner`, same broker queue. The agent path and web path converge.

---

## 4. Agent connection + one-time setup

The web UI cannot reason. So for the **web door**, work reaches the agent through a **pull-based broker**:

1. The UI/backend **enqueues a ReasoningTask** (`POST /api/pacts/{id}/reasoning-tasks`) for judging/coaching/verdict.
2. A connected agent running **`/pact serve`** polls `GET /api/reasoning-tasks` (filtered by its capabilities — e.g. `vision` for photo proof), **claims** one (`POST /api/reasoning-tasks/{tid}/claim`), reasons, and posts the **result** (`POST /api/reasoning-tasks/{tid}/result`).
3. If no capable agent claims within the timeout, the deterministic **`test_llm` fallback** resolves it so the app never hangs.
4. **Coaching relay:** the scheduler writes due nudges to the outbox; the agent pulls `GET /api/outbox?owner=`, relays them in its own channel, and marks `POST /api/coach/{id}/delivered`.

**The one-time setup (the "install" question), per agent:**
1. **Bring an agent** — Hermes / Claude Code / custom MCP (nemoclaw = coming soon).
2. **Install the `/pact` skill** — Hermes: ~built-in; Claude Code: drop the skill file; custom: point at the Pact API/MCP.
3. **Link it to your Pact account** — a token/auth so it claims *your* tasks. **NOT YET BUILT** (today is single-owner / local-first). This is the piece that makes multi-user real.

> The agent only ever reads pact state and posts reasoning results/verdicts. It does **not** handle money — so "how does the agent handle payment/charity?" → it doesn't; the backend does (§6).

---

## 5. Motivation / teeth

Since the charge can't be made un-stoppable (§6), the commitment pressure is non-financial:
- **Streak / record loss** — `Profile` (current/best streak, kept/failed, history). Surfaced on the dashboard.
- **Agent pressure at the deadline** — on a miss, the agent makes the user **approve-or-explicitly-decline** the donation while showing the failure evidence; maximizes the friction of backing out.
- Live progress + milestones + loss-framing during the pact (already designed) keep the user moving.

---

## 6. Link payment flow (charge-on-fail, human-approved)

**Confirmed from the docs (2026-06-27):** Link CLI has **no** pre-auth, scheduling, future-dating, holds, or authorize-now/capture-later. Credentials are **one-time-use, valid 12h**. **Every spend requires synchronous human approval in the Link mobile app** (`spend-request request-approval` blocks; 10-min window). Caps $5k/req, $5k/day, $20k/mo. So money **cannot** move without the user approving in the moment.

**The model:**
- **Connect Link = readiness**, not a charge. `link-cli auth login` (device flow) + a payment method on file. In the backend: `link.py` `connect_account` sets `LinkAccount.connected` (today a safe test stub; live wiring gated). Prompted after the first pact.
- **No money on success.** Nothing is held; nothing moves if you keep your word.
- **On failure — nag until resolved (locked 2026-06-27):** the miss is recorded at verdict finalization (streak resets) **regardless** of payment. The donation then sits at `donation_pending` and the **agent keeps nudging until the user resolves it** — either **approves** it in their Link app (→ `donated`) or **explicitly declines** while looking at the failure evidence (→ `donation_declined`). **No silent timeout** — it stays open and resurfaced. Gated on `is_owner_connected(owner)`; idempotent via `spend_request_id` so it fires at most once.
- **Safety:** `TestLinkProvider` is the default (no real money); `LinkCliProvider` (live) is behind explicit config and never auto-runs; charity URLs checked against a host-suffix **allowlist** (`is_allowed_url`).

---

## 7. End-to-end user flow (web door)

1. **Landing (pact.com)** — Pact mark + a centered simulated iPhone running an iMessage thread (contact "friend"); a bubble flies in *"I wish I worked out more"*, the goal cycling in a vertical carousel. A scroll cue invites continuation. *(No backend.)*
2. **Scroll → Deck** — the same page becomes the deck: *"what are you committing to?"* Pick a card (or custom).
3. **Build (no commitment yet)** — frequency (days×weeks → `target_count`, `deadline`), stake ($10–$500), charity (from `GET /api/charities`). The whole pact is previewed before any agent/account ask. **(Agent choice is deferred to seal — locked 2026-06-27.)**
4. **Seal** — *now* pick the agent (Hermes / Claude / custom; nemoclaw coming soon); first-timers do the one-time setup (§4); consent → `POST /api/pacts/create` → active pact + the agent handoff greeting seeds the coaching thread.
5. **Connect Link** — prompted (readiness; §6) **after the first pact** is sealed and handed off.
6. **Live** — `/pact/:id`: progress ring, photo proof (`proof-token` → `proofs/image`), coaching thread, milestones, loss-framing when behind, cancel.
7. **Deadline → verdict** — settle → kept (streak++) or failed → dispute window → on a real miss, the **nag-until-resolved** donation (§6).

Returning users land on the **dashboard** (record + active pacts + history). The **agent door** skips 1–4: the skill builds + activates the pact directly (the agent is already chosen — it's the one running the skill).

---

## 8. Frontend ↔ backend map (the UI contract)

| Surface | Calls | Reads / writes |
|---|---|---|
| **Landing** | — | none (pure marketing/animation) |
| **Deck / Create** | `GET /api/charities`; `POST /api/pacts/create` | builds the active pact (goal, stake, charity, agent, consent) |
| **Connect-Agent** | *(setup; broker is agent-side)* | one-time skill install + account link |
| **Connect-Link** | `GET /api/link/status`, `POST /api/link/connect` | funding readiness flag |
| **Dashboard (`/`)** | `GET /api/profile`, `GET /api/pacts?owner=` | streak/record + live progress cards + history; Link banner |
| **Living Pact (`/pact/:id`)** | `GET /api/pacts/{id}` (incl. `progress`), `GET /api/pacts/{id}/proofs`, `GET/POST /api/pacts/{id}/coach`, `POST /api/pacts/{id}/proof-token`, `POST /api/pacts/{id}/proofs/image`, `POST /api/pacts/{id}/cancel` | progress, proof, coaching, cancel |
| **Verdict (state of `/pact/:id`)** | `POST /api/pacts/{id}/settle`, `POST /api/pacts/{id}/dispute`, `GET /api/pacts/{id}/packet` | verdict, dispute window, donation status |
| **Demo console** | `POST /demo/seed|advance-day|reset`, `POST /api/tick` | demo clock + scheduler sweep |

**Agent-facing (the `/pact serve` worker + skill):** `GET /api/reasoning-tasks`, `POST /api/reasoning-tasks/{tid}/claim`, `POST /api/reasoning-tasks/{tid}/result`, `GET /api/outbox?owner=`, `POST /api/coach/{id}/delivered`, plus the same pact/proof/settle endpoints for the skill path.

---

## 9. Built vs. not-yet-built

**Built:** the whole backend engine (storage, lifecycle, proof + anti-cheat, settle/dispute, profile), the broker + outbox + `/pact` skill + `pact serve` worker, `test_llm` fallback, the charge-on-fail path + `link.py` connect/gate, the redesigned web surfaces (dashboard + living pact, paused per this session). 395 backend tests green.

**Not yet built / to finish:**
1. **Repository read-path locking** (the parallel-read race; helpers added, conversion pending).
2. **Account-link token** (multi-user auth so a real user's agent claims their tasks).
3. **Landing page** (iMessage hero → scroll → deck).
4. **Live Link wiring** (`LinkCliProvider` real `auth login` + spend-request; stays gated).
5. **nemoclaw** — icon + "coming soon" only.

---

## 10. Decisions — resolved 2026-06-27

- **Agent choice = deferred to seal.** The user builds/previews the entire pact first; the agent is picked (and first-time setup done) only at the seal step. The Create flow already orders it this way.
- **Link-connect = after the first pact.** Seal → handed to agent → then prompt to connect Link (readiness). Build flow stays frictionless.
- **Deadline miss = nag until resolved.** No silent timeout; the agent keeps resurfacing the donation until the user approves (→ `donated`) or explicitly declines (→ `donation_declined`). The miss + streak loss are recorded at verdict finalization regardless. (See §6.)

**Still open (not blocking):**
- **nemoclaw** — identity TBD; "coming soon" icon only.
- **Nag cadence/medium** — how often and through which channel the agent re-nudges a pending donation (tune during build).
