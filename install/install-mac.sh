#!/bin/sh
# Install (or update) XeroForm on a Mac:
#
#   curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-mac.sh | sh
#
# Downloads the latest release for this Mac (Apple Silicon or Intel), puts it in
# /Applications (or ~/Applications if that isn't writable) and opens it. Apps
# downloaded from the command line aren't quarantined, so macOS doesn't show the
# "could not verify" prompt that a browser download of the unsigned app gets.
set -eu

REPO="oumarknt31/xeroform-slicer"
DEST="${XEROFORM_DEST:-/Applications}"

case "$(uname -m)" in
  arm64) flavour="macOS-AppleSilicon" ;;
  x86_64) flavour="macOS-Intel" ;;
  *) echo "XeroForm: unsupported Mac ($(uname -m))" >&2; exit 1 ;;
esac

url=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
      | grep -o "https://[^\"]*-$flavour\.zip" | head -n 1)
if [ -z "$url" ]; then
  echo "XeroForm: no $flavour download found in the latest release" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $(basename "$url")..."
curl -fL --progress-bar "$url" -o "$tmp/XeroForm.zip"
ditto -x -k "$tmp/XeroForm.zip" "$tmp"

if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi
rm -rf "$DEST/XeroForm.app"
ditto "$tmp/XeroForm.app" "$DEST/XeroForm.app"
xattr -dr com.apple.quarantine "$DEST/XeroForm.app" 2>/dev/null || true
echo "Installed $DEST/XeroForm.app"

if [ -z "${XEROFORM_NO_OPEN:-}" ]; then
  open "$DEST/XeroForm.app"
fi
