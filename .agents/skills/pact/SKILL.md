---
name: pact
description: Pact — the self-binding commitment engine. A thin Hermes client over the Pact API. Use to create, track, prove, coach, and settle commitment pacts where money goes to charity on failure. The skill is the BRAIN on the skill path: it reasons inline (draft / judge proof / coach / verdict) and POSTs structured results back to the backend. Triggers on "/pact", "make a pact", "stake on this goal", "pact status", "pact serve".
---

# /pact — the Pact Hermes skill

Pact lets a user bind themselves to a goal: they stake money, and if they fail by
the deadline the stake is donated to a charity they chose. This skill is a **thin
client** over the Pact HTTP API. On the skill path **the agent is the brain**: you
**reason inline** (draft the pact + frozen rubric, judge each proof, coach, write the
verdict prose) and **POST the structured result** to the backend. Deterministic work
(anti-cheat, state machine, money, scheduling) lives server-side — do not re-implement it.

## Base URL

All requests go to the local Pact server:

```
http://127.0.0.1:8000
```

Override with the `PACT_BASE_URL` environment variable when the server runs elsewhere.

## Agent Token

When the server runs with `PACT_AUTH_MODE=agent_token`, worker and outbox calls must
send:

```
Authorization: Bearer <token-from-Pact-settings>
```

The raw token is shown once in Pact. The backend stores only its hash. Use
`pact serve --agent-token <token>` and `pact outbox --agent-token <token>`.

## How reasoning flows (read this first)

- **Skill path (you are inside a Hermes agent):** reason **inline** with your own model,
  then POST the result. Every reasoning step still writes a task record for audit, but
  you apply your own result — you do not wait on the broker.
- **Website path:** the web UI cannot reason, so it **enqueues a reasoning task** on the
  **broker**. A connected agent in `/pact serve` mode claims tasks matching its
  capabilities and posts results. If no capable agent claims within the timeout, the
  backend falls back to the deterministic `test_llm` stub (hybrid mode) so the site still
  works standalone.
- **Capabilities:** photo proofs imply the `vision` capability. Only declare a capability
  you actually have. If a photo proof task includes `required_capability="vision"` and you
  cannot inspect the image artifact, return `ambiguous`; do not pass it from text alone.

## Commands

- `/pact create <natural language>` — reason a draft + **frozen rubric INLINE** (declare
  your model capabilities; refuse or propose another modality if incapable), POST the
  result, and link the user to web confirm.
- `/pact status [<id>]` — GET the pact; show countdown + pace + the next action.
- `/pact submit <id>` — issue a proof token, accept the proof, run anti-cheat, **JUDGE
  INLINE**, and POST the evidence.
- `/pact coach <id> <message>` — respond **INLINE** into the coaching thread.
- `/pact check <id>` — early settle (judge any pending proofs now).
- `/pact verdict <id>` — settle, then GET the evidence + verdict packet.
- `/pact freeze <id>` — spend a freeze (extend the deadline by one period); pre-deadline only.
- `/pact dispute <id>` — submit extra proof into the single dispute window (re-judged once, then final).
- `/pact renew <id>` — clone a finished pact's terms into a fresh pact.
- `/pact me` — your streak + history ("kept N of last M").
- `/pact serve [--owner]` — **worker mode**: poll the broker and resolve pending **website**
  reasoning tasks this agent is capable of, so the website is "live intelligent" via your
  Hermes agent. Runs the `pact serve` worker loop.
- `/pact outbox [--owner]` — **relay pending coaching nudges**: fetch `GET /api/outbox?owner=`,
  deliver each undelivered nudge to the user through this agent's own channel (the user already
  talks to their agent here — no separate transport needed), then call
  `POST /api/coach/{id}/delivered` for each relayed message. Pact owns content + timing;
  the agent owns delivery.

## Endpoints

Pact lifecycle (the skill calls these directly):

- `POST /api/pacts/draft` — `{ prompt }` → drafted pact + frozen rubric (or refusal).
- `POST /api/pacts` — `{ pact_id, stake_amount_cents, charity_id }` → confirm + start.
- `POST /api/pacts/{id}/owner` — `{ owner }` set the owner.
- `POST /api/pacts/{id}/start` — activate (no money moves).
- `GET /api/pacts/{id}` — pact state, proofs, coaching thread, payment status.
- `GET /api/pacts?owner=` — list pacts.
- `POST /api/pacts/{id}/proof-token` — issue a single-use nonce token.
- `POST /api/pacts/{id}/proofs` — text/log/url proof with `{ modality, token, content_ok }`.
- `POST /api/pacts/{id}/proofs/image` — multipart photo proof with `token` + `image`; the
  task payload contains the stored artifact path, pHash, expected token, and rubric.
- `POST /api/pacts/{id}/freeze` — spend a freeze (pre-deadline only).
- `POST /api/pacts/{id}/cancel` — cancel (release or forfeit per timing).
- `POST /api/pacts/{id}/settle` — run the verdict now (also invoked by the scheduler).
- `POST /api/pacts/{id}/dispute` — submit extra proof into the single dispute window.
- `POST /api/pacts/{id}/coach` — `{ message }` user reply into the coaching thread.
- `POST /api/pacts/{id}/renew` — clone terms into a fresh pact.
- `GET /api/pacts/{id}/packet` — evidence + verdict packet (with coaching log).
- `GET /api/pacts/{id}/coach` — read the coaching thread.
- `GET /api/charities` — charity catalogue for the confirm picker.
- `GET /api/profile?owner=` — streak + history for `/pact me`.

Broker (the website enqueues; `/pact serve` resolves):

- `POST /api/pacts/{id}/reasoning-tasks` — `{ type, required_capability, input }` enqueue.
- `GET /api/reasoning-tasks?capability=&status=pending` — list claimable tasks.
- `POST /api/reasoning-tasks/{tid}/claim` — `{ agent_name, capabilities }` claim a task.
- `POST /api/reasoning-tasks/{tid}/result` — `{ result }` post the resolved result.

Outbox (coaching nudge relay — the agent is the delivery channel):

- `GET /api/outbox?owner=` — the owner's undelivered outbound coaching messages. The agent
  fetches this queue, relays each nudge through its own channel, then marks each delivered.
- `POST /api/coach/{msg_id}/delivered` — mark a coaching message as delivered (set
  `delivered_at`). Returns the updated message; 404 if not found.

Ops:

- `POST /api/tick` — run the scheduler once (reconcile, close dispute windows, persist nudges
  to outbox).
- `GET /api/preflight?owner=&charity_id=&amount_cents=` — live-money readiness checks.

## Safety

Real money moves only after explicit human Link approval, behind
`PACT_PAYMENT_MODE=link_cli` and `PACT_LINK_MODE=live`. The skill never auto-executes a
live charge, and Link approval is not the same thing as charity receipt confirmation.
Refuse unsafe goals (self-harm, restrictive-eating, coercive or third-party stakes) at
draft time with a supportive message and a crisis-resource line; enforce that the pact
subject is the staking user.
