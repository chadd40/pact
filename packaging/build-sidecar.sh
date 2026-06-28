#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
uv run pyinstaller packaging/pact-sidecar.spec --noconfirm
TRIPLE="$(rustc -Vv | sed -n 's/^host: //p')"
mkdir -p web/src-tauri/binaries
cp dist/pact-sidecar "web/src-tauri/binaries/pact-sidecar-${TRIPLE}"
echo "staged web/src-tauri/binaries/pact-sidecar-${TRIPLE}"
