# ADR 0167 — Same-workflow GO_B for Boca Cutover A and official import

Status: CODE_ONLY DRAFT, issue #371. No physical GO, host deploy, purchases or reservations.

## RCA
Legacy Cutover A and official notice Environment GO SHA was bound to an UNKNOWN future
GITHUB_RUN_ID before dispatch. With protected Environment reviewer configuration
unreadable through the connector (and previously reported disabled), the old
preflight was impossible to authorize beforehand. An input boolean is not GO.

## Protocol B: one workflow, two dispatches, 25 inputs unchanged

1. PREPARE = operation cutover-a-apply or official-notice-import with empty
   protected_action_context. Runner derives main source SHA from github.sha and
   uses a unique real successful image-release Actions run plus immutable controller
   and browser manifests to derive target GHCR digests/run ID. Missing/ambiguous
   evidence is NO_GO, not "latest" by timestamp.
2. One Boca-only READ_ONLY rootless ZIP/memfd host observation (#373) attests actual
   CID/source/image/config labels, localhost:8443, owner UID10001, volumes and
   topology under an existing single cooperative lock. It may coordinate lock
   metadata under /run/user/10001; Docker/application/data mutations are zero.
   Historical original release ID is separately authenticated through GitHub
   original source SHA + GHCR artifact, never inferred from Docker labels.
3. Official public news has multiple valid source runs. Tincho supplies at most
   one short official_news_run_id, not seven hashes or controller CID; runner
   derives exact artifact ID, GitHub source SHA, ZIP/JSONL/HTML hashes and
   observed UTC from reviewed public news receipt.
4. PREPARE publishes canonical public 15-key receipt and original source
   coordinates, two-day artifact retention. Review GO SHA =
   SHA256(underlying operation-specific bytes + canonical receipt), bound to
   PREPARE run ID, source/owner/ZIP/manifests/CID/Compose, 24h TTL.
   No host effects and no independent GO needed in PREPARE.
5. APPLY = separate dispatch of SAME operation, protected_action_context is
   ONLY prior PREPARE GitHub run ID decimal. GitHub GET must prove completed
   success, owner, main source SHA/ref, run_attempt1 and immutable artifact;
   runner rechecks all current/historical release, public source and ZIP hashes.
   Protected Environment separately supplies EXACT reviewed GO digest. Runner
   stages three 0600 O_EXCL files; native reviewed host preflights also reverify.
6. ONLY APPLY may SSH once under same Boca lease; Cutover ZIP receives
   BOCA_CUTOVER_A_APPROVED_GO_BINDING_SHA256 from runner-validated protected
   file, never dispatch. Official uses runner-host-command-prepared; both backends
   consume O_EXCL+fsync PREPARE replay marker on Boca named volume before effect.
   Terminal ACK is mandatory, Cutover additionally publishes/validates two-line
   BOCA_CUTOVER_A_POSTFLIGHT bytes+inodes/IDs (issue #372); never blind retry/prune.

## Restrictions and blockers
- Issue #373 PR #375 inventory observer must have 4/4 QA GREEN and be overlaid
  into the unique #319 candidate; code-only #371 alone does not prove host access.
- Issue #372 postflight+cleanup checker must remain exact, with real before/after
  disk and inodes, safe cleanup IDs only, retained_uncertain=0; foreign Docker
  applications (Porota etc) are untouchable.
- Predeploy capacity/CPU/RAM/free disk and loopback:8443 must remain checked by
  reviewed host backend; no new ports/HTTPS, BLACKBOX inspection, or backup.
- Missing independent Environment GO, drifted main/owner/source/CID/manifests/
  ZIP/Compose/UTC, missing historical release or multiple candidates => NO_GO.
- Six old install routes and Telegram physical phase2 still NO_GO, no permission
  broadening, no host dispatch from PR validation.
- Exact Environment reviewer settings are NOT readable by current connector;
  physical APPLY requires genuine owner-controlled GO separate from input.
- Android Voice Control: blank PREPARE; copy one short run ID for APPLY. No
  terminal, JSON/base64, credentials, PIN or 64-char manual hashes.

## QA
Unit tests require canonical single-receipt, strict GET success/source/owner,
unique immutable release, exact observer CID, 25 input limit, PREPARE SSH
READ_ONLY only, APPLY exact independent GO/host ACK, no original v1 bypass.
PR CI must be 4/4 GREEN with protected host SKIPPED. Runtime Samsung and
droplet proof require separate true owner GO after code integration.
