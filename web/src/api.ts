import type {
  Charity,
  CoachingMessage,
  DemoAdvanceResult,
  DemoSeedResult,
  LinkStatus,
  Pact,
  Packet,
  Profile,
  Proof,
  TickResult,
  Verdict,
} from "./types";

// The fixed demo owner. Every pact created in this UI is stamped with it so the
// profile aggregates a single coherent track record.
export const DEMO_OWNER = "demo@pact.local";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown }
): Promise<T> {
  const opts: RequestInit = { ...init };
  if (init?.json !== undefined) {
    opts.method = opts.method ?? "POST";
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(init.json);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      // FastAPI puts the human-readable reason on `detail`.
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // ── Pacts ────────────────────────────────────────────────────────────────
  draftPact: (prompt: string) =>
    request<Pact>("/api/pacts/draft", { json: { prompt } }),

  // Structured create: builds an ACTIVE pact directly from the new Create flow's
  // choices (goal, frequency, stake, charity, agent, consent). Returns the created
  // pact so the UI can land straight on the Active screen.
  createPact: (payload: {
    goal_title: string;
    goal_template: string | null;
    days_per_week: number;
    weeks: number;
    stake_amount_cents: number;
    charity_id: string;
    agent: string | null;
    consent_acknowledged: boolean;
    owner: string;
  }) => request<Pact>("/api/pacts/create", { json: payload }),

  confirmPact: (
    pact_id: string,
    stake_amount_cents: number,
    charity_id: string,
    consent_acknowledged: boolean
  ) =>
    request<Pact>("/api/pacts", {
      json: { pact_id, stake_amount_cents, charity_id, consent_acknowledged },
    }),

  setOwner: (pactId: string, owner: string) =>
    request<Pact>(`/api/pacts/${pactId}/owner`, { json: { owner } }),

  getPact: (pactId: string) => request<Pact>(`/api/pacts/${pactId}`),

  listPacts: (owner?: string) =>
    request<Pact[]>(`/api/pacts${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`),

  proofToken: (pactId: string) =>
    request<{ token: string }>(`/api/pacts/${pactId}/proof-token`, { method: "POST" }),

  submitProof: (
    pactId: string,
    body: { modality: string; token: string; content_ok?: boolean; image_path?: string | null }
  ) =>
    request<Proof>(`/api/pacts/${pactId}/proofs`, {
      json: { content_ok: true, image_path: null, ...body },
    }),

  // Real photo proof: EXIF-stripped, stored, pHashed and judged server-side. The
  // backend reads a multipart form (`token`, `content_ok`, file `image`). We hand
  // a FormData straight to fetch and deliberately do NOT set Content-Type — the
  // browser must set it with the multipart boundary or the upload won't parse.
  uploadProofImage: (
    pactId: string,
    token: string,
    file: File,
    contentOk = true
  ) => {
    const form = new FormData();
    form.append("token", token);
    form.append("content_ok", String(contentOk));
    form.append("image", file);
    return request<Proof>(`/api/pacts/${pactId}/proofs/image`, {
      method: "POST",
      body: form,
    });
  },

  // Server-truth proof list for a pact, ordered by received_at.
  getProofs: (pactId: string) => request<Proof[]>(`/api/pacts/${pactId}/proofs`),

  freeze: (pactId: string) =>
    request<Pact>(`/api/pacts/${pactId}/freeze`, { method: "POST" }),

  cancel: (pactId: string) =>
    request<Pact>(`/api/pacts/${pactId}/cancel`, { method: "POST" }),

  settle: (pactId: string) =>
    request<Verdict>(`/api/pacts/${pactId}/settle`, { method: "POST" }),

  dispute: (pactId: string) =>
    request<Verdict>(`/api/pacts/${pactId}/dispute`, { method: "POST" }),

  packet: (pactId: string) => request<Packet>(`/api/pacts/${pactId}/packet`),

  renew: (pactId: string) =>
    request<Pact>(`/api/pacts/${pactId}/renew`, { method: "POST" }),

  // ── Coaching ───────────────────────────────────────────────────────────────
  getCoach: (pactId: string) =>
    request<CoachingMessage[]>(`/api/pacts/${pactId}/coach`),

  postCoach: (pactId: string, message: string) =>
    request<{ inbound: CoachingMessage; outbound: CoachingMessage }>(
      `/api/pacts/${pactId}/coach`,
      { json: { message } }
    ),

  // Run one scheduler sweep: reconcile, close dispute windows, and enqueue any
  // proactive coaching nudges into the outbox.
  tick: () => request<TickResult>("/api/tick", { method: "POST" }),

  // The owner's undelivered outbound coaching messages (the relay queue).
  outbox: (owner: string) =>
    request<CoachingMessage[]>(`/api/outbox?owner=${encodeURIComponent(owner)}`),

  // Mark a coaching/outbox message as delivered so it leaves the relay queue.
  markDelivered: (msgId: string) =>
    request<CoachingMessage>(`/api/coach/${msgId}/delivered`, { method: "POST" }),

  // ── Profile & catalog ────────────────────────────────────────────────────
  profile: (owner: string) =>
    request<Profile>(`/api/profile?owner=${encodeURIComponent(owner)}`),

  charities: () => request<Charity[]>("/api/charities"),

  // ── Link (funding connection) ──────────────────────────────────────────────
  // Connected after the first pact: registers a TEST funding source so the
  // charge-on-fail donation is allowed to fire. No money moves (local-first).
  linkStatus: (owner: string) =>
    request<LinkStatus>(`/api/link/status?owner=${encodeURIComponent(owner)}`),

  linkConnect: (owner: string) =>
    request<LinkStatus>("/api/link/connect", { json: { owner } }),

  // ── Demo control ───────────────────────────────────────────────────────────
  demoSeed: () => request<DemoSeedResult>("/demo/seed", { method: "POST" }),

  demoAdvance: () => request<DemoAdvanceResult>("/demo/advance-day", { method: "POST" }),

  demoReset: () => request<DemoSeedResult>("/demo/reset", { method: "POST" }),
};
