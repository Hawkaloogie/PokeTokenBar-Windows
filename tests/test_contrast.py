"""Text must stay legible in both themes.

Regression: muted labels were switched to palette(mid), which is a BORDER
colour, not a text colour. On the dark background that rendered near-invisible
and text effectively disappeared.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from poketokenbar_windows.theme import build_stylesheet, palette

# WCAG 2.1: 4.5:1 for body text, 3:1 for large or non-essential text.
AA_BODY = 4.5
AA_LARGE = 3.0


def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    adjusted = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def contrast(first: str, second: str) -> float:
    a, b = _luminance(first), _luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


class ContrastTests(unittest.TestCase):
    MODES = ("dark", "light")
    SURFACES = ("bg", "surface", "surface_alt")

    def test_body_text_is_readable_on_every_surface(self) -> None:
        for mode in self.MODES:
            colours = palette(mode)
            for surface in self.SURFACES:
                ratio = contrast(colours["text"], colours[surface])
                self.assertGreaterEqual(
                    ratio, AA_BODY,
                    f"{mode}: body text on {surface} is only {ratio:.2f}:1",
                )

    def test_muted_text_is_readable_on_every_surface(self) -> None:
        """This is the one that broke - muted must remain real text, not a border."""
        for mode in self.MODES:
            colours = palette(mode)
            for surface in self.SURFACES:
                ratio = contrast(colours["text_muted"], colours[surface])
                self.assertGreaterEqual(
                    ratio, AA_BODY,
                    f"{mode}: muted text on {surface} is only {ratio:.2f}:1",
                )

    def test_secondary_text_clears_the_large_text_bar(self) -> None:
        for mode in self.MODES:
            colours = palette(mode)
            for role in ("text_faint", "favourite", "success", "danger", "warning"):
                ratio = contrast(colours[role], colours["surface"])
                self.assertGreaterEqual(
                    ratio, AA_LARGE,
                    f"{mode}: {role} on surface is only {ratio:.2f}:1",
                )

    def test_accent_buttons_are_readable(self) -> None:
        for mode in self.MODES:
            colours = palette(mode)
            ratio = contrast(colours["accent_text"], colours["accent"])
            self.assertGreaterEqual(
                ratio, AA_LARGE, f"{mode}: accent button text is {ratio:.2f}:1"
            )

    def test_the_two_themes_are_actually_different(self) -> None:
        self.assertNotEqual(palette("dark")["bg"], palette("light")["bg"])
        self.assertNotEqual(palette("dark")["text"], palette("light")["text"])

    def test_no_text_colour_is_taken_from_palette_mid(self) -> None:
        """palette(mid) is a border colour; using it for text is the bug."""
        source = Path(__file__).resolve().parents[1] / "src" / "poketokenbar_windows"
        offenders = []
        for path in source.glob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"color:\s*palette\(mid\)", line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(
            offenders, [],
            "palette(mid) used as a text colour - it disappears on dark",
        )

    def test_the_stylesheet_carries_real_colours_for_both_themes(self) -> None:
        for mode in self.MODES:
            sheet = build_stylesheet(mode)
            self.assertIn(palette(mode)["text"], sheet)
            self.assertIn(palette(mode)["text_muted"], sheet)


if __name__ == "__main__":
    unittest.main()
