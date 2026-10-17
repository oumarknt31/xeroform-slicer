XeroForm Slicer - the open-source SLS slicer for the XeroForm printer.

## Install - one line, no security prompts (recommended)

**Mac** - open **Terminal** (⌘-Space, type Terminal) and paste:
```
curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-mac.sh | sh
```
**Windows** - open **PowerShell** (Start menu, type PowerShell) and paste:
```
irm https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-windows.ps1 | iex
```
**Linux** - in a terminal:
```
curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-linux.sh | sh
```
It picks the right version for your computer, installs it (Applications on Mac, Start menu on
Windows, app menu on Linux) and opens XeroForm. Run the same line again to update.

## Or download manually

| Your computer | File |
|---|---|
| Mac with Apple Silicon (M1, M2, M3, M4...) | `XeroForm-…-macOS-AppleSilicon.zip` |
| Mac with an Intel processor | `XeroForm-…-macOS-Intel.zip` |
| Windows 10 / 11 | `XeroForm-…-Windows.zip` |
| Linux (x86-64) | `XeroForm-…-Linux.tar.gz` |

The app isn't code-signed yet, so a manual download shows a security warning the first time:

- **Mac**: double-click, click **Done**, then System Settings ▸ Privacy & Security ▸ **Open Anyway**.
  (macOS 14 and older: right-click ▸ **Open** ▸ **Open**.)
- **Windows**: run **XeroForm.exe** from the unzipped folder; at "Windows protected your PC" click
  **More info** ▸ **Run anyway**.
- **Linux**: `tar xzf XeroForm-…-Linux.tar.gz` and run `XeroForm/XeroForm`.

## Using it

Drop an STL/OBJ/3MF model on the window (or **Add models**), press **Slice**, then look through the layers, the 3D stack and the build layout. **Export** writes the `.cli` laser paths. Laser power/speed values are placeholders until the machine's laser is chosen.
