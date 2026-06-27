# Pact Full Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Pact web app in the Geist style as three surfaces (Dashboard, Create, living Pact), wire the post-creation experience (Link connect, agent loop, motivation), keeping the backend suite green and the demo working end-to-end.

**Architecture:** Backend = the existing FastAPI engine plus a small `link.py` (per-owner funding account), a `progress.py` read-model helper, and a handoff-on-seal hook. Web = three Geist routes sharing `geist.css` tokens and three reusable components (`ProgressRing`, `CoachThread`, `LinkConnect`), both surfaces reading the same server truth. Agent loop reuses broker + outbox + `/pact` skill.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / SQLite (single conn + write-lock); Vite + React + TS; pytest + httpx.

---

## File Structure

**Backend — new:**
- `src/pact/link.py` — `LinkAccount` model helpers + `connect()`; pure.
- `src/pact/progress.py` — `compute_progress(pact, proofs, now)` → derived `{valid_count,target,pct,days_left,on_track,behind,milestone}`.
- `tests/test_link.py`, `tests/test_progress.py`, `tests/test_handoff.py`.

**Backend — modify:**
- `src/pact/repository.py` — `link_accounts` table + `get_link_account`/`save_link_account`.
- `src/pact/api.py` — `GET /api/link/status`, `POST /api/link/connect`; augment `get_pact`/`list_pacts` responses with a `progress` block; settlement Link-gate; handoff enqueue on confirm/seal.
- `src/pact/lifecycle.py` — `close_dispute_window`/settle check `link.connected` before firing the donation (else stay `donation_pending`).
- `src/pact/demo.py` — seed states that exercise active/behind/verdict/donated + a not-connected Link owner.

**Web — new:**
- `web/src/geist.css` — shared `--pc-*` tokens + Geist fonts (extracted from `create.css`).
- `web/src/screens/Dashboard.tsx`, `web/src/screens/Pact.tsx`.
- `web/src/components/ProgressRing.tsx`, `web/src/components/CoachThread.tsx`, `web/src/components/LinkConnect.tsx`.

**Web — modify/remove:**
- `web/src/main.tsx` — routes → `/`, `/create`, `/pact/:pactId`.
- `web/src/api.ts`, `web/src/types.ts` — `linkStatus`/`linkConnect`, `Progress` type, pact `progress` field.
- Remove `web/src/screens/{Home,Confirm,Active,Verdict}.tsx`.

---

## Task 1: Link account — model + persistence

**Files:** Create `src/pact/link.py`, `tests/test_link.py`; Modify `src/pact/repository.py`, `src/pact/models.py`.

- [ ] **Step 1 — failing test** (`tests/test_link.py`):
```python
from datetime import datetime, timezone
from pact.clock import FixedClock
from pact.link import connect_account, new_account

def test_new_account_defaults_disconnected():
    acct = new_account("a@b.com")
    assert acct.owner == "a@b.com" and acct.connected is False and acct.funding_ref is None

def test_connect_sets_connected_and_funding_ref():
    clock = FixedClock(datetime(2026, 6, 26, tzinfo=timezone.utc))
    acct = connect_account(new_account("a@b.com"), clock)
    assert acct.connected is True
    assert acct.funding_ref == "test_funding_a@b.com"
    assert acct.connected_at == clock.now()
```

- [ ] **Step 2 — run, expect fail** (`uv run pytest tests/test_link.py -q`).
- [ ] **Step 3 — implement.** Add `LinkAccount` to `models.py`:
```python
class LinkAccount(BaseModel):
    owner: str
    connected: bool = False
    funding_ref: str | None = None
    connected_at: datetime | None = None
```
Create `src/pact/link.py`:
```python
from pact.clock import Clock
from pact.models import LinkAccount

def new_account(owner: str) -> LinkAccount:
    return LinkAccount(owner=owner)

def connect_account(acct: LinkAccount, clock: Clock) -> LinkAccount:
    # Safe local-first stub: register a deterministic TEST funding ref. Never
    # touches a real card or moves money.
    if acct.connected:
        return acct
    return acct.model_copy(update={
        "connected": True,
        "funding_ref": f"test_funding_{acct.owner}",
        "connected_at": clock.now(),
    })
```
Add repo persistence (`repository.py`): `link_accounts(owner TEXT PRIMARY KEY, data TEXT)` table in `init_schema`, plus:
```python
def save_link_account(self, acct: LinkAccount) -> None:
    with self._write_lock:
        self.conn.execute("INSERT OR REPLACE INTO link_accounts (owner, data) VALUES (?, ?)",
                          (acct.owner, acct.model_dump_json()))
        self.conn.commit()

def get_link_account(self, owner: str) -> LinkAccount | None:
    row = self.conn.execute("SELECT data FROM link_accounts WHERE owner = ?", (owner,)).fetchone()
    return LinkAccount.model_validate_json(row["data"]) if row else None
```
(Import `LinkAccount` in repository.py.)

- [ ] **Step 4 — run, expect pass.**
- [ ] **Step 5 — commit** `feat(link): LinkAccount model + connect stub + persistence`.

## Task 2: Link API — status + connect

**Files:** Modify `src/pact/api.py`; add tests to `tests/test_link.py`.

- [ ] **Step 1 — failing test** (httpx AsyncClient like `test_api_charities.py`):
```python
async def test_link_status_then_connect(tmp_path):
    # build app (reuse a _build helper), owner has no account -> connected False
    r = await client.get("/api/link/status", params={"owner": "a@b.com"})
    assert r.json() == {"owner": "a@b.com", "connected": False, "funding_ref": None}
    r = await client.post("/api/link/connect", json={"owner": "a@b.com"})
    assert r.json()["connected"] is True
    r = await client.get("/api/link/status", params={"owner": "a@b.com"})
    assert r.json()["connected"] is True
```
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement** in `api.py`:
```python
class LinkConnectIn(BaseModel):
    owner: str

@app.get("/api/link/status")
def link_status(owner: str):
    acct = repo.get_link_account(owner) or new_account(owner)
    return {"owner": owner, "connected": acct.connected, "funding_ref": acct.funding_ref}

@app.post("/api/link/connect")
def link_connect(body: LinkConnectIn):
    acct = repo.get_link_account(body.owner) or new_account(body.owner)
    acct = connect_account(acct, clock)
    repo.save_link_account(acct)
    return {"owner": acct.owner, "connected": acct.connected, "funding_ref": acct.funding_ref}
```
(Import `new_account, connect_account`.)
- [ ] **Step 4 — run, expect pass.** **Step 5 — commit** `feat(api): link status + connect endpoints`.

## Task 3: Settlement Link-gate

**Files:** Modify `src/pact/lifecycle.py` (+ `api.py` settle path); `tests/test_link.py`.

Goal: when a pact would donate on fail but the owner's Link is **not connected**, keep it `donation_pending` (no silent drop). When connected, donation fires as today.

- [ ] **Step 1 — failing test:** an owned, failed pact whose owner has no Link account → after `close_dispute_window`/settle, status stays `donation_pending`, `payment.calls == 0`. After `link/connect`, re-running settlement fires the donation (`donated`, `calls == 1`).
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement.** In the donation-firing path (`close_dispute_window` in lifecycle, called from the scheduler/settle), accept a `link_connected: bool` parameter (computed by the caller in `api.py`/scheduler from `repo.get_link_account(pact.owner)`); if not connected, return the pact unchanged at `donation_pending`. Wire the api settle + scheduler callers to pass `link_connected`.
- [ ] **Step 4 — run, expect pass + full suite green.** **Step 5 — commit** `feat(link): gate charge-on-fail on a connected funding source`.

## Task 4: Progress read-model

**Files:** Create `src/pact/progress.py`, `tests/test_progress.py`; Modify `api.py` (`get_pact`/`list_pacts` add `progress`).

- [ ] **Step 1 — failing test** (`tests/test_progress.py`): given a pact (`target_count=5`, deadline) + a list of proofs (3 passed on 3 distinct days), `compute_progress(pact, proofs, now)` →
```python
{"valid_count": 3, "target": 5, "pct": 60, "days_left": <int>, "on_track": <bool>,
 "behind": <bool>, "milestone": 50}
```
`milestone` = highest crossed of {25,50,75,100}; `on_track` = valid_count >= expected-by-now (linear over the window); `behind` = not on_track and days_left small. Pin exact expectations in the test.
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement** `compute_progress` reusing the existing distinct-valid-day logic (the same the settle/`user_reply` path uses — extract or import it; do NOT duplicate the bucket logic). Augment `api.get_pact` and `list_pacts`:
```python
def _with_progress(pact):
    proofs = repo.list_proofs(pact.id)
    d = pact.model_dump(mode="json")
    d["progress"] = compute_progress(pact, proofs, clock.now())
    return d
```
- [ ] **Step 4 — run, expect pass.** **Step 5 — commit** `feat(api): derived progress (valid/pct/days_left/on_track/milestone)`.

## Task 5: Handoff on seal

**Files:** Modify `src/pact/api.py` (confirm/start) + `src/pact/coaching.py` if needed; `tests/test_handoff.py`.

- [ ] **Step 1 — failing test:** after draft→confirm(consent)→owner→start, a handoff/first-coaching `CoachingMessage` exists for the pact (queryable via `GET /api/pacts/{id}/coach` or the outbox), addressed from the assigned agent.
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement:** on `start` (pact goes active), generate the opening coaching message (reuse `coaching.generate`) and persist it (outbox path). Idempotent (don't double-seed on repeated start).
- [ ] **Step 4 — run, expect pass + full suite green.** **Step 5 — commit** `feat: enqueue agent handoff/first coaching on start`.

## Task 6: Web shared foundation (geist.css + api/types + ProgressRing)

**Files:** Create `web/src/geist.css`, `web/src/components/ProgressRing.tsx`; Modify `web/src/api.ts`, `web/src/types.ts`.

- [ ] Extract the `--pc-*` tokens + `@font-face`/font imports from `create.css` into `geist.css`; import it in `main.tsx`. (Leave `create.css` working.)
- [ ] `types.ts`: add `Progress` (`valid_count,target,pct,days_left,on_track,behind,milestone`) and `progress?: Progress` on the pact type; `LinkStatus` (`owner,connected,funding_ref`).
- [ ] `api.ts`: add `linkStatus(owner)`, `linkConnect(owner)`.
- [ ] `ProgressRing.tsx`: SVG ring, props `{pct:number; size?:number; label?:string}`. Pure, no data.
- [ ] Commit `feat(web): shared geist tokens, link api, ProgressRing`.

## Task 7: Routing strip + Dashboard

**Files:** Modify `web/src/main.tsx`; Create `web/src/screens/Dashboard.tsx`, `web/src/components/LinkConnect.tsx`; Remove `Home/Confirm/Active/Verdict.tsx`.

- [ ] Routes → `{path:"/",element:<Dashboard/>}`, `/create`, `{path:"/pact/:pactId",element:<Pact/>}`. Delete old screens + their imports.
- [ ] `Dashboard.tsx`: fetch `profile` + `list_pacts(owner)`. Record band (current/best streak, kept/failed). Active pacts as cards (charity stamp, title, stake, `ProgressRing` from `pact.progress.pct`, days left, on-track/behind chip) → link `/pact/:id`. History list. `LinkConnect` banner shown when `pacts.length>0 && !linkStatus.connected`. Empty state → Create.
- [ ] `LinkConnect.tsx`: explains "register a funding source so your stake is real (no money moves now)"; button → `linkConnect(owner)` → refresh. Used as banner + modal.
- [ ] `npm run build` clean. Commit `feat(web): 3-route shell + Dashboard + LinkConnect`.

## Task 8: Living Pact surface

**Files:** Create `web/src/screens/Pact.tsx`, `web/src/components/CoachThread.tsx`.

- [ ] `Pact.tsx` fetches the pact (with `progress`), proofs, coaching thread; renders by `status`:
  - **active:** header (title/charity/stake), big `ProgressRing` (`progress.pct`, `valid_count of target`), days-left + on-track/behind, **loss-framing** line when `behind` ("$X and {charity} are one missed day away"), **milestone** celebration when `progress.milestone` increases, **photo-proof upload** (reuse existing `uploadProofImage` w/ token nonce), `CoachThread`, **Cancel** (cooling-off/forfeit disclosure), Link-required prompt if `donation_pending` && !connected.
  - **settling/verdict:** wax-stamp pass/fail, single **Dispute** affordance, `needs_review` "under review".
  - **donated/kept:** terminal summary + back to dashboard.
- [ ] `CoachThread.tsx`: renders coaching messages (agent + user check-ins) + a check-in composer (`POST /coach`).
- [ ] `npm run build` clean. Commit `feat(web): living /pact/:id surface + CoachThread`.

## Task 9: Demo harness + agent-loop polish

**Files:** Modify `src/pact/demo.py`, `web/src/App.tsx` (demo bar nav targets), as needed.

- [ ] Demo seed: WIN/FAIL/LIVE already exist; ensure LIVE shows real progress and a coaching thread, FAIL exercises verdict/dispute, and one owner is **Link not-connected** so the banner shows. Add a "behind pace" pact for loss-framing.
- [ ] Verify the agent handoff message appears in the LIVE pact thread; nudges land in the outbox/thread.
- [ ] `uv run pytest -q` green; `npm run build` clean. Commit `feat(demo): seed states for redesigned surfaces`.

## Task 10: Browser verification + merge

- [ ] One-process serve (`npm run build` + `PACT_CLOCK_MODE=demo uvicorn pact.main:app`), browser-verify: Dashboard (record + live cards + Link banner), Create → Open my pact → living Pact (active w/ ring + proof + thread + milestone/loss-framing), verdict state, Link-connect flow.
- [ ] Fix any issues; keep suite green + build clean.
- [ ] Merge `feat/pact-redesign` → `master`; push. Update memory.

---

## Self-Review

**Spec coverage:** §1 surfaces → Tasks 7–8; §2 agent loop → Tasks 5,8,9 (reuses outbox/broker/skill); §3 Link → Tasks 1–3,7; §4 motivation → Tasks 4 (progress/milestone) + 7 (streaks) + 8 (loss-framing/thread) + 9 (nudges); §5 backend additions → Tasks 1–5; §6 data flow (proof) → existing image endpoint + Task 4 progress; §7 scope → stubs/gates preserved; §8 tests → each backend task is TDD + Task 10 browser. Covered.

**Placeholder scan:** progress `on_track`/`behind`/`milestone` exact formula is pinned in the Task-4 test (not left vague). No TBDs.

**Type consistency:** `Progress` fields (`valid_count,target,pct,days_left,on_track,behind,milestone`) identical across `progress.py`, the api `progress` block, `types.ts`, and consumers. `LinkAccount` fields consistent across model/repo/api. `link_status` response shape `{owner,connected,funding_ref}` identical in Task 2 and Task 6 consumer.
