import { useEffect } from "react";

// Decline-confirm: declining a pending donation keeps it unresolved and pauses
// new pacts (the honest consequence the owner agreed to).
export function DeclineModal({
  onClose,
  onConfirm,
}: {
  onClose: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="ov center" role="dialog" aria-modal="true">
      <div className="ov-backdrop" onClick={onClose} />
      <div className="dm">
        <div className="dm-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="24" height="24"><path d="M12 3 2 20h20Z" /><path d="M12 9v5M12 17v.5" /></svg>
        </div>
        <div className="dm-title">Decline the donation?</div>
        <div className="dm-body">You agreed to this when you signed the pact. Declining keeps it unresolved, pauses any new pacts, and escalates a dispute to the team. You can still settle it later.</div>
        <div className="dm-actions">
          <button className="ov-btn" onClick={onClose}>Keep it active</button>
          <button className="ov-btn ghost danger" onClick={onConfirm}>Decline anyway</button>
        </div>
      </div>
    </div>
  );
}
