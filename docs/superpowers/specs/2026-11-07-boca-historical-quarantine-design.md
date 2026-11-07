# Cutover V3: exact, attested historical-image quarantine

Date: 2026-11-07 ART. Issue owners: #417 (RCA), #45 (release).
Status: design for CODE_ONLY review; no authority to bypass host acceptance.

## Physical finding

The READ_ONLY run #862 (`42415370909`) attested a healthy old controller on
`127.0.0.1:8443`, no stage/candidate/worker, and one unreferenced image
`sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`.
The historical release #41559973013, artifact #13196392925 and source
`0e830e3eed941de1da70cef8b42bda9f20258b65` identify its immutable digest
`sha256:7afe5429e34bd39b289e9d1da700fd5cd436cd2bdd413a2c4f8039829f1d034e`.
Its OCI `source` field is absent; the generic planner therefore correctly
classifies it as **uncertain**. The attempted dedicated retirement #746
(`42261978336`) returned exit 3 without a verified removal ACK; do not retry.

The V3 backend currently rejects this uncertainty before irreversibly retiring
the old controller and again after commit in the mandatory cleanup finalizer.
Re-running Cutover unchanged would knowingly reproduce an independent gate
failure and could leave a new failed attempt's residue.

## Decision and rejected alternatives

1. **Chosen:** narrow, explicit **forensic retention** of that one image,
   conditioned on exact immutable ID, only digest, exact release revision,
   expected size, zero tags/foreign aliases, zero container references and a
   fresh inventory throughout the same protected Boca lease. A V2 cleanup
   receipt must name the retained image and historical evidence. Both precommit
   and finalizer must apply the same proof; all other uncertain resources
   remain blocking, and unrelated/foreign host resources are never inspected.
2. Re-running the historical destructive retirement #746 is rejected:
   there is no verified deletion ACK or newly proven root cause.
3. Globally treating Boca-prefix images as trusted, suppressing unknowns, or
   granting generic `preserve_images` acceptance is rejected: none proves
   identity or protects shared Docker resources.

This is an **explicit, narrowly limited exception** to the owner rule that
obsolete Boca images must be deleted after success. It is not literal
compliance with zero obsolete images: the receipt must expose the retained
image. The exception applies only to this exact historical R46 artifact,
requires the existing independent evidence, and must be re-reviewed if any
metadata, references, Docker topology, or host identity changes.

## Contract and acceptance

- Keep source modules, existing planner and single V3 workflow; no new host
  commands or deploy path, privilege, port, volume, or key access.
- Add a narrowly typed historical-retention proof computed from a fresh
  rootless image inventory and the minimal public provenance observer.
- The precommit guard checks that proof before protecting the exact image
  from the generic planner's unknown classification; unknown additional
  images still prevent original retirement.
- The finalizer re-attests the same image **at every inventory probe** under
  the held lease, then preserves its exact ID from deletion. A missing/drifted
  image or a shared reference is a failure, never a successful cleanup.
- All actual Boca attempt residue is subject to the unchanged bounded exact-ID
  cleanup, before/after disk+inode checks, and absence verification.
- The host emits canonical cleanup receipt V2 with `retained_attested`; the
  runner independently validates the fixed fields. All historical V1 receipts
  remain byte-compatible and valid; a forged V2 or V1 with V2 fields fails.
- Tests cover the approved case and mismatched ID, digest, revision, alias,
  reference, missing image, extra unknown, topology drift and altered receipt.
- Green unit CI is CODE_ONLY, not a deploy claim. A fresh dual image release
  from exact merged main, PR0, the protected V3 dispatch and physical
  controller/passkey/cleanup receipt are still required for BETA acceptance.

## Expert review

Architecture/DevOps (`v3_cutover_gate_audit`) and image provenance reviewer
(`v3_image_provenance_audit`) both recommended this proof-bound retention,
independently, while refusing a blind retry of #746. No dissents recorded;
the implementation and complete QA still require independent review.
