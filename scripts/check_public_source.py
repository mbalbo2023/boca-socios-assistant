"""One anonymous public HTTPS observation; source failure is an alert, not a deploy gate.

The response body, headers and exception details are intentionally discarded.
This script is only run by a manually dispatched Actions workflow, not by CI.
"""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

HOST = "bocasocios.bocajuniors.com.ar"
PATH = "/auth/login"
TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class Observation:
    observed_at: str
    color: str
    reason: str
    http_status: int | None


def _classify_status(status: int) -> tuple[str, str]:
    if status == 200:
        # A 200 can still be a challenge, placeholder or changed page.
        return "GREEN", "http_200_unverified"
    if 300 <= status < 400:
        return "YELLOW", "redirect_not_followed"
    if 400 <= status < 500:
        return "YELLOW", "public_access_limited"
    if 500 <= status < 600:
        return "RED", "server_error"
    return "YELLOW", "unexpected_status"


def observe(*, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Observation:
    """Send one GET to a fixed path; TLS verification and direct connection are mandatory.

    http.client never follows redirects or uses environment proxy settings.
    No request body, cookies, credentials or caller-supplied URL exists.
    """
    observed_at = now().astimezone(UTC).isoformat(timespec="seconds")
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(HOST, timeout=TIMEOUT_SECONDS, context=context)
    try:
        connection.request(
            "GET", PATH, headers={"Accept": "text/html", "User-Agent": "BocaSociosSourceStatus/1.0"}
        )
        status = connection.getresponse().status
    except TimeoutError:
        return Observation(observed_at, "RED", "timeout", None)
    except ssl.SSLError:
        return Observation(observed_at, "RED", "tls_error", None)
    except (OSError, http.client.HTTPException):
        return Observation(observed_at, "RED", "transport_error", None)
    finally:
        connection.close()
    color, reason = _classify_status(status)
    return Observation(observed_at, color, reason, status)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="One public source status observation").parse_args(argv)
    print(json.dumps({"target": "boca_public_login", **asdict(observe())}, sort_keys=True))
    # External availability is never a deploy gate. Code errors still fail the job.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
