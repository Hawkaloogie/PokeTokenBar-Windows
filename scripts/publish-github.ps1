param(
    [string]$owner = "",
    [string]$repo = "",
    [string]$visibility = ""
)

$ErrorActionPreference = "Stop"

# Determine owner: param > env > derived from gh api user
if (-not $owner) {
    if ($env:GITHUB_OWNER) {
        $owner = $env:GITHUB_OWNER
    } else {
        try {
            $owner = & gh api user --jq '.login' 2>$null
            if (-not $owner) {
                throw "GitHub API returned empty login"
            }
        } catch {
            Write-Error "Failed to determine GitHub owner: $_`nSet GITHUB_OWNER env var or pass -owner parameter."
            exit 1
        }
    }
}

# Determine repo
if (-not $repo) {
    if ($env:GITHUB_REPO) {
        $repo = $env:GITHUB_REPO
    } else {
        $repo = "PokeTokenBar-Windows"
    }
}

# Determine visibility
if (-not $visibility) {
    if ($env:GITHUB_VISIBILITY) {
        $visibility = $env:GITHUB_VISIBILITY
    } else {
        $visibility = "public"
    }
}
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
