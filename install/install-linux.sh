#!/bin/sh
# Install (or update) XeroForm on Linux (x86-64), for the current user:
#
#   curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-linux.sh | sh
#
# Puts the app in ~/.local/opt/XeroForm, a `xeroform-gui` command in ~/.local/bin
# and a menu entry, then starts it.
set -eu

REPO="oumarknt31/xeroform-slicer"
ROOT="${XEROFORM_DEST:-$HOME/.local/opt}"

url=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
      | grep -o 'https://[^"]*-Linux\.tar\.gz' | head -n 1)
if [ -z "$url" ]; then
  echo "XeroForm: no Linux download found in the latest release" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "Downloading $(basename "$url")..."
curl -fL --progress-bar "$url" -o "$tmp/XeroForm.tar.gz"
mkdir -p "$ROOT"
rm -rf "$ROOT/XeroForm"
tar xzf "$tmp/XeroForm.tar.gz" -C "$ROOT"

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
ln -sf "$ROOT/XeroForm/XeroForm" "$HOME/.local/bin/xeroform-gui"
cat > "$HOME/.local/share/applications/xeroform.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=XeroForm
Comment=SLS slicer for the XeroForm printer
Exec=$ROOT/XeroForm/XeroForm %F
Terminal=false
Categories=Graphics;Engineering;
MimeType=model/stl;
DESKTOP
echo "Installed $ROOT/XeroForm (menu: XeroForm, command: xeroform-gui)"

if [ -z "${XEROFORM_NO_OPEN:-}" ]; then
  nohup "$ROOT/XeroForm/XeroForm" >/dev/null 2>&1 &
fi
