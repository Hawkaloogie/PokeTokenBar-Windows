from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poketokenbar_windows.pokemon import (
    DEFAULT_PACE,
    EGG_HATCH_THRESHOLD,
    GENERATIONS,
    GRADUATION_TOTALS,
    PACE_DIVISORS,
    STARTERS,
    egg_hatch_threshold,
    egg_price,
    generation_bounds,
    generation_cap_label,
    graduation_total,
    item_price,
    normalize_pace,
    phase_threshold,
    rare_candy_xp,
    starters_for,
    starters_of_generation,
)
from poketokenbar_windows.state import (
    GameState,
    MonState,
    StateStore,
    apply_usage,
    buy_item,
    set_pace,
)


class GenerationCapTests(unittest.TestCase):
    def test_a_cap_includes_every_earlier_generation(self) -> None:
        self.assertEqual(generation_bounds(3), (1, 386))
        self.assertEqual(generation_bounds(1), (1, 151))
        self.assertEqual(generation_bounds(5), (1, 649))

    def test_labels_say_cap_not_exact_generation(self) -> None:
        self.assertEqual(generation_cap_label(1), "Gen 1 only (Kanto)")
        self.assertEqual(generation_cap_label(3), "Up to Gen 3 (Kanto-Hoenn)")
        self.assertEqual(generation_cap_label(None), "All generations (1-5)")

    def test_starters_follow_the_cap(self) -> None:
        self.assertEqual(starters_for(1), STARTERS[1])
        self.assertEqual(starters_for(2), STARTERS[1] + STARTERS[2])
        self.assertEqual(len(starters_for(None)), sum(len(v) for v in STARTERS.values()))

    def test_one_generations_starters_can_still_be_isolated(self) -> None:
        self.assertEqual(starters_of_generation(3), [252, 255, 258])

    def test_pikachu_is_a_gen_one_starter(self) -> None:
        self.assertIn(25, STARTERS[1])
        self.assertIn(25, starters_for(1))
        self.assertIn(25, starters_for(None))


class PaceScalingTests(unittest.TestCase):
    """Every token-denominated value must scale together, with no stragglers."""

    ECONOMY = {
        "egg_hatch": lambda p: egg_hatch_threshold(p),
        "grad_common": lambda p: graduation_total("common", p),
        "grad_legendary": lambda p: graduation_total("legendary", p),
        "candy_xp": lambda p: rare_candy_xp(p),
        "candy_price": lambda p: item_price("rare_candy", p),
        "mint_price": lambda p: item_price("mint", p),
        "charm_price": lambda p: item_price("shiny_charm", p),
        "egg_price": lambda p: egg_price(None, p),
        "rare_egg_price": lambda p: egg_price("rare", p),
        "phase": lambda p: phase_threshold("common", 1, 0, p),
    }

    def test_every_value_scales_by_the_same_divisor(self) -> None:
        for pace, divisor in PACE_DIVISORS.items():
            for name, fn in self.ECONOMY.items():
                expected = max(1, round(fn(DEFAULT_PACE) / divisor))
                self.assertEqual(
                    fn(pace), expected,
                    f"{name} did not scale with pace {pace!r} - a dependent was missed",
                )

    def test_nothing_in_the_economy_is_left_at_standard(self) -> None:
        """A straggler would show up as a value identical across paces."""
        for name, fn in self.ECONOMY.items():
            self.assertGreater(
                fn(DEFAULT_PACE), fn("casual"),
                f"{name} is the same at casual and standard - it is not scaled",
            )

    def test_ordering_is_preserved_at_every_pace(self) -> None:
        for pace in PACE_DIVISORS:
            self.assertGreater(graduation_total("legendary", pace), graduation_total("common", pace))
            self.assertGreater(egg_price("rare", pace), egg_price(None, pace))

    def test_values_never_collapse_to_zero(self) -> None:
        for pace in PACE_DIVISORS:
            for name, fn in self.ECONOMY.items():
                self.assertGreaterEqual(fn(pace), 1, f"{name} hit zero at {pace}")

    def test_defaults_are_unchanged_for_existing_players(self) -> None:
        self.assertEqual(egg_hatch_threshold(), EGG_HATCH_THRESHOLD)
        self.assertEqual(graduation_total("common"), GRADUATION_TOTALS["common"])


class NormalizePaceTests(unittest.TestCase):
    def test_junk_falls_back_to_standard(self) -> None:
        for value in (None, "", "turbo", 3, [], {}, True):
            self.assertEqual(normalize_pace(value), DEFAULT_PACE)

    def test_known_paces_survive(self) -> None:
        for pace in PACE_DIVISORS:
            self.assertEqual(normalize_pace(pace), pace)


class PaceInPlayTests(unittest.TestCase):
    class FakeAPI:
        def hatch(self, minimum_rarity=None, shiny_charm=False, generation=None):
            from poketokenbar_windows.pokemon import HatchResult
            return HatchResult(10, [10], "common", "Hardy", False, 200)

    def test_a_casual_player_hatches_far_sooner(self) -> None:
        casual = GameState(); set_pace(casual, "casual")
        standard = GameState()
        tokens = egg_hatch_threshold("casual")
        apply_usage(casual, tokens, self.FakeAPI())
        apply_usage(standard, tokens, self.FakeAPI())
        self.assertIsNotNone(casual.mon, "casual player should have hatched")
        self.assertIsNone(standard.mon, "standard player should still be on the egg")

    def test_shop_prices_follow_the_state_pace(self) -> None:
        state = GameState()
        set_pace(state, "casual")
        state.used_since_install = item_price("mint", "casual")
        ok, _msg = buy_item(state, "mint")
        self.assertTrue(ok, "a casual-priced Mint should be affordable")

    def test_the_same_wallet_cannot_buy_at_standard_pace(self) -> None:
        state = GameState()
        state.used_since_install = item_price("mint", "casual")
        ok, _msg = buy_item(state, "mint")
        self.assertFalse(ok)

    def test_pace_survives_a_save_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = store.load()
            set_pace(state, "light")
            store.save(state)
            self.assertEqual(store.load().pace, "light")

    def test_a_corrupt_pace_on_disk_degrades_to_standard(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            store.save(GameState())
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["pace"] = "hyperspeed"
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(store.load().pace, DEFAULT_PACE)

    def test_changing_pace_never_discards_earned_progress(self) -> None:
        state = GameState()
        state.mon = MonState(
            base_id=1, path_ids=[1], stage_index=0, used_at_stage=40_000_000,
            rarity="common", is_shiny=False, nature="Hardy",
        )
        set_pace(state, "casual")
        self.assertEqual(state.mon.used_at_stage, 40_000_000)



class PaceDowngradeRuleTests(unittest.TestCase):
    """Easing the pace costs a reset; raising difficulty is always free."""

    def test_every_easier_move_is_a_downgrade(self) -> None:
        from poketokenbar_windows.pokemon import is_pace_downgrade

        for current, target in (
            ("standard", "light"),
            ("standard", "casual"),
            ("light", "casual"),
        ):
            self.assertTrue(is_pace_downgrade(current, target), f"{current}->{target}")

    def test_every_harder_move_is_free(self) -> None:
        from poketokenbar_windows.pokemon import is_pace_downgrade

        for current, target in (
            ("casual", "light"),
            ("casual", "standard"),
            ("light", "standard"),
        ):
            self.assertFalse(is_pace_downgrade(current, target), f"{current}->{target}")

    def test_staying_put_is_not_a_downgrade(self) -> None:
        from poketokenbar_windows.pokemon import is_pace_downgrade

        for pace in PACE_DIVISORS:
            self.assertFalse(is_pace_downgrade(pace, pace))

    def test_difficulty_order_matches_the_divisors(self) -> None:
        """Harder must always mean more expensive, or the rule is backwards."""
        from poketokenbar_windows.pokemon import PACE_DIFFICULTY

        ordered = sorted(PACE_DIFFICULTY, key=lambda p: PACE_DIFFICULTY[p])
        costs = [egg_hatch_threshold(p) for p in ordered]
        self.assertEqual(costs, sorted(costs), "difficulty order contradicts cost order")

    def test_junk_paces_do_not_read_as_a_downgrade(self) -> None:
        from poketokenbar_windows.pokemon import is_pace_downgrade

        self.assertFalse(is_pace_downgrade("nonsense", "alsononsense"))

if __name__ == "__main__":
    unittest.main()
