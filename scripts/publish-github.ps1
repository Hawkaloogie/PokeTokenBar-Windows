$ErrorActionPreference = "Stop"

$owner = if ($env:GITHUB_OWNER) { $env:GITHUB_OWNER } else { "pnmartinez" }
$repo = if ($env:GITHUB_REPO) { $env:GITHUB_REPO } else { "PokeTokenBar-Windows" }
$visibility = if ($env:GITHUB_VISIBILITY) { $env:GITHUB_VISIBILITY } else { "public" }
$full = "$owner/$repo"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required. Install it and authenticate with 'gh auth login'."
}

& gh auth status | Out-Null

& gh repo view $full *> $null
if ($LASTEXITCODE -ne 0) {
    & gh repo create $full "--$visibility" --description "Windows port of PokeTokenBar" --source . --remote origin
} else {
    $origin = (& git remote get-url origin 2>$null)
    if (-not $origin) {
        & git remote add origin "https://github.com/$full.git"
    }
}

& git push -u origin main
Write-Host "Published https://github.com/$full"
