import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { asset } from "../lib/asset";

const ITEMS = [
  { to: "/dashboard", label: "Home" },
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
        <img src={asset("/compact_nav_pact.svg")} alt="Pact" className="lm-logo" />
      </button>
      {open && (
        <div className="lm-menu" role="menu">
          <div className="lm-menu-card">
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
