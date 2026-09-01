"""The level text must fit the box the layout reserved for it.

Reported as: "the 'L' in 'Lv.' is not showing completely, it's cut off".

Cause: a Qt style sheet's font-size OUTRANKS QWidget.setFont(). The app-wide
rule is `QWidget { font-size: 13px; }`, so the label was MEASURED with the
scaled font from _level_font() (8pt, 28px wide at pet size 96) and PAINTED at
13px (34px wide). The label is right-aligned, so the 6px of overflow came off
the LEFT - the 'L'.

Same family as the palette(mid) bug: a style sheet quietly overruling what the
code set. The fix restates the size in the label's own style sheet so painted
and measured agree.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from poketokenbar_windows import theme
from poketokenbar_windows.floating_pet import FloatingPetWindow

SIZES = (48, 64, 96, 128, 144, 192)
TEXTS = ("Lv. 5", "Lv. 54", "Lv. 100")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class LevelLabelFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        # Exactly what the running app installs - without this the clash the
        # bug depends on does not exist and the test proves nothing.
        self.app.setStyleSheet(theme.build_stylesheet("light"))

    def tearDown(self) -> None:
        self.app.setStyleSheet("")

    def _pet(self, size: int, text: str) -> FloatingPetWindow:
        pet = FloatingPetWindow(size)
        pet.set_level(text)
        pet._relayout()
        return pet

    def test_the_label_is_never_narrower_than_the_text_it_paints(self) -> None:
        for size in SIZES:
            for text in TEXTS:
                with self.subTest(pet_size=size, level=text):
                    pet = self._pet(size, text)
                    painted = pet.level_label.fontMetrics().horizontalAdvance(
                        pet.level_display_text()
                    )
                    self.assertGreaterEqual(
                        pet.level_label.width(),
                        painted,
                        "right-aligned label is too narrow, so the text clips "
                        "off its LEFT edge - this is the cut-off 'L'",
                    )

    def test_the_label_carries_its_own_font_size(self) -> None:
        """The actual fix. Without this the app-wide 13px wins."""
        for size in SIZES:
            with self.subTest(pet_size=size):
                pet = self._pet(size, "Lv. 54")
                style = pet.level_label.styleSheet()
                self.assertIn("font-size", style)
                self.assertIn(f"{pet._level_point_size()}pt", style)

    def test_the_measured_font_and_the_painted_size_agree(self) -> None:
        for size in SIZES:
            with self.subTest(pet_size=size):
                pet = self._pet(size, "Lv. 54")
                self.assertEqual(
                    pet._level_font().pointSize(),
                    pet._level_point_size(),
                    "the font used for measurement drifted from the one "
                    "written into the style sheet",
                )

    def test_reserved_width_covers_ink_that_overhangs_the_advance(self) -> None:
        """A glyph can paint past its advance width; the reservation allows it."""
        from PySide6.QtGui import QFontMetrics

        for size in SIZES:
            with self.subTest(pet_size=size):
                pet = self._pet(size, "Lv. 100")
                shown = pet.level_display_text()
                metrics = QFontMetrics(pet._level_font())
                ink = metrics.boundingRect(shown)
                gap = pet.level_width() - pet.level_label.width()
                self.assertGreaterEqual(
                    pet.level_label.width(),
                    ink.width() + max(0, -ink.left()),
                    f"reserved width ignores ink overhang (gap={gap})",
                )

    def test_the_level_scales_with_the_pet(self) -> None:
        """It used to be pinned at the app-wide 13px however big the pet was."""
        widths = []
        for size in SIZES:
            pet = self._pet(size, "Lv. 54")
            widths.append(
                pet.level_label.fontMetrics().horizontalAdvance(
                    pet.level_display_text()
                )
            )
        self.assertGreater(
            widths[-1], widths[0],
            "the level paints at the same size for a 48px and a 192px pet, "
            "so the style sheet is still overriding the scaled font",
        )


if __name__ == "__main__":
    unittest.main()
