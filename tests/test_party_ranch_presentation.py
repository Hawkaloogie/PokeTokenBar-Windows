"""The Party tab and Oak's Ranch each show ONE Pokemon, not an evolution line.

Ricky, on where the evolution tree belongs: "No, the Ranch shouldn't have the
evolution card" ... "only the Pokedex".

The Ranch is storage and the Party tab is your loadout; both answer "what do I
have". The evolution line answers "what could this become", which is a Pokedex
question - MainWindow.show_evolution_line already opens it there, with
silhouettes for the forms not yet collected.

The thumbnails on both surfaces were also enlarged and trimmed, which is the
part of the original report that stands.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel

import poketokenbar_windows.ui as ui
from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.state import CatchRecord, GameState, MonState
from poketokenbar_windows.windows import cache_dir


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _catch(species: int, path: list[int]) -> CatchRecord:
    return CatchRecord(
        species_id=species,
        base_id=path[0],
        path_ids=list(path),
        rarity="common",
        is_shiny=False,
        nature="Hardy",
        caught_at="2026-09-01T00:00:00+00:00",
    )


class OneSpritePerCardTests(unittest.TestCase):
    counter = 0

    def setUp(self) -> None:
        self.app = _app()
        OneSpritePerCardTests.counter += 1
        key = f"PTBPresent{OneSpritePerCardTests.counter}"
        self.state = GameState()
        # A three-stage family: if a line were drawn it would be obvious.
        self.state.mon = MonState(1, [1, 2, 3], 1, 0, "common", False, "Hardy")
        self.state.party = [
            MonState(4, [4, 5, 6], 0, 0, "common", False, "Brave"),
            None, None, None, None,
        ]
        self.state.catches = [_catch(2, [1, 2, 3]), _catch(5, [4, 5, 6])]
        self.window = ui.MainWindow(
            self.state, QSettings(key, key), PokeAPIClient(cache_dir())
        )
        self.window.set_state(self.state)
        self.window._render_party(force=True)

    def _sprites(self, widget) -> list:
        return [
            child for child in widget.findChildren(QLabel)
            if child.pixmap() is not None and not child.pixmap().isNull()
        ]

    def test_the_main_party_card_shows_exactly_one_pokemon(self) -> None:
        card = self.window.party_grid.itemAt(0).widget()
        self.assertEqual(
            len(self._sprites(card)), 1,
            "the main card is drawing an evolution line again",
        )

    def test_a_bench_card_shows_exactly_one_pokemon(self) -> None:
        card = self.window.party_grid.itemAt(1).widget()
        self.assertEqual(
            len(self._sprites(card)), 1,
            "a bench card is drawing an evolution line again",
        )

    def test_a_ranch_card_shows_exactly_one_pokemon(self) -> None:
        card = self.window._catch_card(self.state.catches[0], False)
        self.assertEqual(
            len(self._sprites(card)), 1,
            "Oak's Ranch is drawing an evolution line again - it should show "
            "only the Pokemon actually resting there",
        )

    def test_the_pokedex_still_owns_the_evolution_line(self) -> None:
        """Removing it from the other two must not have removed it here."""
        self.assertTrue(hasattr(self.window, "show_evolution_line"))
        self.assertGreater(len(self.window._evolution_line_for(1)), 1)


class ThumbnailSizeTests(unittest.TestCase):
    """The half of the report that stands: they were too small to see."""

    def test_every_thumbnail_grew(self) -> None:
        self.assertGreater(ui.RANCH_SPRITE, 64)
        self.assertGreater(ui.PARTY_MAIN_SPRITE, 84)
        self.assertGreater(ui.PARTY_BENCH_SPRITE, 56)

    def test_the_main_portrait_is_larger_than_a_bench_one(self) -> None:
        self.assertGreater(ui.PARTY_MAIN_SPRITE, ui.PARTY_BENCH_SPRITE)

    def test_no_evolution_stage_constants_survive(self) -> None:
        """They only existed to size a line that no longer gets drawn."""
        for name in (
            "RANCH_STAGE_BOX", "PARTY_MAIN_STAGE_BOX", "PARTY_BENCH_STAGE_BOX"
        ):
            self.assertFalse(
                hasattr(ui, name), f"{name} is dead code - the line was removed"
            )


class PartyDefaultsToMainOnlyTests(unittest.TestCase):
    """Ricky: "keep the pokemon party default to the Main pokemon ... and let
    the user activate the entire party or not"."""

    def test_the_desktop_party_is_off_unless_switched_on(self) -> None:
        from poketokenbar_windows.floating_pet import PET_PARTY_DEFAULT

        self.assertFalse(PET_PARTY_DEFAULT)

    def test_an_unset_setting_yields_main_only(self) -> None:
        from poketokenbar_windows.floating_pet import (
            PET_PARTY_DEFAULT, PET_PARTY_KEY,
        )
        from poketokenbar_windows.pet_logic import settings_bool

        settings = QSettings("PTBPartyDefault", "PTBPartyDefault")
        settings.remove(PET_PARTY_KEY)
        self.assertFalse(
            settings_bool(
                settings.value(PET_PARTY_KEY, PET_PARTY_DEFAULT), PET_PARTY_DEFAULT
            )
        )

    def test_switching_it_on_is_still_possible(self) -> None:
        from poketokenbar_windows.floating_pet import (
            PET_PARTY_DEFAULT, PET_PARTY_KEY,
        )
        from poketokenbar_windows.pet_logic import settings_bool

        settings = QSettings("PTBPartyOn", "PTBPartyOn")
        settings.setValue(PET_PARTY_KEY, True)
        self.assertTrue(
            settings_bool(
                settings.value(PET_PARTY_KEY, PET_PARTY_DEFAULT), PET_PARTY_DEFAULT
            )
        )


if __name__ == "__main__":
    unittest.main()
