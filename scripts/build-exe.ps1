$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = Join-Path $root ".venv-build"
if (-not (Test-Path $venv)) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m venv $venv } else { & python -m venv $venv }
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install ".[build]"

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "build\PokeTokenBar-Windows")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "dist\PokeTokenBar-Windows")

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "PokeTokenBar-Windows" `
    --paths (Join-Path $root "src") `
    --collect-all PySide6 `
    (Join-Path $root "scripts\pyinstaller_entry.py")

$bundleInternal = Join-Path $root "dist\PokeTokenBar-Windows\_internal"
# Codex can add its bundled Poppler runtime to PATH. PyInstaller then mistakes
# Poppler's versioned ICU 78 for the unversioned Windows ICU used by Qt 6.
foreach ($foreignIcu in @("icuuc.dll", "icudt78.dll")) {
    Remove-Item -LiteralPath (Join-Path $bundleInternal $foreignIcu) -Force -ErrorAction SilentlyContinue
}

Write-Host "Built: dist\PokeTokenBar-Windows\PokeTokenBar-Windows.exe"
