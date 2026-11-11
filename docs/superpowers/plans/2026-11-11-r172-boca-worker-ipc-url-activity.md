# Plan R172 — Integración única bajo demanda Boca

**Goal:** conectar el worker navegador por AF_UNIX al panel privado, propagar `SITE_URL` al siguiente arranque y mostrar actividad vigente; evitar duplicar datos/Telegram. **Scope:** sólo Boca Socios Assistant, simulación, CI primero; ningún deploy sin evidencia.

**Architecture:** un listener protegido por UID 10002 usa el protocolo IPC existente; la configuración URL permanece separada del socket y de los datos sensibles; el panel reutiliza su visor. Véase [diseño](../specs/2026-11-11-r172-boca-worker-ipc-url-activity-design.md).

## T1 — IPC (owner exclusivo: browser/integración)

- Archivos: nuevo `src/boca_socios/browser/ipc_server.py`, `Dockerfile.browser`, `compose.beta.browser.yaml`, tests nuevos focalizados.
- RED: demostrar que el entrypoint actual no levanta `synthetic.sock`, y tests de servidor falso, identidad/framing/STOP.
- GREEN: adaptador AF_UNIX de simulación con executor offline inyectable y listener bajo demanda; nunca ejecutar las cajas negras en pruebas.
- Verificar que los archivos privados no cambian sin autorización expresa y huellas en checklist.

## T2 — Configuración `SITE_URL` (owner exclusivo: transporte y panel)

- Archivos a precisar después de inventario: `site_url_settings`, almacenamiento de configuración mínima, creación/custodia de mounts y arranque protegido.
- RED: cambiar URL en 8443 y comprobar que el siguiente START la ve sin reconstrucción, sin acceder a DB/clave/token.
- GREEN: transporte persistente y atestado al worker UID 10002, validación de entrada acotada; sin vetos generales de URL pública/privada.
- Reconciliar especificación de Compose y atestadores host antes de tocar despliegue.

## T3 — Actividad vigente (owner exclusivo: panel/telemetría)

- Archivos: `browser/activity_events.py`, `panel/worker_activity.py`, pruebas asociadas.
- RED: un archivo de Chromium de una sesión antigua no puede figurar como actual.
- GREEN: correlación temporal o identificador opaco verificable, estados `stale`/`unverified` no confundibles con éxito; conservar categorías fijas y sin secretos.

## T4 — Datos y Telegram (owner exclusivo: revisión)

- Confirmar rutas existentes para socios, cifrado, outbox y emisor; agregar sólo pruebas/documentación faltantes, sin nuevo modelo de datos ni duplicación.
- Mantener Telegram OFF hasta rotación del token comprometido y aceptación de custodia/acuse privado.

## Integración y cierre

- Consolidar **un solo candidato** de las tareas independientes desde `origin/main` exacto; cotejar duplicaciones y hashes BLACKBOX.
- `uv sync --frozen`; `ruff check`, `ruff format --check`, `mypy src`, `pytest` focal y general, `scripts/check_repo_policy.py`; documentar RED/GREEN y SHA.
- Revisar AGENTS/README/OPERATIONS/ADR, quality RCA y #417/#45 (Regla84), auditar PR abiertos y exact-SHA CI.
- La publicación, Cutover V3 y prueba física por Boca Actions necesitan diagnóstico fresco y release dual atestada; no afirmar instalación con solo CI.
