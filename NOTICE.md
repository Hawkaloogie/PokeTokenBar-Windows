# Attribution and disclaimer

## Who made what

This project has three layers, and I only wrote the third one.

**1. The original — [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar)**
The idea and the original application, written for macOS in Swift. The game
loop, the balance constants, the usage-tracking model, and the concept of
raising a Pokemon with your token usage are all chattymin's. MIT licensed.

**2. The Windows port — [pnmartinez/PokeTokenBar-Windows](https://github.com/pnmartinez/PokeTokenBar-Windows)**
The entire rewrite from Swift to Python and PySide6, and all the Windows
integration: the notification-area tray app, AppData storage, registry startup,
the provider readers, the official-limit checks, and the packaging. That is a
large body of work, and it is what I actually started from. Contributors to that
port, by commit count at the point I forked:

- Bruno Cerviño ([@cervinho](https://github.com/cervinho))
- [@pnmartinez](https://github.com/pnmartinez)
- pnavarro-hermasa

**3. This fork**
Feature and interface work on top of layer 2 — a six-Pokemon party, a trading
system, Professor Oak's Ranch, generation caps, a pace setting, a rebuilt
settings screen and theme, and a pile of bug fixes. Everything in this layer is
listed in [CHANGES-IN-THIS-FORK.md](CHANGES-IN-THIS-FORK.md).

If something in this fork is broken, it is mine and not theirs. Please report it
here rather than upstream.

Forked from `pnmartinez/PokeTokenBar-Windows` at commit `907e0a0` (2026-09-01).

## Licensing

The upstream projects are MIT licensed, and this fork stays MIT. The original
copyright notice is preserved in [LICENSE](LICENSE) exactly as required, with
copyright lines added for the port and for this fork.

## Trademarks

Pokemon, Pokemon character names, and related marks are trademarks of Nintendo,
Creatures Inc., and GAME FREAK inc. This is an unofficial, non-commercial fan
project and is not affiliated with or endorsed by those companies.

Pokemon metadata and sprites are fetched at runtime from PokeAPI and the PokeAPI
sprites repository. No Pokemon assets are bundled in this repository.
