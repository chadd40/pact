import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Pact, ProofStatus } from "../types";

type Stage = "nonce" | "capture" | "judging" | "result";

// The submit-evidence sheet: one-time code → capture → server judge → verdict.
// The real photo upload (api.uploadProofImage) IS the judge; its returned status
// drives pass/fail/review. The dev simulator buttons (demo flavor) preview the
// fail/review screens without a real upload.
export function SubmitSheet({
  pact,
  onClose,
  onResolved,
}: {
  pact: Pact;
  onClose: () => void;
  onResolved: () => Promise<void> | void;
}) {
  const [stage, setStage] = useState<Stage>("nonce");
  const [token, setToken] = useState<string>("");
  const [secs, setSecs] = useState(300);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [result, setResult] = useState<ProofStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    api.proofToken(pact.id).then((r) => alive && setToken(r.token)).catch(() => {});
    return () => { alive = false; };
  }, [pact.id]);

  // expiry countdown (flavor; the real token TTL is enforced server-side)
  useEffect(() => {
    if (stage !== "nonce") return;
    const id = setInterval(() => setSecs((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [stage]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  // ESC to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const code = (token || "----").replace(/[^a-zA-Z0-9]/g, "").slice(0, 4).toUpperCase() || "7F2A";
  const mmss = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;

  const pickFile = () => fileRef.current?.click();
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (preview) URL.revokeObjectURL(preview);
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const sendForReview = async () => {
    if (!file || !token) return;
    setStage("judging");
    setErr(null);
    try {
      const proof = await api.uploadProofImage(pact.id, token, file, true);
      setResult(proof.status);
      setStage("result");
    } catch {
      setErr("Couldn't submit that proof. Try again.");
      setStage("capture");
    }
  };

  // dev simulator: preview a verdict screen without a real upload
  const simulate = (s: ProofStatus) => { setResult(s); setStage("judging"); setTimeout(() => setStage("result"), 1400); };

  const done = async () => {
    if (result === "passed") { await onResolved(); onClose(); }
    else { setStage("capture"); setFile(null); if (preview) { URL.revokeObjectURL(preview); setPreview(null); } setResult(null); }
  };

  return (
    <div className="ov" role="dialog" aria-modal="true">
      <div className="ov-backdrop" onClick={onClose} />
      <div className="ov-sheet">
        <div className="ov-sheet-head">
          <div>
            <div className="ov-sheet-title">Submit evidence</div>
            <div className="ov-sheet-sub m">{pact.title}</div>
          </div>
          <button className="ov-x" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" width="15" height="15"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div className="ov-sheet-body">
          {err && <div className="ov-err">{err}</div>}

          {/* nonce */}
          {stage === "nonce" && (
            <div className="ss-nonce">
              <div className="ss-lock"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="30" height="30"><path d="M6 10V8a6 6 0 0 1 12 0v2M5 10h14v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1Z" /></svg></div>
              <div className="ss-h">Prove it's happening now</div>
              <div className="ss-p">We'll give you a one-time code. Get it into your photo — it stops old screenshots from counting.</div>
              <div className="ss-code-card">
                <div className="m ss-code-k">Your proof code</div>
                <div className="m ss-code">{code}</div>
                <div className="ss-code-exp"><span className="dot" /><span className="m">Expires in {mmss}</span></div>
              </div>
              <div className="ss-steps">
                <div className="ss-step"><span className="ss-step-n">1</span><span>Write <b className="m">{code}</b> on a sticky note, your hand, or your screen.</span></div>
                <div className="ss-step"><span className="ss-step-n">2</span><span>Take a photo with the code visible. {pact.agent ?? "Hermes"} checks it in seconds.</span></div>
              </div>
              <button className="ov-btn" onClick={() => setStage("capture")}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.3" /></svg>
                I've got it — open camera
              </button>
            </div>
          )}

          {/* capture */}
          {stage === "capture" && (
            <div className="ss-capture">
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />
              <div className="ss-cap-head"><span className="ss-cap-title">Capture your proof</span><span className="m ss-cap-code">CODE {code}</span></div>
              {preview ? (
                <>
                  <div className="ss-photo"><img src={preview} alt="proof preview" /><span className="m ss-photo-tag">{code} visible ✓</span></div>
                  <div className="ss-cap-actions">
                    <button className="ov-btn ghost" onClick={pickFile}>Retake</button>
                    <button className="ov-btn" onClick={sendForReview}>
                      Send to {pact.agent ?? "Hermes"}
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><path d="M5 12h13M12 6l6 6-6 6" /></svg>
                    </button>
                  </div>
                </>
              ) : (
                <button className="ss-drop" onClick={pickFile}>
                  <div className="ss-drop-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="26" height="26"><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.4" /></svg></div>
                  <div className="ss-drop-title">Take a photo or upload</div>
                  <div className="ss-drop-sub">Make sure code {code} is in frame</div>
                </button>
              )}
              <div className="ss-sim">
                <div className="m ss-sim-label">Prototype · simulate {pact.agent ?? "Hermes"}'s verdict</div>
                <div className="ss-sim-btns">
                  <button className="ss-sim-btn pass" onClick={() => simulate("passed")}>Pass</button>
                  <button className="ss-sim-btn fail" onClick={() => simulate("failed")}>Fail</button>
                  <button className="ss-sim-btn review" onClick={() => simulate("ambiguous")}>Review</button>
                </div>
              </div>
            </div>
          )}

          {/* judging */}
          {stage === "judging" && (
            <div className="ss-judging">
              <div className="ss-scan">{preview && <img src={preview} alt="" />}<div className="ss-scan-line" /><span className="m ss-scan-tag">{code}</span></div>
              <div className="ss-judging-h">{pact.agent ?? "Hermes"} is checking your proof…</div>
              <div className="ss-checks">
                <div className="ss-check done"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><path d="M5 12.5 10 17l9-11" /></svg>Reading the photo</div>
                <div className="ss-check done"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><path d="M5 12.5 10 17l9-11" /></svg>Matching code <b className="m">{code}</b></div>
                <div className="ss-check pending"><span className="ss-dots"><span /><span /><span /></span>Checking timestamp &amp; uniqueness</div>
              </div>
            </div>
          )}

          {/* result */}
          {stage === "result" && (
            <div className="ss-result">
              {result === "passed" && (
                <>
                  <div className="ss-res-icon ok"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" width="36" height="36"><path d="M5 12.5 10 17l9-11" /></svg></div>
                  <div className="ss-res-h">Verified — logged.</div>
                  <div className="ss-res-p">Your proof checked out. Your stake is safe and the day counts. {pact.agent ?? "Hermes"} checked it in seconds.</div>
                  <button className="ov-btn" onClick={done}>Done</button>
                </>
              )}
              {result === "failed" && (
                <>
                  <div className="ss-res-icon bad"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="34" height="34"><path d="M6 6l12 12M18 6 6 18" /></svg></div>
                  <div className="ss-res-h">Couldn't verify this one.</div>
                  <div className="ss-res-p">{pact.agent ?? "Hermes"} couldn't confirm code <b className="m">{code}</b> in the photo. Try again with the code clearly in frame.</div>
                  <button className="ov-btn" onClick={done}>Try again</button>
                </>
              )}
              {result === "ambiguous" && (
                <>
                  <div className="ss-res-icon amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="32" height="32"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg></div>
                  <div className="ss-res-h">Sent for review.</div>
                  <div className="ss-res-p">This one's a judgment call, so a human will take a look. We'll update you within 24h — your streak is paused, not broken.</div>
                  <button className="ov-btn" onClick={async () => { await onResolved(); onClose(); }}>Got it</button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
