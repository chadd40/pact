// Mirrors the FastAPI / pydantic shapes in src/pact/models.py. Kept loose where the
// backend is loose (dicts) and precise where the UI depends on it.

export type PactStatus =
  | "draft"
  | "active"
  | "evaluating"
  | "succeeded"
  | "failed"
  | "needs_review"
  | "canceled_release"
  | "canceled_forfeit"
  | "donation_pending"
  | "donated"
  | "donation_failed"
  | "donation_declined";

export type StakeState =
  | "none"
  | "committed"
  | "executing"
  | "executed"
  | "released"
  | "declined"
  | "error";

export type ProofStatus = "passed" | "failed" | "ambiguous";

export type Modality = "photo" | "log" | "url" | "file" | "text";

export interface Rubric {
  modality: Modality;
  require_token: boolean;
  must_show: string[];
  reject_if: string[];
  min_distinct_days: number;
  count_target: number;
  rest_if_injured_counts: boolean;
  rigor_floor: Record<string, unknown>;
}

// Derived progress/pace block the API attaches to a pact (src/pact/progress.py).
export interface Progress {
  valid_count: number;
  target: number;
  pct: number; // 0..100
  days_left: number;
  on_track: boolean;
  behind: boolean;
  milestone: number; // highest crossed of 25/50/75/100, else 0
}

// Derived weekly cadence read-model (src/pact/progress.compute_cadence). Present on
// GET /api/pacts and /api/pacts/:id alongside `progress`.
export interface Cadence {
  days_per_week: number;
  weeks: number;
  week_number: number; // 1..weeks
  this_week_valid: number;
  this_week_target: number;
}

// Donation approve-and-monitor state (the two-phase Link flow).
export type DonationStateName =
  | "idle"
  | "awaiting_approval"
  | "approved"
  | "donated"
  | "denied"
  | "expired"
  | "declined"
  | "error";
export interface DonationState {
  state: DonationStateName;
  status: PactStatus;
  stake_state: StakeState;
  spend_request_id: string | null;
  approval_status?: string | null;
  payment_status?: string | null;
}

export interface Pact {
  id: string;
  owner: string;
  original_prompt: string;
  title: string;
  goal: string;
  timezone: string;
  deadline_at: string;
  target_count: number;
  distinct_days: boolean;
  days_per_week?: number | null;
  weeks?: number | null;
  recommended_stake_cents: number;
  stake_amount_cents: number;
  currency: string;
  charity_id: string;
  charity_url: string;
  agent?: string | null;
  card_art?: string | null;
  signer_name?: string | null;
  proof_source: string;
  freezes_allowed: number;
  freezes_used: number;
  freeze_extension_hours: number;
  rubric: Rubric;
  status: PactStatus;
  stake_state: StakeState;
  spend_request_id: string | null;
  created_at: string;
  started_at: string | null;
  verdict_at: string | null;
  dispute_window_closes_at: string | null;
  progress?: Progress; // present on GET /api/pacts and /api/pacts/:id
  cadence?: Cadence; // present on GET /api/pacts and /api/pacts/:id
}

export interface LinkStatus {
  owner: string;
  connected: boolean;
  funding_ref: string | null;
  ready?: boolean;
  payment_method_id?: string | null;
  payment_method_label?: string | null;
  payment_method_last4?: string | null;
  auth_status?: string | null;
  checked_at?: string | null;
  error?: string | null;
}

export interface RuntimeInfo {
  payment_mode: string;
  link_mode: string;
  reasoning_mode: string;
  auth_mode: string;
  live_money_enabled: boolean;
}

export interface ConnectorEntry {
  key: string;
  name: string;
  kind: string;
  status: string;
  installed: boolean;
  capabilities: string[];
  detail: string;
  action: string;
  command?: string;
  config?: Record<string, unknown>;
  install_path?: string;
}

export interface ConnectorHealth {
  owner: string;
  runtime: {
    reasoning_mode: string;
    auth_mode: string;
    base_url: string;
  };
  agent_token: {
    status: "ready" | "missing" | string;
    token_prefix: string | null;
    expires_at: string | null;
    last_used_at: string | null;
    scopes: string[];
  };
  worker: {
    status: "online" | "offline" | string;
    last_seen_at: string | null;
    presence_window_seconds: number;
  };
  capabilities: {
    text: boolean;
    vision: boolean;
  };
  connectors: ConnectorEntry[];
  mcp: {
    server_name: string;
    command: string;
    config: Record<string, unknown>;
  };
}

export interface Proof {
  id: string;
  pact_id: string;
  modality: Modality;
  received_at: string;
  day_bucket: string;
  token_issued: string | null;
  token_ok: boolean;
  phash: string | null;
  dup_of: string | null;
  artifact_path: string | null;
  status: ProofStatus;
  judge_reason: string;
  judge_checklist: Record<string, unknown>;
}

export interface Verdict {
  pact_id: string;
  status: PactStatus;
  valid_proof_count: number;
  target_count: number;
  freezes_used: number;
  summary: string;
  proof_ids: string[];
  payment_action: string;
  payment_ref: string | null;
  receipt_artifact_path: string | null;
  honesty_note: string;
}

export interface DonationReceipt {
  pact_id: string;
  receipt_status: "unconfirmed" | "manual_receipt" | "provider_confirmed" | "failed_or_reversed" | string;
  receipt_source: string | null;
  receipt_ref: string | null;
  receipt_url: string | null;
  receipt_artifact_path: string | null;
  confirmed_at: string | null;
  confirmation_notes: string | null;
}

export interface Profile {
  owner: string;
  pact_ids: string[];
  current_streak: number;
  best_streak: number;
  kept: number;
  failed: number;
  history: Array<Record<string, unknown>>;
}

export interface CoachingMessage {
  id: string;
  pact_id: string;
  direction: string; // "inbound" | "outbound"
  trigger: string;
  pact_state_snapshot: Record<string, unknown>;
  channel: string;
  body: string;
  sent_at: string;
  delivered_at: string | null;
}

// One scheduler sweep. The backend returns an implementation-defined dict; the UI
// only needs to know a sweep ran, so it's kept loose.
export type TickResult = Record<string, unknown>;

export interface Charity {
  id: string;
  name: string;
  donation_url: string;
  allowed_domains: string[];
  category: string;
  description: string;
  default_amounts: number[];
  checkout_kind: string;
  stamp: string;
}

// Packet shape (built by src/pact/packet.py + coaching_log merged in api.py).
export interface PacketProofRow {
  id: string;
  date: string;
  modality: string;
  status: ProofStatus;
  judge_reason: string;
  judge_checklist: Record<string, unknown>;
  thumbnail: string | null;
}

export interface PacketVerdict {
  status: string;
  banner: string;
  valid_proof_count: number;
  target_count: number;
  freezes_used: number;
  summary: string;
  payment_action: string;
  payment_ref: string | null;
  receipt_artifact_path: string | null;
  receipt_status: "not_required" | "unconfirmed" | "manual_receipt" | "provider_confirmed" | "failed_or_reversed" | string;
  receipt_source: string | null;
  receipt_ref: string | null;
  receipt_url: string | null;
  confirmed_at: string | null;
}

export interface Packet {
  pact: Pact;
  proofs: PacketProofRow[];
  verdict: PacketVerdict;
  honesty_note: string;
  coaching_log: CoachingMessage[];
}

export interface DemoSeedResult {
  win: string;
  fail: string;
  live: string;
}

export interface DemoAdvanceResult {
  now: string;
  settled: string[];
}
