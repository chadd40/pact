#!/usr/bin/env bash
# Drive the full Phase-1 narrative against an already-running DEMO sidecar
# (./scripts/demo/launch.sh demo). Compresses time with the same /demo + /api/tick
# endpoints the on-screen DemoControls use, so this is a faithful dry-run of the
# real lifecycle: create -> coach -> miss -> dispute window -> owed -> agent pays
# (dry-run auto-captures) -> donation_complete -> renew nudge.
#
# Use it to pre-validate before recording, or as a hands-free "auto demo". On
# stage you'd instead click the DemoControls and let your Hermes agent coach.
set -euo pipefail

BASE="${PACT_BASE_URL:-http://127.0.0.1:8000}"
OWNER="${PACT_OWNER:-demo@pact.app}"
CHARITY="${PACT_CHARITY:-against_malaria_foundation}"
PROMPT="${PACT_PROMPT:-Run 3 miles every day for the next 5 days}"

jq_py() { python3 -c "import sys,json;d=json.load(sys.stdin);$1"; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

step "1. Draft a pact (agent reasons terms + frozen rubric)"
PID=$(curl -s -X POST "$BASE/api/pacts/draft" -H 'content-type: application/json' \
  -d "{\"prompt\":\"$PROMPT\"}" | jq_py "print(d['id'])")
echo "   pact id: $PID"
curl -s -X POST "$BASE/api/pacts/$PID/owner" -H 'content-type: application/json' \
  -d "{\"owner\":\"$OWNER\"}" -o /dev/null

step "2. Confirm: stake \$20 -> charity, consent acknowledged (pre-auth card minted)"
curl -s -X POST "$BASE/api/pacts" -H 'content-type: application/json' \
  -d "{\"pact_id\":\"$PID\",\"stake_amount_cents\":2000,\"charity_id\":\"$CHARITY\",\"consent_acknowledged\":true}" \
  | jq_py "print('   status:',d['status'],' card_last4:',d.get('card_last4'))"

step "3. Coach: user sends a message; the coach replies (your Hermes agent if it is serving)"
curl -s -X POST "$BASE/api/pacts/$PID/coach" -H 'content-type: application/json' \
  -d '{"message":"I am behind and unmotivated — only ran once so far."}' \
  | jq_py "print('   coach >', d['outbound']['body'])"

step "4. Time passes: advance past the deadline, run the scheduler (settle -> failed)"
curl -s -X POST "$BASE/demo/advance-day" -H 'content-type: application/json' -d '{"days":7}' -o /dev/null
curl -s -X POST "$BASE/api/tick" -o /dev/null
curl -s "$BASE/api/pacts/$PID" | jq_py "print('   status:',d['status'],' dispute closes:',d.get('dispute_window_closes_at'))"

step "5. Dispute window elapses: advance again, tick (close window -> donation owed)"
curl -s -X POST "$BASE/demo/advance-day" -H 'content-type: application/json' -d '{"days":2}' -o /dev/null
curl -s -X POST "$BASE/api/tick" -o /dev/null
curl -s "$BASE/api/pacts/$PID" | jq_py "print('   status:',d['status'])"

step "6. The agent pays the charity: fetch the single-use card, then resolve"
curl -s -X POST "$BASE/api/pacts/$PID/donation/card-credential" -H 'content-type: application/json' -d '{}' \
  | jq_py "print('   card:', d.get('brand'),'****'+str(d.get('last4')),' billing:', 'yes' if 'billing' in d else 'no')"
curl -s -X POST "$BASE/api/pacts/$PID/donation/resolve" -H 'content-type: application/json' -d '{}' \
  | jq_py "r=d.get('receipt',{}); print('   ->',d['status'],'| receipt:',r.get('receipt_status'),'via',r.get('receipt_source'),'('+str(r.get('confirmation_notes'))+')')"

step "7. Renew nudge fires"
curl -s -X POST "$BASE/api/tick" -o /dev/null
curl -s "$BASE/api/outbox?owner=$OWNER" | jq_py "print('   outbox triggers:', [m['trigger'] for m in d])"

printf '\n\033[1mPhase 1 complete.\033[0m create -> coach -> miss -> dispute -> owed -> donation_complete -> renew\n'
