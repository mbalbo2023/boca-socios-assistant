# R310 — checkpoint del autor separado

Estado: DONE_WITH_CONCERNS para relevo/congelación. Implementación y verificación focal completadas; revisión independiente final, integración/CI y medición física pendientes. El autor no emite voto de aprobación propia.

## Identidad y estado git

Worktree exclusivo: /workspace/scratch/6fbf8bcd39e6/boca-capacity50.
Rama: feature/531-capacity50.
Base recibida:78a07096446fa261671e2f75dac0284ae7f0478d.
Commit congelado:9c08e90d7c16fe12261f7fac35905ced9ebc8541.
Commit modifica sólo3 rutas:src/boca_socios/browser/capacity_fixture.py (nuevo,920 líneas), tests/test_browser_capacity_fixture.py (nuevo,551 líneas), .github/workflows/boca-playwright-offline-diagnostic.yml. Total1486 inserciones/2 eliminaciones.
Después del commit no quedan cambios de archivos tracked; git status muestra únicamente `?? .superpowers/`, que contiene este informe y los logs locales solicitados. No se hizo fetch/rebase/push/PR/Actions.

Consenso previo real4/4:issue531/comment6903879186. AGENTS y spec/plan R310 leídos. Root informó luego que PR530 quedó en main b3200f7bc4391156205dab992989a609253ec6ee con árbol idéntico a la base productiva; no se modificó esa rama ni se repitió su trabajo.

## Implementación C1–C10

- C1:SharedBrowserPool y EngineSessionRegistry reales, EngineIdentity/EngineRequest reales. Observador fino local con préstamo real, contexto/página y sin factory automática BLACKBOX. Imports de Playwright diferidos al trabajo interno; wrapper runner usa stdlib.
- C2:dos activaciones25 (15/5/5) y total30Chromium/10Firefox/10WebKit. Servidor asyncio127.0.0.1 efímero, HTML literal, routing sólo al origen/path fijados; WebSockets se cierran. No URL del titular, login, BD, proveedor ni volumen.
- C3:pool opening_interval8s intacto; admisiones secuenciales por registry con plazos internos existentes. Trabajo600s y cierre independiente15s. Wrapper envelope650s y attach625s para dejar tiempo a lectura/retirada; no retry. La Action conserva timeout externo650s.
- C4:barrera exige50 préstamos no liberados,50 contextos/50 páginas distintos y vivos, distribución exacta, browser conectado y lectura DOM de todos. Escribe los50 pares cookie/localStorage primero y sólo después lee/verifica los50. Valores sintéticos no salen en recibo.
- C5:close_scope=activation A,25 cierres/25B vivos y DOM nuevo B; replay A NO_GO sin crear observadores ni cambiar live_contexts. CierreB, registry y pool; verifica páginas/contextos cerrados y browsers desconectados. Poison/cierre fallido impideGO.
- C6:un contenedor creado con1CPU/768MiB/128PID, UID/GID10002, init/networknone/rootfsRO/capdropALL+SYS_CHROOT/no-new-privileges/IPC+cgroup privados/shm64MiB/tmp32MiB/home16MiB/seccomp existente. validate_worker_boundary y _require_no_egress_namespace (alias require_no_egress) reales, sin wrappers que anulen sus guardas. Atestación CID/imagen/run/comando/perfil/PrivilegedFalse, sin mounts/puertos; seccomp efectivo inline se compara como JSON exacto contra el archivo revisado existente. SYS_CHROOT/CAP_SYS_CHROOT son las dos grafías equivalentes ya admitidas por el atestador del repositorio.
- C7:resource_snapshot(root,browser-worker) real de scripts.measure_browser_budget. Perfil exacto antes de I/O; continuidad de cgroup sólo interna.54 muestras máximas:preflight+50 admisiones+barrera+cierreA+final.10 métricas allowlistedCPU/throttling/memoria/PID con UNKNOWN individual; máximos observados y latencias. Sin gate preventivo de headroom.
- C8:JSON cerrado version1/RUNNER_OFFLINE, source/image/run/perfil, estados/razones finitos, conteos0..50, checks, fases, tiempos finitos<=650, métricas0..2^63−1|UNKNOWN. Duplicados/extra/cambios de correlación/parcialGO inválidos se rechazan.32768B incluyeLF. Recibo extremo construido ensayado26619B (54 muestras, contadores máximos, run20dígitos, tiempos de serialización larga); no es recibo físico.
- C9:capacity50 agregado al selector cerrado; ambos steps históricos se omiten sólo allí, cuerpos/nombres legacy conservados. Build sigue siendo de una imagen. Wrapper crea un únicoCID con cidfile propio, fuente por revisión del ID inmutable, atesta antes de start y antes de retirada; captura acotada sin stderr crudo. GO global exige reciboGO válido + transporte conocido + attachexit0/estadoexited/exitcode0/noOOM/errorvacío + rm exacto del CID atestado y listado exitoso que confirma ausencia. Retirada incierta/timeout/oversize/deriva=>NO_GO. Recibo interno válido se imprime como evidencia y no reemplaza el GO global. Nunca se publica contenido arbitrario.
- C10:sólo tres rutas y ensayos focales. No se modificaron pool/registry/motores/Dockerfile/dependencias/BLACKBOX/otros tests. Root conserva docs/GitHub/CI/operación y la prioridad R309/Telegram.

## RED y correcciones verificadas

Comando base:PYTHONPATH=src:scripts /workspace/scratch/6fbf8bcd39e6/boca-r307/.venv/bin/python -m pytest -q tests/test_browser_capacity_fixture.py

1. Antes de crear fuentes:new module ausente y selector faltante=>2 FAIL/12 ERROR en0.20s; red.log. Los ERROR son aserciones del fixture `capacity measurement harness absent` por la función que todavía no existe; no dependencias/imports externos rotos. No se los presenta como defectos del pool.
2. Primer producto:13 PASS/1 FAIL; green-first.log. Ese fallo era test incorrecto:encode no conoce el SHA externo; la correlación esperada corresponde a decode(raw,meta). Se corrigió la expectativa, sin relajar codec.
3. Regresiones de fronteras:27 PASS/2 FAIL; red-boundaries.log. Fallos productivos del delta:closed_final8 cuando sólo7 contextos existían y ShmSize no atestado. Correcciones:contar sólo contextos existentes cerrados y atestar67108864 exacto. Después29 PASS; green.log.
4. Revisión propia:binding de revisión hacía segunda lectura por tag mutable; RED real1 FAIL/2 PASS en red-identity.log. Corrección:resolverID, validarID y leer revisión por eseID antes de create. Los otros dos casos verifican cambio físico del directorio cgroup y cierre externo detenido con deadlines reales cortos vía API.
5. Revisión de API Docker acreditada por código existente(host_cutover_worker_preflight→_browser_effective_seccomp_options y recovery):SecurityOpt usa JSON efectivo inline. RED2 FAIL en red-seccomp.log para falso rechazo del perfil válido inline y aceptación indebida PrivilegedTrue. Correcciones terminadas dentro del módulo nuevo:JSON exacto fuente/efectivo y PrivilegedFalse.
6. Ruff inicial detectó imports/formato/literales de rutas fijas, y mypy3 anotaciones; corregidos. Revisión YAML corrigió descripción con dos puntos sin comillas antes del commit. YAML final se parseó correctamente.

## Verificación final indispensable

Comando exacto:
`PYTHONPATH=src:scripts /workspace/scratch/6fbf8bcd39e6/boca-r307/.venv/bin/python -m pytest -q -rP tests/test_browser_capacity_fixture.py tests/test_playwright_offline_diagnostic.py::test_closed_mode_is_validated_before_the_first_docker tests/test_playwright_offline_diagnostic.py::test_actual_shell_selects_only_the_closed_profiles_once_in_order tests/test_release_image_capacity_observer.py::test_three_engine_launches_are_independent_opt_in_offline_containers`

Resultado:41 PASS,exit0,0.65s.34 casos nuevosR310 +7 casos de contratos workflow afectados. final-focal.log. No suitebase/pool50 ni benchmark físico local.

Las pruebas usan pool/registry/validadores reales. Dobles sólo en fronteras externas:Playwright/context/page, archivos de cgroup/UID/GID/interfaces, reloj para no esperar392s y subprocessDocker. Un test de transporte ejecuta sólo hijos Python inertemente para comprobar oversize y timeout. Los estadosGO de esas unidades NO acreditan capacidad física.

Casos nuevos:simultaneidad/handles repetidos/aislamiento compartido, apertura parcial, B inutilizable, fallo/timeout de cierre, guardas UID/red/límites antes de admisión, deadlineglobal, continuidadcgroup, codec cerrado/duplicados/correlación/partialGO/NaN/cota extrema, routing origen fijo, outputoverflow, modos/skips/shell, nueve variantes de autoridad externa(recibo/transporte/exit/OOM/retirada/ausencia incierta/deriva/creación incierta), perfil/command/source/mount/port/shm y seccomp efectivo/privilege.

Calidad:
- ruff check src/boca_socios/browser/capacity_fixture.py tests/test_browser_capacity_fixture.py=>All checks passed,exit0; ruff.log.
- ruff format --check mismas dos rutas=>2 files already formatted,exit0; format.log.
- PYTHONPATH=src:scripts mypy src/boca_socios/browser/capacity_fixture.py=>Success:no issues found in1 source file,exit0; mypy.log.
- bash -n del step capacity50=>PASS dentro de focal.
- PyYAML safe_load del workflow final=>PASS; opciones exactasfull3/firefox-pids/capacity50 y último step confirmados. PyYAML trata `on` como True (YAML1.1), sólo se usó para verificar estructura, sin reserializar.
- git diff --check=>exit0 antes de commit.

## Pendientes y riesgos explícitos del relevo

1. NO se ejecutó Docker, buildimagen, Playwright físico, carga392+s, Action ni host. No hay evidencia de50 contextos físicos, runtimeDocker inspect real, recursos observados ni retirada física. No confundir41unidadesPASS con capacidad50.
2. Falta revisión independiente final de Arquitectura/QA/Operaciones/root. El autor no se autoaprueba. El código se congela para evitar pérdida de trabajo durante avisos de red, no para promoverlo.
3. Root debe copiar este informe/logs al checkpoint durable, reconciliar main/base y priorizarCI530/diagnósticoTelegram antes de publicar unPR o ejecutar capacidad50; conservar las instalaciones/observaciones cerradas.
4. CI exacta/merge/mainGREEN y un único despacho runner revisado siguen pendientes. No autorización de prueba de droplet, selectorhost, cuotas mayores o retry.
5. Atestación y transporte son fail-closed; formatos Docker inesperados o límites agotados pueden producirNO_GO. La comparación de seccomp usa JSON fuente exacto, sin aceptar un perfil parecido. Sólo la operación futura podrá acreditar su compatibilidad física.
6. Timeout de envolvente/pérdida de daemon/runner/transporte o imposibilidad de atestar CID puede impedir confirmar retirada. Resultado global debe permanecerNO_GO/UNVERIFIED; no borrar recursos inciertos ni encadenar retry. Un recibo internoGO por sí solo no autoriza nada.
7. El módulo/fixture no acredita proveedor/DOM autenticado, reservas, coordinaciónIPC/durable, panelSTOP, Telegram o capacidad del droplet. SIMULATION_ONLY/senderOFF/datos/passkeys/otrosproyectos intactos.

Instrucción breve de relevo:retomar rama feature/531-capacity50 en 9c08e90d7c16fe12261f7fac35905ced9ebc8541, leer este informe y spec/planR310, NO repetir unidades/baselines acreditados; completar revisión independiente y reconciliaciónroot, manteniendo prioridad de R309/Telegram. Nada fue publicado o despachado por este autor.
