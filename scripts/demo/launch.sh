#!/usr/bin/env bash
# Launch the Pact sidecar in one of two demo profiles, served to a plain browser
# in desktop mode (create flow + DemoControls render without the Tauri shell).
#
#   ./scripts/demo/launch.sh demo   # Phase 1: time-compressed narrative, dry-run money
#   ./scripts/demo/launch.sh live   # Phase 2: real clock + live link-cli money moment
#
# Runs in the foreground (Ctrl-C to stop). Open http://127.0.0.1:$PACT_PORT after
# you see PACT_SIDECAR_READY. For coaching authored by YOUR Hermes agent, have it
# run `/pact serve` in another window (the interactive coach waits up to
# PACT_REASONING_TIMEOUT_POLLS for a serving agent before falling back to the stub).
set -euo pipefail

PROFILE="${1:-demo}"
PORT="${PACT_PORT:-8000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Free the port if something is already bound (a stale sidecar).
if lsof -iTCP:"$PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "Port $PORT busy — stopping the existing listener."
  lsof -tiTCP:"$PORT" -sTCP:LISTEN | xargs -r kill || true
  sleep 1
fi

export PACT_PORT="$PORT"
export PACT_SPA_DESKTOP=1
export PACT_REASONING_MODE="${PACT_REASONING_MODE:-hybrid}"
# Give the serving Hermes agent a real window to author coach/judge/draft results
# before the interactive call falls back to the deterministic stub.
export PACT_REASONING_TIMEOUT_POLLS="${PACT_REASONING_TIMEOUT_POLLS:-20}"

case "$PROFILE" in
  demo)
    export PACT_CLOCK_MODE=demo
    export PACT_PAYMENT_MODE=test_link
    export PACT_LINK_MODE=dry_run
    export PACT_DB_PATH="${PACT_DB_PATH:-pact-demo.db}"
    echo "== Pact demo profile (Phase 1): demo clock, simulated money =="
    ;;
  live)
    export PACT_CLOCK_MODE=real
    export PACT_PAYMENT_MODE=link_cli
    export PACT_LINK_MODE=live
    # Collapse the 24h dispute window and the 60-min cooling-off so a real-clock
    # pact can fail and reach the donation in minutes during a recording.
    export PACT_DISPUTE_GRACE_HOURS="${PACT_DISPUTE_GRACE_HOURS:-0}"
    export PACT_COOLING_OFF_MINUTES="${PACT_COOLING_OFF_MINUTES:-0}"
    export PACT_DB_PATH="${PACT_DB_PATH:-pact-live.db}"
    echo "== Pact LIVE profile (Phase 2): real clock, REAL link-cli money =="
    echo "   Real money moves only after YOU approve the spend in your Link app."
    echo "   Run 'pact preflight' and confirm ready:true before creating a real pact."
    ;;
  *)
    echo "usage: $0 [demo|live]" >&2
    exit 2
    ;;
esac

echo "   DB:        $PACT_DB_PATH"
echo "   URL:       http://127.0.0.1:$PORT  (open in a browser once ready)"
echo "   Clock:     $PACT_CLOCK_MODE   Payment: $PACT_PAYMENT_MODE/$PACT_LINK_MODE"
echo "   Reset state first with: ./scripts/demo/reset.sh $PROFILE"
echo
exec .venv/bin/pact-sidecar
