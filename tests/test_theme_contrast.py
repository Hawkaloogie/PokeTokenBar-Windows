"""Every foreground colour must be visible on the surface it is painted on.

Regression for a reported bug: shop tooltips popped up completely blank. The
QToolTip rule painted `text` on `tooltip_bg`, and light mode happened to define
both as #1b1b1d - identical, so the tooltip drew near-black on near-black.

The instance was one collision. The class is "a token used as a foreground is
never checked against the token it sits on", so this file checks every such
pairing in both palettes rather than only the tooltip.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from poketokenbar_windows import theme

# WCAG 2.1: 4.5:1 for body text, 3:1 for large or non-essential text.
BODY_MIN = 4.5
LARGE_MIN = 3.0
# A hairline only has to be discernible, not readable.
HAIRLINE_MIN = 1.2

# (foreground token, background token, minimum ratio, what it is)
PAIRS = (
    ("text", "bg", BODY_MIN, "body text on the app canvas"),
    ("text", "surface", BODY_MIN, "body text on a card"),
    ("text", "surface_alt", BODY_MIN, "body text on a raised control"),
    ("text_muted", "bg", BODY_MIN, "secondary text on the canvas"),
    ("text_muted", "surface", BODY_MIN, "secondary text on a card"),
    ("text_faint", "bg", LARGE_MIN, "faint text on the canvas"),
    ("text_faint", "surface", LARGE_MIN, "faint text on a card"),
    ("accent_text", "accent", BODY_MIN, "button label on the accent fill"),
    ("tooltip_text", "tooltip_bg", BODY_MIN, "tooltip text on the tooltip"),
    ("tooltip_border", "tooltip_bg", HAIRLINE_MIN, "the tooltip's own hairline"),
    ("border", "bg", HAIRLINE_MIN, "a hairline on the canvas"),
)


def _channels(value: str) -> tuple[float, float, float]:
    raw = value.lstrip("#")
    if len(raw) != 6:
        raise AssertionError(f"expected a 6-digit hex colour, got {value!r}")
    return tuple(int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(value: str) -> float:
    """WCAG relative luminance."""
    linear = [
        channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in _channels(value)
    ]
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class PaletteContrastTests(unittest.TestCase):
    def test_every_foreground_is_readable_on_its_background(self) -> None:
        for mode in ("light", "dark"):
            colours = theme.palette(mode)
            for fore, back, minimum, description in PAIRS:
                with self.subTest(mode=mode, pair=f"{fore} on {back}"):
                    self.assertIn(fore, colours, f"{mode} palette is missing {fore}")
                    self.assertIn(back, colours, f"{mode} palette is missing {back}")
                    ratio = contrast_ratio(colours[fore], colours[back])
                    self.assertGreaterEqual(
                        ratio,
                        minimum,
                        f"{mode}: {description} is only {ratio:.2f}:1 "
                        f"({colours[fore]} on {colours[back]}), needs {minimum}:1",
                    )

    def test_no_foreground_token_equals_its_own_background(self) -> None:
        """The exact shape of the reported bug, stated plainly."""
        for mode in ("light", "dark"):
            colours = theme.palette(mode)
            for fore, back, _minimum, description in PAIRS:
                with self.subTest(mode=mode, pair=f"{fore} on {back}"):
                    self.assertNotEqual(
                        colours[fore].lower(),
                        colours[back].lower(),
                        f"{mode}: {description} - {fore} and {back} are the same "
                        f"colour, so it renders invisible",
                    )

    def test_both_palettes_declare_the_same_tokens(self) -> None:
        """A token added to one mode and forgotten in the other is a KeyError
        at stylesheet-build time, which means a dead app rather than a test."""
        self.assertEqual(
            sorted(theme.palette("light")),
            sorted(theme.palette("dark")),
            "the light and dark palettes have drifted apart",
        )


class ToolTipRuleTests(unittest.TestCase):
    """A source check, because the collision was in the RULE, not the palette.

    Both tokens were individually fine; the bug was the stylesheet reaching for
    the wrong one. Checking the built stylesheet catches that.
    """

    def _tooltip_block(self, mode: str) -> str:
        sheet = theme.build_stylesheet(mode)
        match = re.search(r"QToolTip\s*\{(.*?)\}", sheet, re.DOTALL)
        self.assertIsNotNone(match, "the stylesheet has no QToolTip rule at all")
        return match.group(1)  # type: ignore[union-attr]

    def test_the_tooltip_rule_paints_readable_text(self) -> None:
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                colours = theme.palette(mode)
                block = self._tooltip_block(mode)
                background = re.search(r"background:\s*(#[0-9a-fA-F]{6})", block)
                foreground = re.search(r"color:\s*(#[0-9a-fA-F]{6})", block)
                self.assertIsNotNone(background, "tooltip has no background")
                self.assertIsNotNone(foreground, "tooltip has no colour")
                ratio = contrast_ratio(foreground.group(1), background.group(1))
                self.assertGreaterEqual(
                    ratio,
                    BODY_MIN,
                    f"{mode}: tooltip renders {foreground.group(1)} on "
                    f"{background.group(1)} - only {ratio:.2f}:1",
                )
                self.assertEqual(
                    background.group(1).lower(), colours["tooltip_bg"].lower()
                )
                self.assertEqual(
                    foreground.group(1).lower(), colours["tooltip_text"].lower()
                )


class NativePaletteTests(unittest.TestCase):
    """Qt draws some tooltips itself, from QPalette rather than the stylesheet.

    Fixing only the stylesheet would have left those blank in exactly the same
    way, so the role mapping gets the same check.
    """

    def test_tooltip_roles_are_readable_against_each_other(self) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                theme.apply_base_palette(app, mode)
                painted = app.palette()
                base = painted.color(QPalette.ColorRole.ToolTipBase).name()
                text = painted.color(QPalette.ColorRole.ToolTipText).name()
                ratio = contrast_ratio(text, base)
                self.assertGreaterEqual(
                    ratio,
                    BODY_MIN,
                    f"{mode}: native tooltip is {text} on {base} - "
                    f"only {ratio:.2f}:1",
                )


if __name__ == "__main__":
    unittest.main()
