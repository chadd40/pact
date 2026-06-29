import React from "react";
import { Navigate } from "react-router-dom";
import { api } from "./api";
import { isDesktop } from "./lib/platform";
import { getLocalOwner } from "./owner";
import { Landing } from "./screens/Landing";

export function RootEntry() {
  const desktop = isDesktop();
  const [dest, setDest] = React.useState<string | null>(() => desktop ? null : "__web__");

  React.useEffect(() => {
    if (!desktop) return;
    let alive = true;
    api.listPacts(getLocalOwner())
      .then((pacts) => {
        if (alive) setDest(pacts.length > 0 ? "/dashboard" : "/create");
      })
      .catch(() => {
        if (alive) setDest("/create");
      });
    return () => { alive = false; };
  }, [desktop]);

  if (dest === null) {
    return (
      <div className="root-launch" role="status" aria-label="Opening Pact">
        <img className="root-launch-logo" src="/primary_logo.svg" alt="" />
        <div className="root-launch-card" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="root-launch-copy">
          <div className="root-launch-kicker m">First run check</div>
          <div className="root-launch-title">Opening the pact deck</div>
        </div>
      </div>
    );
  }
  if (dest === "__web__") return <Landing />;
  return <Navigate to={dest} replace />;
}
