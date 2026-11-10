"""R158 volume-equivalent physical harness, stdlib-only regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from boca_socios import host_worker_physical as physical

RUN = "42899999999"
CID = "f" * 64
IPC_DESTINATION = "/run/boca-browser-ipc"


class VolumeContractTests(unittest.TestCase):
    def test_volume_name_is_unique_to_probe_and_not_installed_volume(self) -> None:
        self.assertEqual(physical._volume_name(RUN), "boca-physical-ipc-42899999999")
        self.assertNotEqual(physical._volume_name(RUN), physical.deploy.BROWSER_IPC_VOLUME)
        with self.assertRaises(physical.PhysicalProbeUnavailable):
            physical._volume_name("../not-a-run")

    def test_worker_uses_one_named_volume_not_ipc_tmpfs(self) -> None:
        argv = physical.create_argv(RUN, "/srv/boca/seccomp.json")
        self.assertEqual(
            argv[argv.index("--mount") + 1],
            ("type=volume,source=boca-physical-ipc-42899999999,target=/run/boca-browser-ipc"),
        )
        self.assertNotIn(
            "/run/boca-browser-ipc:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0711",
            argv,
        )
        self.assertEqual(argv.count("--mount"), 1)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--user") + 1], "10002:10002")

    def test_volume_metadata_requires_own_rootless_mountpoint_and_labels(self) -> None:
        name = physical._volume_name(RUN)
        root = Path("/boca-rootless-data")
        mountpoint = str(root / "volumes" / name / "_data")
        good = {
            "Name": name,
            "Driver": "local",
            "Scope": "local",
            "Options": None,
            "Mountpoint": mountpoint,
            "Labels": {
                "boca.socios.physical-probe": "1",
                "boca.socios.physical-run": RUN,
                "boca.socios.physical-release": physical.RELEASE_RUN_ID,
                "boca.socios.physical-kind": "ipc-volume",
            },
        }
        with (
            patch.object(physical.deploy, "_checked_docker_storage_dir", return_value=root),
            patch.object(physical.deploy, "_run", return_value=json.dumps(good)),
            patch.object(Path, "resolve", lambda self, strict=False: self),
        ):
            physical._check_volume(RUN)
            for changed in (
                dict(good, Labels={"boca.socios.physical-probe": "1"}),
                dict(good, Mountpoint="/foreign/root/volumes/other/_data"),
                dict(good, Driver="local-other"),
            ):
                with patch.object(physical.deploy, "_run", return_value=json.dumps(changed)):
                    with self.assertRaises(physical.PhysicalProbeUnavailable):
                        physical._check_volume(RUN)

    def test_create_rejects_prior_name_even_with_matching_labels(self) -> None:
        with (
            patch.object(physical.cleanup, "_docker", return_value=physical._volume_name(RUN)),
            patch.object(physical.deploy, "_run") as docker,
            patch.object(physical, "_cleanup_volume") as cleanup_volume,
        ):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._create_volume(RUN)
            docker.assert_not_called()
            cleanup_volume.assert_not_called()

    def test_lost_volume_create_ack_compensates_only_after_absence_proof(self) -> None:
        with (
            patch.object(physical, "_volume_present", return_value=False),
            patch.object(
                physical.deploy,
                "_run",
                side_effect=physical.deploy.PreflightError("create ACK lost"),
            ),
            patch.object(physical, "_cleanup_volume") as cleanup_volume,
        ):
            with self.assertRaises(physical.deploy.PreflightError):
                physical._create_volume(RUN)
            cleanup_volume.assert_called_once_with(RUN)

    def test_preexisting_name_collision_does_not_cleanup_anothers_resources(self) -> None:
        @contextmanager
        def lease(_run: str):
            yield object()

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(physical.cleanup, "protected_boca_job_lease", lease),
            patch.object(physical, "_verify_rootless"),
            patch.object(physical, "_idle", return_value=(object(), "fingerprint")),
            patch.object(physical, "_verified_boca_home", return_value=Path(directory)),
            patch.object(physical, "_image_pull_and_verify", return_value="before"),
            patch.object(physical, "_profile_path", return_value="/srv/boca/seccomp.json"),
            patch.object(physical, "_create_volume", side_effect=physical.PhysicalProbeUnavailable),
            patch.object(physical, "_cleanup_initializer") as cleanup_initializer,
            patch.object(physical, "_cleanup_volume") as cleanup_volume,
            patch.object(physical, "_exact_cleanup") as cleanup_cid,
        ):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._diagnose(RUN)
        cleanup_initializer.assert_not_called()
        cleanup_volume.assert_not_called()
        cleanup_cid.assert_not_called()

    def test_replayed_claim_never_touches_an_existing_volume(self) -> None:
        @contextmanager
        def lease(_run: str):
            yield object()

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(physical.cleanup, "protected_boca_job_lease", lease),
            patch.object(physical, "_verify_rootless"),
            patch.object(physical, "_idle", return_value=(object(), "fingerprint")),
            patch.object(physical, "_verified_boca_home", return_value=Path(directory)),
            patch.object(physical, "_image_pull_and_verify", return_value="before"),
            patch.object(physical, "_profile_path", return_value="/srv/boca/seccomp.json"),
            patch.object(physical, "_claim_once", side_effect=physical.PhysicalProbeUnavailable),
            patch.object(physical, "_create_volume") as create_volume,
            patch.object(physical, "_cleanup_initializer") as cleanup_initializer,
            patch.object(physical, "_cleanup_volume") as cleanup_volume,
        ):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._diagnose(RUN)
        create_volume.assert_not_called()
        cleanup_initializer.assert_not_called()
        cleanup_volume.assert_not_called()

    def test_new_volume_claim_is_independent_and_permanent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            original = home / f".boca-worker-physical-{physical.RELEASE_RUN_ID}.claim"
            original.write_text("historical-937", encoding="utf-8")
            physical._claim_once(home, RUN)
            marker = home / f".boca-worker-physical-volume-{physical.RELEASE_RUN_ID}.claim"
            self.assertTrue(marker.exists())
            self.assertEqual(original.read_text(encoding="utf-8"), "historical-937")
            self.assertEqual(json.loads(marker.read_text(encoding="ascii"))["run_id"], RUN)
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._claim_once(home, RUN)

    def test_receipt_explicitly_proves_volume_equivalent_cleanup(self) -> None:
        good = {
            "schema": 2,
            "run_id": RUN,
            "release_run_id": physical.RELEASE_RUN_ID,
            "image_ref": physical.BROWSER_IMAGE,
            "container_id": CID,
            "started": True,
            "boot": "FAILED",
            "cause": "STDOUT_ONLY",
            "exit_code": 0,
            "oom": False,
            "controller": "HEALTHY",
            "engine": "STOPPED",
            "installed_worker": "IDLE",
            "cleanup": "VERIFIED",
            "ipc_mount": "ISOLATED_VOLUME",
            "ipc_cleanup": "VERIFIED",
            "image_cache": "RETAINED",
        }
        line = physical.checked(good, RUN)
        self.assertIn('"ipc_mount":"ISOLATED_VOLUME"', line)
        for tamper in (dict(good, ipc_mount="TMPFS"), dict(good, ipc_cleanup="UNKNOWN")):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical.checked(tamper, RUN)

    def test_initializer_uses_reviewed_rootless_bounded_helper_without_browser_start(self) -> None:
        with (
            patch.object(physical, "_check_volume"),
            patch.object(
                physical.deploy, "_browser_named_probe", return_value="BOCA_BROWSER_IPC_DIR_PASS"
            ) as helper,
        ):
            physical._initialize_volume(RUN)
        self.assertEqual(helper.call_args.args[:2], ("ipc-dir-init", RUN))
        argv = helper.call_args.args[2]
        self.assertEqual(argv[:3], ("docker", "run", "--rm"))
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--user") + 1], "0:0")
        self.assertIn(
            "type=volume,source=boca-physical-ipc-42899999999,"
            "target=/run/boca-browser-ipc,volume-nocopy",
            argv,
        )
        self.assertEqual(argv[argv.index("--memory") + 1], "64m")
        self.assertEqual(argv[-3:-1], ("python", "-c"))
        self.assertNotIn("boca_socios.browser.ipc_worker", argv)

    def test_volume_cleanup_refuses_foreign_labels_and_never_removes(self) -> None:
        with (
            patch.object(physical, "_volume_present", return_value=True),
            patch.object(physical, "_check_volume", side_effect=physical.PhysicalProbeUnavailable),
            patch.object(physical.deploy, "_run") as docker,
        ):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._cleanup_volume(RUN)
            docker.assert_not_called()

    def test_volume_cleanup_removes_only_matching_owned_volume(self) -> None:
        name = physical._volume_name(RUN)
        with (
            patch.object(physical, "_volume_present", side_effect=[True, False]),
            patch.object(physical, "_check_volume"),
            patch.object(physical.deploy, "_run", return_value=name) as docker,
        ):
            physical._cleanup_volume(RUN)
            docker.assert_called_once_with("docker", "volume", "rm", name, timeout=25)

    def test_initializer_cleanup_refuses_foreign_container(self) -> None:
        with (
            patch.object(physical.cleanup, "_docker", return_value=CID),
            patch.object(
                physical.deploy,
                "_browser_inspect_record",
                return_value={"Name": "/foreign", "Config": {"Labels": {}}},
            ),
            patch.object(physical.deploy, "_run") as docker,
        ):
            with self.assertRaises(physical.PhysicalProbeUnavailable):
                physical._cleanup_initializer(RUN)
            docker.assert_not_called()

    def test_inspect_requires_exact_named_volume_and_rejects_tmpfs(self) -> None:
        name = physical._volume_name(RUN)
        root = Path("/boca-rootless-data")
        mount = str(root / "volumes" / name / "_data")
        good = {
            "Name": f"/boca-physical-worker-{RUN}",
            "Config": {
                "Image": physical.BROWSER_IMAGE,
                "Labels": {
                    "boca.socios.physical-run": RUN,
                    "boca.socios.physical-release": physical.RELEASE_RUN_ID,
                },
            },
            "State": {"Status": "created", "Running": False},
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": name,
                    "Source": mount,
                    "Destination": IPC_DESTINATION,
                    "RW": True,
                }
            ],
            "HostConfig": {
                "NetworkMode": "none",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "ReadonlyRootfs": True,
                "Memory": 768 * 1024 * 1024,
                "NanoCpus": 1_000_000_000,
                "PidsLimit": 128,
                "IpcMode": "private",
                "CgroupnsMode": "private",
                "LogConfig": {"Type": "none"},
                "CapDrop": ["ALL"],
                "CapAdd": ["SYS_CHROOT"],
                "Binds": None,
                "Tmpfs": {
                    "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108
                    "/home/boca-browser": "rw,noexec,nosuid,size=16m",
                },
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": name,
                        "Target": IPC_DESTINATION,
                        "VolumeOptions": {"NoCopy": False},
                    }
                ],
            },
        }
        with (
            patch.object(physical.deploy, "_browser_inspect_record", return_value=good),
            patch.object(physical.deploy, "_checked_docker_storage_dir", return_value=root),
        ):
            physical._inspect_probe(CID, RUN)
            for bad in (
                dict(good, Mounts=[]),
                dict(good, Mounts=[None]),
                dict(good, HostConfig=dict(good["HostConfig"], Mounts=[None])),
                dict(
                    good,
                    HostConfig=dict(
                        good["HostConfig"],
                        Mounts=[
                            {
                                "Type": "volume",
                                "Source": name,
                                "Target": IPC_DESTINATION,
                                "VolumeOptions": {"NoCopy": True},
                            }
                        ],
                    ),
                ),
                dict(
                    good,
                    HostConfig=dict(
                        good["HostConfig"],
                        Mounts=[{"Type": "volume", "VolumeOptions": None}],
                    ),
                ),
            ):
                with (
                    patch.object(physical.deploy, "_browser_inspect_record", return_value=bad),
                    self.assertRaises(physical.PhysicalProbeUnavailable),
                ):
                    physical._inspect_probe(CID, RUN)

    def test_diagnose_uses_one_start_and_cleans_volume_after_cid_on_exit_zero(self) -> None:
        events: list[str] = []
        installed = object()

        @contextmanager
        def lease(_run: str):
            yield object()

        @contextmanager
        def arm(_socket: object, _cid: str):
            events.append("capture-before-start")

            class Captured:
                @staticmethod
                def finish():
                    return physical.capture.CaptureResult.STDOUT_ONLY

            yield Captured()

        def runner(action: str, *args: str, timeout: int) -> str:
            self.assertEqual(action, "docker")
            if args[0] == "create":
                events.append("docker-create")
                return CID
            if args[0] == "start":
                events.append("docker-start")
                return CID
            self.fail("Unexpected Docker operation")

        def health(_cid: str) -> None:
            events.append("health")
            raise physical.deploy.WorkerHealthPhaseError(
                "HEALTH_EXITED", exit_code=0, oom_killed=False
            )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(physical.cleanup, "protected_boca_job_lease", lease),
            patch.object(physical, "_verify_rootless"),
            patch.object(physical, "_idle", return_value=(installed, "same-fingerprint")),
            patch.object(physical, "_verified_boca_home", return_value=Path(directory)),
            patch.object(physical, "_image_pull_and_verify", return_value="storage-before"),
            patch.object(physical, "_profile_path", return_value="/srv/boca/seccomp.json"),
            patch.object(physical, "_claim_once", side_effect=lambda *_: events.append("claim")),
            patch.object(
                physical, "_create_volume", side_effect=lambda *_: events.append("volume-create")
            ),
            patch.object(
                physical, "_initialize_volume", side_effect=lambda *_: events.append("volume-init")
            ),
            patch.object(
                physical,
                "_cleanup_initializer",
                side_effect=lambda *_: events.append("init-cleanup"),
            ),
            patch.object(
                physical, "_cleanup_volume", side_effect=lambda *_: events.append("volume-cleanup")
            ),
            patch.object(
                physical, "_exact_cleanup", side_effect=lambda *_: events.append("cid-cleanup")
            ),
            patch.object(physical, "_inspect_probe", return_value={"State": {"Status": "created"}}),
            patch.object(physical.deploy, "_run", side_effect=runner),
            patch.object(physical.capture, "attach_output", arm),
            patch.object(physical.deploy, "_browser_wait_healthy", side_effect=health),
            patch.object(physical.deploy, "_storage_snapshot", return_value="storage-after"),
            patch.object(physical.deploy, "_validate_storage_continuity"),
            patch.object(physical, "_image_retained"),
        ):
            receipt = physical._diagnose(RUN)

        self.assertEqual(receipt["cause"], "STDOUT_ONLY")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(receipt["cleanup"], "VERIFIED")
        for event in (
            "claim",
            "volume-create",
            "volume-init",
            "docker-create",
            "capture-before-start",
            "docker-start",
            "cid-cleanup",
            "volume-cleanup",
        ):
            self.assertIn(event, events)
        self.assertLess(events.index("claim"), events.index("volume-create"))
        self.assertLess(events.index("volume-init"), events.index("docker-create"))
        self.assertLess(events.index("capture-before-start"), events.index("docker-start"))
        self.assertEqual(events.count("docker-start"), 1)
        self.assertLess(events.index("cid-cleanup"), events.index("volume-cleanup"))


if __name__ == "__main__":
    unittest.main()
