# ADR 0025: evaluate official Python Alpine image under the strict scan

**Status:** Proposed experiment for issue #54, 2026-10-28. No deployment.

Bookworm produced 61 OS HIGH/CRITICAL findings, including two CRITICAL;
the Trixie candidate #53 reduced that to 44 HIGH and no CRITICAL but still
failed the unchanged gate. This sibling PR evaluates a smaller official
Python 3.12.15 Alpine 3.24 image, pinned to its multi-architecture index:
`sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d`.
The digest came from Docker Hub's tag API; it is not the amd64 child digest.

Alpine uses musl rather than glibc. The Python cryptography project publishes
musllinux wheels, but this repository must actually build and exercise the
vault encryption round trip and an in-memory SQLite query in the resulting
image, alongside the source unit tests, before considering the variant.
The Dockerfile changes the user/group creation to BusyBox's
`addgroup` and `adduser`; nonroot UID/GID 10001, no published port and
simulation-only runtime remain unchanged. The strict Trivy scan of the final
image still fails on any HIGH or CRITICAL OS/library finding. A smaller
finding count is an observation, not a security approval.

This branch includes the scanner from #49 and is stacked directly on the
corrected lock #51/#2, so the scanner and viable base can pass as one review
candidate. #49's standalone Bookworm scan remains evidence of a failed gate.
#23's independent Dockerfile hardening
and lock-based build are not part of this experiment. If Alpine is selected
after review, those controls need a separate compatible integration and
image scan on the final exact SHA/digest. There is no deploy or real Boca
interaction.

Sources: [official Python image manifest](https://github.com/docker-library/official-images/blob/master/library/python),
[Docker Hub tag API](https://hub.docker.com/v2/repositories/library/python/tags/3.12.15-alpine3.24),
[cryptography installation](https://cryptography.io/en/stable/installation/),
[Docker musl/glibc considerations](https://docs.docker.com/dhi/explore/security-concepts/glibc-musl/).
