from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import poketokenbar_windows.limits as limits_module
from poketokenbar_windows.models import LimitWindow, ProviderLimits
from poketokenbar_windows.pokemon import EGG_HATCH_THRESHOLD, HatchResult, phase_threshold
from poketokenbar_windows.state import (
    GameState,
    StateStore,
    apply_usage,
    companion_progress_percent,
    confirm_evolution,
    evolution_target,
)


class FakeAPI:
    """A three-stage line, so there is something to evolve into."""

    def hatch(self, minimum_rarity=None, shiny_charm=False, generation=None):
        return HatchResult(1, [1, 2, 3], "common", "Hardy", False, 200)


class GatedEvolutionTests(unittest.TestCase):
    def _to_the_brink(self, extra: int = 0) -> GameState:
        state = GameState()
        apply_usage(state, EGG_HATCH_THRESHOLD, FakeAPI())
        apply_usage(state, phase_threshold("common", 3, 0) + extra, FakeAPI())
        return state

    def test_it_waits_instead_of_evolving_behind_your_back(self) -> None:
        state = self._to_the_brink()
        self.assertTrue(state.pending_evolution)
        self.assertEqual(state.mon.current_id, 1, "it evolved without being asked")
        self.assertEqual(evolution_target(state), 2)

    def test_the_ready_event_is_announced_once(self) -> None:
        state = GameState()
        apply_usage(state, EGG_HATCH_THRESHOLD, FakeAPI())
        events = apply_usage(state, phase_threshold("common", 3, 0), FakeAPI())
        self.assertIn("evolution_ready:2", events)
        again = apply_usage(state, 5_000, FakeAPI())
        self.assertNotIn("evolution_ready:2", again, "re-announced on every refresh")

    def test_a_waiting_companion_shows_a_full_bar(self) -> None:
        self.assertEqual(companion_progress_percent(self._to_the_brink()), 100)

    def test_tokens_earned_while_waiting_are_banked_not_burned(self) -> None:
        state = self._to_the_brink(extra=250_000)
        self.assertEqual(state.banked_tokens, 250_000)
        confirm_evolution(state, FakeAPI())
        self.assertEqual(state.banked_tokens, 0)
        self.assertEqual(
            state.mon.used_at_stage, 250_000,
            "banked tokens should carry into the new stage",
        )

    def test_waiting_a_long_time_never_costs_progress(self) -> None:
        """Enough banked to clear the next stage entirely."""
        state = self._to_the_brink(extra=phase_threshold("common", 3, 1))
        confirm_evolution(state, FakeAPI())
        # The banked tokens fill stage two, so it is immediately ready again.
        self.assertTrue(state.pending_evolution)
        self.assertEqual(state.mon.current_id, 2)

    def test_confirming_advances_exactly_one_stage(self) -> None:
        state = self._to_the_brink()
        events = confirm_evolution(state, FakeAPI())
        self.assertEqual(events, ["evolved:2"])
        self.assertEqual(state.mon.current_id, 2)
        self.assertFalse(state.pending_evolution)

    def test_confirming_when_nothing_is_pending_does_nothing(self) -> None:
        state = GameState()
        self.assertEqual(confirm_evolution(state, FakeAPI()), [])

    def test_the_pokedex_entry_follows_the_evolution(self) -> None:
        state = self._to_the_brink()
        confirm_evolution(state, FakeAPI())
        self.assertEqual(state.catches[-1].species_id, 2)

    def test_the_pending_flag_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = self._to_the_brink(extra=999)
            store.save(state)
            loaded = store.load()
            self.assertTrue(loaded.pending_evolution)
            self.assertEqual(loaded.banked_tokens, 999)

    def test_a_final_form_still_graduates_without_asking(self) -> None:
        """Only evolutions wait - finishing a line is not something to click."""
        class SingleStage:
            def hatch(self, minimum_rarity=None, shiny_charm=False, generation=None):
                return HatchResult(10, [10], "common", "Hardy", False, 200)

        state = GameState()
        events = apply_usage(state, EGG_HATCH_THRESHOLD + 750_000_000, SingleStage())
        self.assertTrue(any(e.startswith("graduated:") for e in events))
        self.assertFalse(state.pending_evolution)


class ClaudeBlockResetTests(unittest.TestCase):
    """The 5-hour reset is derived from transcripts when the API omits it."""

    def _transcript(self, root: Path, stamps: list[datetime]) -> None:
        path = root / "session.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for stamp in stamps:
                handle.write(json.dumps({
                    "timestamp": stamp.isoformat(),
                    "message": {
                        "model": "claude-opus-5",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                    "requestId": f"r{stamp.timestamp()}",
                }) + "\n")

    def _reset_for(self, stamps, now):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._transcript(root, stamps)
            with patch.object(limits_module, "claude_roots", lambda: [root]):
                return limits_module.claude_block_reset(now)

    def test_the_block_starts_at_the_first_message_after_a_long_gap(self) -> None:
        now = datetime.now().astimezone()
        stamps = [
            now - timedelta(hours=20),
            now - timedelta(hours=19),
            now - timedelta(hours=2),   # new block starts here
            now - timedelta(minutes=30),
        ]
        reset = self._reset_for(stamps, now)
        self.assertIsNotNone(reset)
        expected = (now - timedelta(hours=2)) + timedelta(hours=5)
        self.assertAlmostEqual(reset.timestamp(), expected.timestamp(), delta=2)

    def test_a_lapsed_block_reports_nothing_rather_than_a_past_time(self) -> None:
        now = datetime.now().astimezone()
        stamps = [now - timedelta(hours=9), now - timedelta(hours=8)]
        self.assertIsNone(self._reset_for(stamps, now))

    def test_no_recent_activity_reports_nothing(self) -> None:
        now = datetime.now().astimezone()
        self.assertIsNone(self._reset_for([], now))

    def test_continuous_activity_keeps_the_original_block_start(self) -> None:
        now = datetime.now().astimezone()
        stamps = [now - timedelta(hours=4, minutes=30 - m * 10) for m in range(6)]
        reset = self._reset_for(stamps, now)
        self.assertIsNotNone(reset)
        self.assertLess(reset - now, timedelta(hours=1))


class FillMissingResetTests(unittest.TestCase):
    def test_a_derived_reset_is_flagged_as_an_estimate(self) -> None:
        derived = datetime.now().astimezone() + timedelta(hours=3)
        limits = ProviderLimits(
            provider="claude",
            windows=[LimitWindow("5-hour", 50.0), LimitWindow("Weekly", 20.0)],
        )
        with patch.object(limits_module, "claude_block_reset", lambda: derived):
            filled = limits_module._fill_missing_reset(limits)
        five, weekly = filled.windows
        self.assertEqual(five.resets_at, derived)
        self.assertTrue(five.estimated_reset)
        self.assertIsNone(weekly.resets_at, "weekly must not be guessed at")
        self.assertFalse(weekly.estimated_reset)

    def test_a_reported_reset_is_never_overwritten(self) -> None:
        real = datetime.now().astimezone() + timedelta(hours=1)
        limits = ProviderLimits(
            provider="claude", windows=[LimitWindow("5-hour", 50.0, resets_at=real)]
        )
        with patch.object(limits_module, "claude_block_reset", lambda: datetime.now().astimezone()):
            filled = limits_module._fill_missing_reset(limits)
        self.assertEqual(filled.windows[0].resets_at, real)
        self.assertFalse(filled.windows[0].estimated_reset)

    def test_nothing_derivable_leaves_the_window_untouched(self) -> None:
        limits = ProviderLimits(provider="claude", windows=[LimitWindow("5-hour", 50.0)])
        with patch.object(limits_module, "claude_block_reset", lambda: None):
            filled = limits_module._fill_missing_reset(limits)
        self.assertIsNone(filled.windows[0].resets_at)
        self.assertFalse(filled.windows[0].estimated_reset)


if __name__ == "__main__":
    unittest.main()
