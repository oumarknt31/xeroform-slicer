# Install or update XeroForm on Windows, for the current user (no admin needed):
#
#   irm https://raw.githubusercontent.com/oumarknt31/xeroform-slicer/main/install/install-windows.ps1 | iex
#
# Downloads the latest release, checks it against the release's SHA256SUMS.txt,
# installs it into %LOCALAPPDATA%\Programs\XeroForm with a Start menu shortcut
# and starts it. Files downloaded by PowerShell carry no "downloaded from the
# internet" mark, so SmartScreen doesn't block the (not yet signed) app.
#
# A running XeroForm is never closed for you: the script waits for you to close
# it. The new version replaces the old one in a single step, so a failed update
# leaves the old version working.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # makes Invoke-WebRequest much faster

$base = if ($env:XEROFORM_RELEASE_URL) { $env:XEROFORM_RELEASE_URL } else {
    'https://github.com/oumarknt31/xeroform-slicer/releases/latest/download' }
$root = if ($env:XEROFORM_DEST) { $env:XEROFORM_DEST } else { Join-Path $env:LOCALAPPDATA 'Programs' }
$file = 'XeroForm-Windows.zip'

if (-not [Environment]::Is64BitOperatingSystem) { throw 'XeroForm needs 64-bit Windows.' }

New-Item -ItemType Directory -Force -Path $root | Out-Null
$root = (Resolve-Path $root).Path
$dest = Join-Path $root 'XeroForm'
$exe = Join-Path $dest 'XeroForm.exe'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('XeroForm-' + [guid]::NewGuid())
$staged = Join-Path $root '.XeroForm-new'   # on the same drive as $dest, so the swap is a rename
New-Item -ItemType Directory -Path $tmp | Out-Null

try {
    Write-Host "Downloading $file..."
    try {
        Invoke-WebRequest "$base/$file" -OutFile (Join-Path $tmp $file) -UseBasicParsing
        Invoke-WebRequest "$base/SHA256SUMS.txt" -OutFile (Join-Path $tmp 'SHA256SUMS.txt') -UseBasicParsing
    } catch {
        throw "XeroForm: couldn't download $base/$file. Check your internet connection and try again."
    }
    $line = Get-Content (Join-Path $tmp 'SHA256SUMS.txt') |
        Where-Object { ($_ -split '\s+')[1] -eq $file } | Select-Object -First 1
    $expected = if ($line) { ($line -split '\s+')[0] } else { '' }
    $actual = (Get-FileHash (Join-Path $tmp $file) -Algorithm SHA256).Hash
    if (-not $expected -or $expected -ne $actual) {
        throw 'XeroForm: the download is damaged (checksum mismatch). Please try again.'
    }

    if (Test-Path $staged) { Remove-Item $staged -Recurse -Force }
    Expand-Archive (Join-Path $tmp $file) -DestinationPath $staged -Force
    if (-not (Test-Path (Join-Path $staged 'XeroForm\XeroForm.exe'))) {
        throw "XeroForm: the download doesn't contain XeroForm.exe."
    }

    $running = { Get-Process XeroForm -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } }
    if (& $running) {
        $wait = if ($env:XEROFORM_WAIT) { [int]$env:XEROFORM_WAIT } else { 120 }
        Write-Host 'XeroForm is running. Save your work and close it. Waiting up to 2 minutes...'
        $deadline = (Get-Date).AddSeconds($wait)
        while (& $running) {
            if ((Get-Date) -gt $deadline) { throw 'XeroForm is still running. Close it, then run this command again.' }
            Start-Sleep -Seconds 2
        }
    }

    $old = "$dest.old"
    if (Test-Path $old) { Remove-Item $old -Recurse -Force }
    if (Test-Path $dest) { Rename-Item $dest $old }   # fails cleanly, deleting nothing, if files are in use
    Move-Item (Join-Path $staged 'XeroForm') $dest
    Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $dest -Recurse | Unblock-File
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $staged -Recurse -Force -ErrorAction SilentlyContinue
}

$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'XeroForm.lnk'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = $dest
$link.Save()
Write-Host "Installed $dest (Start menu: XeroForm)"

if (-not $env:XEROFORM_NO_OPEN) { Start-Process $exe }
