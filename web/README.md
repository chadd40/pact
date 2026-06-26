# Pact — Web UI

The demo-facing SPA for **Pact**, a self-binding commitment engine. Built with
Vite + React + TypeScript, wired to the FastAPI backend. Design direction:
**"Binding Contract"** — editorial, document-like, with a warm-coach / cold-auditor
duality.

## Run it

From the **repo root**, start the backend in demo clock mode (so `advance-day` /
`reset` work and the clock is deterministic):

```bash
PACT_CLOCK_MODE=demo uv run uvicorn pact.main:app --port 8000
```

Then start the SPA:

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server proxies `/api` and `/demo` to `http://127.0.0.1:8000`.

## The demo flow

1. Click **Seed demo** in the top console bar — seeds three pacts (WIN / FAIL /
   LIVE), stamps the owner, and pins the demo clock.
2. **Home** shows the streak hero and the ledger. Open the **FAIL** pact to see the
   `FAILED · $5 → CHARITY` wax-seal verdict; the **WIN** pact shows `SUCCEEDED · $0`.
3. **Advance day** moves the demo clock forward; any pact past its deadline settles.
4. **New pact → Create → Confirm → Active**: draft a goal, review the contract,
   approve the stake, then submit a proof (get token → write the nonce in-frame →
   submit → see the judge verdict).

## Structure

```
web/src/
  api.ts             typed fetch client for the FastAPI surface
  types.ts           TS mirrors of the pydantic models
  lib.ts             formatting + status/pace/countdown helpers
  App.tsx            shell + persistent demo console bar + demo-clock context
  styles.css         design tokens (palette, type) + primitives
  components.css     screen + component styles
  components/
    WaxSeal.tsx      the signature circular wax-seal verdict stamp (SVG)
    Reveal.tsx       staggered page-load reveal
  screens/
    Home.tsx         streak hero + pact ledger
    Create.tsx       prompt → draft (handles 422 safety refusals)
    Confirm.tsx      the contract: rubric, stake, 10-charity picker, sign
    Active.tsx       countdown, pace, coach thread, proof-submit flow
    Verdict.tsx      wax-seal verdict + evidence ledger + receipt + renew
```

Type `Fraunces` (display), `Hanken Grotesk` (UI), `JetBrains Mono` (data) load from
Google Fonts. Palette: paper `#F4EFE6`, ink `#1A1714`, stake-red `#7C2D2D`,
sealed-gold `#A6792E`, kept-green `#2F5D4F`.
