"""No control may be too small to show its own contents.

This is the check that was missing. Earlier fixes chased the window's minimum
size, but the real clipping came from widgets pinned to a fixed width that was
narrower than their own text - 'Date & time' needed 146px inside a 112px
button, and clipped at every window size.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QPushButton,
    QTabWidget,
)

from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.state import (
    CatchRecord,
    GameState,
    MonState,
    refresh_trades,
    set_favourite,
)
from poketokenbar_windows.ui import MainWindow
from poketokenbar_windows.windows import cache_dir


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class NoClippingTests(unittest.TestCase):
    counter = 0

    def setUp(self) -> None:
        self.app = _app()
        self.api = PokeAPIClient(cache_dir())

    def _populated_state(self) -> GameState:
        def catch(species, base, path, rarity):
            return CatchRecord(
                species, base, path, rarity, False, "Hardy",
                "2026-09-01T00:00:00+00:00",
            )

        state = GameState()
        state.mon = MonState(4, [4, 5, 6], 1, 0, "rare", False, "Hardy")
        state.party[0] = MonState(25, [25], 0, 0, "uncommon", False, "Hardy")
        state.catches = [
            catch(5, 4, [4, 5, 6], "rare"),
            catch(25, 25, [25], "uncommon"),
            catch(18, 16, [16, 17, 18], "common"),
        ]
        set_favourite(state, 2)
        state.used_since_install = 5_000_000_000
        refresh_trades(state, self.api, "clip-test")
        return state

    def _window(self, state: GameState) -> MainWindow:
        NoClippingTests.counter += 1
        key = f"PTBClipTest{NoClippingTests.counter}"
        window = MainWindow(state, QSettings(key, key), self.api)
        window.show()
        window.set_state(state)
        for _ in range(5):
            self.app.processEvents()
        return window

    def _clipped(self, window: MainWindow) -> list[str]:
        """Visible controls allocated less room than they need."""
        found: list[str] = []
        for kind in (QComboBox, QPushButton, QLabel):
            for widget in window.findChildren(kind):
                if not widget.isVisible():
                    continue
                need = widget.minimumSizeHint()
                # One pixel of slack for rounding.
                if widget.width() < need.width() - 1 or widget.height() < need.height() - 1:
                    text = widget.text() if hasattr(widget, "text") else widget.currentText()
                    found.append(
                        f"{kind.__name__} {text!r}: "
                        f"{widget.width()}x{widget.height()} needs "
                        f"{need.width()}x{need.height()}"
                    )
        return found

    def _sweep(self, window: MainWindow) -> list[str]:
        """Every tab, nested tab and settings page."""
        problems: list[str] = []
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            for _ in range(3):
                self.app.processEvents()
            problems += self._clipped(window)
            for inner in window.tabs.widget(index).findChildren(QTabWidget):
                for j in range(inner.count()):
                    inner.setCurrentIndex(j)
                    for _ in range(3):
                        self.app.processEvents()
                    problems += self._clipped(window)
            if window.tabs.tabText(index) == "Settings":
                for row in range(window.settings_nav.count()):
                    window.settings_nav.setCurrentRow(row)
                    for _ in range(3):
                        self.app.processEvents()
                    problems += self._clipped(window)
        return problems

    def test_nothing_clips_at_the_smallest_allowed_size(self) -> None:
        window = self._window(self._populated_state())
        window.resize(window.minimumWidth(), window.minimumHeight())
        for _ in range(4):
            self.app.processEvents()
        problems = self._sweep(window)
        self.assertEqual(problems, [], "clipped at the minimum window size")

    def test_nothing_clips_when_squeezed_below_the_minimum(self) -> None:
        """The floor must actually hold when something tries to shrink it."""
        window = self._window(self._populated_state())
        window.resize(200, 200)
        for _ in range(4):
            self.app.processEvents()
        self.assertGreaterEqual(window.width(), window.minimumWidth())
        self.assertEqual(self._sweep(window), [])

    def test_nothing_clips_on_a_fresh_save(self) -> None:
        window = self._window(GameState())
        window.resize(window.minimumWidth(), window.minimumHeight())
        for _ in range(4):
            self.app.processEvents()
        self.assertEqual(self._sweep(window), [])

    def test_segmented_buttons_fit_their_own_labels(self) -> None:
        window = self._window(self._populated_state())
        for button in (
            window.limit_used_button,
            window.limit_remaining_button,
            window.limit_time_remaining_button,
            window.limit_time_datetime_button,
            window.pet_bias_left_button,
            window.pet_bias_right_button,
        ):
            self.assertGreaterEqual(
                button.minimumWidth(),
                button.minimumSizeHint().width(),
                f"{button.text()!r} is pinned narrower than its own label",
            )


if __name__ == "__main__":
    unittest.main()
