# R85 — Cutover observation failure provenance (design)

**Decision:** runner-only diagnosis, unanimously recommended by Architecture, QA, Infrastructure and CI/CD in [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6703862467). **Status:** prospective CODE_ONLY design; no physical Cutover permission.

## Intent and evidence

The READ_ONLY `cutover-a-observe` workflow run #815 failed without a terminal READY receipt. Its runner discarded SSH stderr and did not record the exit-code category, so the physical cause is unknown. A distinct later inspection #816 confirmed the original controller RUNNING_HEALTHY, probe #807 ABSENT, seccomp ABSENT and observer_writes=0. That smaller inspection cannot explain #815.

**Goal:** make a future observation distinguish a transport/timeout failure from a *strictly recognized* host rejection, without exposing host diagnostics, private coordinates or any new effect. **Non-goals:** reconstruct #815 retrospectively, alter host checks, retry #815, change GO_B/Cutover, inspect BLACKBOX, touch Docker/volumes, implement Telegram or real Boca navigation.

## Alternatives considered

1. **Runner-only fixed-code classifier (chosen):** preserve the existing host program, SSH argv and protected ZIP bytes. Capture its stderr privately under a hard file-write limit, parse only exact whitelisted literal failure messages and publish fixed categories. A dynamic or malformed message stays UNVERIFIED. This has the smallest impact.
2. **Typed host failure receipt (rejected for R85):** stronger structured provenance but changes `host_first_deploy.py` inside both protected full and worker ZIPs, requiring renewed image/recovery compatibility reviews.
3. **New observer/SSH path (rejected):** duplicates host checks and creates a second route without evidence of need.

## Interface and trust contract

- New `scripts/check_cutover_observe_diagnostic.py` is a **runner-only** parser with CLI `EXIT_CODE STDOUT_PATH STDERR_PATH` and a pure `classify` function. Reuse the existing strict O_NOFOLLOW/regular/owner/inode/size-check reader in `scripts/check_infrastructure_diagnostic.py`; no duplicated file-reader logic.
- A single `timeout 180s ssh ...` from the *existing* workflow step keeps its exact host argv, STDIN, environment, protection and sequence. `umask 077` protects two short-lived runner captures; a subshell `ulimit -f 8` bounds each output file at no more than 8 KiB. The stderr file is deleted by an EXIT trap and is never printed or uploaded.
- For exit 124/137 print `class=TIMEOUT`; for 255 `class=SSH_255` (not a proof of network fault). For exit 1, only when stdout is empty and the entire stderr is one **byte-for-byte reviewed** literal `BOCA_NO_GO: ...\n`, print `class=HOST_VALIDATION reason=<fixed code>`. All others produce `class=UNVERIFIED reason=UNVERIFIED`. All outputs remain `state=NO_GO host=UNVERIFIED cutover=NO_GO no_retry=1`, with no raw messages.
- **Additional deterministically reproduced latent defect:** the current canonical `READY` contains three full OCI digests, a 64-hex legacy CID, two 40-hex source SHAs and fixed fields: exactly **710 bytes including LF**. The old runner rejects `len>640` even though that is the *required* success string. This was not the cause of #815, whose SSH already exited nonzero. For exit zero, require empty stderr and an exact 710-byte, single-LF, ASCII stdout before letting the existing exact-field READY parser run. The parser reads **at most 711 bytes**; all existing field comparisons and emitted host bytes stay unchanged. Any anomaly is NO_GO, no fallback acceptance.
- Classifier output is a report of a known message **claimed by the remote command**, not independent proof of present host state. No error category authorizes a preflight, GO_B, PREPARE, APPLY, repeat or cleanup.

## Test and delivery requirements

- RED→GREEN behavioral tests of the actual classifier: recognized vs unknown literal, rc priority, stdout-forged READY on nonzero, symlink/hardlink/oversize/mutating files, multiline/Unicode/ANSI/NUL/CR/secret injection, zero-exit stderr and **709/710/711 boundaries**.
- Exercise the actual workflow Bash step with fake SSH in a disposable temp directory, proving one call, exact fixed inputs and no host activity. Verify bounded redacted summary and that success READY remains byte-identical.
- Keep protected full, preflight and recovery ZIP byte-identical to R84; leave owner browser BLACKBOX, host scripts, GO_B, cleanup and all safety gates unchanged. Run frozen lock, Ruff, mypy, full pytest and repo policy before one consolidated PR push and exact-SHA 4/4 Actions.
- Reconcile README, ADR0194, RCA #417 and issue #45 with distinct code, release and physical statuses. A new SHA needs a new protected release if future host observation is authorized; PR checks alone do not authorize Cutover.
