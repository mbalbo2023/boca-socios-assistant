"""R260 CODE_ONLY owner WebAuthn acceptance, separate from technical APPLY.

This host-only adapter has NO CLI, workflow, controller route or transport.
The panel cannot currently receive the trusted host challenge; consequently
all *physical* owner acceptance remains NO_GO. An installed HTTP cookie and a
unit ES256 fixture are not an owner acceptance receipt. A future protected
Boca-only operation must authenticate its runner, hold an actual Boca lease,
and transport the ephemeral challenge through a separately reviewed channel.

The owner public credential is read from the independently attested Boca-only
owner volume. No private passkey, assertion, challenge, cookie, raw URL or
member data are persisted. The host-private O_EXCL files contain digest-only
proofs, bounded timing metadata, and a fixed outcome requiring further BETA
postflight. Neither this module nor its tests touch Docker or the droplet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_postflight_volume_attestor_v2 as volumes
from boca_socios import host_cutover_stage as stage
from boca_socios import host_on_demand_service as service
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication

_SHA = re.compile(r"[a-f0-9]{40}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[a-f0-9]{64}\Z")
_WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[a-f0-9]{64}\Z")
_DOMAIN = b"boca-owner-acceptance-v2:\0"
_PREFIX = b"BOCA_OWNER_ACCEPTANCE_V2 "
_ORIGIN = "http://localhost:8443"
_VOLUME = "boca-socios_boca_owner"
_PERMISSIONS = frozenset({"local-status:read"})
_SUBJECT = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MAX = 1024
_WINDOW = 120


class OwnerAcceptanceNoGo(ValueError):
    """Fixed redacted refusal; no host, owner or credential detail escapes."""


def _fail() -> OwnerAcceptanceNoGo:
    return OwnerAcceptanceNoGo("BOCA_OWNER_ACCEPTANCE_V2 NO_GO")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique(entries: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in entries:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _canonical(value: dict[str, object]) -> bytes:
    return (
        _PREFIX
        + json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
        + b"\n"
    )


def _operation(value: object) -> bool:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        return False
    try:
        identity = UUID(value)
        return identity.version == 4 and identity.int != 0 and str(identity) == value
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class InstalledOwnerPair:
    """Runner-pinned coordinates; verified independently against the live host."""

    installation_attempt: str
    source_sha: str
    controller_id: str
    worker_id: str
    controller_ref: str
    worker_ref: str

    def canonical(self) -> bytes:
        if (
            type(self.installation_attempt) is not str
            or _RUN.fullmatch(self.installation_attempt) is None
            or type(self.source_sha) is not str
            or _SHA.fullmatch(self.source_sha) is None
            or any(
                type(cid) is not str or _HEX.fullmatch(cid) is None
                for cid in (self.controller_id, self.worker_id)
            )
            or self.controller_id == self.worker_id
            or type(self.controller_ref) is not str
            or _CONTROLLER.fullmatch(self.controller_ref) is None
            or type(self.worker_ref) is not str
            or _WORKER.fullmatch(self.worker_ref) is None
        ):
            raise _fail()
        return json.dumps(
            (
                self.installation_attempt,
                self.source_sha,
                self.controller_id,
                self.worker_id,
                self.controller_ref,
                self.worker_ref,
            ),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True, slots=True, repr=False)
class HostIssuedOwnerChallenge:
    """Ephemeral host challenge; never serialize/print it to a receipt."""

    operation_id: str
    installed: InstalledOwnerPair
    challenge: bytes
    issued_at: int
    issued_monotonic_ns: int
    verifier_sha256: str
    boot_sha256: str


@dataclass(frozen=True, slots=True)
class HostOwnerAcceptanceReceipt:
    operation_id: str
    filename: str
    raw: bytes
    sha256: str
    accepted_pair_sha256: str

    @property
    def owner_passkey(self) -> Literal["ES256_UP_UV_VERIFIED"]:
        return "ES256_UP_UV_VERIFIED"

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def beta_deploy(self) -> Literal["NO_GO"]:
        return "NO_GO"


def _attest_installed_pair(pins: InstalledOwnerPair, lease: cleanup.BocaJobLease) -> None:
    """Two R177 pairs and pinned systemd binding, *same current host lease*."""
    pins.canonical()
    cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
    original: tuple[bytes, object] | None = None
    for _ in range(2):
        installed = service.read_installed_binding(lease)
        observed = pair.observe(pins.installation_attempt)
        binding._attest(pins.installation_attempt, observed, installed)
        if (
            installed.installation_run_id != pins.installation_attempt
            or installed.source_sha != pins.source_sha
            or installed.controller_id != pins.controller_id
            or installed.worker_id != pins.worker_id
            or installed.controller_image != pins.controller_ref
            or installed.worker_image != pins.worker_ref
        ):
            raise _fail()
        body = json.loads(observed.removeprefix(pair._PREFIX))
        worker = body["services"][1]
        if (worker["status"], worker["pid"], worker["exit_code"]) != ("created", 0, 0):
            raise _fail()
        snapshot = (observed, installed)
        if original is not None and snapshot != original:
            raise _fail()
        original = snapshot
    cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)


def _read_public(folder: Path, filename: str, maximum: int) -> bytes:
    """No-follow read of actual rootless Boca owner-volume PUBLIC files only."""
    parent = -1
    fd = -1
    try:
        parent = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        directory = os.fstat(parent)
        named_directory = os.stat(folder, follow_symlinks=False)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or stat.S_IMODE(directory.st_mode) & 0o022
            or (directory.st_dev, directory.st_ino, directory.st_mode)
            != (named_directory.st_dev, named_directory.st_ino, named_directory.st_mode)
        ):
            raise _fail()
        fd = os.open(
            filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
        )
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_uid, before.st_gid) != (directory.st_uid, directory.st_gid)
            or stat.S_IMODE(before.st_mode) not in (0o400, 0o600)
            or not 0 < before.st_size <= maximum
        ):
            raise _fail()
        raw = os.read(fd, maximum + 1)
        after = os.fstat(fd)
        named = os.stat(filename, dir_fd=parent, follow_symlinks=False)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        for current in (after, named):
            if identity != (
                current.st_dev,
                current.st_ino,
                current.st_mode,
                current.st_uid,
                current.st_gid,
                current.st_mtime_ns,
                current.st_ctime_ns,
            ):
                raise _fail()
        if len(raw) != before.st_size:
            raise _fail()
        named_directory = os.stat(folder, follow_symlinks=False)
        if (directory.st_dev, directory.st_ino, directory.st_mode) != (
            named_directory.st_dev,
            named_directory.st_ino,
            named_directory.st_mode,
        ):
            raise _fail()
        return raw
    except Exception:
        raise _fail() from None
    finally:
        if fd >= 0:
            os.close(fd)
        if parent >= 0:
            os.close(parent)


def _controller_owner_subject(pins: InstalledOwnerPair) -> str:
    """Read only exact CID's effective owner setting; never trust a form/env input."""
    try:
        pins.canonical()
        raw = cleanup._docker("inspect", "--format", "{{json .Config.Env}}", pins.controller_id)
        entries = json.loads(raw)
        if type(entries) is not list or not all(type(item) is str for item in entries):
            raise _fail()
        environment: dict[str, str] = {}
        for entry in entries:
            key, separator, value = entry.partition("=")
            if not separator or key in environment or len(key) > 128 or len(value) > 4096:
                raise _fail()
            environment[key] = value
        required = {
            "BOCA_PANEL_ORIGIN": _ORIGIN,
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
            "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
            "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        }
        if any(environment.get(key) != value for key, value in required.items()):
            raise _fail()
        subject = environment.get("BOCA_OWNER_SUBJECT", "")
        if _SUBJECT.fullmatch(subject) is None:
            raise _fail()
        return subject
    except Exception:
        raise _fail() from None


def _trusted_owner_verifier(
    pins: InstalledOwnerPair, lease: cleanup.BocaJobLease
) -> PasskeyOwnerAuthentication:
    """Read current PUBLIC credential from rootless Boca-only owner volume.

    Production may fail on actual subordinate UID mapping. NEVER chmod/chown,
    use root, Docker exec, relax modes, or substitute an untrusted verifier.
    That physical dependency must be reconciled before connecting this adapter.
    """
    try:
        cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
        _attest_installed_pair(pins, lease)
        inventory = cleanup.capture_inventory()
        root = volumes._root_from_authenticated_inventory(inventory)
        volumes._attest_exact_volume(_VOLUME, root, inventory)
        folder = root / "volumes" / _VOLUME / "_data"
        subject = _controller_owner_subject(pins)
        credential = _read_public(folder, "credential_id", 1024)
        public_der = _read_public(folder, "public_key.der", 4096)
        verifier = PasskeyOwnerAuthentication(
            credential_id=credential,
            public_key_der=public_der,
            rp_id="localhost",
            origin=_ORIGIN,
            owner_subject=subject,
            permissions=_PERMISSIONS,
        )
        fresh_inventory = cleanup.capture_inventory()
        if volumes._root_from_authenticated_inventory(fresh_inventory) != root:
            raise _fail()
        volumes._attest_exact_volume(_VOLUME, root, fresh_inventory)
        _attest_installed_pair(pins, lease)
        cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
        return verifier
    except Exception:
        raise _fail() from None


def _host_boot_digest() -> str:
    """Bind challenge freshness to the same kernel boot, never an input."""
    try:
        with open("/proc/sys/kernel/random/boot_id", "rb") as file:
            raw = file.read(65)
        boot = raw.decode("ascii").strip()
        if not _operation(boot):  # UUID version need not be v4 in all kernels.
            if not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot):
                raise _fail()
        return _sha(boot.encode("ascii"))
    except Exception:
        raise _fail() from None


def _read_digest_record(
    root: int, filename: str, fields: frozenset[str]
) -> tuple[dict[str, object], bytes]:
    raw, _ = stage._read_file(root, filename, None, limit=_MAX)
    if not raw.startswith(_PREFIX) or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise _fail()
    value = json.loads(raw[len(_PREFIX) :], object_pairs_hook=_unique)
    if type(value) is not dict or value.keys() != fields or _canonical(value) != raw:
        raise _fail()
    return value, raw


def _valid_challenge_record(value: dict[str, object]) -> bool:
    def valid_digest(raw: object) -> bool:
        return type(raw) is str and _HEX.fullmatch(raw) is not None

    issued = value.get("issued_at")
    monotonic = value.get("issued_monotonic_ns")
    return (
        type(value.get("version")) is int
        and value["version"] == 2
        and value.get("purpose") == "BOCA_OWNER_POSTDEPLOY_ONLY"
        and all(
            valid_digest(value.get(name))
            for name in (
                "operation_sha256",
                "pair_sha256",
                "challenge_sha256",
                "verifier_sha256",
                "boot_sha256",
            )
        )
        and type(issued) is int
        and 0 < issued <= 2**63 - 1
        and type(monotonic) is int
        and 0 < monotonic <= 2**63 - 1
    )


_CHALLENGE_FIELDS = frozenset(
    {
        "version",
        "purpose",
        "operation_sha256",
        "pair_sha256",
        "challenge_sha256",
        "verifier_sha256",
        "boot_sha256",
        "issued_at",
        "issued_monotonic_ns",
    }
)
_CLAIM_FIELDS = frozenset({"version", "operation_sha256", "challenge_sha256"})
_RECEIPT_FIELDS = frozenset(
    {
        "version",
        "state",
        "operation_sha256",
        "pair_sha256",
        "challenge_sha256",
        "verifier_sha256",
        "boot_sha256",
        "intent_sha256",
        "claim_sha256",
        "assertion_sha256",
        "accepted_at",
        "owner_passkey",
        "beta_deploy",
    }
)


class HostOwnerAcceptanceV2:
    """Asynchronous host-only two-lease protocol with no panel/CLI route.

    Challenge issuance and finalization are separate protected operations;
    never assert the APPLY lease lasts while the owner uses Chrome.
    """

    @staticmethod
    def _names(operation: str) -> tuple[str, str, str]:
        if not _operation(operation):
            raise _fail()
        root = f".boca-owner-accept-{operation}"
        return root + ".challenge", root + ".claim", root + ".receipt"

    def issue(
        self, pins: InstalledOwnerPair, lease: cleanup.BocaJobLease
    ) -> HostIssuedOwnerChallenge:
        """Persist host-generated purpose-bound challenge digest O_EXCL once."""
        try:
            _attest_installed_pair(pins, lease)
            verifier = _trusted_owner_verifier(pins, lease)
            now = int(time.time())
            tick = time.monotonic_ns()
            if now <= 0 or tick <= 0:
                raise _fail()
            boot = _host_boot_digest()
            operation = str(uuid4())
            nonce = secrets.token_bytes(32)
            if len(nonce) != 32 or not _operation(operation):
                raise _fail()
            pair_hash = _sha(pins.canonical())
            verifier_hash = _sha(verifier.authorization_binding)
            transcript = json.dumps(
                (operation, pair_hash, verifier_hash, boot, now, tick, nonce.hex()),
                separators=(",", ":"),
            ).encode("ascii")
            challenge = hashlib.sha256(_DOMAIN + transcript).digest()
            value: dict[str, object] = {
                "version": 2,
                "purpose": "BOCA_OWNER_POSTDEPLOY_ONLY",
                "operation_sha256": _sha(operation.encode()),
                "pair_sha256": pair_hash,
                "challenge_sha256": _sha(challenge),
                "verifier_sha256": verifier_hash,
                "boot_sha256": boot,
                "issued_at": now,
                "issued_monotonic_ns": tick,
            }
            raw = _canonical(value)
            if len(raw) > _MAX or not _valid_challenge_record(value):
                raise _fail()
            challenge_name, _, _ = self._names(operation)
            fd = stage._root_fd()
            try:
                stage._create_exclusive(fd, challenge_name, raw)
                persisted, _ = _read_digest_record(fd, challenge_name, _CHALLENGE_FIELDS)
                if persisted != value:
                    raise _fail()
            finally:
                os.close(fd)
            _attest_installed_pair(pins, lease)
            cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
            return HostIssuedOwnerChallenge(
                operation, pins, challenge, now, tick, verifier_hash, boot
            )
        except Exception:
            raise _fail() from None

    def accept(
        self,
        issued: HostIssuedOwnerChallenge,
        proof: PasskeyAssertion | None,
        lease: cleanup.BocaJobLease,
    ) -> HostOwnerAcceptanceReceipt:
        """Consume host intent once, validate true ES256 UP+UV, O_EXCL receipt.

        Even a rejected signature leaves an immutable claim, so the challenge
        cannot be retried with a second proof or another host Action.
        """
        try:
            if type(issued) is not HostIssuedOwnerChallenge:
                raise _fail()
            challenge_name, claim_name, receipt_name = self._names(issued.operation_id)
            pins = issued.installed
            if (
                type(pins) is not InstalledOwnerPair
                or type(issued.challenge) is not bytes
                or len(issued.challenge) != 32
            ):
                raise _fail()
            _attest_installed_pair(pins, lease)
            verifier = _trusted_owner_verifier(pins, lease)
            clock = int(time.time())
            monotonic = time.monotonic_ns()
            if (
                not 0 <= clock - issued.issued_at <= _WINDOW
                or not 0 <= monotonic - issued.issued_monotonic_ns <= _WINDOW * 1_000_000_000
                or issued.boot_sha256 != _host_boot_digest()
                or issued.verifier_sha256 != _sha(verifier.authorization_binding)
            ):
                raise _fail()
            fd = stage._root_fd()
            try:
                record, intent_raw = _read_digest_record(fd, challenge_name, _CHALLENGE_FIELDS)
                if not _valid_challenge_record(record) or record != {
                    "version": 2,
                    "purpose": "BOCA_OWNER_POSTDEPLOY_ONLY",
                    "operation_sha256": _sha(issued.operation_id.encode()),
                    "pair_sha256": _sha(pins.canonical()),
                    "challenge_sha256": _sha(issued.challenge),
                    "verifier_sha256": issued.verifier_sha256,
                    "boot_sha256": issued.boot_sha256,
                    "issued_at": issued.issued_at,
                    "issued_monotonic_ns": issued.issued_monotonic_ns,
                }:
                    raise _fail()
                claim = _canonical(
                    {
                        "version": 2,
                        "operation_sha256": record["operation_sha256"],
                        "challenge_sha256": record["challenge_sha256"],
                    }
                )
                # Irreversible consume BEFORE any cryptographic or external callback.
                stage._create_exclusive(fd, claim_name, claim)
                actual_claim, claim_bytes = _read_digest_record(fd, claim_name, _CLAIM_FIELDS)
                if actual_claim["challenge_sha256"] != record["challenge_sha256"]:
                    raise _fail()
            finally:
                os.close(fd)
            if type(
                proof
            ) is not PasskeyAssertion or not verifier.verify_public_telegram_stage_signature(
                proof, issued.challenge
            ):
                raise _fail()
            _attest_installed_pair(pins, lease)
            if (
                _sha(_trusted_owner_verifier(pins, lease).authorization_binding)
                != issued.verifier_sha256
            ):
                raise _fail()
            if (
                _host_boot_digest() != issued.boot_sha256
                or not 0 <= int(time.time()) - issued.issued_at <= _WINDOW
            ):
                raise _fail()
            assertion_hash = _sha(
                json.dumps(
                    (
                        proof.credential_id,
                        proof.client_data_json,
                        proof.authenticator_data,
                        proof.signature,
                    ),
                    separators=(",", ":"),
                ).encode("ascii")
            )
            done: dict[str, object] = {
                "version": 2,
                "state": "OWNER_PASSKEY_VERIFIED_PENDING_BETA",
                "operation_sha256": _sha(issued.operation_id.encode()),
                "pair_sha256": _sha(pins.canonical()),
                "challenge_sha256": _sha(issued.challenge),
                "verifier_sha256": issued.verifier_sha256,
                "boot_sha256": issued.boot_sha256,
                "intent_sha256": _sha(intent_raw),
                "claim_sha256": _sha(claim_bytes),
                "assertion_sha256": assertion_hash,
                "accepted_at": int(time.time()),
                "owner_passkey": "ES256_UP_UV_VERIFIED",
                "beta_deploy": "NO_GO",
            }
            raw = _canonical(done)
            if len(raw) > _MAX:
                raise _fail()
            fd = stage._root_fd()
            try:
                stage._create_exclusive(fd, receipt_name, raw)
                reread, _ = _read_digest_record(fd, receipt_name, _RECEIPT_FIELDS)
                if reread != done:
                    raise _fail()
            finally:
                os.close(fd)
            cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
            return HostOwnerAcceptanceReceipt(
                issued.operation_id, receipt_name, raw, _sha(raw), _sha(pins.canonical())
            )
        except Exception:
            raise _fail() from None

    def verify_readonly(
        self, operation_id: str, pins: InstalledOwnerPair, lease: cleanup.BocaJobLease
    ) -> bytes:
        """Independent protected same-host read; no writes or remote GO."""
        try:
            challenge_name, claim_name, receipt_name = self._names(operation_id)
            _attest_installed_pair(pins, lease)
            verifier = _trusted_owner_verifier(pins, lease)
            fd = stage._root_fd()
            try:
                challenge, intent_raw = _read_digest_record(fd, challenge_name, _CHALLENGE_FIELDS)
                claim, claim_raw = _read_digest_record(fd, claim_name, _CLAIM_FIELDS)
                received, receipt_raw = _read_digest_record(fd, receipt_name, _RECEIPT_FIELDS)
                issued_at = challenge.get("issued_at")
                accepted_at = received.get("accepted_at")
                assertion_digest = received.get("assertion_sha256")
                if (
                    not _valid_challenge_record(challenge)
                    or challenge["operation_sha256"] != _sha(operation_id.encode())
                    or challenge["pair_sha256"] != _sha(pins.canonical())
                    or challenge["verifier_sha256"] != _sha(verifier.authorization_binding)
                    or challenge["boot_sha256"] != _host_boot_digest()
                    or claim
                    != {
                        "version": 2,
                        "operation_sha256": challenge["operation_sha256"],
                        "challenge_sha256": challenge["challenge_sha256"],
                    }
                    or received
                    != {
                        "version": 2,
                        "state": "OWNER_PASSKEY_VERIFIED_PENDING_BETA",
                        "operation_sha256": challenge["operation_sha256"],
                        "pair_sha256": challenge["pair_sha256"],
                        "challenge_sha256": challenge["challenge_sha256"],
                        "verifier_sha256": challenge["verifier_sha256"],
                        "boot_sha256": challenge["boot_sha256"],
                        "intent_sha256": _sha(intent_raw),
                        "claim_sha256": _sha(claim_raw),
                        "assertion_sha256": received["assertion_sha256"],
                        "accepted_at": received["accepted_at"],
                        "owner_passkey": "ES256_UP_UV_VERIFIED",
                        "beta_deploy": "NO_GO",
                    }
                    or type(accepted_at) is not int
                    or type(issued_at) is not int
                    or not issued_at <= accepted_at <= issued_at + _WINDOW
                    or type(assertion_digest) is not str
                    or _HEX.fullmatch(assertion_digest) is None
                ):
                    raise _fail()
            finally:
                os.close(fd)
            _attest_installed_pair(pins, lease)
            cleanup.verify_protected_boca_job_lease(lease, lease.attempt_id)
            return receipt_raw
        except Exception:
            raise _fail() from None
