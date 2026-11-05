# ADR 0169 - Observacion READ_ONLY rootless de Cutover A e import oficial

**2026-11-05 ART, issue #373, DRAFT CODE_ONLY. Host NO_GO.**

## RCA y accesibilidad

Cutover A exigia ingresar manualmente source SHA, digest GHCR, SHA del Compose
historico y CID64. El recibo cutover-a-observe no se subia como artifact.
Import oficial tambien requeria un CID exacto. El observador de lifecycle
ADR0165 exige REQUESTED y no sirve para obtener coordenadas de import.
Tincho utiliza Samsung Voice Access: no debe copiar ni calcular hashes.

## Dos modos en el unico ZIP/memfd autenticado

- cutover-inventory-observe: un solo controller legacy RUNNING/healthy.
- official-inventory-observe: dos/tres servicios Boca modernos, controller,
  browser-worker y sender opcional.
- Ambos tienen selftests stdlib -S sin Docker ni host.

El runner crea un argumento base64url de JSON canonico con SOLO:
version, target_source_sha, target_controller_image, target_browser_image,
target_release_run_id, observe_run_id. No es input del usuario ni un GO.
Las versiones son boca-cutover-inventory-observe-v1 y
boca-official-inventory-observe-v1.

Bajo la flock unica Boca en UID10001/GID10001, se capturan DOS inventarios
de un daemon rootless dedicado, cuyo lector rechaza cualquier container,
network o volume no Boca sin inspeccionarlo. Se examinan unicamente campos
Docker permitidos, nunca Config.Env, password, HAR, SQLite o Bot API.
La lease puede crear un archivo de lock vacio 0600 en /run/user/10001:
no se asegura cero escrituras de metadatos, sino cero cambios Docker/DB/app.

## Resultados observacionales (no GO)

Un PASS imprime una sola linea JSON canonica ASCII hasta 2048 bytes.
Un FAIL solo publica state=NO_GO a stderr, sin identificadores host.

Cutover: kind=cutover-inventory, legacy_controller_id CID64,
legacy_source_sha OCI SHA40, legacy_image_ref GHCR digest,
legacy_image_id Docker sha256, legacy_compose_config_hash label SHA64;
ademas version, observe_run_id, target_source_sha, target_release_run_id,
compose_project/service, data/key/owner volume, port=127.0.0.1:8443,
controller_health y observed_at_utc ISO8601 UTC Z.

Official: kind=official-inventory, version, observe_run_id,
source_sha, release_run_id, controller_id/image, worker_id/image,
browser_attempt, controller/worker_config_hash, data_volume,
port, observed_at_utc, y sender quartet opcional
sender_id/config_hash/attempt_id/state. No exige REQUESTED ni
ejecuta engine status; solo inspecciones de Docker.

Legacy exige imagen revision, cgroup 0.5CPU/256MiB/64PIDs, UID10001,
mounts data/key/owner, bridge Boca, Compose labels, rootfs RO,
puerto 127.0.0.1:8443 y ausencia de Browser Worker. Official exige
2/3 servicios exactos con imagen/revision del target, redes y mounts
revisados en ADR0165, aun si engine/Chromium estan parados.

## Frontera de confianza GitHub

**El host NO contiene legacy_release_run_id ni SHA256 del archivo Compose**.
El label com.docker.compose.config-hash NO es el SHA256 de compose.beta.yaml.
Workflow #371 debe consultar GitHub a partir de legacy_source_sha, revisar
bytes del Compose historico, localizar un unico release exitoso y
contrastar su artifact source/digest con la imagen observada. Si falta
cualquier cruce o hay varias fuentes ambiguas: NO_GO, sin pedir IDs a Tincho.
El recibo PREPARE no ejecuta Cutover/import ni autoriza mutaciones; para
APPLY hacen falta GitHub receipt exacto, GO independiente, lease, marker
O_EXCL single-use y ACK fisico.

## Regla84, QA y limites

Owner #373: nuevo modulo/test, ADR0169 y solo cambios aditivos en
builder/bootstrap y tests de ZIP. YAML owner #371, cleanup/backend #372.
Tests fakes para identidad/deriva/foreign/roles y smoke Python -S. Ninguna
accion en servidor, BLACKBOX, Porota, otras apps, backups, compras, reservas,
puertos nuevos o HTTPS. Rama satelite DRAFT no despliega nada.

## A45-R32 — incompatibilidad del adaptador real (05/11/2026 ART)

El PREPARE protegido [run #42073058087](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42073058087) termino **NO_GO** (exit 3) en el paso de lectura rootless, sin receipt fisico; la salida de error fue suprimida, asi que no es posible certificar el primer error host. La inspeccion del codigo si descubrio una incompatibilidad determinista: el adaptador de produccion delegaba a un lector exclusivo de limpieza Docker, cuya allowlist no acepta `Config.Image`, `HostConfig.*`, `State.Health.Status` ni `Mountpoint`, requeridos por los observadores.

El fix-forward DRAFT [PR #378](https://github.com/mbalbo2023/boca-socios-assistant/pull/378), RCA-373, agrega una proyeccion independiente de campos exactos para lectura Docker UID10001 rootless, sin tocar el lector ni la allowlist de limpieza. El adaptador valida ID SHA64 de container y volumen Boca exacto, rechaza `Config.Env` y campos fuera del inventario, y el test `tests/test_host_cutover_inventory_observe.py::test_real_adapter_uses_only_explicit_rootless_inspect_fields` ejercita el adaptador real. Solo codigo/QA; no es un PASS fisico, GO, merge ni release. Nuevo PREPARE exige CI GREEN, integracion revisada y release nuevo SHA.
