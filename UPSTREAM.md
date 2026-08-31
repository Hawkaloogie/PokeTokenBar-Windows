# Upstream tracking

This Windows port is based on `chattymin/PokeTokenBar` and was initially ported from:

- upstream branch: `main`
- upstream commit: `bd0bba9cdf9a46559adc9c5cd099f42caca1aeb6`
- upstream commit date: 2026-08-20
- upstream license: MIT

The implementation reuses the portable Python core developed for the Linux port, while preserving the upstream game-balance constants and local usage-file semantics. Platform integration is Windows-native: Qt/PySide6 notification-area UI, Roaming/Local AppData storage, HKCU Run startup, and Windows provider paths.

## Latest behavior comparison

The Luna Reserve/UI refresh work was compared on 2026-08-30 against upstream `main` at `1ff36e1e8372d85131d67ac5df61248995743ac5` (after tag `v2.5.2`). Relevant parity decisions carried over here are: render every visible Codex time bucket, classify candy rewards by the bucket duration, identify rewards with stable bucket keys rather than reset timestamps, refresh official limits on every automatic poll, and trigger a full refresh after using Rare Candy.

## Limit display and startup review

The Windows limit/startup work was checked again on 2026-08-31 against the same upstream commit:

- Upstream's `limitDisplayMode` is an explicit Used/Remaining picker and defaults to `used`. Windows now uses the same default and migrates the former `limits_show_remaining` checkbox.
- Upstream applies that display mode to limit rows, the compact menu surface, and the floating-pet hover. Windows now applies one mode to Home, tray tooltip, floating-pet hover, system notifications, and pet bubbles. Colors, warning/critical thresholds, rewards, and alert edge detection continue to use utilization (percent used), regardless of display mode.
- Upstream shows a five-hour forecast automatically only when it has enough burn-rate data. Windows keeps the same 5% stability floor, extrapolates average official utilization since the current five-hour window began, shows whether depletion is expected before reset, and adds a user-facing forecast toggle.
- PokeAPI's sprite repository provides a static `sprites/items/poke-ball.png`, but no matching Poké Ball opening GIF. Windows fetches that item sprite at runtime and builds the shake/flash/reveal transition in Qt; no Pokémon asset is bundled.
- Upstream keeps the popover separate from its bootstrap work. Windows now preserves that outcome by keeping both the first main window and the optional floating pet hidden until the initial usage/limits snapshot and companion sprite lookup (including its offline fallback) are complete.

Recent upstream changes were also reviewed for follow-up work. The most useful independent candidates are per-provider additional scan folders, animation-quality controls, provider account labels/session-key setup, Antigravity official limits, and the newer Pi/omp providers. They are intentionally not mixed into this focused UI/startup branch.

## Syncing future upstream changes

When upstream changes provider formats or game constants, compare these areas first:

- `Sources/PokeTokenBar/Core/CompanionModel.swift` -> `pokemon.py`, `state.py`
- `Sources/PokeTokenBar/Core/LocalUsageReader.swift` -> `usage.py`
- `Sources/PokeTokenBar/Core/LocalAdditionalUsageProvider.swift` -> `usage.py`, `cursor.py`
- `Sources/PokeTokenBar/Core/CursorUsageAPI.swift` -> `cursor.py`
- `Sources/PokeTokenBar/Core/OAuthLimitsProvider.swift` -> `limits.py`
- `Sources/PokeTokenBar/Core/CodexRateLimitsProvider.swift` -> `limits.py`
- `Sources/PokeTokenBar/Core/UsageStore.swift` notification rules -> `notifications.py`, `pet_logic.py`
- `Sources/PokeTokenBar/UI/SettingsView.swift` notification preferences -> `ui.py`
- SwiftUI/AppKit files -> `ui.py`, `app.py`, and `windows.py`

Known intentional gaps are tracked in `README.md` under **Parity / known gaps**.
