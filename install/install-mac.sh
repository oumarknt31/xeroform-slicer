#!/bin/sh
# Install or update XeroForm on a Mac:
#
#   curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-mac.sh | sh
#
# Downloads the latest release for this Mac (Apple Silicon or Intel), checks it
# against the release's SHA256SUMS.txt, installs it into /Applications (or
# ~/Applications) and opens it. Command-line downloads aren't quarantined, so
# macOS doesn't show the "could not verify" prompt that a browser download of
# the (not yet signed) app gets.
#
# A running XeroForm is never closed for you: the script waits for you to quit
# it. The new version replaces the old one in a single step, so a failed update
# leaves the old version working.
set -eu

BASE="${XEROFORM_RELEASE_URL:-https://github.com/oumarknt31/xeroform-slicer/releases/latest/download}"
DEST="${XEROFORM_DEST:-/Applications}"
WAIT_SECONDS="${XEROFORM_WAIT:-120}"

fail() {
  echo "XeroForm: $*" >&2
  exit 1
}

# hw.optional.arm64 is 1 on Apple Silicon even when this shell runs under Rosetta
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
  file="XeroForm-macOS-AppleSilicon.zip"
else
  file="XeroForm-macOS-Intel.zip"
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $file..."
curl -fL --progress-bar "$BASE/$file" -o "$tmp/$file" \
  || fail "couldn't download $BASE/$file. Check your internet connection and try again."
curl -fsSL "$BASE/SHA256SUMS.txt" -o "$tmp/SHA256SUMS.txt" \
  || fail "couldn't download the release checksums. Try again in a moment."
expected=$(awk -v f="$file" '$2 == f { print $1 }' "$tmp/SHA256SUMS.txt")
actual=$(shasum -a 256 "$tmp/$file" | awk '{ print $1 }')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  fail "the download is damaged (checksum mismatch). Please try again."
fi

ditto -x -k "$tmp/$file" "$tmp/unpacked"
[ -d "$tmp/unpacked/XeroForm.app" ] || fail "the download doesn't contain XeroForm.app."

mkdir -p "$DEST" 2>/dev/null || true
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
DEST=$(cd "$DEST" && pwd)
app="$DEST/XeroForm.app"

if pgrep -f "$app/Contents/MacOS/XeroForm" >/dev/null 2>&1; then
  echo "XeroForm is running. Save your work and quit it (Cmd-Q). Waiting up to 2 minutes..."
  waited=0
  while pgrep -f "$app/Contents/MacOS/XeroForm" >/dev/null 2>&1; do
    [ "$waited" -lt "$WAIT_SECONDS" ] || fail "XeroForm is still running. Quit it, then run this command again."
    sleep 2
    waited=$((waited + 2))
  done
fi

staged="$DEST/.XeroForm-new.app"
rm -rf "$staged" "$app.old"
ditto "$tmp/unpacked/XeroForm.app" "$staged"
xattr -dr com.apple.quarantine "$staged" 2>/dev/null || true
if [ -d "$app" ]; then
  mv "$app" "$app.old"
fi
mv "$staged" "$app"
rm -rf "$app.old"
echo "Installed $app"

if [ -z "${XEROFORM_NO_OPEN:-}" ]; then
  open "$app"
fi
