"""Regression tests for the 2026-09 reviewer findings (six items).

Each test class is named after the finding it locks down so a future change
cannot quietly reintroduce the bug. Findings 3 and 4 are concurrency bugs and
are tested with real background threads that hold `state_lock` while the
other code path runs concurrently - not just an assertion that a lock object
exists.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from poketokenbar_windows.models import UsageSnapshot
from poketokenbar_windows.pokemon import PokeAPIClient
from poketokenbar_windows.state import CatchRecord, GameState, MonState, StateStore
from poketokenbar_windows.ui import TrayController


def _make_client() -> PokeAPIClient:
    """A PokeAPIClient with real cache directories but no network calls made."""
    client = PokeAPIClient.__new__(PokeAPIClient)
    tmp = Path(tempfile.mkdtemp())
    client.cache_dir = tmp
    client.timeout = 12.0
    client.json_dir = tmp / "api"
    client.sprite_dir = tmp / "sprites"
    client.json_dir.mkdir(parents=True, exist_ok=True)
    client.sprite_dir.mkdir(parents=True, exist_ok=True)
    return client


def _controller() -> TrayController:
    """A TrayController built without running __init__ (no Qt app wiring).

    Same pattern already used throughout tests/test_ui.py: TrayController is
    a QObject, but the handlers under test here are plain Python methods that
    do not depend on __init__ having run.
    """
    return TrayController.__new__(TrayController)


class RefreshWorkerLockScopeTests(unittest.TestCase):
    """Finding 1: state_lock must never be held across a PokeAPI network call."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_worker_releases_state_lock_during_a_slow_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            initial = GameState(mon=MonState(1, [1], 0, 0, "common", False, "Hardy"))
            store.save(initial)

            controller = _controller()
            controller.state_lock = threading.Lock()
            controller.store = store
            controller.state = initial
            controller.bridge = Mock()
            controller.executor = Mock()

            network_call_started = threading.Event()
            release_network_call = threading.Event()

            class SlowBlockingAPI:
                def item_sprite_path(self, name):
                    return None

                def sprite_path(self, species_id, shiny=False, animated=True):
                    # Stands in for a real PokeAPI fetch that is slow to
                    # respond (cold cache, lossy network). If state_lock is
                    # still held while this runs, every other state-locked
                    # action on the GUI thread would freeze for as long as
                    # this call takes.
                    network_call_started.set()
                    release_network_call.wait(timeout=5)
                    return None

                def egg_sprite_path(self):
                    return None

                def localized_name(self, species_id, language="en"):
                    return "Test Species"

            controller.api = SlowBlockingAPI()

            with patch(
                "poketokenbar_windows.ui.scan_all",
                return_value=(UsageSnapshot(providers={}), {}),
            ), patch("poketokenbar_windows.ui.fetch_all_limits", return_value={}):
                worker = threading.Thread(target=controller._refresh_worker)
                worker.start()
                self.assertTrue(
                    network_call_started.wait(timeout=5),
                    "the worker never reached its (fake) network call",
                )

                # THIS thread (not the worker) tries to take state_lock RIGHT
                # NOW, while the worker thread is blocked deep inside a
                # PokeAPI call. It must succeed immediately.
                acquired = controller.state_lock.acquire(timeout=2)
                if acquired:
                    controller.state_lock.release()

                release_network_call.set()
                worker.join(timeout=5)

            self.assertTrue(
                acquired,
                "state_lock could not be acquired from another thread while a "
                "PokeAPI network call was in flight in _refresh_worker - the "
                "lock is still held across network I/O",
            )


class HatchWallClockDeadlineTests(unittest.TestCase):
    """Finding 2: hatch() must bound its worst case by wall-clock time.

    max_attempts alone allows roughly max_attempts * timeout in the worst
    case (~4 hours at the defaults) if every attempt hits an unreachable host
    that hangs for the full timeout before failing.
    """

    def test_hatch_gives_up_by_its_wall_clock_deadline_not_just_attempt_count(self):
        client = _make_client()
        call_count = {"n": 0}

        def slow_unreachable_species(species_id: int):
            call_count["n"] += 1
            time.sleep(0.05)
            raise ConnectionError("simulated unreachable host")

        client.species = slow_unreachable_species  # type: ignore[method-assign]

        with patch("poketokenbar_windows.pokemon.random.randint", return_value=1):
            start = time.monotonic()
            with self.assertRaises(RuntimeError):
                # Without a wall-clock deadline this would attempt up to
                # 10,000 slow calls (~8+ minutes at 0.05s each).
                client.hatch(max_attempts=10_000, max_seconds=0.3)
            elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 3.0,
            f"hatch() ran for {elapsed:.2f}s - it is not bounded by a wall-clock deadline",
        )
        self.assertLess(
            call_count["n"], 200,
            "hatch() kept retrying long past its deadline instead of giving up early",
        )


class ImportStateLockingTests(unittest.TestCase):
    """Finding 3: importing a save must be serialized against a refresh commit."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_import_waits_on_state_lock_instead_of_being_clobbered_by_an_in_flight_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            old_state = GameState(egg_usage=1000)
            store.save(old_state)

            controller = _controller()
            controller.state_lock = threading.Lock()
            controller.store = store
            controller.state = old_state
            controller.window = Mock()
            controller.refresh = Mock()
            controller.refresh_running = False

            import_path = Path(tmp) / "import.json"
            import_path.write_text(
                json.dumps({"egg_usage": 999999, "catches": [], "mon": None, "inventory": {}}),
                encoding="utf-8",
            )

            lock_acquired = threading.Event()
            stale_committed = threading.Event()
            HOLD_SECONDS = 0.3

            def rival_committing_worker():
                # Mimics a refresh worker that captured its candidate from
                # the OLD state BEFORE the import ever started, and is slow
                # to actually reach its commit (the network work that
                # finding 1 moves outside the lock stands in for that
                # slowness here - what matters for THIS test is that it is
                # still holding state_lock while _import_state runs).
                with controller.state_lock:
                    lock_acquired.set()
                    time.sleep(HOLD_SECONDS)
                    stale_candidate = copy.deepcopy(old_state)
                    controller.store.save(stale_candidate)
                    controller.state = stale_candidate
                    stale_committed.set()

            thread = threading.Thread(target=rival_committing_worker)
            thread.start()
            self.assertTrue(lock_acquired.wait(timeout=5), "worker never acquired state_lock")

            with patch.object(
                QFileDialog, "getOpenFileName", return_value=(str(import_path), "")
            ):
                controller._import_state()

            thread.join(timeout=5)

            # If _import_state actually waited on state_lock, the rival's
            # stale commit (egg_usage=1000) must have already landed and
            # finished BEFORE _import_state's own locked section could run -
            # so the import always lands last and wins cleanly.
            self.assertTrue(stale_committed.is_set(), "the rival worker never got to commit")
            self.assertEqual(
                controller.state.egg_usage, 999999,
                "the in-flight worker's commit clobbered the import - "
                "_import_state is not serialized by state_lock",
            )
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                on_disk.get("egg_usage"), 999999,
                "the file on disk does not reflect the import - it was overwritten",
            )

    def test_import_refuses_while_a_refresh_is_reported_in_flight(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            original = GameState(egg_usage=7)
            store.save(original)

            controller = _controller()
            controller.state_lock = threading.Lock()
            controller.store = store
            controller.state = original
            controller.window = Mock()
            controller.refresh = Mock()
            controller.refresh_running = True

            import_path = Path(tmp) / "import.json"
            import_path.write_text(
                json.dumps({"egg_usage": 55555, "catches": [], "mon": None, "inventory": {}}),
                encoding="utf-8",
            )

            with patch.object(
                QFileDialog, "getOpenFileName", return_value=(str(import_path), "")
            ), patch.object(QMessageBox, "information") as info:
                controller._import_state()

            info.assert_called_once()
            controller.refresh.assert_not_called()
            self.assertEqual(controller.state.egg_usage, 7, "import proceeded during a live refresh")
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk.get("egg_usage"), 7)


class QuitAndSaveConcurrencyTests(unittest.TestCase):
    """Finding 4: quit() and a background save must never race the same file."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_quit_blocks_on_state_lock_before_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)

            controller = _controller()
            controller.state_lock = threading.Lock()
            controller.store = store
            controller.state = GameState(egg_usage=42)
            controller.floating_pet = Mock()
            controller.tray = Mock()
            controller.executor = Mock()
            controller.app = Mock()

            lock_acquired = threading.Event()
            HOLD_SECONDS = 0.3

            def rival_holder():
                with controller.state_lock:
                    lock_acquired.set()
                    time.sleep(HOLD_SECONDS)

            thread = threading.Thread(target=rival_holder)
            thread.start()
            self.assertTrue(lock_acquired.wait(timeout=5), "rival never acquired state_lock")

            start = time.monotonic()
            controller.quit()
            elapsed = time.monotonic() - start
            thread.join(timeout=5)

            self.assertGreaterEqual(
                elapsed, HOLD_SECONDS * 0.8,
                "quit() saved without waiting for state_lock - it can race a "
                "background save onto the same file",
            )
            controller.app.quit.assert_called_once()

    def test_save_gives_every_call_its_own_temp_file(self):
        """The mechanism behind the fix: no two saves can share one tmp path."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            seen_tmp_paths: list[Path] = []
            original_write_text = Path.write_text

            def spy(self_path: Path, *args, **kwargs):
                if self_path.suffix == ".tmp":
                    seen_tmp_paths.append(self_path)
                return original_write_text(self_path, *args, **kwargs)

            with patch.object(Path, "write_text", spy):
                store.save(GameState(egg_usage=1))
                store.save(GameState(egg_usage=2))

            self.assertEqual(len(seen_tmp_paths), 2)
            self.assertNotEqual(
                seen_tmp_paths[0], seen_tmp_paths[1],
                "save() reused the same temp filename across calls - two "
                "overlapping saves can truncate/interleave each other",
            )

    def test_concurrent_saves_never_produce_invalid_json_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            # Large-ish payloads and many repeated overlapping writes make a
            # same-temp-file collision reliably reproducible on the unfixed
            # code (each write_text() truncates+writes independently, so two
            # writers sharing "state.tmp" at once interleave bytes).
            state_a = GameState(
                egg_usage=111,
                catches=[
                    CatchRecord(
                        species_id=i, base_id=i, path_ids=[i], rarity="common",
                        is_shiny=False, nature="Hardy", caught_at="2026-01-01T00:00:00+00:00",
                    )
                    for i in range(1, 200)
                ],
            )
            state_b = GameState(
                egg_usage=222,
                catches=[
                    CatchRecord(
                        species_id=i, base_id=i, path_ids=[i], rarity="rare",
                        is_shiny=True, nature="Timid", caught_at="2026-02-02T00:00:00+00:00",
                    )
                    for i in range(1, 200)
                ],
            )

            barrier = threading.Barrier(2)
            errors: list[Exception] = []

            def saver(state: GameState):
                try:
                    barrier.wait(timeout=5)
                    for _ in range(15):
                        store.save(state)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [
                threading.Thread(target=saver, args=(state_a,)),
                threading.Thread(target=saver, args=(state_b,)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            self.assertFalse(errors, f"save() raised under concurrent use: {errors}")
            # The file must be complete, valid JSON belonging to exactly one
            # writer - never a corrupt interleaving of both.
            loaded = store.load()
            self.assertIn(loaded.egg_usage, (111, 222))
            self.assertFalse(
                list(Path(tmp).glob("state-corrupt-*.json")),
                "load() treated the saved file as corrupt - it was not valid JSON",
            )


class CorruptSaveBackupTests(unittest.TestCase):
    """Finding 5: a save this build cannot use is preserved, not silently lost."""

    def test_unparseable_json_is_backed_up_before_falling_back_to_a_fresh_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"egg_usage": not-valid-json!!!', encoding="utf-8")
            store = StateStore(path)

            result = store.load()

            self.assertEqual(result, GameState(), "load() must still fall back to a fresh game")
            backups = list(Path(tmp).glob("state-corrupt-*.json"))
            self.assertEqual(len(backups), 1, "the unparseable save was not backed up")
            self.assertIn("not-valid-json", backups[0].read_text(encoding="utf-8"))

    def test_one_bad_field_backs_up_the_whole_save_before_discarding_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            payload = {
                "version": 3,
                # int("nope") raises ValueError deep inside the coercion try
                # block - this used to discard the ENTIRE save with no trace.
                "egg_usage": "nope",
                "catches": [],
                "mon": None,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            store = StateStore(path)

            result = store.load()

            self.assertEqual(result, GameState())
            backups = list(Path(tmp).glob("state-corrupt-*.json"))
            self.assertEqual(len(backups), 1, "the malformed save was not backed up")
            restored = json.loads(backups[0].read_text(encoding="utf-8"))
            self.assertEqual(restored["egg_usage"], "nope")

    def test_a_healthy_save_never_creates_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            store.save(GameState(egg_usage=5))

            store.load()

            self.assertFalse(list(Path(tmp).glob("state-corrupt-*.json")))

    def test_a_missing_file_never_creates_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)

            store.load()

            self.assertFalse(list(Path(tmp).glob("state-corrupt-*.json")))


class EvolutionChainUrlValidationTests(unittest.TestCase):
    """Finding 6: evolution_chain() must refuse anything but https://pokeapi.co."""

    def test_rejects_a_file_url_without_ever_calling_urlopen(self):
        client = _make_client()
        with patch("poketokenbar_windows.pokemon.urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                client.evolution_chain("file:///etc/passwd")
            urlopen.assert_not_called()

    def test_rejects_a_look_alike_host(self):
        client = _make_client()
        with patch("poketokenbar_windows.pokemon.urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                client.evolution_chain("https://pokeapi.co.evil.example/api/v2/evolution-chain/1/")
            urlopen.assert_not_called()

    def test_rejects_plain_http_to_the_real_host(self):
        client = _make_client()
        with patch("poketokenbar_windows.pokemon.urllib.request.urlopen") as urlopen:
            with self.assertRaises(ValueError):
                client.evolution_chain("http://pokeapi.co/api/v2/evolution-chain/1/")
            urlopen.assert_not_called()

    def test_still_accepts_the_real_https_host(self):
        client = _make_client()
        client._json = Mock(return_value={"chain": {}})  # type: ignore[method-assign]
        result = client.evolution_chain("https://pokeapi.co/api/v2/evolution-chain/1/")
        self.assertEqual(result, {"chain": {}})
        client._json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
