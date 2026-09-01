"""Trading must be a fair swap, priced in Pokemon rather than tokens."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poketokenbar_windows.pokemon import HatchResult, trade_reroll_price
from poketokenbar_windows.state import (
    CatchRecord,
    GameState,
    MonState,
    StateStore,
    accept_trade,
    can_reroll_trades,
    favourite_catches,
    refresh_trades,
    reroll_trades,
    set_favourite,
    trade_candidates,
)
from poketokenbar_windows.trading import (
    TRADE_DISCOUNT,
    TradeOffer,
    describe_value,
    eligible_catches,
    generate_offers,
    load_offers,
    offer_to_dict,
    trade_value,
    value_of,
)


class FakeAPI:
    """Deterministic species: id mod 4 picks the rarity tier."""

    TIERS = ("common", "uncommon", "rare", "legendary")

    def hatch_species(self, species_id: int, shiny_charm: bool = False):
        rarity = self.TIERS[species_id % 4]
        path = [species_id, species_id + 500] if rarity != "legendary" else [species_id]
        return HatchResult(species_id, path, rarity, "Hardy", False, 100)


def catch(species, rarity="common", path=None, shiny=False, fav=False) -> CatchRecord:
    return CatchRecord(
        species_id=species,
        base_id=species,
        path_ids=path or [species],
        rarity=rarity,
        is_shiny=shiny,
        nature="Hardy",
        caught_at="2026-09-01T00:00:00+00:00",
        is_favourite=fav,
    )


class TradeValueTests(unittest.TestCase):
    def test_rarity_dominates_value(self) -> None:
        self.assertGreater(trade_value("legendary"), trade_value("rare"))
        self.assertGreater(trade_value("rare"), trade_value("uncommon"))
        self.assertGreater(trade_value("uncommon"), trade_value("common"))

    def test_raising_a_pokemon_doubles_what_it_is_worth(self) -> None:
        fresh = trade_value("rare", 3, 0)
        raised = trade_value("rare", 3, 2)
        self.assertAlmostEqual(raised, fresh * 2, places=5)

    def test_shiny_is_worth_substantially_more(self) -> None:
        self.assertGreater(trade_value("common", 1, 0, True), trade_value("common", 1, 0))

    def test_a_fresh_pidgey_cannot_buy_a_mewtwo(self) -> None:
        """The whole point: value must be matched."""
        pidgey = catch(16, "common", [16, 17, 18])
        mewtwo_offer = TradeOffer(
            150, "legendary", [150], False,
            trade_value("legendary", 1, 0) * TRADE_DISCOUNT,
        )
        self.assertFalse(mewtwo_offer.accepts(pidgey))

    def test_a_like_for_like_swap_is_accepted(self) -> None:
        offer = TradeOffer(
            58, "uncommon", [58, 59], False,
            trade_value("uncommon", 2, 0) * TRADE_DISCOUNT,
        )
        self.assertTrue(offer.accepts(catch(1, "uncommon", [1, 2])))

    def test_an_unknown_rarity_is_treated_as_the_cheapest(self) -> None:
        self.assertEqual(trade_value("mythicalish"), trade_value("common"))

    def test_the_ask_is_described_in_plain_words(self) -> None:
        self.assertIn("Rare", describe_value(trade_value("rare", 1, 0)))
        self.assertEqual(describe_value(0.1), "almost anything")


class EligibilityTests(unittest.TestCase):
    def _state(self) -> GameState:
        state = GameState()
        state.catches = [
            catch(1, "common", [1, 2]),
            catch(4, "rare", [4, 5], fav=True),
            catch(7, "rare", [7, 8]),
        ]
        return state

    def _rare_offer(self) -> TradeOffer:
        return TradeOffer(
            10, "rare", [10, 11], False, trade_value("rare", 2, 0) * TRADE_DISCOUNT
        )

    def test_only_valuable_enough_pokemon_qualify(self) -> None:
        state = self._state()
        self.assertNotIn(0, eligible_catches(state, self._rare_offer()))

    def test_a_favourite_is_never_eligible(self) -> None:
        state = self._state()
        self.assertNotIn(1, eligible_catches(state, self._rare_offer()))

    def test_the_pokemon_being_raised_is_never_eligible(self) -> None:
        state = self._state()
        state.mon = MonState(7, [7, 8], 0, 0, "rare", False, "Hardy")
        self.assertNotIn(2, eligible_catches(state, self._rare_offer()))

    def test_an_ordinary_match_does_qualify(self) -> None:
        self.assertIn(2, eligible_catches(self._state(), self._rare_offer()))


class FavouriteTests(unittest.TestCase):
    def test_starring_and_unstarring(self) -> None:
        state = GameState()
        state.catches = [catch(1), catch(4)]
        self.assertTrue(set_favourite(state, 1))
        self.assertEqual(favourite_catches(state), [1])
        self.assertTrue(set_favourite(state, 1, False))
        self.assertEqual(favourite_catches(state), [])

    def test_an_invalid_index_is_refused(self) -> None:
        self.assertFalse(set_favourite(GameState(), 5))

    def test_a_favourite_survives_a_save_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = store.load()
            state.catches = [catch(1)]
            set_favourite(state, 0)
            store.save(state)
            self.assertTrue(store.load().catches[0].is_favourite)


class OfferGenerationTests(unittest.TestCase):
    def test_the_same_seed_gives_the_same_offers(self) -> None:
        a = generate_offers(FakeAPI(), 3, seed="window-1")
        b = generate_offers(FakeAPI(), 3, seed="window-1")
        self.assertEqual([offer_to_dict(o) for o in a], [offer_to_dict(o) for o in b])

    def test_a_different_window_gives_different_offers(self) -> None:
        a = generate_offers(FakeAPI(), 3, seed="window-1")
        b = generate_offers(FakeAPI(), 3, seed="window-2")
        self.assertNotEqual([offer_to_dict(o) for o in a], [offer_to_dict(o) for o in b])

    def test_legendaries_are_never_offered(self) -> None:
        offers = generate_offers(FakeAPI(), 8, seed="many")
        self.assertTrue(all(o.gives_rarity != "legendary" for o in offers))

    def test_offers_respect_the_generation_cap(self) -> None:
        offers = generate_offers(FakeAPI(), 5, generation_filter=1, seed="gen1")
        self.assertTrue(all(1 <= o.gives_id <= 151 for o in offers))

    def test_every_offer_asks_for_less_than_it_gives(self) -> None:
        for offer in generate_offers(FakeAPI(), 6, seed="fair"):
            self.assertLess(offer.wants_value, offer.gives_value)


class OfferPersistenceTests(unittest.TestCase):
    def test_offers_round_trip_through_a_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = store.load()
            refresh_trades(state, FakeAPI(), "block-1")
            before = [offer_to_dict(o) for o in state.trade_offers]
            store.save(state)
            loaded = store.load()
            self.assertEqual([offer_to_dict(o) for o in loaded.trade_offers], before)
            self.assertEqual(loaded.trades_window, "block-1")

    def test_corrupt_offers_degrade_to_none_without_losing_the_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            state = store.load()
            state.catches = [catch(1)]
            refresh_trades(state, FakeAPI(), "block-1")
            store.save(state)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["trade_offers"] = ["junk", {"gives_id": "x"}, 7]
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded = store.load()
            self.assertEqual(loaded.trade_offers, [])
            self.assertEqual(len(loaded.catches), 1)

    def test_load_offers_ignores_a_non_list(self) -> None:
        self.assertEqual(load_offers("nope"), [])


class RefreshTests(unittest.TestCase):
    def test_offers_hold_until_the_window_rolls(self) -> None:
        state = GameState()
        self.assertTrue(refresh_trades(state, FakeAPI(), "block-1"))
        first = [offer_to_dict(o) for o in state.trade_offers]
        self.assertFalse(refresh_trades(state, FakeAPI(), "block-1"))
        self.assertEqual([offer_to_dict(o) for o in state.trade_offers], first)

    def test_a_new_window_brings_new_offers(self) -> None:
        state = GameState()
        refresh_trades(state, FakeAPI(), "block-1")
        first = [offer_to_dict(o) for o in state.trade_offers]
        self.assertTrue(refresh_trades(state, FakeAPI(), "block-2"))
        self.assertNotEqual([offer_to_dict(o) for o in state.trade_offers], first)

    def test_a_new_window_restores_the_reroll(self) -> None:
        state = GameState()
        refresh_trades(state, FakeAPI(), "block-1")
        state.trades_rerolled = True
        refresh_trades(state, FakeAPI(), "block-2")
        self.assertFalse(state.trades_rerolled)


class RerollTests(unittest.TestCase):
    def _funded(self) -> GameState:
        state = GameState()
        state.used_since_install = trade_reroll_price() * 4
        refresh_trades(state, FakeAPI(), "block-1")
        return state

    def test_one_reroll_costs_tokens_and_replaces_the_offers(self) -> None:
        state = self._funded()
        before = [offer_to_dict(o) for o in state.trade_offers]
        wallet = state.wallet
        ok, _msg = reroll_trades(state, FakeAPI(), "block-1")
        self.assertTrue(ok)
        self.assertEqual(state.wallet, wallet - trade_reroll_price())
        self.assertNotEqual([offer_to_dict(o) for o in state.trade_offers], before)

    def test_only_one_reroll_per_window(self) -> None:
        state = self._funded()
        self.assertTrue(reroll_trades(state, FakeAPI(), "block-1")[0])
        ok, message = reroll_trades(state, FakeAPI(), "block-1")
        self.assertFalse(ok)
        self.assertIn("Already rerolled", message)

    def test_a_reroll_is_refused_when_it_cannot_be_afforded(self) -> None:
        state = GameState()
        refresh_trades(state, FakeAPI(), "block-1")
        ok, message = reroll_trades(state, FakeAPI(), "block-1")
        self.assertFalse(ok)
        self.assertIn("Costs", message)

    def test_a_failed_reroll_charges_nothing(self) -> None:
        state = GameState()
        refresh_trades(state, FakeAPI(), "block-1")
        reroll_trades(state, FakeAPI(), "block-1")
        self.assertEqual(state.spent_tokens, 0)
        self.assertFalse(state.trades_rerolled)

    def test_availability_is_reported_before_trying(self) -> None:
        state = self._funded()
        self.assertTrue(can_reroll_trades(state)[0])
        reroll_trades(state, FakeAPI(), "block-1")
        self.assertFalse(can_reroll_trades(state)[0])


class AcceptTradeTests(unittest.TestCase):
    def _state(self) -> GameState:
        state = GameState()
        state.catches = [catch(1, "common", [1, 2]), catch(7, "rare", [7, 8])]
        state.trade_offers = [
            TradeOffer(10, "rare", [10, 11], False,
                       trade_value("rare", 2, 0) * TRADE_DISCOUNT)
        ]
        return state

    def test_a_fair_trade_swaps_the_pokemon(self) -> None:
        state = self._state()
        wallet = state.wallet
        ok, _msg = accept_trade(state, 0, 1)
        self.assertTrue(ok)
        species = [c.species_id for c in state.catches]
        self.assertIn(10, species, "did not receive the offered Pokemon")
        self.assertNotIn(7, species, "did not give up the traded Pokemon")
        self.assertEqual(state.wallet, wallet, "the Pokemon is the only price")

    def test_an_unfair_trade_is_refused(self) -> None:
        state = self._state()
        ok, message = accept_trade(state, 0, 0)
        self.assertFalse(ok)
        self.assertIn("needed", message)
        self.assertEqual(len(state.catches), 2)

    def test_a_favourite_cannot_be_traded_away(self) -> None:
        state = self._state()
        set_favourite(state, 1)
        ok, message = accept_trade(state, 0, 1)
        self.assertFalse(ok)
        self.assertIn("Favourites", message)
        self.assertEqual(len(state.catches), 2)

    def test_an_accepted_offer_is_removed(self) -> None:
        state = self._state()
        accept_trade(state, 0, 1)
        self.assertEqual(state.trade_offers, [])

    def test_invalid_indexes_are_refused(self) -> None:
        state = self._state()
        self.assertFalse(accept_trade(state, 9, 0)[0])
        self.assertFalse(accept_trade(state, 0, 9)[0])

    def test_candidates_match_what_accept_will_allow(self) -> None:
        state = self._state()
        self.assertEqual(trade_candidates(state, 0), [1])



class OffersSurviveAFailedRefreshTests(unittest.TestCase):
    """A failed generation must never wipe the board.

    Reported: trades showed up, then vanished after every restart. The refresh
    on launch regenerated offers, PokeAPI was not reachable yet, and the empty
    result was saved over the good ones.
    """

    class DeadAPI:
        def hatch_species(self, species_id, shiny_charm=False):
            raise OSError("network unavailable")

    def _stocked(self) -> GameState:
        state = GameState()
        refresh_trades(state, FakeAPI(), "window-1")
        self.assertEqual(len(state.trade_offers), 3)
        return state

    def test_a_failed_generation_keeps_the_existing_offers(self) -> None:
        state = self._stocked()
        before = [offer_to_dict(o) for o in state.trade_offers]
        refresh_trades(state, self.DeadAPI(), "window-2")
        self.assertEqual([offer_to_dict(o) for o in state.trade_offers], before)

    def test_a_failed_generation_reports_no_change(self) -> None:
        state = self._stocked()
        self.assertFalse(refresh_trades(state, self.DeadAPI(), "window-2"))

    def test_the_window_is_not_advanced_so_it_retries(self) -> None:
        state = self._stocked()
        refresh_trades(state, self.DeadAPI(), "window-2")
        self.assertEqual(state.trades_window, "window-1")
        # The retry on the next refresh succeeds and does move the window.
        self.assertTrue(refresh_trades(state, FakeAPI(), "window-2"))
        self.assertEqual(state.trades_window, "window-2")

    def test_an_empty_board_can_still_be_filled_when_the_api_works(self) -> None:
        state = GameState()
        refresh_trades(state, self.DeadAPI(), "window-1")
        self.assertEqual(state.trade_offers, [])
        self.assertTrue(refresh_trades(state, FakeAPI(), "window-1"))
        self.assertEqual(len(state.trade_offers), 3)

    def test_a_failed_reroll_does_not_consume_the_reroll(self) -> None:
        state = self._stocked()
        state.used_since_install = trade_reroll_price() * 4
        before = [offer_to_dict(o) for o in state.trade_offers]
        reroll_trades(state, self.DeadAPI(), "window-1")
        self.assertEqual([offer_to_dict(o) for o in state.trade_offers], before)

if __name__ == "__main__":
    unittest.main()
