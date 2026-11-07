# R96 — Recuperación Boca aislada de staging de Cutover #844

**Fuente de verdad:** #45 y #417; PREPARE #843 `42381545964`, APPLY #844 `42388694186`, reconciliación READ_ONLY #845 `42388994569`. **07/11/2026 ART.**

## Objetivo y evidencia

Retirar únicamente el stage inconcluso `cutover-a-42388694186`, sin reinstalar, detener, limpiar Docker ni tocar el controlador original, volúmenes de sesión ni sistemas ajenos. #845 observó `intent/result=PRESENT`, `terminal=NO_GO`, `cleanup=INDETERMINATE`, `original_restored=true`, `commit_started=false`, un único controlador original CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` saludable en `127.0.0.1:8443`, candidatos/workers 0, promoción ausente y stage presente con dos entradas raíz. La observación del marcador `/data` fue `UNREADABLE/DIRECTORY`; ello NO autoriza inferir su ausencia ni borrarlo. #843 se trata como consumido permanentemente.

## Enfoques y decisión consensuada

1. **Modificar los pins del recuperador histórico** `cutover-a-stage-recover`: mínimo diff, pero pierde distinción explícita entre incidentes y rompe sus pruebas de continuidad. No elegido.
2. **Nueva operación exacta** `cutover-a-stage-recover-844` que reutiliza sin cambios `scripts/host_cutover_stage_recovery.py`, `host_cutover_stage.discard_recovered` y el bootstrap memfd: elegido por QA/Arquitectura/Infra como frontera auditable, DRY y con un solo propósito.
3. Recuperador genérico que acepte cualquier ID o limpieza global: descartado por riesgo de borrar datos ajenos o permitir replay.

## Contrato del cambio

- Extender **solo** el workflow canónico `boca-first-deploy.yml` con el nuevo valor explícito de operación. La rama debe ser el `main` actual; la fuente se infiere de `github.sha`, sin aceptar referencias arbitrarias.
- Fijar inmutablemente los tres run IDs y el SHA histórico R95, y validar por GitHub API que #843 y #845 terminaron `success`, #844 `failure`, cada uno `workflow_dispatch`, actor `mbalbo2023`, repositorio exacto, intento 1, rama `main`, workflow exacto y tres `head_sha` históricos idénticos. Ejecutar el verificador tipado bajo Python optimizado (`-O`) sin perder ningún control. Revalidar el `main` NUEVO del recuperador antes del SSH.
- Asignar `BOCA-R96-STAGE-844-RECOVER-ONCE` como nombre del único dispatch, exigir histórico REST paginado completo con `gh api --paginate --jq` **sin** opción no disponible `--slurp`, decodificación JSON de páginas concatenadas, `total_count` idéntico inferior al límite de filtrado 1.000, suma de cada página exacta, IDs globalmente únicos y marcador perteneciente a su página, un solo marcador incluso entre SHAs, `GITHUB_RUN_ATTEMPT=1`, PR abiertos **cero**. Una segunda ejecución, página faltante o historia al límite = NO_GO pre-SSH.
- Formulario único: `operation=cutover-a-stage-recover-844`, `protected_action_context=42388694186`, `legacy_release_run_id=42381545964`, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`, **todos** los demás campos vacíos. No usar el GO_B viejo, ni PREPARE para otro APPLY.
- Reutilizar ZIP determinista por SHA y bootstrap memfd, bajo lease exclusivo Boca UID10001. Dentro del script existente, autenticar intent/result, dos snapshots idénticos, marcador de stage, inodo Compose y hashes, y borrar por nombres exactos solo los ficheros permitidos del stage de #844. Si existe `.part`, symlink, hash divergente o estado de Docker distinto: NO_GO sin supuestos.
- Exigir recibo físico único `BOCA_STAGE_RECOVERY state=STAGE_CLEARED ... docker_writes=0 foreign_resources_touched=false retry=NO_GO`; si el ACK falta, no repetir ni limpiar nada por conjetura. El marcador consumido en `/data` permanece intacto.
- Después del retiro, obtener nuevo inventario READ_ONLY con otro run, separando correctamente `terminal=NO_GO` histórico del estado físico actual. No afirmar que la BETA nueva está desplegada.

## No objetivos y riesgos

No corregir aún la causa originaria de la fase `STAGE`/`PREPARE_WORKER` de #844, que no quedó demostrada por el recibo: la salida SSH `host_claim=NONE` pudo esconder el prefijo `OBSERVE` pero no explica por sí misma `ssh_rc=3`. No iniciar otra APPLY ni liberar el PREPARE #843. No tocar código protegido blackbox (`synthetic.py`, `ipc_worker.py`), otros contenedores, red externa, Telegram ni reservas reales. No crear PR huérfanos ni duplicar recuperación existente.

## Criterio de aceptación

Tests RED→GREEN y CI/Security de la rama, revisión QA/Arquitectura/Infra 3/3, PR único fusionado y cero PR abiertos antes de la Action. Ejecución física única bajo **GO del usuario ya vigente**, sin solicitar otra autorización, pero sujeta a identidad, evidencia y controles técnicos. Recibo exacto y nueva reconciliación READ_ONLY; cualquier fallo es NO_GO hasta RCA fix-forward.
