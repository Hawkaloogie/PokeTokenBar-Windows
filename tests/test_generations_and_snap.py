from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poketokenbar_windows.pet_logic import ScreenRect, snap_pet_position
from poketokenbar_windows.pokemon import (
    GENERATION_MAX_ID,
    GENERATION_MIN_ID,
    GENERATIONS,
    generation_bounds,
    generation_label,
    generation_of,
    generation_region,
    normalize_generation,
)
from poketokenbar_windows.state import GameState, StateStore, set_generation_filter


class GenerationMappingTests(unittest.TestCase):
    def test_boundaries_of_every_generation_map_to_that_generation(self) -> None:
        for number, _region, low, high in GENERATIONS:
            self.assertEqual(generation_of(low), number)
            self.assertEqual(generation_of(high), number)

    def test_ranges_are_contiguous_and_ordered(self) -> None:
        for previous, current in zip(GENERATIONS, GENERATIONS[1:]):
            self.assertEqual(previous[3] + 1, current[2])

    def test_every_species_in_the_pool_resolves(self) -> None:
        for species_id in range(GENERATION_MIN_ID, GENERATION_MAX_ID + 1):
            self.assertIsNotNone(generation_of(species_id))

    def test_out_of_pool_ids_are_unknown(self) -> None:
        for species_id in (0, -1, GENERATION_MAX_ID + 1, 1025):
            self.assertIsNone(generation_of(species_id))
            self.assertEqual(generation_label(species_id), "Unknown generation")

    def test_known_species_label(self) -> None:
        self.assertEqual(generation_label(203), "Gen 2 - Johto")
        self.assertEqual(generation_label(1), "Gen 1 - Kanto")
        self.assertEqual(generation_label(649), "Gen 5 - Unova")

    def test_region_lookup(self) -> None:
        self.assertEqual(generation_region(3), "Hoenn")
        self.assertIsNone(generation_region(9))
        self.assertIsNone(generation_region(None))


class NormalizeGenerationTests(unittest.TestCase):
    def test_none_and_junk_mean_all_generations(self) -> None:
        for value in (None, "", "abc", 0, 6, 99, -1, [], {}):
            self.assertIsNone(normalize_generation(value))

    def test_valid_numbers_and_numeric_strings_survive(self) -> None:
        for value, expected in ((1, 1), ("3", 3), (5, 5), (5.0, 5), (1.5, 1)):
            self.assertEqual(normalize_generation(value), expected)

    def test_bounds_for_all_is_the_whole_pool(self) -> None:
        self.assertEqual(generation_bounds(None), (GENERATION_MIN_ID, GENERATION_MAX_ID))

    def test_bounds_are_a_cap_that_includes_every_earlier_generation(self) -> None:
        # Choosing Gen 3 must allow Kanto, Johto AND Hoenn - not Hoenn alone.
        for number, _region, _low, high in GENERATIONS:
            self.assertEqual(generation_bounds(number), (GENERATION_MIN_ID, high))

    def test_a_higher_cap_is_always_a_superset_of_a_lower_one(self) -> None:
        previous = None
        for number, _region, _low, _high in GENERATIONS:
            low, high = generation_bounds(number)
            self.assertEqual(low, GENERATION_MIN_ID)
            if previous is not None:
                self.assertGreater(high, previous)
            previous = high

    def test_bounds_for_an_unknown_generation_fall_back_to_all(self) -> None:
        self.assertEqual(generation_bounds(9), (GENERATION_MIN_ID, GENERATION_MAX_ID))


class GenerationFilterStateTests(unittest.TestCase):
    def test_setter_normalizes_and_returns(self) -> None:
        state = GameState()
        self.assertIsNone(state.generation_filter)
        self.assertEqual(set_generation_filter(state, 4), 4)
        self.assertEqual(state.generation_filter, 4)
        self.assertIsNone(set_generation_filter(state, 42))
        self.assertIsNone(state.generation_filter)

    def test_filter_survives_a_save_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = store.load()
            set_generation_filter(state, 2)
            store.save(state)
            self.assertEqual(store.load().generation_filter, 2)

    def test_corrupt_filter_on_disk_degrades_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            store.save(GameState())
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["generation_filter"] = "not-a-generation"
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertIsNone(store.load().generation_filter)


class HatchGenerationTests(unittest.TestCase):
    """hatch() must never roll a species outside the requested generation."""

    class _Recorder:
        """Minimal stand-in that records rolls and always rejects them."""

        def __init__(self) -> None:
            self.seen: list[int] = []

        def species(self, species_id: int) -> dict:
            self.seen.append(species_id)
            # evolves_from_species set -> rejected, so hatch keeps rolling and
            # exhausts max_attempts. That gives a large sample of the roll range.
            return {"evolves_from_species": {"name": "x"}}

    def _rolls_for(self, generation: int | None, attempts: int = 300) -> list[int]:
        from poketokenbar_windows.pokemon import PokeAPIClient

        recorder = self._Recorder()
        client = PokeAPIClient.__new__(PokeAPIClient)
        client.species = recorder.species  # type: ignore[method-assign]
        with self.assertRaises(Exception):
            client.hatch(generation=generation, max_attempts=attempts)
        return recorder.seen

    def test_rolls_stay_at_or_below_the_generation_cap(self) -> None:
        for number, _region, _low, high in GENERATIONS:
            rolls = self._rolls_for(number)
            self.assertTrue(rolls, "expected the hatcher to roll at least once")
            self.assertTrue(
                all(GENERATION_MIN_ID <= r <= high for r in rolls),
                f"cap {number} rolled outside {GENERATION_MIN_ID}-{high}",
            )

    def test_a_cap_of_one_still_means_kanto_only(self) -> None:
        rolls = self._rolls_for(1)
        self.assertTrue(rolls)
        self.assertTrue(all(1 <= r <= 151 for r in rolls))

    def test_all_generations_never_exceeds_the_pool(self) -> None:
        rolls = self._rolls_for(None, attempts=600)
        self.assertTrue(rolls)
        self.assertTrue(all(GENERATION_MIN_ID <= r <= GENERATION_MAX_ID for r in rolls))

    def test_invalid_generation_falls_back_to_the_whole_pool(self) -> None:
        rolls = self._rolls_for(99, attempts=300)
        self.assertTrue(all(GENERATION_MIN_ID <= r <= GENERATION_MAX_ID for r in rolls))


class SnapPetPositionTests(unittest.TestCase):
    SCREEN = ScreenRect(0, 0, 1920, 1040)  # 1080 tall minus a 40px taskbar

    def test_pet_lands_just_above_the_taskbar(self) -> None:
        _x, y = snap_pet_position(500, 96, self.SCREEN, margin=8)
        self.assertEqual(y, self.SCREEN.bottom - 8 - 96)

    def test_horizontal_position_is_preserved(self) -> None:
        x, _y = snap_pet_position(500, 96, self.SCREEN, margin=8)
        self.assertEqual(x, 500)

    def test_offscreen_x_is_clamped_back_on(self) -> None:
        left, _ = snap_pet_position(-5000, 96, self.SCREEN, margin=8)
        right, _ = snap_pet_position(999_999, 96, self.SCREEN, margin=8)
        self.assertGreaterEqual(left, self.SCREEN.x)
        self.assertLessEqual(right + 96, self.SCREEN.right)

    def test_junk_x_does_not_raise(self) -> None:
        for value in (None, "abc", float("nan"), float("inf"), [], {}):
            x, y = snap_pet_position(value, 96, self.SCREEN, margin=8)
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)

    def test_snapping_is_idempotent(self) -> None:
        first = snap_pet_position(500, 96, self.SCREEN, margin=8)
        second = snap_pet_position(first[0], 96, self.SCREEN, margin=8)
        self.assertEqual(first, second)

    def test_works_on_a_secondary_monitor_with_an_offset_origin(self) -> None:
        screen = ScreenRect(1920, -200, 1280, 984)
        x, y = snap_pet_position(2000, 96, screen, margin=8)
        self.assertEqual(y, screen.bottom - 8 - 96)
        self.assertGreaterEqual(x, screen.x)
        self.assertLessEqual(x + 96, screen.right)

    def test_taskbar_on_a_side_edge_still_uses_the_work_area_bottom(self) -> None:
        # Left-docked taskbar: work area starts at x=60, full height.
        screen = ScreenRect(60, 0, 1860, 1080)
        x, y = snap_pet_position(0, 96, screen, margin=8)
        self.assertEqual(y, screen.bottom - 8 - 96)
        self.assertGreaterEqual(x, screen.x)


class WidePetPositionTests(unittest.TestCase):
    """A party row makes the window wider than tall; clamps must respect that."""

    SCREEN = ScreenRect(0, 0, 1920, 1040)

    def test_a_wide_window_is_clamped_by_its_width_not_its_sprite(self) -> None:
        x, _y = snap_pet_position(1900, 96, self.SCREEN, margin=8, width=366)
        self.assertLessEqual(x + 366, self.SCREEN.right)

    def test_width_defaults_to_the_sprite_box(self) -> None:
        self.assertEqual(
            snap_pet_position(500, 96, self.SCREEN, margin=8),
            snap_pet_position(500, 96, self.SCREEN, margin=8, width=96),
        )

    def test_a_width_smaller_than_the_sprite_is_ignored(self) -> None:
        self.assertEqual(
            snap_pet_position(500, 96, self.SCREEN, margin=8, width=10),
            snap_pet_position(500, 96, self.SCREEN, margin=8),
        )

    def test_recover_also_keeps_a_wide_window_on_screen(self) -> None:
        from poketokenbar_windows.pet_logic import recover_pet_position

        x, _y = recover_pet_position(1900, 500, 96, [self.SCREEN], width=366)
        self.assertLessEqual(x + 366, self.SCREEN.right)

    def test_vertical_snap_still_uses_the_sprite_height(self) -> None:
        _x, y = snap_pet_position(100, 96, self.SCREEN, margin=8, width=366)
        self.assertEqual(y, self.SCREEN.bottom - 8 - 96)


if __name__ == "__main__":
    unittest.main()
