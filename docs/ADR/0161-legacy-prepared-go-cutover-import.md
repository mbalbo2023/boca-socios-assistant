# ADR 0161 — contexto PREPARE verificable para GO Cutover A e importación oficial

**2026-11-05 ART · issue #360 / #352 · estado DRAFT, CODE_ONLY, sin SSH, host ni GO físico.**

## RCA constatado

Los dos gates anteriores son intencionalmente estrictos pero no precomputables
antes del despacho humano: `scripts/check_cutover_a_go.py:authorization_digest`
ata `GITHUB_RUN_ID=plan.attempt_id` y `GITHUB_RUN_ATTEMPT=1`; el valor de
`vars.BOCA_CUTOVER_A_GO_BINDING_SHA256` debe existir antes de SSH.
`src/boca_socios/host_official_notice_actions.py:expected_go_sha256`
incluye también `operation_run_id=GITHUB_RUN_ID` en
`vars.BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256`. Actions asigna cada ID sólo
tras pulsar Run workflow, así que una variable preparada antes no puede
ligarlo a un ID aún desconocido. GH Actions verdes validan código, no resuelven
esa carrera. No se demostró un `Environment` que pause el efecto para actualizar
variables al vuelo (referencias #352, ADR0159 y checkpoint #45).

## Contrato CODE_ONLY incorporado

Este ADR añade **dos funciones puras, ninguna activada por el workflow**:

- `cutover_prepared_context_sha256(request, prepare_run_id)` devuelve SHA256
  canónico, con dominio `boca-cutover-a-prepared-review-v1`. Antes valida
  main/owner/intento actual, proyecta **sólo para el hash** los campos
  `github_run_id` y `plan.attempt_id` al ID PREPARE ya conocido y llama
  al validador v1 original para **todos los otros campos**: tres manifiestos
  de release, imágenes, SHAs, historical/target/overlay Compose, seccomp,
  paquete ZIP Option B completo, identidad owner y `origin`.
- `official_prepared_context_sha256(coords, prepare_run_id, actor)` entrega
  otro hash con dominio distinto
  `boca-official-import-prepared-review-v1`, usando el validador v1 para
  ligar las coordenadas exactas: main, imagen/controlador, releases, Artifact
  ZIP y SHA/HTML/JSONL del único anuncio informativo, cinco ventanas
  `actionable=false`, actor y destino fijo Boca.

Este digest PUBLICO de contexto puede formar parte de un futuro artifact
`boca-prepared-go-v1` verificado por el runner propietario #352; **no es
aprobación, firma, receipt de host ni autorización**. El GO independiente
debe cubrir el recibo PREPARE completo, con SHA/owner/run/attempt/manifiestos,
expiración, artefacto GH inmutable validado y consumo único; sin un segundo
despacho humano para APPLY no hay autorización. Se conserva el verificador
v1 de ambas operaciones sin excepciones ni modificación de flags CLI.
Dar el digest PREPARE como valor del GO v1 será siempre NO_GO.

## Requisitos de un futuro APPLY (no implementados en este issue)

1. PREPARE inerte `host_calls=0`, en el único
   `.github/workflows/boca-first-deploy.yml` (owner #352), obtiene las
   coordenadas revisadas y crea un artifact público canónico con
   `prepare_run_id` real y `public_context_sha256` exacto. No guarda
   secretos ni lee datos privados en el artifact.
2. Tincho revisa los pins del PREPARE y aprueba un digest **independiente**
   específico del recibo en la variable correspondiente del Environment.
3. APPLY posterior verifica por API de GitHub PREPARE éxito, SHA de artifact,
   owner, origen y release actuales, Context SHA, GO Environment y caducidad;
   el runner **inyecta su propio `GITHUB_RUN_ID` después del despacho** al
   plan efectivo de host (nunca se pide como input). Conserva segundo recheck
   de main antes de SSH y lease nueva.
4. **Replay físico P0**: la operación host debe marcar `prepare_run_id`
   consumido de modo durable/atómico O_EXCL bajo volumen Boca existente y
   misma lease, *antes* del efecto, y fallar sin retry ante resultado incierto.
   El Cutover A actual tiene receipts asociados al **run APPLY**; no se ha
   comprobado un marcador PREPARE en el backend. Ese módulo no pertenece a
   este ownership, por lo que Cutover A permanece NO_GO hasta incorporar
   dicha protección y pruebas de caída/reintento. La importación existente
   resuelve importaciones iguales con `UNCHANGED`, pero idempotencia de datos
   no reemplaza el consumo de autorización; también requiere un recibo de
   consumo PREPARE antes de ENABLE APPLY. No se altera el formato de
   credenciales/SQLite ni se crea un volumen nuevo.

## Evidencia, pruebas y alcance

Test-first: selectores
`tests/test_cutover_a_go.py::test_prepared_cutover_review_remains_exact_across_distinct_apply_runs`,
`test_prepared_cutover_review_rejects_any_reviewed_bytes_drift`, y
`tests/test_host_official_notice_actions_r24.py::test_official_prepared_context_binds_known_prepare_not_unknown_apply_run`.
Los tests comprueban estabilidad al cambiar el futuro run APPLY, variación
al cambiar PREPARE/artefactos, validación de todos los bytes de revisión y
rechazo del digest nuevo por el gate v1. Registrar luego SHA/TREE y número
real de PASS / CI de este PR; ningún resultado se infiere antes de Actions.

**Límites:** no modificar workflow, ZIP/host backend, BLACKBOX, fuentes Boca,
SQLite legacy0008, Sidecar, Telegram, otros workloads/puertos, Porota,
backups, recursos Docker ni GO real. Sólo `127.0.0.1:8443` seguirá siendo
el origen privado. Importación documental no habilita boletos: las ventanas
son informativas y `actionable=false`. La seguridad adicional puede ser P2,
pero los gates operativos y aislamiento existente se mantienen intactos.
