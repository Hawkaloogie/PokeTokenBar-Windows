# PokeTokenBar Windows

A native Windows port of [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar): your local AI coding-token usage raises a Pokemon companion from the Windows notification area.

> **Status: alpha.** The token tracker, game loop, tray UI, local state, shop/bag, runtime Pokemon fetching, Windows startup integration, and Claude/Codex official-limit checks are implemented. See **Parity / known gaps** before replacing the macOS app in a workflow you depend on.

## What works

- Windows 10/11 notification-area tray icon + Qt/PySide6 window, with current companion and stage progress in the tray tooltip
- Windows balloon/toast-style tray notifications for hatch/evolution/candy events
- Animated Gen-V Pokemon sprites with static fallback, fetched and cached at runtime
- Egg -> hatch -> real evolution path -> graduation progression
- Upstream balance values: 5M hatch threshold; 750M / 1.875B / 3B / 6B graduation totals by rarity
- 25 natures, PokeAPI capture-rate rarity, shiny hatches, and Shiny Charm
- Bag and token shop: Rare Candy, Mint, Shiny Charm, normal/Uncommon/Rare eggs
- Rare Candy rewards when an official 5-hour/weekly limit reaches 100%, with upstream-compatible first-snapshot seeding
- Install-time usage baseline: pre-install usage is never retroactively converted into growth or shop currency
- Collection/catch history and persistent state under `%APPDATA%\PokeTokenBar-Windows`
- Sprite/API cache under `%LOCALAPPDATA%\PokeTokenBar-Windows\Cache`
- Start with Windows via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- Local token/cost aggregation for Claude Code, Codex, Gemini CLI, OpenCode, Hermes Agent, Cursor, Grok CLI, GitHub Copilot CLI, and Kiro CLI
- Claude official limits via `~\.claude\.credentials.json`
- Codex official remaining limits and available reset-credit expiry via `codex app-server --stdio`; limit windows are ordered chronologically and each reset credit stays last in its provider block, turns amber when it expires before Weekly or within one week, red within 72 hours, and adds a matching 🟠/🔴 warning to the tray tooltip

## Install

### Standalone EXE

GitHub Actions builds a Windows artifact containing `PokeTokenBar-Windows.exe`. Extract the artifact and run the EXE; it is a GUI executable and does not need a console window.

### From source

Requirements: Windows 10/11 and Python 3.10+.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
pythonw -m poketokenbar_windows
```

For development:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pythonw -m poketokenbar_windows
```

Build the standalone Windows directory with PyInstaller:

```powershell
.\scripts\build-exe.ps1
```

The result is `dist\PokeTokenBar-Windows\PokeTokenBar-Windows.exe`.

## Local data sources

The Windows port reads the same underlying local formats as upstream and uses native Windows locations where needed.

| Tool | Windows locations / behavior |
|---|---|
| Claude Code | `$env:CLAUDE_CONFIG_DIR\projects`, `%USERPROFILE%\.config\claude\projects`, `%USERPROFILE%\.claude\projects`; Claude Desktop session stores under AppData are also probed |
| Codex | `$env:CODEX_HOME\sessions` or `%USERPROFILE%\.codex\sessions`, plus `archived_sessions` |
| Gemini CLI | `%USERPROFILE%\.gemini\tmp\**\chats\*.json(l)` |
| OpenCode | `$env:OPENCODE_DATA_DIR` or `%USERPROFILE%\.local\share\opencode` (the Windows location documented by OpenCode) |
| Hermes Agent | `$env:HERMES_HOME\state.db` or `%USERPROFILE%\.hermes\state.db` |
| Cursor | `%APPDATA%\Cursor\User\globalStorage\state.vscdb` for login token; usage from `cursor.com` dashboard API (local bubbles are fallback; they are often 0 on current Cursor) |
| Grok CLI | `$env:GROK_HOME\sessions\**\updates.jsonl` or `%USERPROFILE%\.grok\sessions` |
| Copilot CLI | `$env:COPILOT_HOME\session-store.db` or `%USERPROFILE%\.copilot\session-store.db` |
| Kiro CLI | `$env:KIRO_CLI_HOME\data.sqlite3`, plus Local/Roaming AppData and `%USERPROFILE%\.kiro` candidates |

No model turn is started to collect usage. Claude limits make an authenticated GET to Anthropic's OAuth usage endpoint using Claude Code's existing local OAuth token. Codex limits query the local Codex app-server account snapshot.

### Overrides

The existing provider environment variables above are honored. The port also supports:

- `PTB_STATE_DIR` — alternate state directory, useful for QA/demo isolation
- `PTB_CACHE_DIR` — alternate Pokemon metadata/sprite cache directory
- `CODEX_BIN` — explicit Codex executable path; otherwise the current Codex Desktop binary is
  discovered under `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` on Windows

## Privacy

Token logs are parsed locally. Outbound requests are limited to functionality that needs them:

- `pokeapi.co` for species/evolution metadata
- `raw.githubusercontent.com/PokeAPI/sprites` for sprites
- `api.anthropic.com` for Claude official limits
- `cursor.com` for Cursor usage when local bubble token counts are zero (uses the existing Cursor IDE login; disable with `CURSOR_USAGE_API=0`)

Codex official limits use a local child process. The app does not upload your local usage logs.

## Parity / known gaps

This is a serious first Windows port, not a bit-for-bit rewrite of the SwiftUI app. Current gaps:

- Antigravity's protobuf-in-SQLite reader is not ported yet.
- The floating desktop pet is not yet implemented; the companion lives in the tray and main window.
- Kiro's Windows database location is probed across likely AppData layouts because its local layout has changed between releases; `KIRO_CLI_HOME` is the authoritative override.
- Codex fork/replay dedup is simplified versus upstream's deep parent-rollout reconciliation. Normal `token_count` snapshots are deduplicated, but pathological fork histories may differ slightly.
- Provider incident banners and in-app self-updater are not included yet.
- UI localization is not yet ported; Pokemon names can already be resolved through PokeAPI language data in the core.
- The actual GUI/notification-area behavior must be validated on a Windows desktop; non-UI core and packaging checks can run cross-platform.

## Tests

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

CI runs those checks on `windows-latest` for Python 3.10 and 3.12 and builds a PyInstaller artifact on Windows.

## Publish to GitHub

The repository is prepared for `pnmartinez/PokeTokenBar-Windows`. With GitHub CLI authenticated:

```powershell
.\scripts\publish-github.ps1
```

Override the target with `GITHUB_OWNER`, `GITHUB_REPO`, or `GITHUB_VISIBILITY` if desired.

See `UPSTREAM.md` for the pinned upstream commit and the files to compare when syncing future upstream changes.

## Upstream credit

This project ports the behavior and balance of [PokeTokenBar](https://github.com/chattymin/PokeTokenBar), originally written in Swift/SwiftUI by chattymin and contributors. The upstream MIT license is preserved in `LICENSE`. See `NOTICE.md` for the Pokemon/PokeAPI disclaimer.
