"""The pace picker must always return to the pace that is actually in effect.

Regression for a reported bug: cancelling the "easier pace resets your game"
warning put the picker back on the WRONG entry. The revert used to read
self.state, and a background refresh landing while the modal dialog was open
replaces self.state with a fresh snapshot - so the picker snapped to whatever
that snapshot carried.
"""
from __future__ import annotations

import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

import poketokenbar_windows.ui as ui
from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.state import GameState, MonState, set_pace
from poketokenbar_windows.windows import cache_dir


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Store:
    def __init__(self) -> None:
        self.saves = 0

    def save(self, _state) -> None:
        self.saves += 1


class _Controller(ui.TrayController):
    """Only the pieces _set_pace touches, so no tray or timers are needed."""

    def __init__(self, state, window) -> None:
        self.state = state
        self.window = window
        self.state_lock = threading.RLock()
        self.store = _Store()
        self.setup_ran = False
        self.refreshed = False

    def _run_setup(self) -> None:
        self.setup_ran = True

    def refresh(self) -> None:
        self.refreshed = True


class PaceComboRevertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        self._original_warning = ui.QMessageBox.warning
        self.counter = 0

    def tearDown(self) -> None:
        ui.QMessageBox.warning = self._original_warning

    def _build(self, pace: str = "standard"):
        self.counter += 1
        state = GameState()
        set_pace(state, pace)
        state.mon = MonState(203, [203], 0, 0, "common", False, "Hardy")
        key = f"PTBRevertTest{self.counter}"
        window = ui.MainWindow(state, QSettings(key, key), PokeAPIClient(cache_dir()))
        window.set_state(state)
        controller = _Controller(state, window)
        window.pace_changed.connect(controller._set_pace)
        return state, window, controller

    def _pick(self, window, pace: str) -> None:
        window.pace_combo.setCurrentIndex(window.pace_combo.findData(pace))
        self.app.processEvents()

    def test_cancelling_returns_the_picker_to_the_live_pace(self) -> None:
        _state, window, controller = self._build("standard")
        ui.QMessageBox.warning = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Cancel
        )
        self._pick(window, "casual")
        self.assertEqual(window.pace_combo.currentData(), "standard")
        self.assertEqual(controller.state.pace, "standard")

    def test_a_refresh_during_the_dialog_cannot_misdirect_the_revert(self) -> None:
        """The reported bug: it snapped to a third pace, not the real one."""
        _state, window, controller = self._build("standard")

        def racing_cancel(*_a, **_k):
            stale = GameState()
            set_pace(stale, "light")
            window.state = stale  # exactly what render() does on a refresh
            return QMessageBox.StandardButton.Cancel

        ui.QMessageBox.warning = staticmethod(racing_cancel)
        self._pick(window, "casual")
        self.assertEqual(
            window.pace_combo.currentData(),
            "standard",
            "picker snapped to the refresh snapshot's pace instead of the real one",
        )
        self.assertEqual(controller.state.pace, "standard")

    def test_cancelling_leaves_the_save_untouched(self) -> None:
        _state, window, controller = self._build("standard")
        ui.QMessageBox.warning = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Cancel
        )
        self._pick(window, "casual")
        self.assertEqual(controller.store.saves, 0)
        self.assertIsNotNone(controller.state.mon)
        self.assertFalse(controller.setup_ran)

    def test_confirming_applies_the_easier_pace_and_resets(self) -> None:
        _state, window, controller = self._build("standard")
        ui.QMessageBox.warning = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        self._pick(window, "casual")
        self.assertEqual(controller.state.pace, "casual")
        self.assertIsNone(controller.state.mon)
        self.assertTrue(controller.setup_ran)

    def test_raising_difficulty_never_prompts_and_keeps_everything(self) -> None:
        _state, window, controller = self._build("casual")

        def must_not_prompt(*_a, **_k):
            raise AssertionError("raising difficulty must not show a warning")

        ui.QMessageBox.warning = staticmethod(must_not_prompt)
        self._pick(window, "standard")
        self.assertEqual(controller.state.pace, "standard")
        self.assertIsNotNone(controller.state.mon)
        self.assertEqual(window.pace_combo.currentData(), "standard")

    def test_every_cancelled_downgrade_pairing_reverts_correctly(self) -> None:
        ui.QMessageBox.warning = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Cancel
        )
        for start, attempted in (
            ("standard", "light"),
            ("standard", "casual"),
            ("light", "casual"),
        ):
            _state, window, controller = self._build(start)
            self._pick(window, attempted)
            self.assertEqual(
                window.pace_combo.currentData(), start,
                f"cancelling {start}->{attempted} left the picker wrong",
            )
            self.assertEqual(controller.state.pace, start)


if __name__ == "__main__":
    unittest.main()
