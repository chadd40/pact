#!/usr/bin/env bash
# Produce a WORKING ad-hoc (non-notarized) macOS DMG from a Tauri build.
#
# Why this exists: Tauri signs the bundle with the HARDENED RUNTIME, which turns on
# macOS library validation. The Python sidecar is a PyInstaller one-file binary that
# extracts and dlopen()s libpython3.12.dylib at runtime; library validation rejects
# that dylib ("code signature not valid ... different Team IDs"), so the sidecar dies
# on launch and the app shows a dock icon with no window. Re-signing WITHOUT hardened
# runtime (plain ad-hoc) keeps the bundle sealed (so it isn't "damaged") but disables
# library validation, so the sidecar can load its dylibs.
#
# Usage:
#   (cd web && npm run tauri build)   # builds app + a broken hardened-runtime DMG
#   scripts/package-macos-adhoc.sh    # re-signs + repackages -> working DMG
#
# For a NOTARIZED release (clean download, no xattr), use .github/workflows/release.yml
# with a Developer ID cert. Notarization REQUIRES hardened runtime, so that path must
# add an entitlements plist granting com.apple.security.cs.disable-library-validation
# to the sidecar (and likely sign the sidecar separately with it).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/web/src-tauri/target/release/bundle/macos/Pact.app"
DMG="$ROOT/web/src-tauri/target/release/bundle/dmg/Pact_0.1.0_aarch64.dmg"

if [ ! -d "$APP" ]; then
  echo "No app bundle at $APP — build first: (cd web && npm run tauri build)" >&2
  exit 1
fi

echo "Re-signing $APP ad-hoc, WITHOUT hardened runtime..."
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
echo "Sidecar flags (want plain 'adhoc', not 'adhoc,runtime'):"
codesign -dv --verbose=2 "$APP/Contents/MacOS/pact-sidecar" 2>&1 | grep -i flags || true

STAGE="$(mktemp -d)/Pact"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
mkdir -p "$(dirname "$DMG")"
hdiutil create -volname "Pact" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "Wrote $DMG ($(du -h "$DMG" | cut -f1))"
echo "This DMG still needs the download-quarantine step on the user's machine:"
echo "  xattr -dr com.apple.quarantine /Applications/Pact.app"
