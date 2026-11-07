# R95 implementation plan — STOP `-t` portability

1. R94 physical recovery #839 is CLEANED/VERIFIED; keep any **new** preflight/Cutover NO_GO. Record the design's alternatives and do not identify an unverified root cause as fact.
2. Make five existing strict synthetic STOP command assertions expect `("docker", "stop", "-t", "5", CID)`; run targeted tests RED against unmodified preflight code.
3. Add one synthetic CLI differential where `--time` would produce a deprecation warning and CID in stdout, while `-t` produces only a clean CID; full ACK mismatch continues fail-closed on any malformed output.
4. Change exactly one production argument in `_cleanup_exact`, retaining 20s timeout, ACK equality, one STOP, RM only after positive ACK and postflight. Run targeted GREEN, full `pytest -n 2`, Ruff/format/mypy/policy, protected ZIP limits.
5. Update ADR/Rule84 current docs and add R95 to the explicit protected FirstDeploy test selector with contract regression. Obtain 3 independent reviews, commit a separate branch/PR only after R94 stopped-only recovery #834 is physically VERIFIED (#839). Require four PR checks, two postmerge checks, release dual for new SHA, PR0 and new physically reviewed GO before any new preflight.

**Host operations are explicitly excluded from the code-change stage.**
