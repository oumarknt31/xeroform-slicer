# Changelog

## 0.1.1 (2026-10-17)

- The one-line installers wait for you to quit a running XeroForm before
  updating, instead of closing it and losing unsaved work.
- Updates replace the app in one step, so a failed update leaves the old
  version working.
- Installers verify each download against `SHA256SUMS.txt` and no longer use
  the rate-limited GitHub API.
- The Mac installer picks the Apple Silicon build even when Terminal runs under
  Rosetta. The Linux installer refuses unsupported processors and adds an icon.
- Release files have stable names, for example `XeroForm-Windows.zip`.
- MIT license, third-party notices (also inside the app), this changelog.
- Screen-reader names for icon-only buttons; slightly larger small labels.

## 0.1.0 (2026-10-17)

First release: slicing, laser settings, scan order, nesting, HTML preview,
command line and the XeroForm desktop app for macOS, Windows and Linux.
