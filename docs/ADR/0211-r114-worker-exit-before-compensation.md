# ADR 0211 — R114: ExitCode/OOMKilled tipados antes de compensación

Fecha: 2026-11-07 ART. Owner: RCA #417 / continuidad #45.
Estado: **CODE_ONLY**, sin host ni nueva operación Cutover.

## Evidencia y problema concreto

Cutover V3 físico [#42422235097](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42422235097)
informó `PREPARE_WORKER/HEALTH_EXITED` y compensación `VERIFIED`, pero no
publicó los campos de salida del proceso: el worker ya estaba eliminado al
terminar. El diagnóstico posterior R112
[#42424149186](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42424149186)
terminó `INDETERMINATE`; R113
[#42424918383](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42424918383)
acotó su causa diagnóstica a `DOCKER_OUTPUT_INVALID`, todavía sin razón física
del worker. Ninguno autoriza reutilizar el incidente ni reintentar a ciegas.

## Decisión mínima

En el **mismo** `docker inspect` ya ejecutado por `_browser_wait_healthy`,
cuando `State.Running` es exactamente `false`, conservar exclusivamente:

- `State.ExitCode`: `int` exacto entre 0 y 255, si no `UNKNOWN`. `bool` jamás
  es un entero válido; no interpretar strings ni números fuera de rango.
- `State.OOMKilled`: `bool` exacto; `true` = `YES`, `false` = `NO`, de lo
  contrario `UNKNOWN`.

Propagar los dos campos por `WorkerHealthPhaseError`,
`CutoverWorkerPhaseError` incluso si la compensación falla, `CutoverReceipt`,
recibo terminal O_EXCL/fsync y CLI. Sólo el fallo `HEALTH_EXITED` con ambos
campos explícitos habilita **terminal v3**; v1/v2 permanecen con los mismos
campos y bytes históricos. El parser runner exige en orden exacto
`exit_code=0..255|UNKNOWN oom=YES|NO|UNKNOWN`; rechaza duplicados, 01,
valor extra, texto privado y fase incompatible. El diagnóstico sigue
`host=UNVERIFIED terminal=UNVERIFIED no_retry=true`; la transacción sigue
`NO_GO` aunque la limpieza selectiva se complete.

Ningún `State.Error`, `Config.Env`, mounts, log de salud, stdout/stderr Docker
ni datos de otro proyecto cruzan esa frontera. No se agrega ningún comando,
consulta inspect, puerto, permiso, red, volumen, reintento o ruta de deploy.
El worker sigue compensándose por identidad positiva y el original se
preserva. Un `137` **no prueba OOM** sin `OOMKilled=YES`; `OOMKilled=NO`
no explica por sí solo el motivo de salida. R114 recoge evidencia de un
**futuro** único Cutover autorizado/revisado, nunca restaura datos perdidos.

## Transporte y controles

El paquete memfd mantiene exactamente el mismo inventario de entradas,
digest SHA exacto y límite comprimido `512000` bytes. Los archivos allowlisted
R114 miden `869791` bytes descomprimidos, `1791` sobre el techo anterior
`868000`. Se eleva **sólo** el límite descomprimido a `872000`, en productor y
bootstrap verificador, con holgura `2209` bytes; cualquier bytes excedentes
siguen NO_GO y el bootstrap rechaza ZIP alterado. Las variantes recovery y
preflight mantienen sus propios límites `256000`/`480000` y `128000` bytes
comprimidos cada una.

TDD: 43 nuevos casos RED antes de implementación, cubriendo 0/1/137,
OOM YES/NO/UNKNOWN, bool-as-int, compensación VERIFIED/INDETERMINATE,
recibo v3 persistente, parser estricto y no filtración. Los 185 casos de
base pasaron antes del cambio; tras implementación 228 del conjunto focal
pasaron. Pruebas de transporte 48 PASS, y 63 PASS en la suite extendida que
incluye el pin SHA-256 exacto del nuevo ZIP R114; el pin R110 anterior sigue
guardado como dato histórico. Ruff/Mypy/policy y suite completa deben
verificarse en el SHA final antes de CI exacta, merge y uso físico.
Los dos módulos de navegación BLACKBOX permanecen excluidos e intocados.

## Límites de aceptación

Un cambio CODE_ONLY no certifica el droplet. Después de PR, revisión
independiente y exact-SHA CI, el coordinador debe reconciliar estado físico,
PR0 y release dual antes del **único** dispatch protegido de Cutover V3; su
resultado se documentará en #417/#45, sin inferir éxito a partir de pruebas.
