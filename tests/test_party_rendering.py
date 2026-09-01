"""The Party tab must populate on the refresh path, not only on a state change.

Reported bug: the Party tab was blank. _render_party was only reached from
set_state(), but startup and every periodic refresh go through render(), so the
tab stayed empty until the user happened to change a setting.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.state import GameState, MonState, PARTY_TOTAL_SIZE
from poketokenbar_windows.ui import MainWindow, RefreshResult
from poketokenbar_windows.usage import ProviderUsage, UsageSnapshot
from poketokenbar_windows.windows import cache_dir


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def mon(species: int) -> MonState:
    return MonState(species, [species], 0, 0, "common", False, "Hardy")


class PartyRenderingTests(unittest.TestCase):
    counter = 0

    def setUp(self) -> None:
        self.app = _app()
        self.api = PokeAPIClient(cache_dir())

    def _window(self, state: GameState) -> MainWindow:
        PartyRenderingTests.counter += 1
        key = f"PTBPartyRender{PartyRenderingTests.counter}"
        return MainWindow(state, QSettings(key, key), self.api)

    def _result(self, state: GameState) -> RefreshResult:
        return RefreshResult(
            UsageSnapshot(providers={"claude": ProviderUsage("claude", today_tokens=10)}),
            {}, {}, state, [], None, "Pokemon",
        )

    def _cells(self, window: MainWindow) -> list:
        return [
            window.party_grid.itemAt(i).widget()
            for i in range(window.party_grid.count())
        ]

    def test_the_refresh_path_populates_the_party(self) -> None:
        state = GameState()
        state.mon = mon(4)
        window = self._window(state)
        window.render(self._result(state))
        self.app.processEvents()
        self.assertEqual(
            window.party_grid.count(), PARTY_TOTAL_SIZE,
            "Party tab was blank after a refresh",
        )

    def test_it_populates_even_with_an_empty_bench(self) -> None:
        state = GameState()
        state.mon = mon(4)
        window = self._window(state)
        window.render(self._result(state))
        self.app.processEvents()
        self.assertEqual(window.party_grid.count(), PARTY_TOTAL_SIZE)

    def test_it_populates_when_the_main_slot_is_an_egg(self) -> None:
        state = GameState()
        window = self._window(state)
        window.render(self._result(state))
        self.app.processEvents()
        self.assertEqual(window.party_grid.count(), PARTY_TOTAL_SIZE)

    def test_an_unchanged_party_is_not_rebuilt(self) -> None:
        """Rebuilding every refresh would destroy an open slot picker."""
        state = GameState()
        state.mon = mon(4)
        window = self._window(state)
        result = self._result(state)
        window.render(result)
        self.app.processEvents()
        before = self._cells(window)
        window.render(result)
        self.app.processEvents()
        self.assertEqual(before, self._cells(window))

    def test_a_changed_party_is_rebuilt(self) -> None:
        state = GameState()
        state.mon = mon(4)
        window = self._window(state)
        result = self._result(state)
        window.render(result)
        self.app.processEvents()
        before = self._cells(window)
        state.party[0] = mon(25)
        window.render(result)
        self.app.processEvents()
        self.assertNotEqual(before, self._cells(window))

    def test_swapping_the_main_rebuilds(self) -> None:
        state = GameState()
        state.mon = mon(4)
        state.party[0] = mon(25)
        window = self._window(state)
        result = self._result(state)
        window.render(result)
        self.app.processEvents()
        before = self._cells(window)
        state.mon, state.party[0] = state.party[0], state.mon
        window.render(result)
        self.app.processEvents()
        self.assertNotEqual(before, self._cells(window))

    def test_set_state_still_renders_it(self) -> None:
        state = GameState()
        state.mon = mon(4)
        window = self._window(state)
        window.set_state(state)
        self.app.processEvents()
        self.assertEqual(window.party_grid.count(), PARTY_TOTAL_SIZE)


if __name__ == "__main__":
    unittest.main()
