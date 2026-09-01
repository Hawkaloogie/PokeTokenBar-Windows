from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poketokenbar_windows.pokemon import EGG_HATCH_THRESHOLD, HatchResult
from poketokenbar_windows.state import (
    PARTY_BENCH_SIZE,
    PARTY_TOTAL_SIZE,
    CatchRecord,
    GameState,
    MonState,
    StateStore,
    add_to_party,
    apply_usage,
    assign_party_slot,
    clear_party_slot,
    confirm_evolution,
    party_members,
    party_open_slot,
    party_slot_from_catch,
    swap_main,
)


class FakeAPI:
    """Hatches a predictable single-stage Pokemon so growth math stays obvious."""

    def __init__(self, base_id: int = 10) -> None:
        self.base_id = base_id
        self.rarities_requested: list = []

    def hatch(self, minimum_rarity=None, shiny_charm=False, generation=None):
        self.rarities_requested.append(minimum_rarity)
        result = HatchResult(
            base_id=self.base_id,
            path_ids=[self.base_id],
            rarity="common",
            nature="Hardy",
            is_shiny=False,
            capture_rate=200,
        )
        self.base_id += 1
        return result


def mon(base_id: int, *, stage: int = 0, used: int = 0) -> MonState:
    return MonState(
        base_id=base_id,
        path_ids=[base_id, base_id + 100],
        stage_index=stage,
        used_at_stage=used,
        rarity="common",
        is_shiny=False,
        nature="Hardy",
    )


class PartyShapeTests(unittest.TestCase):
    def test_a_fresh_state_has_five_empty_bench_slots(self) -> None:
        state = GameState()
        self.assertEqual(len(state.party), PARTY_BENCH_SIZE)
        self.assertTrue(all(slot is None for slot in state.party))

    def test_party_members_is_main_plus_bench(self) -> None:
        state = GameState()
        state.mon = mon(1)
        state.party[0] = mon(2)
        members = party_members(state)
        self.assertEqual(len(members), PARTY_TOTAL_SIZE)
        self.assertIs(members[0], state.mon)
        self.assertIs(members[1], state.party[0])

    def test_open_slot_reports_first_gap_then_none_when_full(self) -> None:
        state = GameState()
        self.assertEqual(party_open_slot(state), 0)
        for index in range(PARTY_BENCH_SIZE):
            self.assertEqual(add_to_party(state, mon(index + 1)), index)
        self.assertIsNone(party_open_slot(state))
        self.assertIsNone(add_to_party(state, mon(99)))

    def test_a_short_or_overlong_bench_is_normalized(self) -> None:
        state = GameState()
        state.party = [mon(1)]
        self.assertEqual(len(party_members(state)), PARTY_TOTAL_SIZE)
        state.party = [mon(i) for i in range(20)]
        self.assertEqual(len(party_members(state)), PARTY_TOTAL_SIZE)


class SwapMainTests(unittest.TestCase):
    def test_swap_exchanges_main_and_bench_slot(self) -> None:
        state = GameState()
        state.mon = mon(1)
        state.party[2] = mon(2)
        self.assertTrue(swap_main(state, 2))
        self.assertEqual(state.mon.base_id, 2)
        self.assertEqual(state.party[2].base_id, 1)

    def test_growth_progress_survives_a_round_trip(self) -> None:
        state = GameState()
        state.mon = mon(1, stage=1, used=4_242)
        state.party[0] = mon(2, stage=0, used=99)
        swap_main(state, 0)
        swap_main(state, 0)
        self.assertEqual(state.mon.base_id, 1)
        self.assertEqual(state.mon.stage_index, 1)
        self.assertEqual(state.mon.used_at_stage, 4_242)
        self.assertEqual(state.party[0].used_at_stage, 99)

    def test_swapping_into_an_empty_slot_benches_the_main(self) -> None:
        state = GameState()
        state.mon = mon(1)
        self.assertTrue(swap_main(state, 3))
        self.assertIsNone(state.mon)
        self.assertEqual(state.party[3].base_id, 1)

    def test_swap_is_rejected_when_both_sides_are_empty(self) -> None:
        state = GameState()
        self.assertFalse(swap_main(state, 0))

    def test_out_of_range_slots_are_rejected(self) -> None:
        state = GameState()
        state.mon = mon(1)
        for slot in (-1, PARTY_BENCH_SIZE, 99):
            self.assertFalse(swap_main(state, slot))
        self.assertEqual(state.mon.base_id, 1)

    def test_egg_progress_is_parked_not_destroyed_and_never_leaks(self) -> None:
        # Swapping used to zero egg_usage/egg_tier, silently destroying a tier
        # the player may have paid billions for. It must be parked instead -
        # and it must still not leak into the incoming Pokemon's counter.
        state = GameState()
        state.egg_usage = 4_999_999
        state.egg_tier = "legendary"
        state.party[0] = mon(7)
        swap_main(state, 0)
        self.assertEqual(state.mon.base_id, 7)
        self.assertEqual(state.mon.used_at_stage, 0)
        self.assertEqual(state.egg_usage, 4_999_999)
        self.assertEqual(state.egg_tier, "legendary")

    def test_a_parked_paid_egg_tier_is_still_honoured_when_it_finally_hatches(self) -> None:
        # Park a paid legendary egg by swapping a bench Pokemon into the main
        # slot, raise that one to graduation, and the parked tier must still be
        # spent on a real legendary hatch rather than quietly discarded.
        state = GameState()
        state.egg_usage = 4_999_999
        state.egg_tier = "legendary"
        state.party[0] = mon(7)
        swap_main(state, 0)
        api = FakeAPI()
        # mon(7) has two forms, so it now pauses for the player mid-way; confirm
        # the evolution and let the rest of the tokens carry through to the egg.
        apply_usage(state, EGG_HATCH_THRESHOLD + 750_000_000, api)
        while state.pending_evolution:
            confirm_evolution(state, api)
        self.assertIn("legendary", api.rarities_requested)
        # Consumed by the hatch, not left dangling.
        self.assertIsNone(state.egg_tier)


class BenchEditingTests(unittest.TestCase):
    def test_clear_empties_a_slot(self) -> None:
        state = GameState()
        state.party[1] = mon(5)
        self.assertTrue(clear_party_slot(state, 1))
        self.assertIsNone(state.party[1])

    def test_clearing_an_empty_or_invalid_slot_reports_failure(self) -> None:
        state = GameState()
        self.assertFalse(clear_party_slot(state, 0))
        self.assertFalse(clear_party_slot(state, 99))

    def test_assign_places_a_pokedex_entry_at_its_owned_stage(self) -> None:
        state = GameState()
        catch = CatchRecord(
            species_id=102,
            base_id=2,
            path_ids=[2, 102, 202],
            rarity="rare",
            is_shiny=True,
            nature="Bold",
            caught_at="2026-09-01T00:00:00+00:00",
        )
        self.assertTrue(assign_party_slot(state, 4, catch))
        placed = state.party[4]
        self.assertEqual(placed.base_id, 2)
        self.assertEqual(placed.stage_index, 1)
        self.assertTrue(placed.is_shiny)
        self.assertEqual(placed.nature, "Bold")

    def test_assign_tolerates_a_species_missing_from_its_own_path(self) -> None:
        catch = CatchRecord(
            species_id=999,
            base_id=2,
            path_ids=[2, 3],
            rarity="common",
            is_shiny=False,
            nature="Hardy",
            caught_at="2026-09-01T00:00:00+00:00",
        )
        placed = party_slot_from_catch(catch)
        self.assertEqual(placed.stage_index, 1)


class GraduationTests(unittest.TestCase):
    def _graduate_one(self, state: GameState, api: FakeAPI) -> list[str]:
        # Enough usage to hatch an egg and finish a common single-stage Pokemon.
        return apply_usage(state, EGG_HATCH_THRESHOLD + 750_000_000, api)

    def test_a_graduate_lands_on_the_bench(self) -> None:
        state = GameState()
        events = self._graduate_one(state, FakeAPI())
        self.assertTrue(any(e.startswith("graduated:") for e in events))
        self.assertEqual(state.party[0].base_id, 10)

    def test_a_full_bench_reports_rather_than_dropping_the_pokemon(self) -> None:
        state = GameState()
        for index in range(PARTY_BENCH_SIZE):
            state.party[index] = mon(index + 1)
        events = self._graduate_one(state, FakeAPI())
        self.assertTrue(any(e.startswith("party_full:") for e in events))
        # Still recorded in the Pokedex, so it can be benched later by hand.
        self.assertTrue(any(c.base_id == 10 for c in state.catches))

    def test_the_main_slot_reopens_as_an_egg_after_graduating(self) -> None:
        state = GameState()
        self._graduate_one(state, FakeAPI())
        self.assertIsNone(state.mon)
        self.assertEqual(state.egg_tier, None)


class BenchDoesNotGrowTests(unittest.TestCase):
    def test_only_the_main_pokemon_consumes_tokens(self) -> None:
        state = GameState()
        state.mon = mon(1)
        benched = mon(2, used=500)
        state.party[0] = benched
        before = benched.used_at_stage
        apply_usage(state, 10_000_000, FakeAPI())
        self.assertEqual(state.party[0].used_at_stage, before)
        self.assertGreater(state.mon.used_at_stage, 0)


class PartyPersistenceTests(unittest.TestCase):
    def test_bench_survives_a_save_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = store.load()
            state.mon = mon(1, stage=1, used=77)
            state.party[2] = mon(4, used=123)
            store.save(state)

            loaded = store.load()
            self.assertEqual(loaded.mon.base_id, 1)
            self.assertEqual(loaded.mon.used_at_stage, 77)
            self.assertEqual(loaded.party[2].base_id, 4)
            self.assertEqual(loaded.party[2].used_at_stage, 123)
            self.assertEqual(len(loaded.party), PARTY_BENCH_SIZE)

    def test_a_save_written_before_parties_existed_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            state = GameState()
            state.mon = mon(1)
            store.save(state)
            raw = json.loads(path.read_text(encoding="utf-8"))
            del raw["party"]
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = store.load()
            self.assertEqual(loaded.mon.base_id, 1)
            self.assertEqual(len(loaded.party), PARTY_BENCH_SIZE)
            self.assertTrue(all(slot is None for slot in loaded.party))

    def test_a_corrupt_bench_slot_degrades_without_losing_the_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            state = GameState()
            state.mon = mon(1)
            state.party[0] = mon(2)
            store.save(state)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["party"] = ["garbage", {"bad": "shape"}, None, 42, None]
            path.write_text(json.dumps(raw), encoding="utf-8")

            loaded = store.load()
            self.assertEqual(loaded.mon.base_id, 1)
            self.assertEqual(len(loaded.party), PARTY_BENCH_SIZE)
            self.assertTrue(all(slot is None for slot in loaded.party))

    def test_an_overlong_bench_on_disk_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            state = GameState()
            for index in range(PARTY_BENCH_SIZE):
                state.party[index] = mon(index + 1)
            store.save(state)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["party"] = raw["party"] * 4
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(len(store.load().party), PARTY_BENCH_SIZE)


if __name__ == "__main__":
    unittest.main()
