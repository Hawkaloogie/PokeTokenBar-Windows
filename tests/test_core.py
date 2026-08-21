from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
import base64

from poketokenbar_windows.formatting import compact_tokens
from poketokenbar_windows.models import LimitWindow, ProviderLimits
from poketokenbar_windows.pokemon import (
    EGG_HATCH_THRESHOLD,
    GRADUATION_TOTALS,
    HatchResult,
    egg_price,
    phase_threshold,
    rarity_from,
)
from poketokenbar_windows.state import GameState, StateStore, apply_limit_rewards, apply_usage, buy_egg, usage_delta
from poketokenbar_windows.usage import parse_claude_object, parse_codex_object
from poketokenbar_windows.cursor import (
    cache_account_identifier,
    has_next_page,
    parse_cursor_bubble,
    parse_usage_event,
    workos_session_cookie,
)
from poketokenbar_windows.windows import cache_dir, cursor_database_candidates, kiro_database_candidates, state_dir


class FakeAPI:
    def hatch(self, minimum_rarity=None, shiny_charm=False):
        return HatchResult(
            base_id=1,
            path_ids=[1, 2, 3],
            rarity="common",
            nature="Hardy",
            is_shiny=False,
            capture_rate=45,
        )


class BalanceTests(unittest.TestCase):
    def test_phase_thresholds_sum_to_graduation_total(self):
        for rarity, total in GRADUATION_TOTALS.items():
            for forms in (1, 2, 3):
                self.assertAlmostEqual(
                    sum(phase_threshold(rarity, forms, index) for index in range(forms)),
                    total,
                    delta=forms,
                )

    def test_rarity_boundaries(self):
        self.assertEqual(rarity_from(255, False, False), "common")
        self.assertEqual(rarity_from(120, False, False), "uncommon")
        self.assertEqual(rarity_from(45, False, False), "rare")
        self.assertEqual(rarity_from(3, True, False), "legendary")

    def test_egg_prices(self):
        self.assertEqual(egg_price(None), 1_000_000_000)
        self.assertEqual(egg_price("uncommon"), 2_500_000_000)
        self.assertEqual(egg_price("rare"), 4_000_000_000)


class UsageParserTests(unittest.TestCase):
    def test_claude(self):
        entry = parse_claude_object({
            "type": "assistant",
            "timestamp": "2026-08-21T10:00:00Z",
            "requestId": "r1",
            "message": {
                "id": "m1",
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                },
            },
        })
        self.assertIsNotNone(entry)
        self.assertEqual(entry.total_tokens, 200)
        self.assertEqual(entry.id, "claude|m1|r1")

    def test_codex_last_usage(self):
        entry = parse_codex_object({
            "timestamp": "2026-08-21T10:00:00Z",
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 200}},
            },
        }, file_id="rollout.jsonl", turn=0, model="gpt-5.5")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.input_tokens, 600)
        self.assertEqual(entry.cache_read_tokens, 400)
        self.assertEqual(entry.total_tokens, 1200)


class CursorUsageTests(unittest.TestCase):
    def test_zero_bubble_tokens_are_ignored(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        entry = parse_cursor_bubble(
            {
                "tokenCount": {"inputTokens": 0, "outputTokens": 0},
                "createdAt": "2026-08-18T13:00:00.000Z",
                "modelType": "gpt-4o",
            },
            key="bubbleId:tab:zero",
            since=since,
        )
        self.assertIsNone(entry)

    def test_dashboard_event_includes_cache_tokens(self):
        since = datetime(2025, 1, 1, tzinfo=timezone.utc)
        entry = parse_usage_event(
            {
                "timestamp": "1750979225854",
                "model": "claude-opus-5-thinking-high",
                "tokenUsage": {
                    "inputTokens": 126,
                    "outputTokens": 450,
                    "cacheWriteTokens": 6112,
                    "cacheReadTokens": 11964,
                },
            },
            row_index=0,
            since=since,
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.input_tokens, 126)
        self.assertEqual(entry.output_tokens, 450)
        self.assertEqual(entry.cache_write_tokens, 6112)
        self.assertEqual(entry.cache_read_tokens, 11964)
        self.assertTrue(entry.id.startswith("cursor|api|"))

    def test_workos_cookie_and_account_id(self):
        payload = base64.urlsafe_b64encode(b'{"sub":"user_01TEST"}').decode("ascii").rstrip("=")
        jwt = f"hdr.{payload}.sig"
        self.assertEqual(workos_session_cookie(jwt), f"user_01TEST::{jwt}")
        self.assertEqual(cache_account_identifier(jwt), "subject:user_01TEST")
        self.assertEqual(cache_account_identifier(f"user_01TEST::{jwt}"), "subject:user_01TEST")

    def test_has_next_page_uses_total_count(self):
        self.assertTrue(has_next_page(None, total_count=239, page=1, event_count=100))
        self.assertFalse(has_next_page(None, total_count=239, page=3, event_count=39))


class StateTests(unittest.TestCase):
    def test_usage_delta_seeds_install_baseline_and_resets_daily(self):
        state = GameState()
        self.assertEqual(usage_delta(state, 10, date(2026, 8, 21)), 0)
        self.assertTrue(state.install_baseline_set)
        self.assertEqual(usage_delta(state, 15, date(2026, 8, 21)), 5)
        self.assertEqual(usage_delta(state, 3, date(2026, 8, 22)), 3)
        self.assertEqual(state.used_since_install, 8)

    def test_new_provider_is_seeded_without_retroactive_credit(self):
        state = GameState()
        self.assertEqual(usage_delta(state, {"claude": 100}, date(2026, 8, 21)), 0)
        self.assertEqual(usage_delta(state, {"claude": 110, "codex": 500}, date(2026, 8, 21)), 10)
        self.assertEqual(usage_delta(state, {"claude": 120, "codex": 520}, date(2026, 8, 21)), 30)

    def test_hatch_and_evolve(self):
        state = GameState()
        events = apply_usage(state, EGG_HATCH_THRESHOLD, FakeAPI())
        self.assertEqual(events, ["hatched:1"])
        self.assertIsNotNone(state.mon)
        first = phase_threshold("common", 3, 0)
        events = apply_usage(state, first, FakeAPI())
        self.assertEqual(events, ["evolved:2"])
        self.assertEqual(state.mon.current_id, 2)

    def test_limit_candy_is_once_per_window_after_initial_seed(self):
        state = GameState()
        first = {"claude": ProviderLimits(provider="claude", windows=[
            LimitWindow("Weekly", 100.0, datetime(2026, 8, 24, tzinfo=timezone.utc))
        ])}
        self.assertEqual(apply_limit_rewards(state, first), [])
        self.assertEqual(state.inventory["rare_candy"], 0)

        next_window = {"claude": ProviderLimits(provider="claude", windows=[
            LimitWindow("Weekly", 100.0, datetime(2026, 8, 31, tzinfo=timezone.utc))
        ])}
        self.assertEqual(len(apply_limit_rewards(state, next_window)), 1)
        self.assertEqual(state.inventory["rare_candy"], 5)
        self.assertEqual(apply_limit_rewards(state, next_window), [])
        self.assertEqual(state.inventory["rare_candy"], 5)

    def test_fresh_egg_discards_active_ungraduated_catch(self):
        state = GameState(install_baseline_set=True, used_since_install=2_000_000_000)
        apply_usage(state, EGG_HATCH_THRESHOLD, FakeAPI())
        self.assertEqual(len(state.catches), 1)
        ok, _ = buy_egg(state, None)
        self.assertTrue(ok)
        self.assertIsNone(state.mon)
        self.assertEqual(state.catches, [])

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.json")
            state = GameState(egg_usage=123, used_since_install=456)
            store.save(state)
            loaded = store.load()
            self.assertEqual(loaded.egg_usage, 123)
            self.assertEqual(loaded.used_since_install, 456)


class WindowsIntegrationTests(unittest.TestCase):
    def test_native_appdata_paths(self):
        env = {
            "USERPROFILE": r"C:\Users\ash",
            "APPDATA": r"C:\Users\ash\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\ash\AppData\Local",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(
                PureWindowsPath(str(state_dir())),
                PureWindowsPath(r"C:\Users\ash\AppData\Roaming\PokeTokenBar-Windows"),
            )
            self.assertEqual(
                PureWindowsPath(str(cache_dir())),
                PureWindowsPath(r"C:\Users\ash\AppData\Local\PokeTokenBar-Windows\Cache"),
            )
            self.assertIn(
                PureWindowsPath(r"C:\Users\ash\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"),
                [PureWindowsPath(str(path)) for path in cursor_database_candidates()],
            )
            self.assertIn(
                PureWindowsPath(r"C:\Users\ash\AppData\Local\kiro-cli\data.sqlite3"),
                [PureWindowsPath(str(path)) for path in kiro_database_candidates()],
            )

    def test_hidden_subprocess_flags(self):
        from poketokenbar_windows.windows import hidden_subprocess_kwargs, resolve_gui_binary

        kwargs = hidden_subprocess_kwargs()
        self.assertIn("creationflags", kwargs)
        self.assertEqual(resolve_gui_binary(r"C:\missing-codex.cmd"), r"C:\missing-codex.cmd")


class FormattingTests(unittest.TestCase):
    def test_compact_tokens(self):
        self.assertEqual(compact_tokens(200_700_000), "200.7M")
        self.assertEqual(compact_tokens(1_000_000_000), "1B")


if __name__ == "__main__":
    unittest.main()
