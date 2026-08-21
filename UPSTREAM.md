# Upstream tracking

This Windows port is based on `chattymin/PokeTokenBar` and was initially ported from:

- upstream branch: `main`
- upstream commit: `bd0bba9cdf9a46559adc9c5cd099f42caca1aeb6`
- upstream commit date: 2026-08-20
- upstream license: MIT

The implementation reuses the portable Python core developed for the Linux port, while preserving the upstream game-balance constants and local usage-file semantics. Platform integration is Windows-native: Qt/PySide6 notification-area UI, Roaming/Local AppData storage, HKCU Run startup, and Windows provider paths.

## Syncing future upstream changes

When upstream changes provider formats or game constants, compare these areas first:

- `Sources/PokeTokenBar/Core/CompanionModel.swift` -> `pokemon.py`, `state.py`
- `Sources/PokeTokenBar/Core/LocalUsageReader.swift` -> `usage.py`
- `Sources/PokeTokenBar/Core/LocalAdditionalUsageProvider.swift` -> `usage.py`, `cursor.py`
- `Sources/PokeTokenBar/Core/CursorUsageAPI.swift` -> `cursor.py`
- `Sources/PokeTokenBar/Core/OAuthLimitsProvider.swift` -> `limits.py`
- `Sources/PokeTokenBar/Core/CodexRateLimitsProvider.swift` -> `limits.py`
- SwiftUI/AppKit files -> `ui.py`, `app.py`, and `windows.py`

Known intentional gaps are tracked in `README.md` under **Parity / known gaps**.
