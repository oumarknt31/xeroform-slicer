XeroForm Slicer, the open-source SLS slicer for the XeroForm printer. See
[CHANGELOG.md](https://github.com/oumarknt31/xeroform-slicer/blob/main/CHANGELOG.md)
for what changed.

## Install with one line (recommended)

The command picks the right build for your computer, checks the download,
installs it and opens XeroForm. No security prompt appears. Run the same line
again to update; if XeroForm is open, it waits for you to save and quit.

**Mac**: open **Terminal** (⌘-Space, type "Terminal") and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-mac.sh | sh
```

**Windows**: open **PowerShell** (Start menu, type "PowerShell") and paste:

```powershell
irm https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-windows.ps1 | iex
```

**Linux (x86-64)**: in a terminal, run:

```bash
curl -fsSL https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-linux.sh | sh
```

## Or download manually

| Your computer | File |
|---|---|
| Mac with Apple Silicon (M1, M2, M3, M4…) | `XeroForm-macOS-AppleSilicon.zip` |
| Mac with an Intel processor | `XeroForm-macOS-Intel.zip` |
| Windows 10 or 11 (64-bit) | `XeroForm-Windows.zip` |
| Linux (x86-64) | `XeroForm-Linux.tar.gz` |

To check which Mac you have, open the Apple menu ▸ **About This Mac**: a "Chip"
line means Apple Silicon, a "Processor" line means Intel. `SHA256SUMS.txt` lists
the checksum of every file.

The app isn't code-signed yet, so a manual download shows a security warning the
first time.

**Mac**

1. Unzip the file and drag **XeroForm** into **Applications**.
2. Double-click XeroForm. When macOS says it "could not verify" XeroForm, click
   **Done**.
3. Open **System Settings ▸ Privacy & Security**, scroll to "XeroForm was
   blocked", click **Open Anyway** and confirm. macOS won't ask again.

If there is no **Open Anyway** button, run this in Terminal instead:

```bash
xattr -dr com.apple.quarantine /Applications/XeroForm.app
```

On macOS 14 and older you can also right-click XeroForm ▸ **Open** ▸ **Open**.

**Windows**

1. Unzip the file anywhere, for example in Documents.
2. Run **XeroForm.exe** in the XeroForm folder. If "Windows protected your PC"
   appears, click **More info** ▸ **Run anyway**.

**Linux**

```bash
tar xzf XeroForm-Linux.tar.gz && XeroForm/XeroForm
```

## Get started

Drop an STL, OBJ, PLY or 3MF model on the window (or click **Add models**), press
**Slice**, then look through the layers, the 3D stack and the build layout.
**Export** writes the `.cli` laser paths. Laser power and speed are placeholders
until the machine's laser is chosen.
