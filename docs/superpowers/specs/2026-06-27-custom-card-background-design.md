# Custom-goal card background image — design spec

**Date:** 2026-06-27
**Status:** Proposed (awaiting review)
**Scope:** The `/create` flow only — the "Create your own" (custom goal) path, stage 1 ("Name it & set the pace").

## Summary

On the custom-goal step, let the user pick a **background photo** for their pact card.
Shrink the goal-title input and place a **photo-icon button** to its right; clicking it
opens a picker of **5 presets** (`create_1`–`create_5`). The choice is **persisted on the
pact** (a new backend field) and **rendered on the card within the create flow**. Home and
Pact-detail keep today's glyph icons for now — wiring the saved image into those screens is a
separate, later piece of work.

## Locked decisions (from review)

| Decision | Choice |
|---|---|
| Image source | **5 presets only** (`create_1`–`create_5`) — no custom upload yet |
| Persistence | **Persist** the selection on the pact (survives creation) |
| Render scope | **Create flow only** — do not change Home / Pact-detail card renders yet |
| Applies to | **Custom goals only** — templated cards keep their baked-in painterly art |

## Assets

Source files live at `~/Desktop/images/create_1.png … create_5.png` (~2 MB each).

- Copy them into `web/public/card-bg/` → served as `/card-bg/create_1.png` … `/card-bg/create_5.png`.
- These are large source PNGs; before shipping, **downscale/compress** to a card-appropriate
  size (target ≲ 250 KB each, ~900px wide) so the picker and card render stay fast. The picker
  thumbnails can use the same files via CSS sizing for now, but compression is required before merge.

## Backend changes

Thread a new optional field along the **exact path the recently-added `description` field
takes** (commit 7b4fe81):

1. `src/pact/api.py` — add `card_background: str | None = None` to `CreateIn`; pass
   `card_background=body.card_background` into `create_pact_structured(...)` in the
   `/api/pacts/create` handler.
2. `src/pact/lifecycle.py` — add a `card_background: str | None = None` parameter to
   `create_pact_structured(...)` and set it on the constructed `Pact(...)`. (Unlike
   `description`, which is woven into the `goal` text, this is stored as its own field.)
3. `src/pact/models.py` — add `card_background: str | None = None` to the `Pact` model.
   `model_dump(mode="json")` then surfaces it automatically in all pact responses.

**Validation:** accept only the 5 known preset paths (`/card-bg/create_{1..5}.png`); reject
anything else with a 422 so the field can't be used to inject arbitrary URLs. Keep the
allowed set in one place (a small constant) mirroring the charity-URL allowlist pattern.

## Frontend changes (`web/src/screens/Create.tsx` + `create.css`)

**State:**
- Add `const [customBg, setCustomBg] = useState<string | null>(null);`
- Reset it in `select()` and (if kept) any restart path, alongside `setCustomDesc("")`.
- Add a `BG_PRESETS = ["/card-bg/create_1.png", … "/card-bg/create_5.png"]` constant.

**Picker UI (stage 1, `isCustom` only):**
- Wrap the existing `.pc-name-input` in a row: input (flex-grows, slightly narrower) +
  a square `.pc-bg-btn` to its right.
- `.pc-bg-btn` shows a small **photo/image icon** when nothing is chosen, and the **selected
  thumbnail** once a preset is picked (immediate feedback).
- Clicking it toggles a compact popover/grid of the 5 preset thumbnails; selecting one sets
  `customBg` and closes the popover. Keyboard-accessible (focusable options, Esc to close),
  matching the existing `useFocusTrap` / a11y patterns in the codebase.

**Card render (create flow):**
- Pass `customBg` into `createPact({ …, card_background: customBg ?? undefined })` in `seal()`.
- Render the chosen photo on the custom card so the choice is visible in-flow (see open
  question below for exactly where).

**Type:** add `card_background?: string | null` to the `Pact` interface in `web/src/types.ts`,
and `card_background?: string` to the `createPact` request body type in `web/src/api.ts`.

## Open question (resolve during review)

The hero card is **flipped to its back** (the editorial parchment) during stages 1–4, so the
card *front* isn't visible while the user is choosing. Where should the chosen photo appear so
the selection feels real in-flow?

- **Option A (recommended):** Render a **photo header band** at the top of the card *back*
  (`CardBack`) for custom goals — the parchment editorial sits below it. Strongest immediate
  feedback; makes custom cards visually distinct from templated ones.
- **Option B:** Keep the photo on the **front art only** (photo + title overlay, mirroring how
  templated cards bake title into art). In-flow feedback is limited to the picker-button
  thumbnail until the card is shown un-flipped elsewhere; cleaner consistency with templated cards.

Both persist the same `card_background` value; this only affects where it renders during creation.

## Out of scope (explicitly deferred)

- Rendering the saved background on **Home** and **Pact-detail** cards (they keep `GoalGlyph`).
- **Custom uploads** (only the 5 presets for now).
- Background images for **templated** goals (they keep their painterly front art).

## Acceptance criteria

1. On the custom-goal step, the title input is narrower and a photo-icon button sits to its right.
2. The button opens a picker of 5 presets; choosing one updates the button thumbnail.
3. The chosen photo is visible on the card during the create flow (per the resolved open question).
4. Sealing persists `card_background`; `GET /api/pacts/:id` returns it.
5. The backend rejects any `card_background` not in the 5-preset allowlist (422).
6. Templated goals, Home, and Pact-detail are visually unchanged.
7. `tsc -b` passes; no new console errors in the create flow.
