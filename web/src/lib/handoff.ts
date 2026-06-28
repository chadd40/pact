// Self-contained web->app handoff: a pact drafted on the web is encoded to a
// copy-paste blob and decoded + re-validated in the desktop app. No server.
export type PactDraft = {
  goal: string;
  goal_template?: string;
  what_counts?: string;
  frequency: { days_per_week: number; weeks: number };
  stake_amount_cents: number;
  charity_id: string;
  agent: string;
  signer_name?: string;
};

export type PactDraftTransfer = {
  v: 1;
  kind: "pact-draft";
  issued_at: string;
  nonce: string;
  checksum: string;
  draft: PactDraft;
};

const PREFIX = "pact1:";

// djb2 over the canonical draft JSON — catches paste truncation/corruption.
function checksum(draft: PactDraft): string {
  const s = JSON.stringify(canonical(draft));
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

// Stable key order so the checksum is reproducible across encode/decode.
// Optional fields (goal_template, what_counts, signer_name) are omitted when
// absent so they round-trip faithfully as undefined for drafts that lack them.
function canonical(d: PactDraft) {
  const base = {
    goal: d.goal,
    frequency: { days_per_week: d.frequency.days_per_week, weeks: d.frequency.weeks },
    stake_amount_cents: d.stake_amount_cents,
    charity_id: d.charity_id,
    agent: d.agent,
  };
  const withTemplate = d.goal_template ? { ...base, goal_template: d.goal_template } : base;
  const withCounts = d.what_counts ? { ...withTemplate, what_counts: d.what_counts } : withTemplate;
  return d.signer_name ? { ...withCounts, signer_name: d.signer_name } : withCounts;
}

function toB64url(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64url(s: string): string {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

export function encodeDraft(draft: PactDraft): string {
  const payload: PactDraftTransfer = {
    v: 1,
    kind: "pact-draft",
    issued_at: new Date().toISOString(),
    nonce: crypto.randomUUID(),
    checksum: checksum(draft),
    draft: canonical(draft),
  };
  return PREFIX + toB64url(JSON.stringify(payload));
}

export function decodeDraft(
  text: string
): { ok: true; draft: PactDraft } | { ok: false; error: string } {
  const t = text.trim();
  if (!t.startsWith(PREFIX)) return { ok: false, error: "That doesn't look like a Pact link. Copy it again from the web." };
  let obj: unknown;
  try {
    obj = JSON.parse(fromB64url(t.slice(PREFIX.length)));
  } catch {
    return { ok: false, error: "This pact link looks corrupted or incomplete. Copy the whole thing again." };
  }
  const p = obj as Partial<PactDraftTransfer>;
  if (p.v !== 1 || p.kind !== "pact-draft" || !p.draft)
    return { ok: false, error: "This pact link is from an unsupported version." };
  const d = p.draft as Partial<PactDraft>;
  const okShape =
    typeof d.goal === "string" &&
    d.frequency && typeof d.frequency.days_per_week === "number" && typeof d.frequency.weeks === "number" &&
    typeof d.stake_amount_cents === "number" &&
    typeof d.charity_id === "string" &&
    typeof d.agent === "string";
  if (!okShape) return { ok: false, error: "This pact link is missing some fields. Copy it again from the web." };
  const draft: PactDraft = canonical(d as PactDraft);
  if (checksum(draft) !== p.checksum)
    return { ok: false, error: "This pact link looks corrupted or incomplete. Copy the whole thing again." };
  return { ok: true, draft };
}
