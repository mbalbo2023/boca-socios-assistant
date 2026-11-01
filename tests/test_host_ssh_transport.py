"""Exercise workflow shell through OpenSSH's remote command string boundary."""

import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
SHA = "a" * 40
COMPOSE_SHA = "b" * 64


def _transport(step: str, image: str) -> list[str]:
    block = WORKFLOW.read_text(encoding="utf-8").split(f"      - name: {step}\n", 1)[1]
    script = textwrap.dedent(block.split("      - name:", 1)[0].split("        run: |\n", 1)[1])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        helper = root / "src/boca_socios/host_first_deploy.py"
        helper.parent.mkdir(parents=True)
        helper.write_text("import json, sys\nprint(json.dumps(sys.argv))\n", encoding="utf-8")
        (root / "boca-compose.sha").write_text(COMPOSE_SHA + "\n", encoding="utf-8")
        # OpenSSH joins command argv with spaces; the remote shell parses again.
        # This local shim uses no connection and executes only the stdin recorder.
        shim = (
            'ssh() { test "$1" = -F; shift 2; test "$1" = boca-target; shift; /bin/sh -c "$*"; }\n'
        )
        result = subprocess.run(  # noqa: S603 - fixed local shell, synthetic transport only
            ["/bin/bash", "-e", "-o", "pipefail"],
            input=shim + script,
            cwd=root,
            env={
                "PATH": "/usr/bin:/bin",
                "RUNNER_TEMP": directory,
                "BOCA_IMAGE_REF": image,
                "BOCA_SOURCE_SHA": SHA,
            },
            text=True,
            capture_output=True,
            timeout=3,
            check=True,
        )
        return json.loads(result.stdout)


def test_inspection_preserves_remote_argv() -> None:
    for image in ("", "sha256:example", "spaces 'quotes' ; $(printf injected)"):
        assert _transport("Inspect dedicated user prerequisites without Docker", image) == [
            "-",
            "inspect-prerequisites",
            image,
            SHA,
            COMPOSE_SHA,
        ]


def test_observe_preserves_remote_argv() -> None:
    for image in ("", "sha256:example", "spaces 'quotes' ; $(printf injected)"):
        assert _transport("Observe host capacity and Boca namespace without an image", image) == [
            "-",
            "observe",
            image,
            SHA,
            COMPOSE_SHA,
        ]
