"""Regressions for defects found by the QC panel on feat/gen-filter-snap-reset.

Each test names the finding it locks down so a future refactor cannot quietly
reintroduce it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poketokenbar_windows.pet_logic import ScreenRect, recover_pet_position
from poketokenbar_windows.pokemon import normalize_generation
from poketokenbar_windows.state import (
    PARTY_BENCH_SIZE,
    CatchRecord,
    GameState,
    MonState,
    StateStore,
    assign_party_slot,
    buy_egg,
    catch_in_use,
)


def mon(base_id: int, **kw) -> MonState:
    return MonState(
        base_id=base_id,
        path_ids=kw.get("path_ids", [base_id]),
        stage_index=kw.get("stage_index", 0),
        used_at_stage=kw.get("used_at_stage", 0),
        rarity=kw.get("rarity", "common"),
        is_shiny=kw.get("is_shiny", False),
        nature=kw.get("nature", "Hardy"),
    )


def catch(species_id: int, **kw) -> CatchRecord:
    return CatchRecord(
        species_id=species_id,
        base_id=kw.get("base_id", species_id),
        path_ids=kw.get("path_ids", [species_id]),
        rarity=kw.get("rarity", "common"),
        is_shiny=kw.get("is_shiny", False),
        nature=kw.get("nature", "Hardy"),
        caught_at="2026-09-01T00:00:00+00:00",
    )


def _save_then_corrupt(mutate) -> GameState:
    """Write a healthy save, corrupt one part of it, reload."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        store = StateStore(path)
        state = GameState()
        state.mon = mon(203)
        state.used_since_install = 5_000_000_000
        state.catches = [catch(203), catch(25)]
        state.party[0] = mon(25)
        store.save(state)

        raw = json.loads(path.read_text(encoding="utf-8"))
        mutate(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")
        return store.load()


class SaveWipeRegressions(unittest.TestCase):
    """QC finding: one malformed field wiped wallet, Pokedex, bench and filter."""

    def test_an_extra_key_on_mon_no_longer_destroys_the_whole_save(self) -> None:
        def mutate(raw):
            raw["mon"]["bogus_extra_field"] = 1

        loaded = _save_then_corrupt(mutate)
        # Unknown keys are now ignored outright, so the Pokemon survives whole -
        # previously this single extra key wiped wallet, Pokedex and bench.
        self.assertIsNotNone(loaded.mon)
        self.assertEqual(loaded.mon.base_id, 203)
        self.assertEqual(len(loaded.catches), 2)
        self.assertEqual(loaded.used_since_install, 5_000_000_000)
        self.assertEqual(loaded.party[0].base_id, 25)

    def test_a_missing_key_on_mon_no_longer_destroys_the_whole_save(self) -> None:
        def mutate(raw):
            del raw["mon"]["nature"]

        loaded = _save_then_corrupt(mutate)
        self.assertIsNone(loaded.mon)
        self.assertEqual(len(loaded.catches), 2)
        self.assertEqual(loaded.used_since_install, 5_000_000_000)

    def test_one_bad_pokedex_row_drops_only_that_row(self) -> None:
        def mutate(raw):
            raw["catches"][0] = {"species_id": "not-a-number"}

        loaded = _save_then_corrupt(mutate)
        self.assertEqual(len(loaded.catches), 1)
        self.assertEqual(loaded.catches[0].species_id, 25)
        self.assertIsNotNone(loaded.mon)


class TypeInvalidFieldRegressions(unittest.TestCase):
    """QC finding: wrong-typed values passed load, then crashed the renderer."""

    def _bench_slot_survives(self, bad_slot) -> GameState:
        def mutate(raw):
            raw["party"][0] = bad_slot

        return _save_then_corrupt(mutate)

    def test_type_invalid_bench_values_degrade_at_load_not_at_render(self) -> None:
        poisoned = [
            {"base_id": 1, "path_ids": "not-a-list", "stage_index": 0,
             "used_at_stage": 0, "rarity": "common", "is_shiny": False, "nature": "Hardy"},
            {"base_id": 1, "path_ids": [1], "stage_index": {"a": 1},
             "used_at_stage": 0, "rarity": "common", "is_shiny": False, "nature": "Hardy"},
            {"base_id": 1, "path_ids": None, "stage_index": None,
             "used_at_stage": None, "rarity": "common", "is_shiny": False, "nature": "Hardy"},
            {"base_id": [1, 2], "path_ids": [1], "stage_index": 0,
             "used_at_stage": 0, "rarity": "common", "is_shiny": False, "nature": "Hardy"},
        ]
        for bad in poisoned:
            loaded = self._bench_slot_survives(bad)
            self.assertIsNone(loaded.party[0], f"should have degraded: {bad}")
            # And the rest of the save is intact.
            self.assertEqual(len(loaded.catches), 2)

    def test_a_loaded_member_always_has_a_usable_current_id(self) -> None:
        """current_id used to raise TypeError deep inside the Party renderer."""
        def mutate(raw):
            raw["party"][0] = {
                "base_id": 1, "path_ids": [1, 2], "stage_index": 99,
                "used_at_stage": -5, "rarity": "common",
                "is_shiny": False, "nature": "Hardy",
            }

        loaded = _save_then_corrupt(mutate)
        member = loaded.party[0]
        self.assertIsNotNone(member)
        self.assertIsInstance(member.current_id, int)
        self.assertEqual(member.stage_index, 1)   # clamped into the path
        self.assertEqual(member.used_at_stage, 0)  # never negative

    def test_an_unknown_rarity_is_rejected_rather_than_crashing_growth_math(self) -> None:
        def mutate(raw):
            raw["party"][0]["rarity"] = "mythicalish"

        self.assertIsNone(_save_then_corrupt(mutate).party[0])


class DuplicationRegressions(unittest.TestCase):
    """QC finding: the picker could clone a Pokemon, including the live main."""

    def test_the_active_main_cannot_be_cloned_onto_the_bench(self) -> None:
        state = GameState()
        state.mon = mon(203, used_at_stage=123_456)
        entry = catch(203)
        self.assertTrue(catch_in_use(state, entry))
        self.assertFalse(assign_party_slot(state, 0, entry))
        self.assertIsNone(state.party[0])

    def test_the_same_entry_cannot_occupy_two_bench_slots(self) -> None:
        state = GameState()
        entry = catch(25)
        self.assertTrue(assign_party_slot(state, 0, entry))
        self.assertFalse(assign_party_slot(state, 1, entry))
        self.assertIsNone(state.party[1])

    def test_reassigning_the_same_slot_to_itself_is_allowed(self) -> None:
        state = GameState()
        entry = catch(25)
        assign_party_slot(state, 0, entry)
        self.assertTrue(assign_party_slot(state, 0, entry))

    def test_a_different_shiny_or_nature_counts_as_a_different_pokemon(self) -> None:
        state = GameState()
        assign_party_slot(state, 0, catch(25))
        self.assertTrue(assign_party_slot(state, 1, catch(25, is_shiny=True)))
        self.assertTrue(assign_party_slot(state, 2, catch(25, nature="Bold")))


class BuyEggRegressions(unittest.TestCase):
    """QC finding: buy_egg could orphan a benched Pokemon from the Pokedex."""

    def test_buy_egg_keeps_a_pokedex_entry_the_bench_depends_on(self) -> None:
        state = GameState()
        state.used_since_install = 10_000_000_000
        state.mon = mon(203)
        state.catches = [catch(203)]
        state.party[0] = mon(203)  # same identity, benched
        ok, _msg = buy_egg(state, None)
        self.assertTrue(ok)
        self.assertTrue(
            any(c.base_id == 203 for c in state.catches),
            "benched Pokemon lost its Pokedex entry",
        )

    def test_buy_egg_still_discards_an_unbenched_in_progress_catch(self) -> None:
        state = GameState()
        state.used_since_install = 10_000_000_000
        state.mon = mon(203)
        state.catches = [catch(203)]
        ok, _msg = buy_egg(state, None)
        self.assertTrue(ok)
        self.assertEqual(state.catches, [])


class MiscRegressions(unittest.TestCase):
    def test_a_boolean_generation_filter_is_not_gen_one(self) -> None:
        """bool is an int subclass; True must not silently mean Kanto-only."""
        self.assertIsNone(normalize_generation(True))
        self.assertIsNone(normalize_generation(False))

    def test_monitor_choice_accounts_for_the_wide_party_row(self) -> None:
        left = ScreenRect(0, 0, 800, 600)
        right = ScreenRect(800, 0, 800, 600)
        x, _y = recover_pet_position(700, 300, 96, [left, right], width=366)
        self.assertLessEqual(x + 366, right.right)

    def test_state_version_records_the_party_schema(self) -> None:
        from poketokenbar_windows.state import STATE_VERSION

        self.assertGreaterEqual(STATE_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
