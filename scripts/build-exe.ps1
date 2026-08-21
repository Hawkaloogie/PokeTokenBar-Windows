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

Write-Host "Built: dist\PokeTokenBar-Windows\PokeTokenBar-Windows.exe"
