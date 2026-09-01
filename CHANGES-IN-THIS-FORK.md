# What this fork changes

Everything below was added on top of
[pnmartinez/PokeTokenBar-Windows](https://github.com/pnmartinez/PokeTokenBar-Windows).
Nothing here is upstream's work. If a bug appears in one of these areas, it is
mine, not theirs.

Forked at upstream commit `907e0a0` (2026-09-01). 33 commits.

---

## Party of six

Upstream raises one Pokemon at a time. This fork adds a full party.

- One **main** Pokemon plus a **five-slot bench**, like the games.
- **Only the main is affected by tokens and Rare Candy.** The bench is stored,
  not raised. Swapping a bench Pokemon into the main slot is how you change
  what your usage feeds.
- The bench renders on the desktop beside the main sprite, at **half the main's
  artwork height**, and sits level with its feet.
- A setting to show the whole party on the desktop or the main Pokemon alone.

## Professor Oak's Ranch

- Everything you own that is **not** in your party lives at the Ranch.
- The Ranch lists only non-party Pokemon, so it never duplicates what the Party
  tab already shows.

## Trading

A trade board that refreshes with your limit window.

- **Value-matched offers.** Every Pokemon carries a trade value built from
  rarity, how far up its evolution line it has been raised, and whether it is
  shiny. An offer only accepts a Pokemon worth at least what it gives away, so
  you cannot swap a fresh Pidgey for a Mewtwo.
- **The Pokemon is the whole price.** No tokens are involved in a trade.
- Raising a Pokemon is how you trade upward — a fully evolved one is worth
  double its freshly hatched self.
- **One paid reroll** per window if you dislike the offers.
- **Favourites are never eligible**, and neither is the Pokemon you are
  currently raising. Neither can be lost to a trade by accident.
- Legendaries are given out by hatching only. An offer of one would demand
  another legendary to pay for it, which nobody can do until they already have
  one.
- The board is seeded from the window, so restarting the app shows the same
  offers rather than rerolling them.

## Favourites

- A solid star on any Pokemon, set from the Ranch, the Party tab, or the catch
  log.
- The star follows the Pokemon between the party and the Ranch.
- Favourited Pokemon are protected from trades.

## Generations

- Pick a generation **cap**, not a single generation: choosing Gen 3 includes
  Gens 1 through 3.
- Or pick ALL.
- Pikachu is available as a Gen 1 starter alongside the three originals.

## Pace (difficulty)

Light Claude users could never progress far enough to see the game. Pace fixes
that without changing any displayed number.

- Pace is a **speed boost applied to growth**, nothing else.
- **Shop prices are identical at every pace.** No parallel economy to balance.
- **Every number the app shows you is your real token usage.** The boost is
  applied behind the display, never to it.
- Easing the pace forces a full reset and warns you first. Raising it is free
  and instant.

## Level

- A **level badge** beside the sprite, on its baseline.
- Level spans the **whole evolution line**, not the current stage — so a
  three-stage Pokemon reads 0 to 100 across all three, rather than resetting
  each time it evolves.

## Evolution you watch

- Evolution waits for you to click instead of happening silently between
  refreshes.
- Clicking plays a short evolution animation.
- The Pokedex shows a species' full evolution line and which stages you have
  collected. Click any Pokemon to see it.

## Limit reset clock

The estimated reset time disagreed with Claude's own usage page by 161 minutes
at every look-back tested, from 10 hours to 30 days.

- The derivation is **switched off on purpose** rather than left to show a wrong
  number.
- Instead you tell the app once when your window actually resets, and it rolls
  that anchor forward in five-hour blocks.
- The countdown appears under the percentage, and on the tray and the desktop
  pet.

## Desktop pet

- **Snaps above the taskbar** instead of floating loose.
- Choose which **screen edge** it lives against; the party lines up on the
  inward side.
- Choose the Pokemon's size.

## Settings

- Rebuilt as a sidebar with six pages: Game, Desktop pet, Limits, Tray, General,
  Advanced.
- **A Save button.** Settings now stage until you save them, because a stray
  scroll wheel over a dropdown used to change the generation or the pace
  instantly.
- Discard puts everything back.
- The window can no longer be resized small enough to clip its own controls.

## First run and reset

- A first-run questionnaire: generation cap and starter choice.
- A full app reset that actually clears everything.

## Look

- A design-token stylesheet: one 8px spacing system, one type scale, one set of
  colours, applied app-wide.
- Dark theme rebuilt in **true neutral grey** — the previous near-black had an
  elevated blue channel that cooled the warm sprite colours sitting on it.
- Light and dark both supported, with real Windows theme detection and live
  switching.
- Elevation by surface tone rather than outlines, so screens stop reading as
  boxes inside boxes.

## Single instance

- Launching the app twice focuses the running copy instead of starting a second
  one.

---

## Bugs fixed along the way

Kept here because most of them are the kind that come back.

- **Progress bars rendered empty.** The stylesheet gave the filled portion a
  rounded corner but no colour, so Qt drew nothing. The level bar was the most
  visible casualty.
- **Tooltips rendered blank.** Light mode inverts its tooltip on purpose, but
  the rule painted it with the ordinary body-text colour — both were `#1b1b1d`,
  a 1.00:1 contrast ratio. The Qt palette had the identical collision, so
  natively drawn tooltips were blank too.
- **Dark-mode text was invisible** where the stylesheet reached for
  `palette(mid)`, which resolves to Windows' native palette rather than the
  app's, and came back as light grey.
- **The bench rendered larger than the main Pokemon** — 114% of it — because the
  size was measured against the sprite canvas instead of the visible artwork.
- **The trade board wiped itself on every restart**: a failed PokeAPI call at
  launch saved an empty offer list over the good one.
- **The trade board never drew on the refresh path**, so trades vanished a few
  minutes after appearing.
- **The Party tab was blank** for the same reason — rendered on load, never on
  refresh.
- **The app failed to launch** because evolution signals were connected before
  the object they pointed at existed.
- **The pace picker snapped to the wrong entry** when you cancelled a change,
  if a background refresh landed while the warning dialog was open.
- **Settings clipped their own dropdowns** at small window sizes — the real
  cause was a fixed width on segmented buttons whose labels needed more.
- Save-loss, state cloning, egg destruction, and a drag jump, all found by a
  review pass before release.

## Known limitation

The reset countdown needs you to tell it once when your window resets. It cannot
read that from Claude locally, and deriving it from message timestamps produced
a consistently wrong answer. If you know a reliable way to get the real reset
time on Windows, that is the most useful thing anyone could contribute.
