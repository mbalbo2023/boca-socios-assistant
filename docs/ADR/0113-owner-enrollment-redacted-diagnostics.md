# ADR 0113 — Fail-closed phase diagnostics for real Chrome owner enrollment

**Status:** candidate PR #276, RCA #275. This ADR documents a code change;
the host and Chrome have **not** been retested with the proposed diagnostics.

## Evidence, 2026-11-02 ART

Real protected owner-prepare #304 succeeded with source SHA
`0e830e3eed941de1da70cef8b42bda9f20258b65`, release #298 and a
stopped rootless Boca daemon. Two successive owner-enroll attempts
[#305](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41566871210)
and [#306](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41568180039)
failed inside **Start disposable owner enrollment only on Boca loopback 8443**.
Both later selected Bocа-only cleanup and daemon stop steps were SUCCESS.
Neither reached the READY receipt. No passkey, panel or BETA deployment followed.

The **cause of the host start failure is unknown**. The known code/contract
defect is that the protected workflow redirected remote stderr to
`/dev/null` and deliberately suppressed every nonzero exit's detailed
response. It published generic NO_GO only, preventing reliable RCA.

## Reviewed diagnostic change

1. `_owner_enroll_start` annotates a **fixed, code-owned phase name**
   immediately before each existing call: coordinates, preflight, port,
   storage, image inventory, marker, pull, image provenance, storage
   continuity, public recipient, volume create/verify/permissions,
   network create/verify, container create/verify, and listener health.
   Exceptions during this phase become `owner enrollment phase=<code>`,
   never raw storage paths, SSH, Docker diagnostics or private values.
2. GitHub Actions holds **only the failed start's stderr** in an ephemeral
   private runner file. `owner_enroll_diagnostic` reads at most 2 KiB via
   no-follow regular-file access, accepts one exact line from a closed
   phase allowlist, and prints only that code. Invalid, multiline,
   malformed, absent or oversized content becomes `unclassified`.
   Neither raw stdout/stderr nor bearer URL/ciphertext is put in
   Step Summary, logs or artifacts.
3. The original failed job remains **red**. Existing unconditional
   Boca-specific staged-resource cleanup and dedicated-daemon stop remain
   in the same job. No retry is triggered, and no existing security,
   identity, digest, capacity, storage, Docker Engine, network or
   `127.0.0.1:8443` control is bypassed.
4. Tests cover closed codes, malformed/sensitive payloads, symlink denial,
   redaction of underlying exceptions, busy-port no-side-effect and
   protected workflow structure.

## Next admission gate

Do not rerun #305/#306 or try another Chrome URL with the old SHA.
Only after exact candidate PR checks and technical review, a new
main commit and matching image-release manifest, and explicit safe
host state should a **new one-shot key** be used for one protected attempt.
That attempt must emit `BOCA_OWNER_ENROLL state=READY` or its fixed
failure phase. A failure phase narrows investigation, **not** a root-cause
assertion. Request manual Chrome action only after READY and before the
900-second one-use deadline.

No changes to the unrelated Porota workloads, Docker daemon, reverse
proxy, other ports, backups, user data or real Boca logins are permitted.
