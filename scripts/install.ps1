$ErrorActionPreference = "Stop"

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    & py -3 -m pip install --user .
} else {
    & python -m pip install --user .
}

Write-Host "PokeTokenBar installed."
Write-Host "Run (no console window):"
Write-Host '  pyw -3 -m poketokenbar_windows'
Write-Host "or:  pythonw -m poketokenbar_windows"
