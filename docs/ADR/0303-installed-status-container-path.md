# ADR 0303 — Installed status reads SQLite in the controller namespace

## Status and scope

2026-11-15 ART. Narrow maintenance tracked in #518 after the R297 promotion.
The [four prior design votes](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889977546)
authorize the reader correction and its regression. Final code review and
exact-SHA CI precede a single corrected physical observation. This is not a
second product release, installation, admin provisioning or feature change.

## Observed installation and incident

PR #517 was merged as `5281efae7dafe89be047073796b3e0a7e19785ed`.
[Release 866](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43680526402)
published the immutable controller and worker images for that source.
[APPLY 1134](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43681576798)
returned `ACCEPTED`, `cleanup=ACCEPT`, `failed_phase=NONE`, `old_restored=false`.
The terminal receipt identifies controller
`dac696b916055c0385519ce1a6f3679bbb831d9ab8d757d2468841348eb9c848`
and worker
`6c9947b7ee819841a83daec3d27362421b93722637cdc2b01ff60c174f6cbef0`.

[ADMIN 1135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43682305029)
returned `PROVISIONED`, `sector_schema=2`, `legacy_writes=0`. Its Telegram
projection was `ABSENT`, `NOT_PAIRED`, sender `ABSENT` and human receipt
`UNVERIFIED`. [STATUS 1136](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43682391989)
then returned `NO_GO observer_writes=0`. Telegram preparation was not dispatched.
These results are distinct: the failed reader does not erase the accepted
installation, and deployment success does not substitute for postflight.

The failed run verifies main and the protected bundle before exiting. Its
bounded public output does not identify the first failing internal guard.
The namespace defect below is independently reproducible; it must not be
described as the uniquely proven cause of every check in that run until a
corrected physical observation supplies the missing evidence.

## Cause

`OnDemandInstallation.database_path` names the SQLite file in the host's
Boca Docker volume. That path participates in the installation fingerprint
and remains correct for host identity checks. The current-status reader
passed it as an argument to a program executed inside the exact controller
container. The controller mounts that volume at `/data`, so its SQLite path
is `/data/boca.sqlite3`; the host path is not its filesystem path.

The previous regression used one temporary filesystem path both as the host
binding and as the database opened by a subprocess. It tested the ledger but
did not represent the different mount namespaces, allowing this defect.
The offline reproduction preserved database bytes and inode and demonstrated
the old program's failure when supplied the host path.

## Decision

The in-container program receives exactly one argument: the existing
host-derived fingerprint. Tuple unpacking rejects missing or extra arguments.
It opens the fixed `/data/boca.sqlite3` with `readonly=True`; a caller cannot
supply another path. The Docker invocation removes only its former database
path argument. The host binding and fingerprint calculation do not change.

Preserve exact controller identity, UID `10001:10001`, lease, mount and physical
attestation, both stable ledger/physical samples, binding reread, schema/inode
checks, bounded output and the canonical schema-3 receipt. Historical STOP
classification and all existing refusal conditions remain intact.

The reviewed observer is transported in the existing installed-admin archive
by GitHub Actions. The controller helpers that it imports already exist in
the installed image. The workflow source and installed product source are
deliberately distinct fields in the existing status contract. No new image,
release, APPLY, admin operation, schema, cap or access exception is needed.

## Regression and archive evidence

The test executes the exact in-container program. Its only filesystem seam
requires `/data/boca.sqlite3` and `readonly=True`, then delegates to the real
ledger helper and real SQLite database. The host binding uses a different,
nonexistent path. It exercises the actual Docker-argument construction,
host-derived fingerprint, two reads, unchanged inode/bytes and six invalid
argument cases that must open no ledger at all.

Before production edits, the affected new cases produced four failures and
four passing negative controls. After the three-line production correction,
all 36 cases in `test_r294_installed_status.py` passed, including the previous
28 ledger, verifier, historical STOP and race cases. RCA-518 records the
three regression selectors; full exact-SHA CI remains the integration gate.

Only the full and installed-admin source sets include this changed module.
Measured deterministic archives, with existing membership and limits:

| Archive | Members | Source bytes | ZIP bytes | Source limit |
| --- | ---: | ---: | ---: | ---: |
| Full | 47 | 1,155,362 | 274,695 | 1,158,144 |
| Installed admin/status | 32 | 851,732 | 207,502 | 900,000 |

Full SHA-256:
`066214cb4ae6a84f9e88973e38e58f7780dccf9556d1beb75cfb7c3b3a500c0e`.
Installed-admin/status SHA-256:
`62ea45671ebe8af3521d2bd0c37026d956ce92e314346f99972fd19979aad494`.
The current full-bundle regression gains an explicit R298 pin and preserves
all historical pins. Neither bundle grows; no bound or reserve is relaxed.

## Physical continuation and limits

After merge and exact checks, perform one `boca-installed-status-observe`
from current main through the protected serialized workflow. Keep its
source/image/release inputs blank as specified by that operation. Verify the
actual terminal summary and its installed identities, not just Actions green.
Keep STATUS 1136 as failed evidence. A new NO_GO requires diagnosis, never an
automatic retry or a repeated installation.

Only after verified status, continue the already authorized `telegram-prepare`
against the same installed source and release 866 images. The existing
workflow proves that installed source's ancestry to the new workflow SHA;
no gate is bypassed. Preparation does not activate a sender, send a test,
transmit a ticket or prove pairing. Preserve SIMULATION_ONLY, all owner/key/data
volumes, BLACKBOX boundaries, caps and isolation from Porota and PPI Watch.

Private Samsung/WebAuthn acceptance and physical capacity for 50 contexts
remain separate, unproved items. Neither offline regression, CI screenshots
with synthetic fixtures nor these maintenance receipts certify those items.
