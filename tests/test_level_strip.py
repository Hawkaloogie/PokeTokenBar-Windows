"""The level indicator must never sit on top of the Pokemon artwork."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from poketokenbar_windows.floating_pet import LEVEL_OPACITY, FloatingPetWindow
from poketokenbar_windows.pet_logic import ScreenRect, recover_pet_position, snap_pet_position
from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.windows import cache_dir


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class LevelStripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        self.api = PokeAPIClient(cache_dir())

    def _pet(self, size: int = 96, level: str = "Lv. 73") -> FloatingPetWindow:
        pet = FloatingPetWindow(size)
        pet.show()
        pet.set_sprite(self.api.sprite_path(25, animated=False), is_egg=False)
        if level:
            pet.set_level(level)
        self.app.processEvents()
        return pet

    def test_the_strip_starts_below_the_artwork(self) -> None:
        for size in (48, 96, 160, 192):
            pet = self._pet(size)
            self.assertGreaterEqual(
                pet.level_label.geometry().top(), pet.sprite_area(),
                f"level overlapped the sprite at {size}px",
            )

    def test_the_sprite_keeps_its_full_size(self) -> None:
        """Making room for the level must not shrink the Pokemon."""
        for size in (96, 128, 160):
            pet = self._pet(size)
            self.assertEqual(pet.sprite_area(), size)
            self.assertEqual(pet.label.pixmap().height(), size)

    def test_the_window_grows_only_by_the_strip(self) -> None:
        pet = self._pet(96)
        self.assertEqual(pet.height(), 96 + pet.level_strip_height())

    def test_no_level_means_no_strip_and_a_square_window(self) -> None:
        pet = self._pet(96, level="")
        self.assertEqual(pet.level_strip_height(), 0)
        self.assertEqual(pet.height(), 96)
        self.assertFalse(pet.level_label.isVisible())

    def test_clearing_the_level_collapses_the_strip_again(self) -> None:
        pet = self._pet(96)
        self.assertGreater(pet.level_strip_height(), 0)
        pet.set_level("")
        self.app.processEvents()
        self.assertEqual(pet.level_strip_height(), 0)
        self.assertEqual(pet.height(), 96)

    def test_it_is_rendered_at_half_opacity(self) -> None:
        pet = self._pet(96)
        self.assertIn(f"{int(255 * LEVEL_OPACITY)}", pet.level_label.styleSheet())

    def test_the_strip_stays_a_modest_fraction_of_the_pet(self) -> None:
        for size in (48, 96, 192):
            pet = self._pet(size)
            self.assertLess(
                pet.level_strip_height(), size * 0.35,
                "the level should be a glance, not a banner",
            )

    def test_the_bench_sits_on_the_sprite_baseline_not_the_strip(self) -> None:
        pet = self._pet(96)
        pet.set_bench([self.api.sprite_path(1, animated=False)] + [None] * 4)
        self.app.processEvents()
        bench = pet.bench_labels[0].geometry()
        self.assertEqual(bench.bottom() + 1, pet.sprite_area())


class TallWindowPositionTests(unittest.TestCase):
    SCREEN = ScreenRect(0, 0, 1920, 1040)

    def test_snapping_keeps_a_taller_window_on_screen(self) -> None:
        _x, y = snap_pet_position(500, 96, self.SCREEN, margin=8, height=113)
        self.assertLessEqual(y + 113, self.SCREEN.bottom)

    def test_recovering_keeps_a_taller_window_on_screen(self) -> None:
        _x, y = recover_pet_position(500, 5000, 96, [self.SCREEN], height=113)
        self.assertLessEqual(y + 113, self.SCREEN.bottom)

    def test_height_defaults_to_the_sprite_box(self) -> None:
        self.assertEqual(
            snap_pet_position(500, 96, self.SCREEN, margin=8),
            snap_pet_position(500, 96, self.SCREEN, margin=8, height=96),
        )


if __name__ == "__main__":
    unittest.main()
