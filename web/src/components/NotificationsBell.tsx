import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useDemo } from "../App";
import { useAppData } from "../data";
import { useLocalOwner } from "../owner";
import { dollars, formatDate } from "../lib";
import type { Charity, CoachingMessage, Pact, PactStatus } from "../types";

// Pacts in one of these states are stuck waiting on the human — a stake that was
// never resolved, a declined donation, or a failed charge. They belong at the top
// of the notifications tray as "needs resolution". needs_review is deliberately
// excluded: that's a suspended verdict where no money has moved and there's
// nothing for the owner to act on yet.
const RESOLVE_STATUS = new Set<PactStatus>(["donation_pending", "donation_declined", "donation_failed"]);

function resolutionLine(p: Pact, charityName: string): { sub: string; cta: string; icon: "alert" | "clock" } {
  const stake = dollars(p.stake_amount_cents);
  switch (p.status) {
    case "donation_pending":
      return { sub: `${stake} unresolved · ${charityName}`, cta: "Resolve", icon: "alert" };
    case "donation_declined":
      return { sub: "Donation declined · still unresolved", cta: "Resolve", icon: "alert" };
    case "donation_failed":
      return { sub: `Donation failed · retry ${stake}`, cta: "Retry", icon: "clock" };
    default:
      return { sub: `${stake} · needs resolution`, cta: "Resolve", icon: "alert" };
  }
}

function relTime(iso: string, nowMs: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const mins = Math.round((nowMs - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return formatDate(iso);
}

const BellIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="19" height="19">
    <path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7" />
    <path d="M9.5 20a2.5 2.5 0 0 0 5 0" />
  </svg>
);
const AlertIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);
const ClockIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" />
  </svg>
);
const CoachIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z" />
  </svg>
);
const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
    <circle cx="12" cy="12" r="9" /><path d="M8.5 12.5 11 15l4.5-6" />
  </svg>
);
const XIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="13" height="13">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export interface NotificationsMenuProps {
  resolutions: Pact[];
  nudges: CoachingMessage[];
  charityById: Record<string, Charity>;
  pactById: Record<string, Pact>;
  nowMs: number;
  onResolve: (id: string) => void;
  onOpenPact: (id: string) => void;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
}

// Presentational tray. Prop-driven (no hooks/network) so it's trivially testable.
// The NotificationsBell container below wires the live data.
export function NotificationsMenu({
  resolutions,
  nudges,
  charityById,
  pactById,
  nowMs,
  onResolve,
  onOpenPact,
  onMarkRead,
  onMarkAllRead,
}: NotificationsMenuProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const count = resolutions.length + nudges.length;

  // Close on outside click or Escape while open.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const ordered = [...resolutions].sort(
    (a, b) => +new Date(a.verdict_at || a.deadline_at) - +new Date(b.verdict_at || b.deadline_at)
  );

  return (
    <div className="nb-wrap" ref={wrapRef}>
      <button
        className="nb-btn"
        aria-label={count > 0 ? `Notifications, ${count} need you` : "Notifications"}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <BellIcon />
        {count > 0 && <span className="nb-badge">{count > 9 ? "9+" : count}</span>}
      </button>

      {open && (
        <div className="nb-menu" role="dialog" aria-label="Notifications">
          <div className="nb-head">
            <span className="nb-title">Notifications</span>
            {nudges.length > 0 && (
              <button className="nb-markall" onClick={onMarkAllRead}>Mark all read</button>
            )}
          </div>

          {ordered.length > 0 && (
            <>
              <div className="nb-sec nb-urgent">Needs resolution</div>
              <div className="nb-list nb-list--urgent">
                {ordered.map((p) => {
                  const charityName = charityById[p.charity_id]?.name ?? "charity";
                  const line = resolutionLine(p, charityName);
                  return (
                    <div className="nb-row nb-urgent" key={p.id}>
                      <button className="nb-rbody" onClick={() => onOpenPact(p.id)}>
                        <span className="nb-ico nb-urgent">{line.icon === "clock" ? <ClockIcon /> : <AlertIcon />}</span>
                        <span className="nb-rmain">
                          <span className="nb-rtitle">{p.title}</span>
                          <span className="nb-rsub">{line.sub}</span>
                        </span>
                      </button>
                      <span className="nb-trail">
                        <button className="nb-resolve" onClick={() => onResolve(p.id)}>{line.cta}</button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {nudges.length > 0 && (
            <>
              <div className="nb-sec">From your coach</div>
              <div className="nb-list">
                {nudges.map((n) => {
                  const title = pactById[n.pact_id]?.title;
                  return (
                    <div className="nb-row nb-coach" key={n.id}>
                      <button className="nb-rbody" onClick={() => onOpenPact(n.pact_id)}>
                        <span className="nb-ico nb-coach"><CoachIcon /></span>
                        <span className="nb-rmain">
                          <span className="nb-coach-body">{n.body}</span>
                          <span className="nb-coach-meta">Coach · {relTime(n.sent_at, nowMs)}{title ? ` · ${title}` : ""}</span>
                        </span>
                      </button>
                      <span className="nb-trail">
                        <button className="nb-dismiss" aria-label="Mark read" onClick={() => onMarkRead(n.id)}><XIcon /></button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {count === 0 && (
            <div className="nb-empty">
              <div className="nb-empty-ico"><CheckIcon /></div>
              <div className="nb-empty-title">You're all caught up</div>
              <div className="nb-empty-sub">Resolutions and coach nudges will show up here.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Live container: derives the resolution set from the shared pact list and pulls
// the owner's undelivered coach nudges from the outbox relay queue (populated by
// the scheduler's tick). "Mark read" drains a nudge from that queue via
// api.markDelivered — the dashboard is the only web consumer of the outbox, so
// this is safe and is exactly what markDelivered is for.
export function NotificationsBell() {
  const { pacts, charityById } = useAppData();
  const { bump, nowIso } = useDemo();
  const [owner] = useLocalOwner();
  const navigate = useNavigate();
  const [nudges, setNudges] = useState<CoachingMessage[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (!owner) return;
    let alive = true;
    api.outbox(owner)
      .then((m) => { if (alive) setNudges(m); })
      .catch(() => { if (alive) setNudges([]); });
    return () => { alive = false; };
  }, [owner, bump]);

  const resolutions = useMemo(() => pacts.filter((p) => RESOLVE_STATUS.has(p.status)), [pacts]);
  const pactById = useMemo(() => Object.fromEntries(pacts.map((p) => [p.id, p])), [pacts]);
  const visibleNudges = useMemo(() => nudges.filter((n) => !dismissed.has(n.id)), [nudges, dismissed]);
  const nowMs = nowIso ? Date.parse(nowIso) : Date.now();

  const markRead = (id: string) => {
    setDismissed((prev) => new Set(prev).add(id));
    api.markDelivered(id).catch(() => {});
  };
  const markAll = () => {
    const ids = visibleNudges.map((n) => n.id);
    setDismissed((prev) => { const next = new Set(prev); ids.forEach((id) => next.add(id)); return next; });
    ids.forEach((id) => api.markDelivered(id).catch(() => {}));
  };

  return (
    <NotificationsMenu
      resolutions={resolutions}
      nudges={visibleNudges}
      charityById={charityById}
      pactById={pactById}
      nowMs={nowMs}
      onResolve={(id) => navigate(`/pact/${id}`)}
      onOpenPact={(id) => navigate(`/pact/${id}`)}
      onMarkRead={markRead}
      onMarkAllRead={markAll}
    />
  );
}
