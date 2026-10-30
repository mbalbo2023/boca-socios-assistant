# ADR 0035: owner-dispatched read-only host preflight

**Status:** Proposed for issue #84, 2026-10-29. No host operation performed.

The rootless Docker boundary and host capacity cannot be inferred from a
GitHub-hosted runner. The single protected Boca workflow gains a manual
`preflight` operation, separate from `first-install` and `diagnostic`. It is
available only on the exact current `main` SHA to the repository owner, with
the protected `boca-first-deploy` environment, pinned SSH host identity and
fixed `controller` / 0.5 CPU, 256 MiB, 64 PID budget. It requires **blank**
image and release-run inputs, so it cannot publish or pull an image.

The standalone operation calls the helper's `observe` phase with no image;
`first-install` still calls its original `preflight` phase with a verified
digest. This separation prevents one mode from weakening the other's input
gate. Both check
the dedicated UID/path, Docker rootless socket, cgroup v2/systemd delegation,
architecture, aggregate free capacity and an empty Boca namespace. It does
not stage Compose, create a volume or key, pull an image, start a container,
read another workload, visit Boca or run a reservation. Its output has bounded
capacity facts and a PASS/NO-GO marker without secrets or database rows. The
workflow's other operations still require matching image digest and successful
release run and cannot use an empty image. A successful preflight is one
observation at one instant; it does not grant a subsequent install, prove
effective cgroup limits or substitute for SSH privilege review.

This operation remains undispatched until the objective gates are verified:
protected `main` and environment restrictions, exact-SHA green checks and
recorded agent technical review, a dedicated account and pinned SSH host
identity, capacity, and an authorized time window. The readiness variable
alone is insufficient. The owner's standing direction requires no additional
human approval once these gates pass; #91 still blocks any host dispatch.
