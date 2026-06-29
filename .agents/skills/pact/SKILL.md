---
name: pact
description: Pact — the self-binding commitment engine. A thin Hermes client over the Pact API, callable as raw HTTP or via the bundled MCP tools (`pact mcp`). Use to make, review, prove, coach, and settle commitment pacts where money goes to charity on failure, and to recall what you've told the user about each pact before coaching. The skill is the BRAIN on the skill path: it reasons inline (draft / judge proof / coach / verdict) and POSTs structured results back to the backend. Triggers on "/pact", "make a pact", "stake on this goal", "pact status", "pact serve".
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
- `/pact pay <id>` — **complete a failed pact's donation by crawling the charity page**:
  provision the card (`donation/card`), fetch the full single-use card via
  `donation/card-credential`, open the chosen charity's donate page in your own browser, pay
  with that card, then confirm the receipt (`donation/receipt`). Only after the human approved
  the spend in Link. Treat the card as a secret — it is single-use and locked to that one
  charity. `donated` (Link approval) is NOT a charity-confirmed receipt; the receipt is.
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

- `POST /api/pacts/draft` — `{ prompt }` → 200 drafted pact + frozen rubric. A refusal for an unsafe/self-harm goal comes back as **422 with `detail` = the supportive refusal message** — read `detail` and surface it, don't treat it as a generic error.
- `POST /api/pacts` — `{ pact_id, stake_amount_cents, charity_id, consent_acknowledged }` → confirm + start. `consent_acknowledged` must be **true** (set it only after the user acknowledges money goes to charity on failure) or the call 422s.
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

Donation (charge-on-fail completion — the agent finishes paying the charity):

- `POST /api/pacts/{id}/donation/initiate` — open the Link spend-request (→ awaiting the
  human's approval in their Link app; no money moves yet).
- `POST /api/pacts/{id}/donation/approve` — capture once the human approved in Link.
- `GET /api/pacts/{id}/donation/status` — poll the donation state (idle/awaiting_approval/
  donated/declined/reconcile).
- `POST /api/pacts/{id}/donation/card` — provision the single-use, merchant-locked virtual
  card. Returns only non-secret metadata (last4/brand/expiry); the PAN stays server-side.
- `POST /api/pacts/{id}/donation/card-credential` — the FULL single-use card (number/cvc/
  expiry) for the owner's agent to enter on the charity's donate page (agent-side crawl).
  Secret; single-use and merchant-locked. Owner-scoped when auth is on.
- `POST /api/pacts/{id}/donation/checkout` — `{ confirm }` drive the chosen charity's donate
  page with the card and record the receipt. Idempotent (refuses a re-charge once confirmed);
  records a donation ONLY on a confirmed outcome — never on a decline or unverified result.
- `POST /api/pacts/{id}/donation/receipt` — record/confirm the charity receipt (agent-driven
  completion, or manual entry by the owner).

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

## MCP tools (equivalent to the raw HTTP above)

Any MCP-compatible agent can drive Pact through the bundled MCP server instead of
hand-rolling HTTP. Start it once and point your agent at it:

```
pact mcp --base-url http://127.0.0.1:8000 --agent-token <agent-token>
```

The tools are **thin pass-throughs** to the endpoints above — same shapes, same
results. The split is unchanged: **you are the brain** (draft the pact + rubric, judge
proofs against that rubric, write coaching grounded in pace, write the verdict); the
tool just persists what you reasoned. A tool cannot use your model, so no tool reasons
for you. Each tool returns one JSON text block (the whole response). A refusal or a
missing pact comes back as an error whose message carries the API `detail` — read it.

The capabilities map to tools as follows:

| Capability | Tools |
| --- | --- |
| **Make a pact** | `pact_draft` (natural language → draft + frozen rubric), `pact_create` (structured terms, **creates AND activates** in one shot), `pact_confirm` (stake + charity, activates a draft), `pact_set_owner`, `pact_start`. Use `pact_charities` to pick a charity. `pact_create` and `pact_confirm` require `consent_acknowledged=true` — set it only after the user acknowledges money goes to charity on failure, else they 422. |
| **Review a pact** | `pact_list_pacts`, `pact_get` (state + progress + cadence), `pact_list_proofs`, `pact_packet` (verdict + coaching log), `pact_profile` (streak/history), `pact_connector_health`. |
| **Recall what you told the user** | `pact_get_coaching` — read the full thread **before** you coach so your next message stays consistent with what you already said. |
| **Coach around evidence** | `pact_coach` (send a message into the thread). Recall first with `pact_get_coaching`. |
| **Submit evidence** | `pact_issue_proof_token` → `pact_submit_proof` (text/log/url) or `pact_submit_proof_image` (reads a local image file and uploads it). The backend judges the proof against the frozen rubric and returns the verdict. |
| **Submit evidence decisions** | `pact_settle` (judge pending proofs now, compute the verdict, fire donation if failed); or the broker loop — `pact_list_reasoning_tasks` → `pact_claim_reasoning_task` → reason inline → `pact_post_reasoning_result`. The posted `result` **is** the decision (judge `{status, reason, checklist}`, coach `{message}`, verdict prose, or a draft). |
| **Complete a donation** (agent-side crawl) | After a failed pact is approved (status `donated`): `pact_provision_card` → `pact_card_credential` (the full single-use, merchant-locked card), open the charity's donate page in your own browser and pay with that card, then `pact_record_donation_receipt` with your evidence. The card is a secret — use it only on that one charity's page. |

**Two decision paths.** Direct: you own a pact by id, so `pact_submit_proof[_image]`
(judged inline) and/or `pact_settle` finalizes it. Broker: for a task the website
enqueued — in this product the website is only the landing page + `/create`, so the one
task it enqueues is the **draft**; after that it hands the user off to download and
install the app, where you are the primary brain. The broker tools need an agent token
with the `claim_tasks` + `post_results` scopes; the direct tools work without auth in
`local_dev`.

## Safety

Real money moves only after explicit human Link approval, behind
`PACT_PAYMENT_MODE=link_cli` and `PACT_LINK_MODE=live`. The skill never auto-executes a
live charge, and Link approval is not the same thing as charity receipt confirmation.
Refuse unsafe goals (self-harm, restrictive-eating, coercive or third-party stakes) at
draft time with a supportive message and a crisis-resource line; enforce that the pact
subject is the staking user.
