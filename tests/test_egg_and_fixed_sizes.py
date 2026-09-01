"""Sprite sizes are a property of the size setting, not of the current sprite.

Two reported bugs, one root cause.

  "the egg model messes up the desktop sprite ... the egg needs to be scaled up
   to generally match the size of standard pokemon"
  "it causes the other pokemon in the party to shrink as well"

PokeAPI's egg.png is a 96x96 image containing a 28x30 egg - the artwork covers
under a third of it. An animated Pokemon GIF frame is cropped to its artwork and
covers about 98%. Scaling both into the same box drew the egg at roughly a third
of a Pokemon's size.

The party then inherited it: bench slots were measured from the main slot's
visible artwork, so a tiny egg in the main slot shrank every bench Pokemon too.

Two fixes: trim static sprites to their artwork before scaling, and size the
bench from the configured pet size rather than from whatever the main holds.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from poketokenbar_windows.floating_pet import (
    BENCH_SCALE,
    FloatingPetWindow,
    _egg_pixmap,
    _trim_transparent,
    _visible_rect,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _padded(canvas: int, artwork: int, artwork_width: int | None = None) -> QPixmap:
    """A sprite-shaped image: a blob centred in a larger transparent canvas.

    This is exactly PokeAPI's egg.png shape - the thing that broke. Width can
    differ from height, because real sprites are rarely square and a couple of
    these checks depend on that.
    """
    width = artwork if artwork_width is None else artwork_width
    pixmap = QPixmap(canvas, canvas)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.fillRect(
        (canvas - width) // 2, (canvas - artwork) // 2, width, artwork,
        QColor("#3fb950"),
    )
    painter.end()
    return pixmap


# A path that does not exist: set_bench falls back to a drawn Poke Ball,
# which still occupies a real bench slot. Enough to widen the window,
# which is all these checks need.
_TINY_SPRITE = Path("no-such-bench-sprite.png")


def _artwork_height(pixmap: QPixmap) -> int:
    """Visible artwork height, treating a fully opaque image as all artwork.

    _visible_rect returns None for a pixmap with no transparent pixels at all,
    because it derives its bounds from the alpha mask. A trimmed sprite IS
    fully opaque, so that case means "the whole thing", not "nothing".
    """
    bounds = _visible_rect(pixmap)
    return pixmap.height() if bounds is None else bounds.height()


class TrimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()

    def test_trimming_a_heavily_padded_sprite_yields_only_its_artwork(self) -> None:
        trimmed = _trim_transparent(_padded(96, 30))
        self.assertEqual((trimmed.width(), trimmed.height()), (30, 30))

    def test_a_padded_sprite_scales_up_to_fill_its_box_once_trimmed(self) -> None:
        """The egg's actual failure, in miniature."""
        padded = _padded(96, 30)
        untrimmed = padded.scaled(96, 96)
        trimmed = _trim_transparent(padded).scaled(96, 96)
        self.assertEqual(_artwork_height(untrimmed), 30)
        self.assertEqual(_artwork_height(trimmed), 96)


class FixedSizeTests(unittest.TestCase):
    """The bench must not care what the main slot is holding."""

    def setUp(self) -> None:
        self.app = _app()

    def test_bench_size_is_the_same_whatever_the_main_sprite_is(self) -> None:
        pet = FloatingPetWindow(96)
        sizes = set()
        for pixmap in (_padded(96, 28), _padded(96, 94), _egg_pixmap(96), QPixmap()):
            pet.label.setPixmap(pixmap)
            sizes.add(pet.bench_size())
        self.assertEqual(
            len(sizes),
            1,
            f"bench size drifted with the main sprite: {sorted(sizes)}",
        )

    def test_bench_size_is_the_configured_fraction_of_the_pet_size(self) -> None:
        for size in (48, 96, 144, 192):
            with self.subTest(pet_size=size):
                pet = FloatingPetWindow(size)
                self.assertEqual(pet.bench_size(), max(12, round(size * BENCH_SCALE)))

    def test_a_tiny_main_sprite_cannot_shrink_the_bench(self) -> None:
        """The reported regression, stated directly."""
        pet = FloatingPetWindow(96)
        pet.label.setPixmap(_padded(96, 94))
        healthy = pet.bench_size()
        pet.label.setPixmap(_padded(96, 28))  # an egg-shaped sprite
        self.assertEqual(
            pet.bench_size(),
            healthy,
            "a heavily padded main sprite dragged the bench size down with it",
        )

    def test_main_height_tracks_the_size_setting_not_the_sprite(self) -> None:
        pet = FloatingPetWindow(128)
        pet.label.setPixmap(_padded(128, 20))
        self.assertEqual(pet.main_visible_height(), 128)


class EggRendersLikeAPokemonTests(unittest.TestCase):
    """The headline ask: the egg should read as the same size as a Pokemon."""

    def setUp(self) -> None:
        self.app = _app()

    def test_the_drawn_egg_fills_its_canvas_once_trimmed(self) -> None:
        trimmed = _trim_transparent(_egg_pixmap(96))
        self.assertEqual(_artwork_height(trimmed), trimmed.height())

    def test_a_padded_egg_and_a_tight_pokemon_render_within_a_tenth_of_each_other(
        self,
    ) -> None:
        """Different sources, comparable on-screen size. That is the whole ask."""
        area = 96
        # A heavily padded source (the egg) and a tightly cropped one (an
        # animated Pokemon frame), each put through the same render path.
        egg = _trim_transparent(_padded(96, 28)).scaledToHeight(area)
        pokemon = _trim_transparent(_padded(64, 62)).scaledToHeight(area)
        egg_h = _artwork_height(egg)
        pokemon_h = _artwork_height(pokemon)
        self.assertLessEqual(
            abs(egg_h - pokemon_h) / max(egg_h, pokemon_h),
            0.10,
            f"egg renders {egg_h}px against a Pokemon's {pokemon_h}px",
        )


class AnimatedFramesAreNotTrimmedTests(unittest.TestCase):
    """Trimming an animation per frame would make it jitter.

    Each GIF frame has its own artwork bounds, so trimming frame-by-frame would
    rescale the sprite on every tick. Animated frames are deliberately left
    alone; they are already cropped tight by the source, which is why the
    padding problem was specific to static images.
    """

    def setUp(self) -> None:
        self.app = _app()

    def test_frames_with_different_bounds_would_scale_differently_if_trimmed(
        self,
    ) -> None:
        wide = _trim_transparent(_padded(96, 60, artwork_width=90)).scaledToHeight(96)
        narrow = _trim_transparent(_padded(96, 60, artwork_width=40)).scaledToHeight(96)
        self.assertNotEqual(
            wide.width(),
            narrow.width(),
            "if this ever becomes equal, per-frame trimming stopped causing "
            "jitter and the animated-frame exclusion could be revisited",
        )

    def test_the_render_path_only_trims_when_not_animated(self) -> None:
        """Guards the branch itself, so the exclusion cannot be dropped silently."""
        import inspect

        source = inspect.getsource(FloatingPetWindow._render_current_frame)
        self.assertIn("if not animated:", source)
        self.assertIn("_trim_transparent(pixmap)", source)


if __name__ == "__main__":
    unittest.main()


class CalloutAnchorTests(unittest.TestCase):
    """The speech bubble belongs over the MAIN Pokemon, not the whole party.

    Reported as: "the speech bubble on the desktop sprite stays in the center
    about the entire party, versus only on top of the main pokemon".

    The pet window spans the main sprite PLUS the level text PLUS every filled
    bench slot, so centring a callout on the window centred it on the party.
    """

    def setUp(self) -> None:
        self.app = _app()

    def _pet(self, bench: int, bias: str) -> FloatingPetWindow:
        from poketokenbar_windows.floating_pet import PET_BIAS_LEFT, PET_BIAS_RIGHT

        pet = FloatingPetWindow(96)
        pet.bias = PET_BIAS_RIGHT if bias == "right" else PET_BIAS_LEFT
        pet.set_level("Lv. 54")
        pet.set_bench([_TINY_SPRITE] * bench)
        return pet

    def test_the_main_slot_is_narrower_than_the_window_once_benched(self) -> None:
        pet = self._pet(bench=3, bias="right")
        self.assertLess(
            pet.main_slot_rect().width(),
            pet.width(),
            "fixture did not actually add bench slots",
        )

    def test_the_anchor_centre_follows_the_main_not_the_window(self) -> None:
        for bias in ("left", "right"):
            with self.subTest(bias=bias):
                bare = self._pet(bench=0, bias=bias)
                bare_offset = bare.main_slot_rect().center().x() - bare.x()
                crowded = self._pet(bench=3, bias=bias)
                crowded_offset = crowded.main_slot_rect().center().x() - crowded.x()
                window_offset = crowded.width() // 2
                self.assertNotEqual(
                    crowded_offset,
                    window_offset,
                    "the anchor is still the window centre, so the bubble "
                    "would sit over the middle of the party",
                )
                if bias == "right":
                    self.assertGreater(
                        crowded_offset,
                        bare_offset,
                        "bench sits left of the main when right-biased, so the "
                        "main's centre should move right within the window",
                    )

    def test_the_anchor_stays_inside_the_window(self) -> None:
        pet = self._pet(bench=5, bias="right")
        anchor = pet.main_slot_rect()
        self.assertGreaterEqual(anchor.x(), pet.x())
        self.assertLessEqual(anchor.right(), pet.x() + pet.width())


class TradeSpritePresentationTests(unittest.TestCase):
    """Trade offers show one Pokemon each and it should be readable.

    Reported as: "for the trading store, can we make the pokemon larger to be
    more viewable". Enlarging the box alone would not have done it - a static
    PokeAPI sprite covers roughly half its canvas, so most of a bigger box
    would have been transparent padding.
    """

    def setUp(self) -> None:
        self.app = _app()

    def test_trimming_is_off_by_default(self) -> None:
        """Other surfaces rely on the padding to stay optically aligned."""
        from poketokenbar_windows.ui import _sprite_pixmap
        import inspect

        signature = inspect.signature(_sprite_pixmap)
        self.assertIs(signature.parameters["trim"].default, False)

    def test_the_trade_box_is_bigger_than_the_old_thumbnail(self) -> None:
        from poketokenbar_windows.ui import TRADE_SPRITE_BOX

        self.assertGreater(TRADE_SPRITE_BOX, 64)

    def test_a_trimmed_sprite_fills_far_more_of_its_box(self) -> None:
        from poketokenbar_windows.ui import TRADE_SPRITE_BOX, _sprite_pixmap
        import tempfile

        source = _padded(96, 30)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sprite.png"
            source.save(str(path))
            old = _artwork_height(_sprite_pixmap(path, 60))
            new = _artwork_height(_sprite_pixmap(path, TRADE_SPRITE_BOX, trim=True))
        self.assertGreaterEqual(
            new / old, 3.0,
            f"trade sprite only went from {old}px to {new}px",
        )
        self.assertEqual(
            new, TRADE_SPRITE_BOX, "a trimmed sprite should fill its box"
        )
