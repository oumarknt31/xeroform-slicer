# Install (or update) XeroForm on Windows, for the current user (no admin needed):
#
#   irm https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-windows.ps1 | iex
#
# Downloads the latest release into %LOCALAPPDATA%\Programs\XeroForm, adds a Start
# menu shortcut and starts it. Files downloaded by PowerShell carry no "downloaded
# from the internet" mark, so SmartScreen doesn't block the unsigned app.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # makes Invoke-WebRequest much faster

$repo = 'oumarknt31/xeroform-slicer'
$root = if ($env:XEROFORM_DEST) { $env:XEROFORM_DEST } else { Join-Path $env:LOCALAPPDATA 'Programs' }
$dest = Join-Path $root 'XeroForm'

$release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
$asset = $release.assets | Where-Object { $_.name -like '*-Windows.zip' } | Select-Object -First 1
if (-not $asset) { throw "XeroForm: no Windows download found in the latest release" }

Write-Host "Downloading $($asset.name)..."
$zip = Join-Path ([IO.Path]::GetTempPath()) "XeroForm-$([guid]::NewGuid()).zip"
Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
Get-Process XeroForm -ErrorAction SilentlyContinue | Stop-Process -Force   # updating a running copy
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force -Path $root | Out-Null
Expand-Archive $zip -DestinationPath $root -Force   # the zip holds a XeroForm folder
Remove-Item $zip
Get-ChildItem $dest -Recurse | Unblock-File

$exe = Join-Path $dest 'XeroForm.exe'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'XeroForm.lnk'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = $dest
$link.Save()
Write-Host "Installed $dest (Start menu: XeroForm)"

if (-not $env:XEROFORM_NO_OPEN) { Start-Process $exe }
