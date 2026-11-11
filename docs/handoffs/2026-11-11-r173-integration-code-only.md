# A45-R173 — integración R172, RCA y gates CODE_ONLY

Fecha: 2026-11-11. Issue canónico: #417. **Estado: NO_GO para Cutover físico** hasta verificaciones de GitHub Actions y host. No se ejecutaron reservas reales, operaciones en Porota, comandos contra Docker ajeno ni navegación hacia sitios de socios.

## Proveniencia y alcance

- `main` observado antes de integración: `361e3ff42c44e1b8699d7a3e2d158c9a367b2f86`.
- Handoff R172: `handoff/417-r172-code-only-20261111` en `c87038a6665bd6c2f797fb9dc0d69f04ecd1c502`; el parche WIP de **28 archivos** pasó `git apply --check` y `git diff --check` y fue recuperado desde la base `main` en el commit local `7d92bc4`.
- Integración R173 realizada mediante commits de ownership no solapado: host/Telegram y flujo de release `563e09c`; IPC `58f99a2`; panel `24073a5`; Cutover y bundle `2b7b8aa`.
- Archivos históricos `browser/synthetic.py` y `browser/ipc_worker.py` continúan inalterados; ningún cambio a identidad, redes o recursos Porota.
- Este documento registra estados y decisiones verificables; **no reemplaza evidencia remota** ni aprueba promociones automáticamente.

## RCA, cambios y límites

| Bloqueante observado | Causa/alcance | Corrección R173 y prueba negativa |
| --- | --- | --- |
| Worker `ExitCode=1`/`MISSING_BARE_SYNTHETIC`, IPC no activo | `ipc_worker.py` legado realiza sesiones one-shot y termina, no escucha un socket AF_UNIX. La imagen/workflow seguía validando su comando antiguo. | `browser/ipc_server.py` con STOP bajo demanda, cancelación que falla cerrado y categorías de observación sin equiparar tokens a reservas. Dockerfile R172 usa `ipc_server`, el release workflow y la prueba de lifecycle R173 ya exigen ese entrypoint. Validación del socket **física pendiente** por `EPERM` de AF_UNIX en este sandbox. |
| `SITE_URL` y volumen de configuración | La publicación puede divergir del valor del panel; formatos IPv4 decimal/hex y rutas de tokens evitaban controles; caracteres UTF-8 multibyte excedían el tamaño real del JSON. | Se valida formato sin exigir URL pública, se prohíben rutas de token y metadata peligrosa, límite 512 **bytes** UTF-8, START rechaza con HTTP 503 ante divergencia, datos y credenciales separados. El volumen `boca-socios_boca_site_config` es protegido también frente a borrado directo/plan genérico. |
| Actividad Chromium sin telemetría | El archivo vacío podía presentarse como actividad disponible. | Estado `desconocido/degradado`, categorías fijas sin exponer URL, token, cookie ni PII. |
| Cutover bloqueado por topología y falta de volumen | Inventario del instalado y compensación no contemplaban `boca_site_config`. | Inventario exige la topología nueva, volumen creado sólo después de IPC, rechazo de preexistentes, identidad por labels/driver/mountpoint/inode, compensación de **un recurso exacto y no adjunto** verificada, nunca limpieza general. |
| Paquete protegido excede límite | Fuentes para ZIP Cutover completas exceden techo existente de 1.152.000 bytes. | Compactación del transporte **únicamente** de tokens de comentario de `host_first_deploy.py` **si** la fuente completa excede ese techo. Comparación de AST, compilación y cantidad de líneas; resto de variantes y ZIP de pruebas pequeñas sin alteraciones. No subir límites ni quitar validaciones. |
| Telegram y custodias | El inventario post-Cutover esperaba cuatro volúmenes; el diseño nuevo exige cinco. Material antiguo muestra token posiblemente comprometido. | Lector Telegram y pruebas actualizados a volumen exclusivo. Sender ON permanece bloqueado hasta rotación del token por titular y aceptación segura. No copiar tokens al issue, CI ni registros. |

## Verificación local e invariantes

- Antes de resolver los bloqueantes R172, suite íntegra: **6.588 PASS, 50 FAIL, 26 ERROR, 34 subtests PASS**; por tanto NO_GO. El error de paquete protegido y los fixtures de topología dominaron varios casos.
- Después de integrar IPC, SITE_URL y protección de volúmenes: **250/250 pruebas focales PASS**. Limpieza y host/Telegram: **284/284 PASS**. El equipo Cutover certificó **185/185 pruebas focales** en su branch aislada.
- `uv run ruff check .`: **PASS**; `uv run ruff format --check .`: **PASS**, 820 archivos; `uv run mypy src`: **PASS**, 152 archivos; `uv run python scripts/check_repo_policy.py`: **PASS**; `git diff --check`: **PASS**.
- Suite global **integrada** con `uv run --frozen pytest -q -n 4 --tb=line`: **6.710 PASS, 34 subtests PASS, 0 FAIL** en 46,35 s. Antes, una pasada monoproceso detectó (a) pin desactualizado tras integrar la limpieza de volumen y (b) una carrera en la prueba de cuota del lector de Docker. El pin se actualizó tras dos reconstrucciones idénticas; la prueba permite `BrokenPipeError` solamente cuando el lector alcanza `LIMIT` y sigue exigiendo esa categoría terminal. Suite completa posterior PASS. Una comprobación local **nunca** basta para afirmar GREEN de instalación.
- ZIP Cutover completo reproducible tras integración y guard host adicional: SHA-256 `c4958187deae82c0732c59861ccc6ce8258274b44d5c96a2e022d46d577beaa7`, 282.043 bytes comprimidos, verificado en dos builds independientes. Se conserva el límite de 1.152.000 bytes de fuente y 512.000 comprimidos. Los SHAs anteriores son evidencia histórica, no pins para el release nuevo.
- Protección de los volúmenes persistentes: casos TDD RED para `boca_site_config` candidato de limpieza y borrado directo de los cinco nombres; luego GREEN, preservando los contratos históricos del controller original.

## Pendientes remotos y seguridad de promoción

1. Publicar rama de integración con base comprobada, abrir PR; verificar todos los checks por **SHA exacto**, revisar cambios y ausencia de código duplicado.
2. PR Dependabot abiertos al comenzar R173: #474 Playwright y #475 upload-artifact tenían checks rojos; #476 zizmor y #477 mypy checks verdes. Analizar cada uno por cambios/costes de riesgo y no fusionarlos automáticamente ni afirmar que su estado persiste sin lectura actualizada. No bloquear el examen del PR R173 por upgrades ajenos.
3. La última Action física Cutover `42912586832` terminó FAIL en la observación del controller original. Se necesita un **nuevo preflight protegido** con imagen/digest exactos, inventarios rootless exclusivamente Boca y evidencia de montaje SITE_URL, socket IPC, persistencia, START/STOP, actividad y Telegram read-only.
4. No crear volumen si se encuentra preexistente y no atestado; no borrar recursos ajenos ni cambiar el puerto 8443. Cualquier divergencia/indeterminación es **NO_GO** y requiere RCA antes de retry; no poner en funcionamiento reservas reales.
5. Obtener rotación de credencial Telegram antes de sender ON. El token antiguo no es evidencia segura ni está autorizado su uso.
6. Solo después de test, PR, digest y preflight host conformes, evaluar Cutover A protegido. **Todavía no hay evidencia física R173 ni GREEN del droplet**.

## R173 posteriores a la primera revisión y Actions

- **Panel START sin configurar (P1):** un primer START sin URL guardada se encolaba y despertaba al host hasta fallar. Se introdujo rechazo HTTP 503 antes de crear intención/wake, tanto ante falta como divergencia con el espejo. RED observado y GREEN, con fixtures de lifecycle actualizados para declarar explícitamente una URL sintética ya publicada (sin tráfico externo).
- **Guard host independiente:** antes de captura/arm/`docker start`, el controlador Boca **ya atestado** comprueba en su namespace el archivo URL-only mediante `read_site_url()`. El ejecutor recibe únicamente el acuse `BOCA_SITE_URL_READY`; cualquier resultado distinto, excepción o corrupción es `SITE_URL_UNVERIFIED`, sin arranque. No utiliza rutas Docker del host o datos de socios.
- **STOP→START y actividad (P1):** un nuevo listener rechazaba sus propios `chromium-events.jsonl` y `chromium-events.previous` persistentes. Ahora elimina sólo esos inodes transitorios tras verificar nombre, UID/GID, modo, tamaño, nlink y estabilidad; cualquier entrada extraña/socket residual es NO_GO. Siete regresiones RED→GREEN.
- **Simulación DOM independiente (CODE_ONLY):** `browser/offline_fixture.py` define una interacción local con HTML literal en `about:blank`, contexto offline, rutas de red abortadas y cierre acotado. Excluye por completo las dos cajas negras, así como URL, socios y credenciales. Es un *smoke* opt-in `--smoke`, no la ejecución predeterminada del bot ni prueba de reservas. Se añadió al paso de validación PR de imagen bajo Docker runner **`--network none`**, con el mismo aislamiento del preflight Chromium anterior. Su aceptación real requiere nuevos Actions sobre SHA actualizado.
- **Documentación viva:** cabeceras actuales en `README.md` y `docs/OPERATIONS.md` explican límites y marcan R170/R171 como antecedentes. El primer paquete de 6.710 PASS y 5/5 Actions SUCCESS correspondía al HEAD remoto `fee7c7b`, **no** acredita estas correcciones posteriores: retest completo y nuevos Actions obligatorios.
- **RCA host de 2026-11-10:** Action `42912586832` expuso `BOCA_LEGACY_PREPARE state=NO_GO reason=LEGACY_SINGLETON`; fuente `_observation` rechaza `len(inventory.containers) != 1`, sin distinguir cero de varios. No atribuirlo al IPC ni borrar residuo a ciegas. El próximo diagnóstico necesita censo actual rootless Boca-only READ_ONLY revisado; operaciones históricas `cutover-a-worker-inspect/events-r112` no cubren ese inventario actual.
- **Gobernanza:** PRs #474–#477 cerrados individualmente sin merge ni borrado de ramas, tras consenso documentado de Arquitectura/Seguridad, Infraestructura/DevOps y QA en [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6797512465). #478 permanece candidato único DRAFT hasta recertificación y host.

## Continuidad y enlaces

- Checkpoint original: [R172 canónico](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6796157137).
- Estado de rescate: [R173 primer checkpoint](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6796390754).
- Evidencia incremental: [R173 controles y RCA](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6796676516).
