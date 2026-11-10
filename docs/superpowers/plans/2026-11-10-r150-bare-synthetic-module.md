# R150 Worker Bare Module Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la imagen del worker encuentre el nombre público bare `synthetic` sin ejecutar ni modificar su caja negra.

**Architecture:** Conservar el paquete y `python -m boca_socios.browser.ipc_worker` existentes. Ampliar sólo `PYTHONPATH` en la imagen; un test hijo con `find_spec` replica la resolución de rutas sin ejecutar el archivo.

**Tech Stack:** Dockerfile, Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-r150-bare-synthetic-module-design.md`

## Global Constraints

- BLACKBOX: jamás abrir, interpretar, ejecutar en tests ni modificar `synthetic.py` e `ipc_worker.py`.
- Exclusión absoluta de Porota/PPI Watch, otras instalaciones, Cutover y navegación real.
- Sin nuevo arranque físico del worker. El W1 #934 ya consumió su único inicio.

## Review Focus

- El nombre bare debe resolverse en el intérprete del worker, no sólo existir en un COPY.
- La búsqueda no debe importar ni ejecutar código del archivo protegido.
- Se conserva `/app/src` para los imports de paquete.
- No cambiar el entrypoint, UID10002, modo rootless, red ni cgroups.
- Una imagen con un archivo faltante debe dar NO_GO en build/CI, no fallar sólo en el droplet.

### Task 1 — Emisión de imagen y regresión sin BLACKBOX

**Files:** `Dockerfile.browser`, `tests/test_browser_image_packaging.py`, `README.md`.

**Interfaces:** `PYTHONPATH` de la imagen; Python `importlib.util.find_spec("synthetic")` sin `import_module`.

- [ ] Escribir el test que extrae el valor del `PYTHONPATH` efectivo de `Dockerfile.browser`, sustituye `/app` por el directorio de la copia local y ejecuta un Python hijo con `find_spec("synthetic")`, esperando `.../browser/synthetic.py`.
- [ ] Ejecutar el selector y observar RED por ausencia del nombre bare.
- [ ] Añadir al `PYTHONPATH` el directorio `/app/src/boca_socios/browser`; agregar un gate de build post-COPY que use `find_spec` sin ejecutar el módulo.
- [ ] Ejecutar el selector y comprobar GREEN; luego ejecutar pytest completo, Ruff, Mypy y repo-policy y registrar cualquier fallo.
- [ ] Revisar diffs/SHAs/BLACKBOX, dejar un único commit y PR de cambio de código/image (no PR de diagnóstico), con checklist de aceptación y evidencia #934.
