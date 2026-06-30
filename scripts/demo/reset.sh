#!/usr/bin/env bash
# Wipe the demo/live DB to a clean slate so no stale pacts (with old timestamps)
# pollute a recording. Pact ids are a deterministic hash of the prompt, so a
# leftover row from a prior run can shadow a "new" pact — always reset first.
#
#   ./scripts/demo/reset.sh demo   # clears pact-demo.db
#   ./scripts/demo/reset.sh live   # clears pact-live.db
set -euo pipefail

PROFILE="${1:-demo}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

case "$PROFILE" in
  demo) DB="${PACT_DB_PATH:-pact-demo.db}" ;;
  live) DB="${PACT_DB_PATH:-pact-live.db}" ;;
  *) echo "usage: $0 [demo|live]" >&2; exit 2 ;;
esac

rm -f "$DB" "$DB-wal" "$DB-shm"
echo "Cleared $DB (+ wal/shm). Fresh schema is created on next launch."
echo "Tip: in the UI you can also press Reset then Seed on the DemoControls strip."
