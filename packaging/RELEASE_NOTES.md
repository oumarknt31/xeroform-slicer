XeroForm Slicer - the open-source SLS slicer for the XeroForm printer.

## Download

| Your computer | File |
|---|---|
| Mac with Apple Silicon (M1, M2, M3, M4...) | `XeroForm-…-macOS-AppleSilicon.zip` |
| Mac with an Intel processor | `XeroForm-…-macOS-Intel.zip` |
| Windows 10 / 11 | `XeroForm-…-Windows.zip` |
| Linux (x86-64) | `XeroForm-…-Linux.tar.gz` |

Not sure which Mac you have? Apple menu ▸ About This Mac: "Chip" means Apple Silicon, "Processor" means Intel.

## Install

The app isn't code-signed yet, so the first launch shows a security warning. That's expected.

**Mac**
1. Unzip and drag **XeroForm** into **Applications**.
2. Right-click XeroForm ▸ **Open**, then **Open** again in the dialog. (Double-clicking the first time only shows "can't be opened".)
   On newer macOS, if there is no Open button: try to open it once, then System Settings ▸ Privacy & Security ▸ **Open Anyway**.

**Windows**
1. Unzip the folder anywhere (for example Documents).
2. Run **XeroForm.exe** inside it. If "Windows protected your PC" appears: **More info** ▸ **Run anyway**.

**Linux**
1. `tar xzf XeroForm-…-Linux.tar.gz`
2. Run `XeroForm/XeroForm`.

## Using it

Drop an STL/OBJ/3MF model on the window (or **Add models**), press **Slice**, then look through the layers, the 3D stack and the build layout. **Export** writes the `.cli` laser paths. Laser power/speed values are placeholders until the machine's laser is chosen.
