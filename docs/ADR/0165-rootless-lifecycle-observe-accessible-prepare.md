# ADR 0165 — observador rootless READ_ONLY y PREPARE accesible (#366)

**05/11/2026 ART · DRAFT / CODE_ONLY / host NO_GO.**
Integración única en candidato #319. No hubo SSH ni despliegue.

## RCA de accesibilidad

El PREPARE de #352 exigía introducir manualmente un campo protected_action_context
base64url de 1–2 KiB con IDs Docker, config hashes, mountpoint y acción. Tincho
utiliza Samsung con Voice Access: construir ese JSON no es operativo y,
además, un ID escrito manualmente no certifica su estado en el droplet.

Las imágenes y SHA vienen de dos manifests inmutables y main atestados en
GitHub Actions. Los IDs, config hashes, browser attempt, sender opcional y
data mountpoint se obtienen del Docker **rootless Boca UID10001 observado**.
La acción se deriva de la única REQUESTED del ledger legacy.

## Decisión: PREPARE y APPLY, sin tercer dispatch

1. Tincho solicita START/STOP desde Chrome; el panel registra REQUESTED
   sin actuar físicamente.
2. Ejecuta protected-go-prepare con el contexto vacío. El runner
   autentica main/actor/release y genera un pequeño JSON interno de seis
   campos: version=boca-lifecycle-observe-v1, source_sha, controller_image,
   worker_image, release_run_id y observe_run_id=GITHUB_RUN_ID actual.
3. En **una llamada host READ_ONLY** el ZIP/memfd protegido ejecuta
   lifecycle-observe con un único argumento base64url canónico generado
   internamente; abre flock Boca y observa Docker rootless exacto sin
   modificar contenedores ni aplicaciones.
4. El código exige 2 servicios controller/browser-worker, o 3 si existe
   Telegram sender OFF/ON; coteja etiquetas Compose, IDs, repositorio GHCR,
   hashes, red, usuarios, UID10001, montajes y único puerto 127.0.0.1:8443.
   No inspecciona un daemon con componentes ajenos a Boca.
5. Consulta **SQLite legacy modo=ro + PRAGMA query_only=ON** con esquema
   0001–0007, cero schema 0008 y exactamente una intención vigente REQUESTED.
   Abre una transacción de lectura, reobserva el estado del componente y
   comprueba de nuevo el mismo intent. No REQUEST/CLAIM/ACK, no migración,
   no CREATE, no DELETE y ningún efecto sobre el motor/Chromium/Telegram.
6. Emite **una sola línea JSON pública canónica** de schema PREPARE v1
   (version, kind=lifecycle, source_sha, controller_id/image, worker_id/image,
   browser_attempt, controller/worker_config_hash, data_mountpoint,
   expected_component/target y quartet sender opcional). No incluye
   attempt_id, prepare_run_id, token, PIN ni credenciales.
7. Workflow owner #352 revalida la salida contra manifests y actor,
   genera automáticamente token largo y artifact de APPLY y muestra
   referencia PREPARE corta para copiar con la voz. APPLY es un segundo
   dispatch humano con GO independiente. El observador jamás otorga GO.

## Frontera de confianza y NO_GO

- El contexto host de seis campos se construye desde Actions; no es
  un formulario ni una capacidad arbitraria de Chrome.
- El host obtiene los IDs desde Docker y compara imágenes/procedencia
  inmutables del runner, luego vuelve a atestarlos mediante RootlessLifecycleProbe.
  Config hashes y browser attempt son **valores observados de labels
  contrastados contra estado físico**, no una firma criptográfica del
  deployment histórico; el GO y la revalidación en APPLY siguen obligatorios.
- Faltante de rootless UID10001, contenedores extraños, mountpoint
  no probado, archivo legacy owner0600 inaccesible, falta REQUESTED,
  múltiples pendientes, clock/manifest ambiguo => NO_GO, cero falso token.
- La lease canónica utiliza observe_run_id de PREPARE; su archivo
  cooperativo de lock vacío es el único posible metadato de exclusión,
  sin alterar datos o SQLite. No hay writes app, Docker, backups ni
  cambios a BLACKBOX, Porota, otros servicios o puerto.
- Chromium RUNNING+UNHEALTHY puede observarse para STOP si bot STOPPED
  y controller HEALTHY; bot START/Chromium START mantienen health gate.
- Un PREPARE observado NO prueba ACK físico ni sesión Chrome/Telegram.
  Sólo APPLY posterior bajo GO, release, lease y marker PREPARE O_EXCL
  puede certificarlo, con recibo terminal del host.

## Ownership y QA

Issue #366, ADR0165, módulo nuevo host_lifecycle_observe.py y
test_host_lifecycle_observe.py. Ajustes acotados exclusivamente a
scripts/build_protected_boca_bundle.py,
scripts/boca_protected_memfd_bootstrap.py y
tests/test_protected_boca_bundle.py para permitir ZIP/memfd stdlib-only.

YAML y scripts/check_protected_go_prepare.py son de #352: **no se editan**.
Test-first offline: cuatro acciones, sender OFF/ON, Chromium STOP degradado,
START NO_GO, source/digest/config drift, container ajeno, doble REQUESTED,
schema legacy0008, mount inexistente, formato/duplicados, sin write DB,
ZIP python -S, BLACKBOX excluida. QA exact SHA/Actions obligatorio
antes de trasladar los seis paths al candidato único #319.

No host real, compra/reserva, Telegram externo, backup, deploy ni GO.
Seguridad adicional P2 según orden de Tincho; aislamiento Boca sigue P0.
