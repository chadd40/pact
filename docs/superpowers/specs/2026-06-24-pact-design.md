# Pact — Design Spec

**Date:** 2026-06-24
**Status:** Approved decisions locked; ready for implementation plan.
**Context:** Hermes Agentic Business hackathon. Standalone build (no dependency on other local projects). Target window: ~3–4 days.

---

## 1. What Pact Is

Pact is a **self-binding commitment agent**. You tell Hermes, in natural language, what you'll do, by when, and what money is at stake. Hermes turns it into a concrete contract, **coaches** you toward it through the week, **audits** your proof at the deadline, and — only if you fail — has you approve a donation of the stake to a charity you chose up front.

**Category line:** the agent that holds you to your word — coach until the deadline, auditor at the deadline.

**The honest promise (this is load-bearing, see §8):** Pact never holds your money. It is a commitment device, not an escrow or bank. At the deadline, *if* you missed, Hermes shows you the evidence and asks you to approve the donation right then. The deterrent is having to actively decline while staring at proof you fell short — plus the public verdict packet.

### Golden demo
> "Work out 5 times this week or $20 goes to charity." Each session is proven with a photo (or a non-photo log), judged by Hermes against a rubric agreed during drafting. Demoed in ~3 minutes via a simulated clock.

A "5× this week" goal is **one pact** with a single end-of-week deadline and a criterion of **5 distinct dated proofs** — not five separate pacts.

---

## 2. Scope

### In scope (weekend build)
- NL intake → AI-drafted pact → confirm contract + pick charity → active coaching → proof submission + agent judging → deadline verdict → charge-on-fail donation → evidence/verdict packet.
- Two surfaces over one engine: **web UI** and **`/pact` Hermes skill**, sharing stable pact IDs.
- Multimodal, agent-judged proof with real anti-cheat (§6).
- Full coaching with an outbound channel (§7).
- `test_link` deterministic payment by default; real Link virtual-card → charity page as a guarded, optional coda (§8).
- Demo harness: injectable clock, seeded WIN/FAIL pacts, reset (§10).
- Safety gate, PII handling, legal disclosures (§9).

### Out of scope (explicit non-goals)
- No escrow / custody / holding of funds (impossible on the Link rail; also money-transmission risk).
- No multi-user accounts or auth — single implicit owner (the host Link wallet is global, §8).
- No habit marketplace, social network, recurring subscriptions.
- No partial-credit payouts — verdict is all-or-nothing for v1 (§5).
- No native mobile app.
- No anti-charity / adversarial donation destinations.

---

## 3. Architecture

### One brain, two mouths
**All LLM reasoning (draft, judge-proof, coach, verdict) lives in the FastAPI backend** and calls the Anthropic API server-side. The web UI and the `/pact` skill are both **thin clients** of the same HTTP API. The skill never judges or mints state; it relays. This prevents split-brain verdicts where the two surfaces interpret the same rubric differently.

```
Web UI  ─┐
         ├─►  Pact API (FastAPI)  ──►  LLMProvider (claude | test_llm)
/pact   ─┘        │                ──►  PaymentProvider (link_cli | test_link)
 skill            │                ──►  ProofJudge / AntiCheat
                  └──►  SQLite (single source of truth) + artifact store
                  └──►  Clock (injectable) + Scheduler/reconciler
```

### Components
1. **Pact engine** — lifecycle state machine, transitions, API surface (§11).
2. **LLMProvider** — interface with two impls: `test_llm` (deterministic canned outputs for demo/tests) and `claude` (Anthropic API, vision for photo judging). Selected by `PACT_LLM_MODE`.
3. **PaymentProvider** — interface with `test_link` (instant fake spend-request id + receipt, no network) and `link_cli` (shells real `link-cli` as a background job). Selected by `PACT_PAYMENT_MODE`. Identical result shape so the UI never branches.
4. **ProofJudge + AntiCheat** — nonce verification, server-time distinct-day gate, perceptual-hash dedup, frozen-rubric VLM judging (§6).
5. **Coach** — scheduled touchpoints, pace math, nag-governor, bidirectional thread (§7).
6. **Clock + Scheduler** — single injectable `now()`; startup reconciliation sweep + a ticker that settles due pacts even if the user ghosts (§5).
7. **Web UI** — 4 screens (§ below). **`/pact` skill** — command parity over the API.

### Tech stack
Python 3.11+, FastAPI, Pydantic v2, SQLite (via `sqlite3` or SQLModel), `uv` for env/deps, `httpx` for tests, Playwright for the real-donation coda, `imagehash`+`Pillow` for pHash (install in a venv — system Python is PEP-668 locked). Simple server-rendered HTML/JS or a light SPA — kept minimal.

### Web screens
1. **Create** — one NL textbox ("what, by when, what's at stake"), examples, **Generate pact**.
2. **Confirm** — generated terms, frozen rubric, deadline, stake, **charity picker (10)**, safety/legal disclosures + consent checkboxes, **Start pact** (no money moves here).
3. **Active** — headline, time/pace remaining, proof count (e.g. 2/5 across distinct days), coaching thread (bidirectional), submit-proof (with nonce token), per-proof judgments, "Advance day" (demo).
4. **Verdict / Evidence packet** — verdict banner (SUCCEEDED $0 moved / FAILED $20 → charity), 5-row proof table (date · thumbnail · pass/fail · judge reason), coaching log, payment receipt/ref, stable per-pact URL.

---

## 4. Data Model

### Pact
```jsonc
{
  "id": "pact_a1b2c3",
  "owner": "colehaddad40@gmail.com",        // display/filter only; no auth in v1
  "original_prompt": "work out 5x this week or $20 to charity",
  "title": "Work out 5× this week",
  "goal": "Complete 5 workout sessions on 5 distinct days this week.",
  "timezone": "America/Los_Angeles",
  "deadline_at": "2026-06-28T23:59:59-07:00",  // explicit UTC-derived instant
  "target_count": 5,
  "distinct_days": true,
  "stake_amount_cents": 2000,                  // frozen, <= 50000, capped per safety
  "currency": "usd",
  "charity_id": "world_central_kitchen",       // frozen
  "charity_url": "https://wck.org/donate",     // frozen, allowlisted
  "rubric": { /* frozen JSON, see §6 */ },
  "status": "draft|active|evaluating|succeeded|failed|needs_review|canceled_release|canceled_forfeit|donation_pending|donated|donation_failed|donation_declined",
  "stake_state": "none|committed|executing|executed|released|declined|error",  // "committed" = amount frozen + consented; NOT a real authorization/hold (Link can't hold). Real spend only at deadline-on-fail.
  "spend_request_id": null,                    // set only at deadline-on-fail
  "checkin_plan": [ /* scheduled touchpoints */ ],
  "created_at": "...", "started_at": "...", "verdict_at": "..."
}
```

### Rubric (frozen at confirm; see §6)
```jsonc
{
  "modality": "photo|log|url|file|text",
  "require_token": true,
  "must_show": ["person mid/post exercise OR gym equipment OR cardio-machine screen"],
  "reject_if": ["stock/watermark", "pure UI screenshot", "missing token"],
  "min_distinct_days": 5,
  "count_target": 5,
  "rest_if_injured_counts": true              // safety clause baked in
}
```

### Proof
```jsonc
{
  "id": "proof_1", "pact_id": "pact_a1b2c3",
  "modality": "photo",
  "received_at": "2026-06-24T18:03:00-07:00",  // SERVER time = source of truth for the day
  "day_bucket": "2026-06-24",                   // computed in pact tz
  "token_issued": "PACT-7Q", "token_ok": true,
  "phash": "f0e1...", "dup_of": null,
  "artifact_path": "artifacts/pact_a1b2c3/proof_1.jpg",  // EXIF-stripped, TTL-deleted
  "status": "passed|failed|ambiguous",
  "judge_reason": "Token PACT-7Q visible; person on treadmill; no reuse.",
  "judge_checklist": { "token": true, "content": true, "not_dup": true }
}
```

### CoachingMessage
```jsonc
{
  "id": "msg_3", "pact_id": "pact_a1b2c3",
  "direction": "outbound|inbound",
  "trigger": "mid_week|behind_pace|deadline_eve|reply|proof_ack",
  "pact_state_snapshot": { "valid": 2, "target": 5, "days_left": 2 },
  "channel": "email|web",
  "body": "2 of 5 done, 2 days left — you need 3...",
  "sent_at": "..."
}
```

### Charity
```jsonc
{
  "id": "world_central_kitchen", "name": "World Central Kitchen",
  "donation_url": "https://wck.org/donate",
  "allowed_domains": ["wck.org", "donate.wck.org"],
  "category": "disaster_food_relief",
  "default_amounts": [10, 20], "checkout_kind": "stripe|paypal|other"  // for the coda automation
}
```

### Verdict (packet)
```jsonc
{
  "pact_id": "pact_a1b2c3", "status": "succeeded|failed|needs_review",
  "valid_proof_count": 4, "target_count": 5,
  "summary": "4 of 5 distinct-day proofs by deadline. Pact failed.",
  "proof_ids": [...], "coaching_log_ids": [...],
  "payment_action": "none|donation_executed|donation_failed|donation_declined",
  "payment_ref": null, "receipt_artifact_path": null,
  "honesty_note": "Commitment device; proofs judged best-effort, not forensically verified."
}
```

---

## 5. Lifecycle State Machine

```
draft ──confirm+start──► active ──deadline reached──► evaluating
                           │                              │
                  cancel before first proof window        ├─ valid >= target ─► succeeded   (stake_state: released; NO link-cli calls)
                           │                              ├─ ambiguous decisive ─► needs_review (NEVER auto-donates)
                  ► canceled_release (no donation)        └─ honest shortfall ─► failed ─► donation_pending
                           │                                                                   │
                  cancel after underway                                            user approves│decline / fail
                           │                                                                   ▼
                  ► canceled_forfeit ─► donation_pending                         donated | donation_failed | donation_declined
```

### Rules
- **All-or-nothing v1:** `valid_proof_count >= target_count` → `succeeded`, else `failed`. Partial progress (3/5) is shown in copy but the money is binary against the single frozen amount. Contract states "partial credit not supported."
- **Cancel semantics** (consented to on Screen 2): cancel within a short **cooling-off window** after start (before the first scheduled check-in fires) → `canceled_release` (no donation). Cancel **after** that → `canceled_forfeit` (donation fires). Backing out of a started commitment is exactly what the stake guards against. (Great demo beat: "you can't wriggle out once it's live.")
- **needs_review never moves money.** Default-safe: at deadline count only *clearly valid* proofs; if removing ambiguous ones still meets the target → succeed; if it still fails regardless → honest fail; otherwise hold and ask the user for a re-submit / one-tap human confirm before any donation. There is a bounded window + a swept timeout so `needs_review` always reaches a terminal state.
- **Single clock:** all lifecycle code reads an injected `now()`. Never call `datetime.now()` directly. The demo "Advance day" endpoint and the real scheduler share this clock.
- **Ghosting is the default failure path:** no proofs by deadline → `failed` → donation, with zero user interaction required to *reach the verdict*.
- **Durability:** pacts persist to SQLite. On startup, a reconciliation sweep settles any `active` pact past its deadline. A ticker polls for due pacts (no in-memory per-pact timers). Verify by killing/restarting the server mid-pact.
- **Idempotency:** the verdict→donate transition is guarded — flip to `executing` before any `link-cli` call; a unique constraint ensures **at most one** `spend_request_id` per pact; a second trigger is a no-op.

---

## 6. Proof & Anti-Cheat

The novel, defensible core. Four layers, the first three deterministic and run **before** the LLM:

1. **Per-submission nonce token.** When the user taps "submit proof," the backend issues a short single-use token (e.g. `PACT-7Q`, ~10-min TTL) they must write on paper/phone and **capture in-frame**. The judge requires the exact current token visible. One move defeats old / stock / reused / borrowed / AI-pulled photos.
2. **Server timestamp = day source of truth.** The proof's day is the backend `received_at` bucketed into the pact's timezone — **never** EXIF (strippable/absent) or user-typed dates. At most one valid proof counts per calendar day. Surfaced in the packet ("5 proofs across 5 distinct days: Mon/Tue/Thu/Fri/Sat"). This kills "dump 5 photos Sunday night."
3. **Perceptual-hash dedup.** Compute pHash for each proof; reject/flag if Hamming distance to any prior accepted proof is ≤ ~6 (catches reuse, crops, recompresses). Borderline → `needs_review`, not auto-reject.
4. **Frozen-rubric VLM judge.** At confirm, Hermes emits a **frozen JSON rubric** stored on the pact. Each proof is judged with that exact object, temperature 0, returning a structured checklist (token / content / not-dup → pass/fail + reason). Same rubric in → same verdict out; the rubric and per-proof checklist go verbatim into the packet for auditability.

**Honesty:** AI image-detection and identity proof are unsolved in a weekend. The UI states plainly it's best-effort, not forensic. A human-in-the-loop confirm gates any real (non-`test_link`) donation so a contested verdict never irreversibly moves money.

---

## 7. Coaching

Coaching is half the pitch and must appear in the deliverable — not generic cheerleading.

- **Outbound channel:** **email** (cheapest reliable; we have the user's address) for proactive reach, mirrored as a **web thread**. A coach that only speaks when you open the app isn't a coach. The demo "Advance day" fires that day's touchpoint so it's visible without waiting on real mail.
- **Touchpoints (≥3 per pact):** mid-week nudge, behind-pace alert, deadline-eve final call. Generated by Hermes from live pact state.
- **Behavioral playbook** (in the prompt + fed real state): (1) **pace math** in every message — "2 of 5 done, 2 days left, you need 3"; (2) **stake as loss** — "$20 to [charity] is 60% locked in"; (3) **friction reducer** — one specific next action; (4) **identity reinforcement** on success.
- **Nag-governor:** max one proactive message per simulated day; never two unprompted in a row; **suppress the day's nudge if a proof already landed**; escalate tone only on crossing a pace threshold or an overdue proof (event-driven, not timer-driven); always pair urgency with an actionable out.
- **Bidirectional:** the web thread accepts replies; **replying with a photo is the primary proof path.** Hermes reflects intent back as micro-commitments ("Locked: two sessions tomorrow — I'll check in tomorrow night").
- **Coaching log in the packet:** every nudge, the state that triggered it, and whether a proof landed within ~24h — with a one-line "coaching impact" note. Makes the coach legible alongside the verdict.

**Demo arc (scripted, not random):** Day 1 plan → Day 3 supportive (on pace) → Day 5 escalation (behind; tone shifts to urgent pace math) → Day 7 verdict. The visible tone shift *is* the demo moment.

---

## 8. Payment — Charge-on-Fail

**Decision: charge-on-fail.** Link has no hold/escrow/authorize-and-capture-later and no fundable balance; a `spend-request` is create→approve→execute for one specific charge with a short TTL. So:

- **Screen 2 creates NO spend request.** It only freezes `{amount_cents, charity_id, charity_url}` onto the pact and collects consent. Success is therefore trivially safe — **zero `link-cli` calls** on any non-failure verdict (asserted by a test).
- **At the deadline, only if `failed`/`canceled_forfeit`:** `status → donation_pending`; create the Link spend request with the frozen amount + charity, the pact id + charity name in the required 100-char `context`; request approval; on approval execute; capture receipt → `donated`. If declined/timed-out/failed → `donation_declined` / `donation_failed` (explicit terminal states, surfaced honestly, "retry donation" button guarded by idempotency).
- **PaymentProvider interface, identical result shape:**
  - `test_link` (default, recording-safe): instant fake `spend_request_id` + receipt, no network. The demo "committed/locked" UX is a `test_link`-backed fiction; real Link is charge-at-deadline.
  - `link_cli`: shells real `link-cli` **as a background job** (never inline in a request — `create --request-approval` blocks/polls up to 300s and would hang the worker). On approval kickoff: store id, set `awaiting_approval`, return immediately; web polls for status flips.
- **Real-donation coda (optional, guarded):** real Link **virtual card** (`--credential-type card`) driven by Playwright into **one pre-scouted charity donate page** whose form fields/selectors you've inspected (prefer plain Stripe Checkout). The other 9 charities are metadata-only picker entries that fall back to `test_link`. Treat live automation as an "and it works for real" coda *after* the verdict already landed; keep a 15–20s screen recording as the safe artifact. MPP (`shared_payment_token`/`mpp pay`) is out of scope — charity donate pages aren't 402 endpoints.
- **Single-user reality:** `link-cli` auth is one host-global wallet. v1 is single-user; `owner` is display/filter only; all real spends go through the host wallet behind an explicit confirm.

---

## 9. Safety, Privacy, Legal

- **Intake safety gate** (classifier in the drafting prompt, *before* a pact exists): hard-refuse weight-loss-rate goals, calorie/fasting/purge goals, "every single day, no rest" exercise goals, and goals naming injury/pain. Cap frequency (≤6 sessions/week, mandatory rest day), cap duration, and bake a **"rest if injured still counts as compliant"** clause into every fitness rubric. Show the refusal reason. Also screen self-punishment / self-harm / restrictive-eating language and coercive/third-party stakes → refuse with a supportive message + crisis-resource line; enforce that the pact subject == the staking user.
- **Irreversibility guard:** `needs_review` never moves money; a mandatory hold window (time-compressed in demo) sits between a `failed` verdict and execution for a late proof / dispute; a human **"confirm donation"** click is required before any non-`test_link` charge. The agent never auto-executes the real card.
- **Photo PII:** strip EXIF/GPS on upload; store a low-res thumbnail + verdict + pHash; delete the raw image after judging (max 7-day TTL); per-pact non-identifiable filenames; a one-line consent checkbox at submission; offer a **non-photo proof option** (text log / wearable screenshot) so no one is forced to share body photos.
- **Donation locking:** hardcoded 10-charity domain allowlist; the executor refuses any off-allowlist navigation/payment; spend amount is exactly the frozen stake (never user-typed at pay time); low **max stake $5–$20** for the demo.
- **Legal framing** (copy on Screen 2 + packet): "Pact is a voluntary self-commitment tool, not an escrow, bank, or money transmitter. We never hold your money — funds move directly from your Link card to your chosen charity only if you choose to honor a failed pact. Not financial or tax advice." Plus an **18+ / affordability acknowledgement** checkbox at start.

---

## 10. Demo Harness

- **Injectable clock + `POST /demo/advance-day`** (and an "Advance Day" button) bump a server-held `now()` and re-run the due-pact check. Deadlines are seeded relative to the injectable clock so N advances cross deterministically.
- **Two pre-seeded pacts:** `pact-WIN` (5 valid distinct-day proofs, judged PASS) and `pact-FAIL` (4 valid + 1 rejected). Live-demo intake + one real proof submission on a fresh pact for authenticity, then switch to the seeded pacts and advance each to the deadline to show verdict + donation-vs-no-donation side by side.
- **`POST /demo/reset`** restores all three to known state in one call.
- **Determinism on stage:** `test_llm` + `test_link` by default; the one live-submitted proof has a pinned/cached judgment; show the judge's structured checklist so the verdict reads as legible, not a coin flip; spinner copy ("Auditing proof against rubric…") covers latency.
- **The closing artifact:** the Evidence & Verdict packet view (§3 screen 4) at a stable per-pact URL — the final slide for both WIN and FAIL.

---

## 11. API Surface

```
POST /api/pacts/draft            { prompt } -> draft pact + frozen rubric + ambiguity/safety notes (or refusal)
POST /api/pacts                  { confirmed terms, charity_id, consents } -> pact (status=draft->active on start)
POST /api/pacts/{id}/start       activates (no money moves)
GET  /api/pacts/{id}             pact state, proofs, coaching thread, payment status
GET  /api/pacts?owner=           list
POST /api/pacts/{id}/proof-token issue a single-use nonce token for a new submission
POST /api/pacts/{id}/proofs      submit proof (image/log) -> anti-cheat + judge -> evidence
POST /api/pacts/{id}/coach       user reply into the coaching thread -> Hermes response
POST /api/pacts/{id}/settle      run verdict now (also invoked by scheduler/reconciler)
POST /api/pacts/{id}/cancel      -> canceled_release | canceled_forfeit per timing
POST /api/pacts/{id}/confirm-donation   human gate before a real (non-test) charge
GET  /api/pacts/{id}/packet      evidence & verdict packet
POST /demo/advance-day | /demo/reset | /demo/seed
```

All LLM reasoning happens behind these endpoints. `link-cli` invocations run as background jobs.

---

## 12. `/pact` Skill (thin client)

```
/pact create <natural language>     -> POST /draft, render terms, link to web confirm
/pact status [<id>]                 -> GET, countdown + pace + next action
/pact submit <id>                   -> issue token, accept proof, POST /proofs
/pact coach <id> <message>          -> POST /coach
/pact check <id>                    -> POST /settle (early proof check)
/pact verdict <id>                  -> GET /packet
```
The skill prints `pact_id` + its web URL in every response so the user can hop between surfaces. It holds no authoritative state.

---

## 13. Charity Catalog (10)

Reuse the PRD list (Against Malaria Foundation, World Central Kitchen, St. Jude, Doctors Without Borders, American Red Cross, Wikimedia, EFF, The Trevor Project, Feeding America, charity: water). Each entry carries `donation_url`, `allowed_domains`, `category`, `default_amounts`, and a `checkout_kind` to inform the coda automation. **Re-verify reachable donate pages before recording**; pick the one with the simplest (Stripe Checkout) flow as the live-coda charity.

---

## 14. Build Plan (spine never at risk)

- **Day 1 — spine:** engine + lifecycle state machine + `test_llm`/`test_link` providers + SQLite + draft→confirm→start→proof-token→submit→anti-cheat(token+server-day+pHash)→frozen-rubric judge→settle→all-or-nothing verdict→`test_link` donation + packet + tests (incl. "no spend-request on success", idempotency, restart reconciliation).
- **Day 2 — demo-able:** 4 web screens + `/demo/seed`/`advance-day`/`reset` + injectable clock + full coach (touchpoints, pace math, nag-governor, bidirectional thread, coaching log) + safety intake gate + PII handling + legal copy.
- **Day 3 — Hermes-native + real rails:** `/pact` skill parity over the API; swap in real `claude` vision judging; email channel; scheduler/reconciler ticker.
- **Stretch:** real Link virtual-card → one real charity page via Playwright (guarded coda) + recorded fallback; digital proof checkers (url/git/file/tests) for non-fitness pacts.

---

## 15. Acceptance Criteria

- Create a pact from one NL prompt; Hermes drafts structured terms + a frozen rubric; vague/dangerous goals are reformed or refused before any pact exists.
- A 5×/week pact is one pact with 5 distinct-day proofs; the day is server-time, dedup'd by pHash, gated by nonce token.
- No money moves on success — provably zero `link-cli` calls. Failure (or post-start cancel) reaches an explicit donation outcome; `needs_review` never auto-donates.
- Verdict uses only the frozen rubric + agreed criteria; evidence packet shows per-proof checklist, coaching log, and payment result/ref.
- Server can be killed mid-pact and still settle the deadline on restart; a ghosting user's pact still reaches a verdict.
- Web + `/pact` skill operate on the same pact id; the skill never judges.
- Full golden path (WIN and FAIL) demonstrable in under 3 minutes with `test_link`/`test_llm`; one real proof submitted live for authenticity.
- Real-card donation coda works against one rehearsed charity, with a recorded fallback.

---

## 16. Open Risks (track during build)

1. Real charity donate-page automation is the single most fragile thing — keep it strictly optional and recorded.
2. VLM judging latency/variance on stage — mitigated by pinned judgments + structured checklist + spinner copy.
3. `link-cli` auth token expiry before the demo — pre-authenticate and run `link-cli demo` backstage minutes before.
4. Two-clock double-fire — mitigated by single injected clock + `executing` guard + unique spend-request constraint.
5. Honest framing must be visible (commitment device, not forensic verification, not escrow) so judges' obvious probes land well.
