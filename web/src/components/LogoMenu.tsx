import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

const ITEMS = [
  { to: "/dashboard", label: "Home" },
  { to: "/coach", label: "Coach" },
  { to: "/charities", label: "Charities" },
  { to: "/settings", label: "Settings" },
];

export function LogoMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  const isActive = (to: string) =>
    to === "/dashboard" ? loc.pathname === "/dashboard" || loc.pathname.startsWith("/pact/") : loc.pathname === to;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div className={"lm-nav" + (open ? " open" : "")} ref={ref}>
      <button type="button" className="lm-navbtn" aria-haspopup="menu" aria-expanded={open} aria-label="Pact menu" onClick={() => setOpen((o) => !o)}>
        <img src="/compact_nav_pact.svg" alt="Pact" className="lm-logo" />
        <svg className="lm-navcaret" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="lm-menu" role="menu">
          <div className="lm-menu-card">
            <div className="lm-menu-eyebrow m">Pact</div>
            {ITEMS.map((it) => (
              <Link key={it.to} to={it.to} role="menuitem" className={"lm-menu-item" + (isActive(it.to) ? " active" : "")} onClick={() => setOpen(false)}>
                {it.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
