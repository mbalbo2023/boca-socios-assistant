# ADR 0047: preserve read-only SSH command arguments

**Status:** Proposed, 2026-10-31. Issue #123, PR #124.

## RCA

Manual inspection run 41254752250 reached the remote Python parser but lost
the empty image argument. Quoting a local shell argument does not preserve
its boundary across OpenSSH: SSH joins the command arguments with spaces and
the remote shell parses that command string. The parser consequently reported
a missing compose_sha. The observe path used the same defective transport.
Tests of the Python helper and the initial readiness gate did not exercise
this second shell parsing boundary.

## Decision and verification

For inspect-prerequisites and observe, build one POSIX shell command string
with Python standard-library shlex.join, then pass it as one SSH argument.
Keep the reviewed host helper on stdin. Empty arguments, spaces, quotes and
shell metacharacters retain literal values through the remote shell.
No SSH options, readiness variables, host helper, input validation, permitted
operations or effectful command paths change.

The regression extracts each actual workflow step, substitutes a local SSH
function that joins command arguments and invokes /bin/sh -c, and supplies a
harmless stdin argument recorder. It reproduces both failures on main and
checks the complete argv for empty, populated and metacharacter cases after
the fix. It opens no connection and does not run the actual host helper.
This tests transport, not SSH authentication, host readiness or deployment.
The first-attempt and current-main gates still require a fresh manual
read-only dispatch after merge; never rerun failed run 41254752250.

Installation, release, backup and real member data remain outside this change.
