# Changelog

## 0.4.0 (2026-10-18)

- The plate in 3D: every copy of every part where it will be printed. Drag a
  part to move it, click a face to lay the part flat on it (*Pick a face*), and
  *Arrange* to pack everything again. Parts too close together or to the walls
  turn red, with the reason under the view.
- Packing goes by the parts' real shapes, not their bounding boxes: parts sit
  inside rings and cups and in the corners of brackets. Builds of irregular
  parts come out up to a third lower. Parts placed by hand stay put and new
  copies are packed around them.
- Parts can have their own laser power, speed and hatch spacing (*Part
  settings*).
- Undo and redo for every change to the parts and settings.
- XeroForm says when a newer version is out, with the command that updates it
  (once a day; can be turned off under *Help*).
- Shells that touch or overlap are sliced as one solid instead of as a tangle
  of outlines; cavities modelled as inside-out shells stay hollow.
- The command line slices a saved project: `xeroform build.xeroform -o build.cli`.
- Projects save the parts' own settings and the places of parts placed by hand.

## 0.3.0 (2026-10-18)

- Orient parts in the app: X/Y/Z angles, ±90° turns, *Lay flat* (rests the
  part on its largest flat face, then the next), *Lowest height* (fewest
  layers) and *Reset*, with a 3D preview and live size and layer count.
- `--orient lowest` and `--rotate X Y Z` on the command line.
- Orientation is saved in project files.

## 0.2.0 (2026-10-17)

- The Python package is now `xeroform` (`import xeroform`, `python -m xeroform`).
  The `slicerkit` commands and `.slicerkit` project files are no longer
  supported; re-save old projects as `.xeroform`.
- The header shows the project's folder name instead of its full path.
- The Linux installer registers the app icon with the desktop.
- Screenshots in the README, security policy and bug report template.

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
