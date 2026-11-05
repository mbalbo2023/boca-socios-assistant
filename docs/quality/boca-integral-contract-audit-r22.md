# Boca Socios Assistant — Auditoría integral de contratos BETA R22

**Corte:** 2026-11-05 ART · **Scope:** #45, #227/#320, #321, #328,
#315, #314, #323. **Estado:** TEST-FIRST / CODE_ONLY / DRAFT; **NO_GO
físico** hasta recibos protegidos. **Sin merge, release, dispatch ni deploy.**

## Base, ownership y evidencia

- Reconciliación: issue #45 A45-R10/R11 y A45-R21.6.1, `AGENTS.md`,
  `README.md`, `docs/DEVELOPMENT_POLICY.md`, ADR0137/0143/0144/0147;
  consulta GitHub de DRAFT #319, #336, #338, #339, #340, #341.
- Candidato central **PR #319**: `ea64d92d84a6c9be1300dc66a0e24d93c293b3ad`,
  tree `8f706f66329691cb3c61566edb0e8cb0096164b2`; `main` instalado
  históricamente `cabce9f1e452e63ded115f447559a358dc0f4d1b`.
  GitHub 7/7 Actions completed/success del **SHA #319 anterior**, incluido
  first-deploy PR-validation, pero `approved-boca-manual-operation` **SKIPPED**;
  ni ese recibo ni los tests confirman estado físico actual.
- PRs incrementales separados: #336 Cutover CLI (`42b249c`), #338 motor
  AF_UNIX (`1d5accd`), #340 Telegram cifrado (`3c93da8`), #339 artículo
  oficial→JSONL (`7a51891`), #341 limpieza dual-FS (`f939b53`). Los dos
  últimos no integrados en la base exacta ensayada. Cada nuevo SHA requiere
  su propia ejecución y revisión; nunca heredar GREEN de otro árbol.
- **Ownership de este PR:** exclusivamente
  `tests/test_beta_integral_contract_r22.py` y este informe. Sin source, YAML,
  Docker, rama main ni módulos BLACKBOX modificados. Los fakes de contrato
  no son atestadores Docker reales.

## Matriz de aceptación sintética implementada

| Contrato end-to-end lógico | Evidencia GREEN reproducible | Límite/estado físico |
| --- | --- | --- |
| Opción B: SQLite de sesión lateral dentro del volumen existente, cookie owner 400d, reconstrucción tras restart y DB legacy intacta | `test_chrome_option_b_survives_new_service_without_legacy_schema_mutation`: `boca_owner_session.sqlite3` conserva token; CSRF nuevo; checksum del controller y ledger sin 0008 | **CODE GREEN, HOST NO_GO**: no hay reinicio observado desde Samsung/Termius; requiere bootstrap protegido en el cutover |
| Bot START condicionado a worker Chromium healthy; STOP posible con worker no saludable | `test_bot_start_requires_healthy_worker_but_stop_can_drain_unhealthy_worker` para worker parado y worker running/unhealthy, usando `LifecycleHostSnapshot.require` | **POLICY GREEN, HOST NO_GO**: snapshot fake no prueba worker real ni engine AF_UNIX por ID; necesita workflow con observación independiente y ACK |
| Telegram Chrome recibe ciphertext pero no habilita emisor | `test_private_telegram_stage_is_ciphertext_only_and_sender_stays_off`: POST owner→0600 file, `202 STAGED_PENDING_PROTECTED_CUTOVER`, `sender=OFF`, `telegram_connected=false`, sin nonce ni token plaintext | **STAGING GREEN, PAIRING NO_GO**: `stage_id` no es nonce protegido. Falta consumo único bajo lease, recibo del dueño, custodia y verificación de notificación; token real no ingresado |
| Aviso oficial JSONL informativo, no ticket-intent | `test_official_jsonl_projection_never_promotes_window_to_ticket_action`: línea JSON sintética→catalog→JSON privado/HTML; `actionable=false`, sin formularios de compra | **PROJECTION GREEN, SITE/REAL AVAILABILITY UNVERIFIED**; PR #339 añade pipeline público/artifact real separado, sin cupos verificados ni reservas |
| Cutover sin GO exacto no muta host | `test_cutover_default_missing_go_never_invokes_host_effect` con bundle memfd válido, ejecutor espía y CLI por defecto: retorno `3`, cero llamadas | **FAIL-CLOSED GREEN, CUTOVER NO_GO**: todavía falta GO protegido enlazado de verdad a única transacción y recibo final |
| Limpieza Docker selectiva SIEMPRE en SUCCESS y FAILURE | `test_selective_cleanup_both_outcomes_preserve_foreign_and_boca_state`: cuatro residuos exactos eliminados por `execute`, snapshot extranjero/volumen Boca conservados | **POLICY GREEN, HOST NO_GO**: simulador de inventario no ejecuta Docker; #341 dual-FS adicional sin integrar y `execute_protected` requiere mismo lease + hook físico `finally` |

**Ejecución local en base exacta #319 + archivo R22 (antes de publicar):**
`uv run pytest -q` sobre R22 y siete contratos existentes — **160 passed en
3.81 s**, de los cuales **8 casos nuevos** (parametrizados); `uv run ruff
check tests/test_beta_integral_contract_r22.py` **GREEN**; `uv run mypy src`
**GREEN** (118 fuentes); `uv run python scripts/check_repo_policy.py`
**POLICY_PASS**. Test aislado R22 **8 passed en 0.47 s**. Son checks
locales sin host, redacción de credenciales ni sitios externos. No hay
fallos deliberados ni `xfail` enviados al candidato.

## RCA arquitectónico: dependencias concretas para GO integral

1. **P0 — Una única transacción protegida y GO host efectivo.**
   `host_boca_cutover_cli.run_cli` verifica el digest de GO y fuente memfd
   antes de `execute`; sin autorización independiente siempre devuelve NO_GO.
   #336 es un CLI code-only. El workflow protegido necesita el gate exacto
   en main/release, atestación del legacy por ID, misma lease desde park
   hasta postflight, terminal receipt durable y cleanup `finally` para ambas
   salidas. Un test del fake no certifica que SSH/runner/host conserven la
   lease. No agregar ruta alternativa ni dispatch automático.
2. **P0 — Worker y motor desacoplados del panel HTTP, pero con recibo real.**
   Los endpoints `/control` crean solicitudes auditables, no acciones
   ejecutadas. AF_UNIX local permite `start_engine/stop_engine` reales dentro
   del controller, pero falta la atestación externa de Docker/UID/puerto,
   invocación exact-ID y el enlace protegido `REQUESTED→CLAIMED→APPLIED`.
   Un START de bot sin Chromium healthy debe rechazarse; STOP de bot debe
   seguir siendo posible aunque falle el worker. No detener el panel para
   implementar STOP: perdería el único control accesible para Tincho.
3. **P0 — Telegram staged ≠ Telegram connected.**
   El callback privado cifra y persiste una única ranura, pero no puede
   despachar ni demostrar control del token. Necesita consumidor único de
   etapa bajo misma lease, comprobación y consumo irreversible del nonce
   firmado por owner, custodia 0007 separada, sender habilitado sólo tras
   recibos auténticos, prueba sintética y posterior confirmación humana.
   Nunca introducir token en PR, Actions input público, comentarios o chat.
4. **P0 — Limpieza OCI y capacidad real en dos sistemas de archivos.**
   La política `cleanup.execute` preserva imagen/container activos y todo
   recurso ajeno; un stub de `probe/delete` no garantiza su ejecución tras
   éxito o fallo. Integrar #341 dual-FS del data-root rootless y staging,
   binding de attempt/IDs, `finally` bajo mismo lease, recibos de bytes e
   inodos pre/post y rechazo de drift/timeout sin `docker prune` global.
   Si Docker/SSH/runner se pierde, declarar `INDETERMINATE/NO_GO` y conservar
   lo incierto; no simular una limpieza que no se observó.
5. **P1 — Avisos oficiales UI vs ingestión.** Integrar #339 sólo tras
   comprobar SHA/artefacto y parser semántico (incluido separador U+200D),
   conservar `source_sha256` raw y `SOURCE_OBSERVED_UNVERIFIED`.
   No transformar calendarios, ventanas, ni apariciones del artículo en
   elegibilidad, disponibilidad, intent de compra ni navegación a la fila.
6. **P0 — Aceptación física y evidencia.** Después del GO correspondiente:
   único merge→release build-once→Actions protegido→postflight con receipts;
   verificar en **Samsung Chrome + Termius** `localhost:8443`, cookie
   persistente tras restart controlado, Chromium/bot start-stop real,
   simulación sin reserva/compra, Telegram privado y Docker ajeno intacto.
   Hasta esa prueba no afirmar BETA integral instalada ni limpiar datos,
   modificar otros servicios, registrar nuevo puerto o pedir PIN/token.

## Checklist de integración sin trabajo duplicado

- Integrador central #319 puede aplicar **sólo estos dos nuevos archivos**
  una vez GREEN la rama de auditoría; tests no importan ni inspeccionan
  `synthetic.py` o `ipc_worker.py`, no crean sockets de red ni contactan
  proveedores. Los helpers importados proceden de suites de pruebas ya
  existentes y usan snapshots/envelopes 100 % sintéticos.
- Reconciliar deltas #339/#341 y Cutover GO/host lifecycle de sus owners;
  revisar PR Actions **sobre nuevo SHA candidato exacto**. Este corte no
  reemplaza los tests más profundos de cada módulo ni el predeploy integral.
- **Regla 84:** mantener comentario en #45 con PR audit SHA, tree, nuevos
  tests, Actions, campos `NO_GO`/pendientes; actualizar este informe cuando
  un recibo físicamente confiable cambie el estado. Seguridad scanner P2 por
  prioridad funcional del owner, sin eliminar controles de aislamiento.

**Prohibiciones respetadas:** cero compra/reserva/login real, sin Queue-it,
sin backup, sin token/clave, sin puerto adicional/HTTPS, sin tocar Porota,
otros recursos Docker, BLACKBOX, ni ejecutar Cutover/host/deploy.
