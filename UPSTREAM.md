# Upstream tracking

This Windows port is based on `chattymin/PokeTokenBar` and was initially ported from:

- upstream branch: `main`
- upstream commit: `bd0bba9cdf9a46559adc9c5cd099f42caca1aeb6`
- upstream commit date: 2026-08-20
- upstream license: MIT

The implementation reuses the portable Python core developed for the Linux port, while preserving the upstream game-balance constants and local usage-file semantics. Platform integration is Windows-native: Qt/PySide6 notification-area UI, Roaming/Local AppData storage, HKCU Run startup, and Windows provider paths.

## Latest behavior comparison

The Luna Reserve/UI refresh work was compared on 2026-08-30 against upstream `main` at `1ff36e1e8372d85131d67ac5df61248995743ac5` (after tag `v2.5.2`). Relevant parity decisions carried over here are: render every visible Codex time bucket, classify candy rewards by the bucket duration, identify rewards with stable bucket keys rather than reset timestamps, refresh official limits on every automatic poll, and trigger a full refresh after using Rare Candy.

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
