# Plan R122 — Diagnóstico tipado de ExitCode=1

**Meta:** explicitar la inferencia admisible de la falla histórica #878 en
GitHub Actions sin cambiar el flujo del host ni revelar datos privados.

## Tarea 1 — Pruebas RED

- Archivo: `tests/test_cutover_a_go.py`.
- Casos positivos: recibo v3 realista, `HEALTH_EXITED`, exit=1, oom=NO,
  compensation=VERIFIED, `PREPARE_WORKER`, archivo temporal y estado NO_GO.
- Casos negativos: `HEALTH_UNHEALTHY`, `START`, código 0/137/UNKNOWN,
  OOM YES/UNKNOWN, compensación incierta, extra/tokens privados/duplicados,
  pérdida del archivo, truncamiento y `ssh_rc=124/255`.
- Probar la función verdadera `classify_cutover_ssh_failure` y observar el
  fallo esperado *por ausencia de campos*, no por entorno o importación.

## Tarea 2 — Implementación mínima y GREEN

- Archivo: `scripts/check_cutover_a_go.py`.
- Agregar exclusivamente tres literales derivados de los claims estrictos
  existentes cuando `ssh_rc=3`, sin cambiar el parser, `assert_actions_host_receipt`, YAML,
  host CLI, protocolos o contratos Docker.
- Ejecutar las pruebas focales y asegurar que todo resultado se mantenga
  `state=NO_GO`, `terminal=UNVERIFIED`, `no_retry=true`.

## Tarea 3 — Regla 84, revisión y gates

- Documentar causalidad perdida y alcance del nuevo clasificador en
  `docs/ADR/0216-r122-worker-exit-one-diagnostic-classification.md`,
  `README.md`, `docs/OPERATIONS.md` y este diseño/plan.
- Verificar `uv run --frozen pytest -q -n auto`, `uv run --frozen ruff check .`,
  `uv run --frozen ruff format --check .`, `uv run --frozen mypy src`,
  `uv run --frozen python scripts/check_repo_policy.py`, `git diff --check`.
- Revisión independente del diff, SHA y no contacto con otros workloads;
  documentar issue #45/#417. Abrir PR pequeño si el proveedor GitHub permite
  el push normal; un rechazo de permisos no se elude con otro transporte.

## R123 — trabajo posterior, no parte del cambio

Diseñar la captura prospectiva de *flags sin contenido* en el mismo inspect.
Analizar costo en bundle, versionado terminal V4, fixtures, seguridad y valor
incremental antes de optar por implementación. Ningún host dispatch ni Cutover
es parte de R122/R123.
