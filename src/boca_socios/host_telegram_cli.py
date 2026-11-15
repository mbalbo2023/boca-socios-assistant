"""Protected Telegram CLI."""

from __future__ import annotations

import re
import signal
import sys
from collections.abc import Sequence
from functools import partial

OPERATIONS = {
    "telegram-schema-observe": "observe",
    "telegram-migrate": "migrate",
    "telegram-prepare": "prepare",
    "telegram-activate": "activate",
    "telegram-sender-recover": "recover",
    "telegram-renew-stage": "renew",
    "telegram-complete-sender": "complete",
}
_NO_GO = b"BOCA_TELEGRAM_HOST state=NO_GO reason=arguments_or_receipt_unverified\n"


def _interrupted(_number: int, _frame: object) -> None:
    # Interrupt through finally; forced kill needs explicit no-send recovery.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise RuntimeError("telegram_protected_transport_interrupted")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ["selftest"]:
            from boca_socios.host_telegram_backend import (
                activate_installed_telegram,
                migrate_installed_telegram,
                prepare_installed_telegram,
                renew_installed_telegram_stage,
                verify_backend_receipt,
            )
            from boca_socios.host_telegram_sender import activate_installed_sender

            assert all(
                callable(item)
                for item in (
                    activate_installed_telegram,
                    prepare_installed_telegram,
                    migrate_installed_telegram,
                    verify_backend_receipt,
                    activate_installed_sender,
                    renew_installed_telegram_stage,
                )
            )
            print(
                "BOCA_TELEGRAM_HOST state=INSTALLED_CLOSURE_READY host=untouched sender_action=NONE"
            )
            return 0
        verify_only = args[:1] == ["verify-receipt"]
        if verify_only:
            args = args[1:]
        if len(args) != 4:
            raise ValueError("arguments")
        operation, source_sha, workflow_sha, attempt_id = args
        if (
            operation not in OPERATIONS
            or re.fullmatch(r"[a-f0-9]{40}", source_sha) is None
            or re.fullmatch(r"[a-f0-9]{40}", workflow_sha) is None
            or re.fullmatch(r"[1-9][0-9]{0,19}", attempt_id) is None
        ):
            raise ValueError("arguments")
        from boca_socios.host_telegram_backend import (
            TelegramBackendError,
            TelegramBackendReceipt,
            _execute,
            activate_installed_telegram,
            migrate_installed_telegram,
            prepare_installed_telegram,
            renew_installed_telegram_stage,
            verify_backend_receipt,
        )

        if verify_only:
            raw = verify_backend_receipt(
                sys.stdin.buffer.read(1025),
                attempt_id=attempt_id,
                expected_source_sha=source_sha,
                operation=OPERATIONS[operation],
                allow_failure=True,
            )
            print("BOCA_TELEGRAM_HOST " + raw.decode("ascii"))
            return 0
        from boca_socios.host_boca_cleanup import protected_boca_job_lease

        signal.signal(signal.SIGTERM, _interrupted)
        signal.signal(signal.SIGHUP, _interrupted)
        status = 0
        entered = False
        try:
            with protected_boca_job_lease(attempt_id) as lease:
                entered = True
                if operation in {"telegram-sender-recover", "telegram-complete-sender"}:
                    from boca_socios.host_telegram_sender import (
                        complete_installed_telegram_sender,
                        recover_installed_sender,
                    )

                    resume = (
                        recover_installed_sender
                        if operation == "telegram-sender-recover"
                        else complete_installed_telegram_sender
                    )
                    result = resume(
                        lease=lease,
                        expected_source_sha=source_sha,
                        workflow_sha=workflow_sha,
                        attempt_id=attempt_id,
                    )
                    receipt = TelegramBackendReceipt(
                        OPERATIONS[operation],
                        attempt_id,
                        source_sha,
                        result.state,
                        result.restoration,
                        result.sender_state,
                    )
                else:
                    execute = {
                        "telegram-schema-observe": partial(
                            _execute, "observe", reader=None
                        ).__call__,
                        "telegram-migrate": migrate_installed_telegram,
                        "telegram-prepare": prepare_installed_telegram,
                        "telegram-activate": activate_installed_telegram,
                        "telegram-renew-stage": renew_installed_telegram_stage,
                    }[operation]
                    receipt = execute(
                        attempt_id,
                        lease=lease,
                        expected_source_sha=source_sha,
                        workflow_sha=workflow_sha,
                    )
        except TelegramBackendError as error:
            receipt, status = error.receipt, 3
        except Exception:
            receipt = TelegramBackendReceipt(
                OPERATIONS[operation],
                attempt_id,
                source_sha,
                "FAILED_STATE_PRESERVED" if entered else "PREFLIGHT_FAILED",
                "INDETERMINATE" if entered else "NOT_NEEDED",
                "UNVERIFIED",
            )
            status = 3
        raw = verify_backend_receipt(
            receipt.redacted_json(),
            attempt_id=attempt_id,
            expected_source_sha=source_sha,
            operation=OPERATIONS[operation],
            allow_failure=True,
        )
        sys.stdout.buffer.write(raw + b"\n")
        return status
    except Exception:
        sys.stdout.buffer.write(_NO_GO)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
