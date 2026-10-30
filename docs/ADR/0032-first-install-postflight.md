# ADR 0032: verify the installed controller before declaring first-install success

**Status:** Proposed for issue #70, 2026-10-29. No host operation performed.

The first-install helper already validates the reviewed Compose model and the
image digest/source revision before creating the key. A healthy Docker
healthcheck proves only that the process can answer its local probe; it does
not independently prove that the running container still has the approved
image reference, Compose identity, dormant engine, resource limits or secret
file metadata.

After `docker compose up --wait` and its health check, run the same strict
read-only inspection used by the manual diagnostic (#68): check the staged
Compose hash and owner-only key metadata without reading the key, then
validate the running container ID, image digest and revision, project/service
labels, nonroot UID, simulation and engine-off environment, health, CPU/RAM/PID
limits, read-only root, an explicit empty port-binding map and no privileged
mode. Missing or malformed port metadata is NO-GO. Only
then print `BOCA_DEPLOY_PASS`.

If a command, metadata read, JSON parse, unexpected metadata type/field or
contract check fails after the container starts, stop **only** the Boca
controller. Preserve its key, image and volume for a separately reviewed
diagnosis; do not retry the first
installation, delete data, or modify another workload. The diagnostic itself
remains a separate manual read-only operation. The host preflight and
GitHub environment/review/authorization gates remain mandatory.

Unit tests cover success ordering and the stop/preserve boundary for a
contract mismatch, malformed Docker JSON and metadata, and a file read
failure. This is synthetic evidence; a green PR does not prove actual droplet
state.
