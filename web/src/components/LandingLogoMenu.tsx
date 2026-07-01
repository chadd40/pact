import { useEffect, useRef, useState } from "react";
import { asset } from "../lib/asset";
import "./LandingLogoMenu.css";

export const PACT_DOWNLOAD_URL = "https://github.com/chadd40/pact/releases/latest";
export type LandingMenuTarget = "top" | "integrations" | "faq";

interface LandingLogoMenuProps {
  onGoTo: (target: LandingMenuTarget) => void;
}

export function LandingLogoMenu({ onGoTo }: LandingLogoMenuProps) {
  const [open, setOpen] = useState(false);
  const navRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const goTo = (target: LandingMenuTarget) => {
    setOpen(false);
    onGoTo(target);
  };

  return (
    <div className="lp-chrome">
      <div className={"lp-nav" + (open ? " open" : "")} ref={navRef}>
        <button
          type="button"
          className="lp-navbtn"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Pact menu"
          onClick={() => setOpen((o) => !o)}
        >
          <img src={asset("/compact_nav_pact.svg")} alt="Pact" className="lp-logo" />
        </button>

        {open && (
          <div className="lp-menu" role="menu">
            <div className="lp-menu-card">
              <button className="lp-menu-item" role="menuitem" onClick={() => goTo("top")}>
                Home
              </button>
              <button className="lp-menu-item" role="menuitem" onClick={() => goTo("integrations")}>
                How it works
              </button>
              <button className="lp-menu-item" role="menuitem" onClick={() => goTo("faq")}>
                FAQ
              </button>
            </div>
            <a className="lp-menu-download" href={PACT_DOWNLOAD_URL} target="_blank" rel="noreferrer" role="menuitem" onClick={() => setOpen(false)}>
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path d="M12 4v11m0 0l-4-4m4 4l4-4M5 19h14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Download Pact
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
