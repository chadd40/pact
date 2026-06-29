from __future__ import annotations

import sys

if len(sys.argv) > 1 and sys.argv[1] == "--pact-charity-checkout":
    from pact.charity_checkout import main

    raise SystemExit(main(sys.argv[2:]))

from pact.sidecar import main

main()
