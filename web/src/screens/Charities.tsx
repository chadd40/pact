import { useAppData } from "../data";

// Browse the charity catalog — where forfeited stakes go. Read from shared AppData.
export function Charities() {
  const { charities } = useAppData();

  return (
    <div className="pg">
      <div className="pg-head">
        <div className="pg-eyebrow m">Where the stakes go</div>
        <div className="pg-title">Charities</div>
        <div className="pg-lede">Every pact names a cause. If you miss, your stake is donated here — verified organizations, real impact. Pick one when you build a pact.</div>
      </div>

      {charities.length === 0 ? (
        <div className="pg-empty">Loading…</div>
      ) : (
        <div className="ch-grid">
          {charities.map((c) => (
            <a key={c.id} className="ch-card" href={c.donation_url} target="_blank" rel="noreferrer">
              <div className="ch-stamp">{c.stamp ? <img src={c.stamp} alt={c.name} /> : null}</div>
              <div className="ch-name">{c.name}</div>
              <div className="ch-cat m">{c.category}</div>
              <div className="ch-visit">Visit
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="13" height="13"><path d="M7 17 17 7M9 7h8v8" /></svg>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
