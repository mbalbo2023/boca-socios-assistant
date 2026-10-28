# ADR 0001: Python, SQLite, isolated Docker Compose

Status: Accepted for foundation, 2026-10-28.

Decision: Python 3.12, typed modular architecture, SQLite WAL in a
dedicated Compose named volume, external AES-GCM master key, GitHub Actions
for CI and only future authorized deployments. Compose project name
boca-socios, resource caps and zero host port exposure.

Reason: a small memory-bounded controller with explicit DB invariants and
no runtime or import dependency on unrelated workloads.

Consequence: heavy browser workloads are not guaranteed to fit. They must
be separately measured/isolated before any deployment.

