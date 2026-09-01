"""A trade can be paid with several Pokemon at once.

The reported problem was "why can't I trade in the trade shop". The board was
working exactly as written; the economy was the dead end.

Rarity is worth 1 / 3 / 8 / 25, and raising a Pokemon all the way only DOUBLES
it. So a Common tops out at 2.0 while the cheapest fully-grown Uncommon offer
asks 5.4. One Pokemon paid per trade meant no quantity of Commons could ever
buy an Uncommon - and the only other way to get one was to hatch it, at which
point the trade was pointless. The ladder had no bottom rung.

Value is additive now: three Commons buy that Uncommon.
"""
from __future__ import annotations

import unittest

from poketokenbar_windows.state import (
    CatchRecord,
    GameState,
    MonState,
    accept_trade,
    trade_candidates,
)
from poketokenbar_windows.trading import (
    RARITY_VALUE,
    TRADE_DISCOUNT,
    TradeOffer,
    bundle_value,
    tradeable_catches,
    trade_value,
    value_of,
)
from poketokenbar_windows.state import set_favourite

from test_trading import catch


def _uncommon_offer() -> TradeOffer:
    """The shape that was unreachable: a fully-grown Uncommon, asking 5.4."""
    return TradeOffer(28, "uncommon", [28], False, trade_value("uncommon", 1, 0) * TRADE_DISCOUNT)


class TheReportedDeadEndTests(unittest.TestCase):
    """Reconstructed from the actual save that prompted the report."""

    def _state(self) -> GameState:
        state = GameState()
        # Four fully-raised Commons, worth 2.0 each - exactly what was owned.
        state.catches = [
            catch(26, "common", [25, 26]),
            catch(85, "common", [84, 85]),
            catch(99, "common", [98, 99]),
            catch(78, "common", [77, 78]),
        ]
        state.trade_offers = [_uncommon_offer()]
        return state

    def test_one_common_still_cannot_buy_an_uncommon(self) -> None:
        state = self._state()
        self.assertLess(value_of(state.catches[0]), state.trade_offers[0].wants_value)
        ok, message = accept_trade(state, 0, 0)
        self.assertFalse(ok)
        self.assertIn("needs", message)

    def test_three_commons_together_buy_the_uncommon(self) -> None:
        """The fix, stated as the thing that was impossible before."""
        state = self._state()
        ok, message = accept_trade(state, 0, [0, 1, 2])
        self.assertTrue(ok, message)
        species = [c.species_id for c in state.catches]
        self.assertIn(28, species, "did not receive the offered Pokemon")
        self.assertEqual(len(state.catches), 2, "should have spent three, kept one")
        self.assertNotIn(26, species)
        self.assertNotIn(85, species)
        self.assertNotIn(99, species)
        self.assertIn(78, species, "the unspent Pokemon was taken too")

    def test_two_commons_are_still_not_enough(self) -> None:
        state = self._state()
        ok, message = accept_trade(state, 0, [0, 1])
        self.assertFalse(ok)
        # 2.0 + 2.0 = 4.0 against a 5.4 price. The message must name both, so
        # the player can see how much more to add.
        self.assertIn("4.0", message)
        self.assertIn("5.4", message)
        self.assertEqual(len(state.catches), 4, "a refused trade took Pokemon anyway")

    def test_the_wallet_is_never_touched(self) -> None:
        state = self._state()
        wallet = state.wallet
        accept_trade(state, 0, [0, 1, 2])
        self.assertEqual(state.wallet, wallet, "the Pokemon are the only price")


class RemovalTests(unittest.TestCase):
    """Removing several entries at once is where an index bug would hide."""

    def _state(self) -> GameState:
        state = GameState()
        # Fully raised (species_id is the LAST id in the path), so each is
        # worth 2.0 and three of them clear the 5.4 asking price.
        state.catches = [
            catch(2, "common", [1, 2]),
            catch(5, "common", [4, 5]),
            catch(8, "common", [7, 8]),
            catch(11, "common", [10, 11]),
        ]
        state.trade_offers = [_uncommon_offer()]
        return state

    def test_the_right_pokemon_are_removed_whatever_the_order(self) -> None:
        """Popping low-to-high would shift later indexes and take the wrong ones."""
        for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2], [2, 0, 1]):
            with self.subTest(order=order):
                state = self._state()
                ok, message = accept_trade(state, 0, list(order))
                self.assertTrue(ok, message)
                left = sorted(c.species_id for c in state.catches)
                self.assertEqual(
                    left, [11, 28],
                    f"picking {order} removed the wrong Pokemon",
                )

    def test_the_same_pokemon_cannot_pay_twice(self) -> None:
        """One Pokemon is worth 2.0 against a 5.4 price, so listing it three
        times must not be counted as 6.0."""
        state = self._state()
        ok, _message = accept_trade(state, 0, [0, 0, 0])
        self.assertFalse(ok, "one Pokemon paid for the whole trade three times")
        self.assertEqual(len(state.catches), 4)


class ProtectionsSurviveTests(unittest.TestCase):
    """Bundling must not become a way around the existing protections."""

    def _state(self) -> GameState:
        state = GameState()
        state.catches = [
            catch(26, "common", [25, 26]),
            catch(85, "common", [84, 85]),
            catch(99, "common", [98, 99]),
        ]
        state.trade_offers = [_uncommon_offer()]
        return state

    def test_a_favourite_cannot_be_smuggled_into_a_bundle(self) -> None:
        state = self._state()
        set_favourite(state, 1)
        ok, message = accept_trade(state, 0, [0, 1, 2])
        self.assertFalse(ok)
        self.assertIn("Favourites", message)
        self.assertEqual(len(state.catches), 3)

    def test_the_main_cannot_be_smuggled_into_a_bundle(self) -> None:
        state = self._state()
        # The main is matched on base_id + path + shiny, so the catch record
        # standing in for it has to carry the same base_id (25), not the
        # evolved species id the test helper would default to.
        state.catches[0] = CatchRecord(
            species_id=26,
            base_id=25,
            path_ids=[25, 26],
            rarity="common",
            is_shiny=False,
            nature="Hardy",
            caught_at="2026-09-01T00:00:00+00:00",
        )
        state.mon = MonState(25, [25, 26], 1, 0, "common", False, "Hardy")
        self.assertNotIn(
            0, tradeable_catches(state), "fixture is wrong: 0 is not the main"
        )
        ok, message = accept_trade(state, 0, [0, 1, 2])
        self.assertFalse(ok)
        self.assertIn("main", message.lower())
        self.assertEqual(len(state.catches), 3)

    def test_an_empty_selection_is_refused(self) -> None:
        state = self._state()
        ok, message = accept_trade(state, 0, [])
        self.assertFalse(ok)
        self.assertIn("at least one", message)

    def test_an_out_of_range_index_in_a_bundle_refuses_the_whole_trade(self) -> None:
        state = self._state()
        ok, _message = accept_trade(state, 0, [0, 1, 99])
        self.assertFalse(ok)
        self.assertEqual(len(state.catches), 3, "a partial bundle was spent")


class BundleValueTests(unittest.TestCase):
    def test_value_is_additive(self) -> None:
        records = [catch(26, "common", [25, 26]), catch(85, "common", [84, 85])]
        self.assertAlmostEqual(
            bundle_value(records), sum(value_of(r) for r in records)
        )

    def test_an_empty_bundle_is_worth_nothing(self) -> None:
        self.assertEqual(bundle_value([]), 0.0)

    def test_a_bundle_cannot_cheaply_reach_a_legendary(self) -> None:
        """Additive value must not make the top tier trivially farmable."""
        legendary = RARITY_VALUE["legendary"]
        fully_raised_common = RARITY_VALUE["common"] * 2
        needed = legendary * TRADE_DISCOUNT / fully_raised_common
        self.assertGreaterEqual(
            needed, 10,
            "a legendary should cost double figures in fully raised Commons",
        )


class SingleIndexStillWorksTests(unittest.TestCase):
    """A bare int has to keep working - plenty of callers still pass one."""

    def test_a_bare_int_is_treated_as_a_bundle_of_one(self) -> None:
        state = GameState()
        state.catches = [catch(7, "rare", [7, 8])]
        state.trade_offers = [
            TradeOffer(10, "rare", [10, 11], False,
                       trade_value("rare", 2, 0) * TRADE_DISCOUNT)
        ]
        ok, message = accept_trade(state, 0, 0)
        self.assertTrue(ok, message)
        self.assertIn(10, [c.species_id for c in state.catches])


if __name__ == "__main__":
    unittest.main()
