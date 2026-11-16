# R309 — Ajuste focal de expectativas legacy tras CI1281

## Entrega

Commit: **35dffc177f87f05fd5bb14616edc887e067f7cba**.
Base local recibida: `b4300cc`.
Rama: `feature/529-r308-countdown`.
Autor separado: `/root/r309_author`, sin voto independiente.

La adenda fue aprobada 4/4 y registrada por root **antes de modificar código**, en PR530, comentario **6903779092**. Su alcance autoriza exclusivamente seis literales de expectativas en cuatro archivos de tests. Root conserva documentación, RCA, publicación e integración.

## RED real reutilizado

La evidencia de fallo es **CI1281**, candidato `b3ecd499`, cuyo árbol root verificó idéntico al local `b4300cc`. Root informó cinco tests fallidos por expectativas cerradas anteriores al selector y **10010 tests aprobados más 34 subtests**. Se reutilizó esa CI como RED real; no se volvió a ejecutar la CI ni se reprodujo un RED local innecesario.

Los cinco selectores afectados se identificaron en los asserts autorizados y son exactamente los ejecutados después del ajuste.

## Cambio exacto

El commit tiene **cuatro archivos, seis líneas agregadas y seis reemplazadas**. Cada cambio añade exclusivamente `telegram-prepare-diagnose` al final de la lista/condición correspondiente. Se conservaron todos los selectores anteriores, su orden, el cierre exacto de las expectativas y las demás aserciones.

| Archivo | Literales ajustados |
|---|---:|
| `tests/test_browser_ipc_workflow.py` | Dos listas de case |
| `tests/test_lifecycle_mobile_workflow_r28.py` | Una lista de case |
| `tests/test_protected_ops_workflow_r26.py` | Una lista de case |
| `tests/test_telegram_release_lineage_r34.py` | Condición compartida por admisión/main y una lista de case |

No se editaron workflow, producto, guardas, cotas, builder, memfd ni otros tests. No se relajó ninguna expectativa mediante búsquedas parciales nuevas, comodines, skips o eliminación de asserts. La condición de R34 sigue verificando tanto admisión como selección del SHA de main.

## GREEN focal

Comando ejecutado una sola vez:

```text
.venv/bin/python -m pytest -q tests/test_browser_ipc_workflow.py::test_browser_option_is_separately_gated_without_weakening_legacy_operations tests/test_browser_ipc_workflow.py::test_telegram_migrate_routes_only_through_installed_transaction tests/test_lifecycle_mobile_workflow_r28.py::test_mobile_prepare_artifact_is_not_itself_approval_or_telegram_access tests/test_protected_ops_workflow_r26.py::test_installed_telegram_has_one_lease_route_and_no_legacy_daemon_steps tests/test_telegram_release_lineage_r34.py::test_protected_workflow_keeps_telegram_two_sha_review_before_any_host_transport
```

Resultado real: **5 passed in 0.25s**.
Log: `.superpowers/sdd/r309/legacy-ci-green.log`.

Calidad, limitada a esos cuatro archivos:

```text
.venv/bin/ruff check tests/test_browser_ipc_workflow.py tests/test_lifecycle_mobile_workflow_r28.py tests/test_protected_ops_workflow_r26.py tests/test_telegram_release_lineage_r34.py
.venv/bin/ruff format --check tests/test_browser_ipc_workflow.py tests/test_lifecycle_mobile_workflow_r28.py tests/test_protected_ops_workflow_r26.py tests/test_telegram_release_lineage_r34.py
git diff --check
```

Resultados: **All checks passed**, **4 files already formatted**, diffcheck limpio. Logs: `legacy-ci-ruff.log` y `legacy-ci-format.log`, en la misma carpeta de evidencia.

No se ejecutaron suite base, suites históricas completas, ZIP ni mypy de producto. Los bytes productivos permanecen intactos; no corresponde presentar una medición nueva del paquete por un cambio exclusivo de expectativas de tests.

## Aislamiento y cierre

El commit incluye sólo los cuatro tests autorizados. Los WIP de root en `docs/BETA_INTEGRATION_STATUS.md`, `docs/quality/rca-lessons.json` y el plan R309 se preservaron fuera del commit y no fueron editados por el autor.

No hubo push, fetch, rebase, reset, host, SSH, Docker daemon, proveedor ni Telegram. No se repitió ninguna operación histórica. La evidencia acredita el ajuste focal de expectativas; la publicación y la siguiente CI corresponden a root. No se emite un voto independiente ni se declara una CI posterior aprobada.

El autor libera ownership de estos cuatro archivos al entregar este commit y el informe para la revisión del delta mínimo.
