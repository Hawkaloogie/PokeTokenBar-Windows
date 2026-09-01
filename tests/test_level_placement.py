"""The level indicator sits beside the Pokemon - never on it, never above it.

Two regressions are locked down here:
  1. It was originally composited onto the sprite, covering the artwork.
  2. Moving it below the sprite made the window taller than the art, so snapping
     to the taskbar left the Pokemon floating above the edge.
It now sits to the LEFT on the sprite's baseline, keeping the window exactly as
tall as the artwork.
"""
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


class LevelBesideSpriteTests(unittest.TestCase):
    SIZES = (48, 96, 160, 192)

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

    def test_the_window_is_never_taller_than_the_sprite(self) -> None:
        """The snap regression: extra height lifted the Pokemon off the edge."""
        for size in self.SIZES:
            pet = self._pet(size)
            self.assertEqual(
                pet.height(), size,
                f"window grew taller than the artwork at {size}px",
            )

    def test_the_level_sits_entirely_left_of_the_sprite(self) -> None:
        for size in self.SIZES:
            pet = self._pet(size)
            self.assertLessEqual(
                pet.level_label.geometry().right(),
                pet.label.geometry().left(),
                f"level overlapped the sprite at {size}px",
            )

    def test_it_is_level_with_the_sprites_feet(self) -> None:
        for size in self.SIZES:
            pet = self._pet(size)
            self.assertEqual(
                pet.level_label.geometry().bottom(),
                pet.label.geometry().bottom(),
                "level is not on the sprite's baseline",
            )

    def test_the_sprite_keeps_its_full_size(self) -> None:
        for size in (96, 128, 160):
            pet = self._pet(size)
            self.assertEqual(pet.sprite_area(), size)
            self.assertEqual(pet.label.pixmap().height(), size)

    def test_the_window_widens_by_exactly_the_level(self) -> None:
        pet = self._pet(96)
        self.assertEqual(pet.width(), 96 + pet.level_width())

    def test_no_level_means_no_lead_and_a_square_window(self) -> None:
        pet = self._pet(96, level="")
        self.assertEqual(pet.level_width(), 0)
        self.assertEqual((pet.width(), pet.height()), (96, 96))
        self.assertEqual(pet.label.geometry().left(), 0)
        self.assertFalse(pet.level_label.isVisible())

    def test_clearing_the_level_returns_the_window_to_square(self) -> None:
        pet = self._pet(96)
        self.assertGreater(pet.level_width(), 0)
        pet.set_level("")
        self.app.processEvents()
        self.assertEqual(pet.level_width(), 0)
        self.assertEqual((pet.width(), pet.height()), (96, 96))

    def test_it_is_rendered_at_half_opacity(self) -> None:
        pet = self._pet(96)
        self.assertIn(f"{int(255 * LEVEL_OPACITY)}", pet.level_label.styleSheet())

    def test_the_number_is_always_readable_whatever_form_is_used(self) -> None:
        """The prefix may be trimmed to fit, but the level itself never is."""
        for size in self.SIZES:
            for level in ("Lv. 0", "Lv. 7", "Lv. 42", "Lv. 100"):
                pet = self._pet(size, level=level)
                digits = level.rsplit(" ", 1)[-1]
                self.assertTrue(
                    pet.level_display_text().endswith(digits),
                    f"{level} at {size}px showed {pet.level_display_text()!r}",
                )

    def test_the_displayed_form_never_exceeds_its_budget(self) -> None:
        from PySide6.QtGui import QFontMetrics

        from poketokenbar_windows.floating_pet import LEVEL_MAX_SHARE

        for size in self.SIZES:
            pet = self._pet(size, level="Lv. 100")
            advance = QFontMetrics(pet._level_font()).horizontalAdvance(
                pet.level_display_text()
            )
            self.assertLessEqual(advance, size * LEVEL_MAX_SHARE + 1)

    def test_the_level_stays_a_modest_share_of_the_window(self) -> None:
        for size in self.SIZES:
            pet = self._pet(size, level="Lv. 100")
            self.assertLess(
                pet.level_width(), size * 0.75,
                "the level should be a glance, not half the widget",
            )

    def test_the_bench_starts_after_the_level_and_the_sprite(self) -> None:
        pet = self._pet(96)
        pet.set_bench([self.api.sprite_path(1, animated=False)] + [None] * 4)
        self.app.processEvents()
        self.assertGreaterEqual(
            pet.bench_labels[0].geometry().left(),
            pet.label.geometry().right(),
        )

    def test_the_bench_still_stands_on_the_sprite_baseline(self) -> None:
        pet = self._pet(96)
        pet.set_bench([self.api.sprite_path(1, animated=False)] + [None] * 4)
        self.app.processEvents()
        self.assertEqual(pet.bench_labels[0].geometry().bottom() + 1, pet.sprite_area())


class SnapHeightTests(unittest.TestCase):
    SCREEN = ScreenRect(0, 0, 1920, 1040)

    def test_snapping_puts_the_feet_on_the_work_area_edge(self) -> None:
        _x, y = snap_pet_position(500, 96, self.SCREEN, margin=8, height=96)
        self.assertEqual(y + 96, self.SCREEN.bottom - 8)

    def test_a_taller_window_is_still_clamped_by_its_real_height(self) -> None:
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
