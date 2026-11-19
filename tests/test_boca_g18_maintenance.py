"""Offline fault-injection checks for Boca G18 one-shot maintenance.
No Docker, systemd, network, real DB, or host access.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from boca_socios import host_boca_g18_maintenance as m


class G18MaintenanceContract(unittest.TestCase):
    def test_bad_or_missing_receipts_never_certify_shutdown(self) -> None:
        for raw in (b"", b"BOCA_G18_STOP state=STOPPED\n", b"{}\n{}\n",
                    b"BOCA_G18_INVENTORY {}\nBOCA_G18_STOP {}\n"):
            with self.subTest(raw=raw[:32]), self.assertRaises(m.NoGo):
                m.verify(raw, "123456789")

    def test_no_host_writes_on_ineligible_dispatch(self) -> None:
        with patch.object(m.cleanup, "protected_boca_job_lease") as lease:
            self.assertEqual(m.main(["host", "not-a-run", "f" * 40]), 3)
            lease.assert_not_called()
            self.assertEqual(m.main(["host", "123456789", m.INSTALL_SOURCE]), 3)
            lease.assert_not_called()

    def test_missing_optional_socket_not_stopped(self) -> None:
        with patch.object(m, "_unit", return_value={
            "LoadState": "not-found", "ActiveState": "inactive",
            "UnitFileState": ""
        }), patch.object(m.service, "_systemctl") as systemctl:
            m._quiet_unit("docker.socket", optional=True)
            systemctl.assert_not_called()
            with self.assertRaises(m.NoGo):
                m._quiet_unit("docker.service", optional=False)

    def test_unit_stop_and_disable_are_fixed(self) -> None:
        states = [
            {"LoadState": "loaded", "ActiveState": "active",
             "UnitFileState": "enabled"},
            {"LoadState": "loaded", "ActiveState": "inactive",
             "UnitFileState": "disabled"},
        ]
        with patch.object(m, "_unit", side_effect=states), patch.object(
            m.service, "_systemctl", return_value=""
        ) as systemctl:
            m._quiet_unit("boca-bot-control.socket")
        self.assertEqual([call.args[-2:] for call in systemctl.call_args_list],
                         [("stop", "boca-bot-control.socket"),
                          ("disable", "boca-bot-control.socket")])

    def test_metadata_scan_no_symlink_follow(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "backups").mkdir()
            (base / "backups" / "old.sql.gz").write_bytes(b"x" * 400)
            outside = base.parent / "not-boca"
            (base / "backups" / "link.sql.gz").symlink_to(outside)
            (base / "current.log").write_bytes(b"y" * 20)
            with patch.object(m.cleanup, "EXPECTED_UID", os.geteuid()):
                info = m._du_bounded(base)
            self.assertEqual(info["state"], "COMPLETE")
            self.assertEqual(info["backups"], 1)
            self.assertEqual(info["backup_bytes"], 400)
            self.assertEqual(info["logs"], 1)
            self.assertEqual(info["symlinks_skipped"], 1)

    def test_database_sizes_are_metadata_only(self) -> None:
        values = {
            "boca.sqlite3": {"bytes": 1200, "allocated_bytes": 4096},
            "boca.sqlite3-wal": None, "boca.sqlite3-shm": None,
        }
        with patch.object(m.cleanup, "_docker", return_value=json.dumps(values)) as docker:
            value = m._database_sizes()
            self.assertEqual(value["state"], "OBSERVED")
            self.assertEqual(docker.call_args.args[:5],
                             ("exec", "--user", "10001:10001",
                              m.CONTROLLER, "/app/.venv/bin/python"))
            self.assertIn("-B", docker.call_args.args)
        with patch.object(m.cleanup, "_docker", side_effect=m.cleanup.CleanupError("NO")):
            self.assertEqual(m._database_sizes()["state"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
