#!/bin/sh
# Install or update XeroForm on a Linux PC (x86-64), for the current user:
#
#   curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-linux.sh | sh
#
# Downloads the latest release, checks it against the release's SHA256SUMS.txt,
# puts the app in ~/.local/opt/XeroForm with a menu entry and a `xeroform-gui`
# command, then starts it. A running XeroForm is never closed for you, and the
# new version replaces the old one in a single step.
set -eu

BASE="${XEROFORM_RELEASE_URL:-https://github.com/oumarknt31/xeroform-slicer/releases/latest/download}"
ROOT="${XEROFORM_DEST:-$HOME/.local/opt}"
FILE="XeroForm-Linux.tar.gz"
WAIT_SECONDS="${XEROFORM_WAIT:-120}"

fail() {
  echo "XeroForm: $*" >&2
  exit 1
}

machine=$(uname -m)
[ "$machine" = "x86_64" ] || fail "only x86-64 PCs are supported so far (this one is $machine)."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $FILE..."
curl -fL --progress-bar "$BASE/$FILE" -o "$tmp/$FILE" \
  || fail "couldn't download $BASE/$FILE. Check your internet connection and try again."
curl -fsSL "$BASE/SHA256SUMS.txt" -o "$tmp/SHA256SUMS.txt" \
  || fail "couldn't download the release checksums. Try again in a moment."
expected=$(awk -v f="$FILE" '$2 == f { print $1 }' "$tmp/SHA256SUMS.txt")
actual=$(sha256sum "$tmp/$FILE" | awk '{ print $1 }')
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  fail "the download is damaged (checksum mismatch). Please try again."
fi

mkdir -p "$ROOT"
ROOT=$(cd "$ROOT" && pwd)
app="$ROOT/XeroForm"

if pgrep -f "$app/XeroForm" >/dev/null 2>&1; then
  echo "XeroForm is running. Save your work and quit it. Waiting up to 2 minutes..."
  waited=0
  while pgrep -f "$app/XeroForm" >/dev/null 2>&1; do
    [ "$waited" -lt "$WAIT_SECONDS" ] || fail "XeroForm is still running. Quit it, then run this command again."
    sleep 2
    waited=$((waited + 2))
  done
fi

staged="$ROOT/.XeroForm-new"
rm -rf "$staged" "$app.old"
mkdir -p "$staged"
tar xzf "$tmp/$FILE" -C "$staged"
[ -x "$staged/XeroForm/XeroForm" ] || fail "the download doesn't contain the XeroForm app."
if [ -d "$app" ]; then
  mv "$app" "$app.old"
fi
mv "$staged/XeroForm" "$app"
rm -rf "$staged" "$app.old"

icons="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$icons"
ln -sf "$app/XeroForm" "$HOME/.local/bin/xeroform-gui"
icon=$(find "$app" -name xeroform-icon.svg -print | head -n 1)
[ -n "$icon" ] && cp "$icon" "$icons/xeroform.svg"
cat > "$HOME/.local/share/applications/xeroform.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=XeroForm
Comment=SLS slicer for the XeroForm printer
Exec="$app/XeroForm" %F
Icon=xeroform
Terminal=false
Categories=Graphics;Engineering;
MimeType=model/stl;model/obj;model/3mf;
DESKTOP
echo "Installed $app (menu: XeroForm, command: xeroform-gui)"

if [ -z "${XEROFORM_NO_OPEN:-}" ]; then
  nohup "$app/XeroForm" >/dev/null 2>&1 &
fi
