# R97 implementation plan — phase claims after a valid Cutover observation

**Spec:** `docs/ADR/0205-r97-cutover-failure-phase-claims.md`
**Base:** `origin/main` at `43edb1ae786b58ea832feb9e758fb99edc967d98`.
**Review focus:** no false host acceptance, no leaked host bytes, unchanged
positive ACK, no extra effects or inspection of protected browser modules.

## Task 1 — regression first

Files: `tests/test_cutover_a_go.py`.
Write tests covering a canonical GHCR/ID/SHA OBSERVE prefix and STAGE or
PREPARE_WORKER phase; preserve legacy phase-only case. Add rejections for
double/partial/altered/extra OBSERVE, forged terminal and private text.

Expected: `uv run pytest -q tests/test_cutover_a_go.py -k failed_ssh` fails
solely on the new canonical-prefix positive test, proving lost provenance.

## Task 2 — narrow parser correction

Files: `scripts/check_cutover_a_go.py`.
Add one exact bounded observation-line pattern, consume it once before the
existing optional POSTFLIGHT/phase handling, never synthesize `ACCEPTED`.

Expected: `uv run pytest -q tests/test_cutover_a_go.py -k failed_ssh` PASS.

## Task 3 — quality and factually bounded handoff

Files: `docs/quality/rca-lessons.json`, README current Cutover status if
needed. Register new deterministic regression without overwriting historical
fix PR attribution. Run Ruff, mypy, full pytest, policy checker; review final
diff independently. Publish one atomic commit/PR, 0 orphan PRs before release.

Expected: exact test suite, static quality and independent review GREEN.
Code-only integration alone is not a host GO; separate GHCR release, PREPARE,
Cutover and postflight evidence must validate physical BETA.
