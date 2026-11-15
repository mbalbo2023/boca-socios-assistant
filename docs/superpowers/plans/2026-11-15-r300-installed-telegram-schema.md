# R300 — Installed Telegram Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** permitir la migración explícita 0007 del par Boca ya instalado, con restauración verificada del panel y sin activar Telegram.

**Architecture:** redirigir el selector existente `telegram-migrate` al backend instalado y su lease única. Reutilizar el CLI `telegram_storage_gate migrate` que ya contiene la imagen M mediante un helper atestado por CID; no modificar SQL ni la imagen. Prepare conserva el rechazo explícito si falta 0007.

**Tech Stack:** Python, SQLite, Bash/GitHub Actions, Docker rootless y ZIP stdlib aislado; sin dependencias nuevas.

**Spec:** [RCA1142](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6890939744) y [contrato R300-01..08 / cuatro votos de diseño](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6891021673).

## Global Constraints

- Base de desarrollo O `f16db1008418889ffdd9b35a57bf77f1238ec659`.
- Producto instalado M `5281efae7dafe89be047073796b3e0a7e19785ed`, release866, APPLY1134 y STATUS1138 se conservan. No repetir release/APPLY/admin/STATUS.
- W del workflow y M de las imágenes tienen comprobaciones independientes de main, manifests, ascendencia e identidad instalada.
- SIMULATION_ONLY; sin reservas, proveedores, activación, pruebas de envío o mensajes.
- `synthetic.py` e `ipc_worker.py` permanecen sin leer ni modificar. Porota/PPI fuera de alcance.
- Helper: imagen M, UID10001, red none, rootfs readonly, cap-drop ALL, logs none, único mount Boca data RW, .25CPU/64MiB/16PID.
- Solicitud de migración exactamente `{}`. Ninguna ruta, SQL, módulo o argumento arbitrario del caller.
- Mantener `TELEGRAM_INSTALLED_ENTRIES` y caps 450000 B de fuente / 300000 B de ZIP; no ampliar reservas ni allowlists de archivos.
- No cambiar `telegram_maintenance.py`, su MOUNTS, `telegram_storage_gate.py`, SQL0007, inicializador o imagen. Reutilizar sus pruebas certificadas.
- La preservación transaccional no es un backup SQLite. No afirmar que existe uno.
- Autor de implementación: implement_r300_migration; diseño técnico: diagnose_engine_visual. Root: documentación/publicación/único operador Actions. Arquitectura, QA y Operaciones revisan el código del autor; éste no emite aprobación independiente propia.

## Review Focus

1. W distinto de M puede pasar un gate y caer después en legacy: probar el encaminamiento completo y exclusión de todos los pasos históricos.
2. Un entorno editable puede ocultar imports faltantes: ejecutar el ZIP publicado bajo `-I -S -B`, sin depender del checkout.
3. Creación/ACK/cierre/remoción inciertos pueden dejar un escritor SQLite: bloquear restore hasta acreditar la retirada del CID exacto.
4. Una migración puede haber comprometido datos aunque se pierda el recibo: preservar estado y fallo, sin declarar rollback ni reintentar automáticamente.
5. Un helper favorable no basta si falla restore o la comprobación final: el recibo de éxito exige todas las pruebas y sender OFF.

## Task 1: Conectar y verificar la migración instalada

**Files (autor):**

- Modify: `.github/workflows/boca-first-deploy.yml` — ruta instalada exclusiva, W/M y estado esperado.
- Modify: `src/boca_socios/host_telegram_backend.py` — secuencia explícita y recibo migrate.
- Modify: `src/boca_socios/host_telegram_cli.py` — dispatch y cierre de imports.
- Modify: `src/boca_socios/host_telegram_maintenance.py` — helper escritor fijo, atestación y retirada.
- Modify: `scripts/boca_protected_memfd_bootstrap.py` — admitir migrate exclusivamente en el modo instalado existente.
- Test: `tests/test_r296_telegram_backend.py`.
- Test: `tests/test_r296_telegram_maintenance.py`.
- Test: `tests/test_r296_telegram_installed_bundle.py`.
- Test: `tests/test_browser_ipc_workflow.py`.
- Test: `tests/test_telegram_release_lineage_r34.py` — actualizar únicamente la expectativa de selectors instalados y su cobertura de migrate; ampliación causal aprobada al detectar la condición histórica literal.

**Interfaces:**

- Consumes: `resolve_installed_context(attempt_id, *, lease, reader, expected_source_sha, workflow_sha)` y sus `stop()`, `restore()`, `healthy()`, `check_binding()` existentes.
- Consumes: `_telegram_container(image, "telegram_storage_gate", "migrate", writable=True)` y el CLI ya instalado. Su respuesta aceptable es exactamente `BOCA_TELEGRAM_STORAGE state=MIGRATED schema=0007\n`.
- Produces: `migrate_installed_telegram(attempt_id: str, *, lease: BocaJobLease, reader: LifecycleDockerIO | None = None, expected_source_sha: str, workflow_sha: str) -> TelegramBackendReceipt`.
- Produces: `InstalledMaintenance.call("migrate-schema", {}) -> {"schema": 7}`, delegando a `_migrate_schema()`. El resto de `call` conserva su semántica.
- Produces: recibo version1 existente, `operation=migrate`, `state=SCHEMA_READY`, `restoration=CONTROLLER_HEALTHY_ENGINE_OFF`, `sender_state=OFF`, `human_receipt=UNVERIFIED`; las categorías de fallo permanecen cerradas.

- [x] **Escribir las regresiones de la conexión faltante.** Usar estos selectores: `test_installed_migration_uses_existing_image_cli_and_exact_boundary`, `test_installed_migration_adds_only_seven_and_is_idempotent`, `test_installed_migration_failures_preserve_and_restore`, `test_installed_migration_uncertain_helper_blocks_restore`, `test_installed_migration_refuses_arbitrary_request_before_effect`, `test_migration_receipt_requires_schema_ready_restored_sender_off`, `test_telegram_migrate_routes_only_through_installed_transaction`, `test_isolated_archive_executes_migration_with_distinct_workflow_source`.
- [x] **Registrar RED pertinente.** La ausencia de ruta/helper/migrate en el candidato actual debe fallar; no aceptar como reproducción un error de dependencia o de fixture.
- [x] **Implementar la rama privada de mantenimiento.** Convertir el builder fijo de `run --rm` a create/logs-none/name+label, atestar antes y después, start/stop/rm por CID exacto. Aceptar sólo `{}` y el stdout literal; mantener separados fallo primario y cleanup. El retiro se acredita únicamente por eliminación exacta e inventario posterior sin ese CID.
- [x] **Implementar la secuencia del backend y CLI.** Precheck baseline/7; worker OFF; stop del controller exacto; helper; retiro confirmado; restore; verify-schema readonly final. Omitir owner, recipient, provision, custody y publish-status. Prepare no invoca migración.
- [x] **Conservar el fence de escritor.** Un fallo primario con retiro confirmado permite restore, pero conserva NO_GO. Creación/identidad/cierre/remoción inciertos impiden restore y producen CLEANUP_INDETERMINATE/restoration INDETERMINATE. No eliminar por nombre, ni reintentar, ni suponer rollback.
- [x] **Conectar todos los puntos del workflow y bootstrap.** Migrate entra en guardas W/M, presupuesto, environment, main W, manifests/ascendencia, construcción del ZIP y transacción; queda excluido de cada start-existing/fase/stop-test legacy. El estado esperado es SCHEMA_READY.
- [x] **Verificar GREEN focal.** Ejecutar sólo los módulos afectados y el subconjunto nuevo de frontera; usar el intérprete congelado existente con PYTHONPATH=src. La prueba de almacenamiento usa SQLite y el CLI reales, con mapping de FS/UID limitado al harness; conserva versiones/inodo/filas y demuestra idempotencia. Cubrir timeout, exit, stdout, atestación, cleanup, restore, postverify y señal.
- [x] **Verificar paquete y calidad del delta.** ZIP real `-I -S -B`, entradas exactas, caps vigentes, checker W/M real, Ruff/formato y tipos afectados. Informar cualquier cierre adicional necesario antes de ampliar archivos. No repetir la suite local del árbol base.

## Task 2: Revisar, publicar y completar la operación protegida

**Files (root):** este plan; `docs/quality/rca-lessons.json`; cabeceras actuales de `AGENTS.md`, `README.md`, `docs/BETA_DELIVERY_PLAN.md`, `docs/BETA_INTEGRATION_STATUS.md`, `docs/DEVELOPMENT_POLICY.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`.

- [x] **Registrar resultados reales y RCA.** Distinguir RED/GREEN local, gates publicados y recibos del host. Conservar cortes históricos identificados.
- [ ] **Obtener cuatro votos finales sobre el árbol exacto.** Arquitectura/QA/Operaciones independientes y root; resolver hallazgos antes de publicar.
- [ ] **Publicar un cambio consolidado.** PR de mantenimiento desde O; proteger expected-head y revisar árbol/head. CI y contrato PR del SHA definitivo deben pasar antes del squash protegido; comprobar después main y sus gates.
- [ ] **Despachar una migración instalada.** Sólo root, Actions Boca protegida, main definitivo, source M/digests release866 y campos ajenos vacíos. Observar Summary real y validar el recibo estricto. Ante fallo, clasificar evidencia antes de cualquier nuevo efecto.
- [ ] **Despachar prepare después de SCHEMA_READY aceptado.** Otra operación serializada, sin activate/test/send. Exigir PREPARED, restauración saludable/OFF y sender OFF; conservar prueba física y limpieza.
- [ ] **Actualizar GitHub y aceptación.** #417, #45, #113 y PR reflejan el resultado real. La aceptación privada Samsung, capacidad física50 y requisitos de resultado/captura/notificación siguen diferenciados; esta migración no los certifica.

## Self-review y estado

R300-01/02 se cubren en workflow/CLI; 03/06/07 en backend y recibos; 04/05 en mantenimiento; 08 en reutilización y verificación. Los cinco riesgos de revisión tienen selectores focales arriba. No se introduce otra pila de despliegue ni un contrato de proveedor supuesto.

Diseño aprobado por cuatro disciplinas antes del código. Ejecución autónoma delegada y paralelización de revisiones conforme al mandato vigente del titular; todas las operaciones del servidor permanecen serializadas. Estado del candidato: Task 1 implementada con RED pertinente y GREEN focal 132 pruebas (6,04 s), Ruff/mypy del delta aprobados y ZIP instalado de 47 entradas exactas: 449262 B de fuente / 126404 B de ZIP, dentro de caps vigentes. El pin de cutover completo permanece 066214cb4ae6a84f9e88973e38e58f7780dccf9556d1beb75cfb7c3b3a500c0e. RCA520 registrada. Revisión final, publicación/gates y aceptación física siguen pendientes; no se repitieron despliegues ni pruebas del árbol base.
