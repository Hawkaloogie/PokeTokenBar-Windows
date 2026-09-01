"""Only one copy of the app may run; a second launch raises the first."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from poketokenbar_windows.app import _claim_single_instance, _single_instance_key


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


class SingleInstanceKeyTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("PTB_STATE_DIR", None)

    def test_the_normal_install_has_a_stable_key(self) -> None:
        self.assertEqual(_single_instance_key(), _single_instance_key())
        self.assertIn("PokeTokenBar", _single_instance_key())

    def test_an_isolated_state_dir_gets_its_own_key(self) -> None:
        normal = _single_instance_key()
        os.environ["PTB_STATE_DIR"] = r"D:\somewhere\else"
        self.assertNotEqual(_single_instance_key(), normal)

    def test_blank_isolation_is_treated_as_the_normal_install(self) -> None:
        normal = _single_instance_key()
        os.environ["PTB_STATE_DIR"] = "   "
        self.assertEqual(_single_instance_key(), normal)


class SingleInstanceClaimTests(unittest.TestCase):
    """Isolated from the real install, or these would fight the running app.

    Without this the tests connect to a genuinely running PokeTokenBar and the
    first claim correctly fails - which proves the feature works, but tests
    nothing.
    """

    def setUp(self) -> None:
        self.app = _app()
        os.environ["PTB_STATE_DIR"] = r"D:\test-isolated-instance"
        self.key = _single_instance_key()
        QLocalServer.removeServer(self.key)
        self.servers: list[QLocalServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.close()
        QLocalServer.removeServer(self.key)
        os.environ.pop("PTB_STATE_DIR", None)

    def test_the_first_launch_claims_the_name(self) -> None:
        server = _claim_single_instance(self.app, lambda: None)
        self.assertIsNotNone(server, "the first launch should own the instance")
        self.servers.append(server)
        self.assertTrue(server.isListening())

    def test_a_second_launch_is_turned_away(self) -> None:
        first = _claim_single_instance(self.app, lambda: None)
        self.servers.append(first)
        second = _claim_single_instance(self.app, lambda: None)
        self.assertIsNone(second, "a second launch should not start")

    def test_a_second_launch_asks_the_first_to_show_itself(self) -> None:
        shown: list[bool] = []
        first = _claim_single_instance(self.app, lambda: shown.append(True))
        self.servers.append(first)
        self.assertIsNone(_claim_single_instance(self.app, lambda: None))
        for _ in range(40):
            self.app.processEvents()
            if shown:
                break
        self.assertTrue(shown, "the running instance was never asked to show")

    def test_a_stale_name_left_by_a_crash_is_reclaimed(self) -> None:
        stale = QLocalServer()
        stale.listen(self.key)
        stale.close()  # leaves the name behind without a listener
        server = _claim_single_instance(self.app, lambda: None)
        self.assertIsNotNone(server)
        self.servers.append(server)
        self.assertTrue(server.isListening())


if __name__ == "__main__":
    unittest.main()
