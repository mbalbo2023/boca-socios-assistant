# ADR 0297 — R282/R293: CI medible y lecciones del reemplazo post-PARK

**Fecha:** 13-NOV-2026 (ART). **Estado R293:** integración CODE_ONLY de R282
existente (`78cf88ae94485c04ceebaa29885388b1268f57f5`) sobre base
`0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe`, rama
`feature/417-r293-ci-measured`. El estado y los tiempos del SHA revisado se
registran en [#417/R293](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869386141).
Este cambio no publica imágenes ni instala código en el droplet.
**Autoridad:** titular, issue
[#417 R277](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861598271);
RCA [R276-a](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861462459).

## Incidente, sin confundir causa con síntomas

El 13/11, el APPLY [#1085, run 43479367282](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43479367282)
del fuente `3a933f0` duró aproximadamente 3 minutos y terminó después
de SSH/PARK, **antes** de crear contenedores nuevos:
`failed_phase=CREATE_WORKER`, `commit_started=false`,
`old_restored=false`, `cleanup=INDETERMINATE`. El tiempo de
indisponibilidad posterior no es una compilación Docker de dos días.
El código de `retained_resources` buscaba el inode de control en
la ruta canónica que `park_binding` acababa de mover a la ruta
estacionada. La compensación `restore_old` repetía esa misma
suposición de ruta, bloqueando también el regreso. Los objetos Docker
anteriores no fueron declarados corruptos.

La observación READ_ONLY inicial
[#1090, run 43489690300](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43489690300)
probó **dos CIDs históricos exactos estacionados**, binding estacionado y
journal precommit, con `observer_writes=0`. Luego la restauración protegida
**[#1095, run 43498113370](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43498113370)**
terminó `RECOVERED_OLD_PAIR`, con `foreign_resources_touched=0`, sin arrancar
el worker. El observador independiente **[#1096, run 43498385438](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43498385438)**
probó `source_sha=b61ca3e`, controller `running/healthy` en loopback 8443,
worker `Created/PID0` y `observer_writes=0`. R281 cerró la recuperación del
servicio anterior. Posteriormente R280 se integró por PR #514; release #864
y [APPLY #1102](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43534359504)
instalaron la pareja nueva de `0ebecb6`, certificada por
[R291](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6868819579):
controller healthy, worker CREATED/PID0, SQLite estable y HTTP 200 en 8443.
El observador histórico #1108 no prueba fallo del par actual. Este ADR no autoriza
reejecutar #1085, R186 ni la recuperación #1095.

## Qué construye realmente CI/CD

- CI tiene `quality-and-tests` y `image-build`. En código, la segunda
  prueba una pareja local controller/browser. Para PRs Markdown internos
  ya se omiten imágenes por un clasificador estricto R245.
- `Image Security` en main tiene dos builds/escaneos independientes con
  caché Buildx **sólo de lectura**. Antes de R293, CI exportaba en main los
  scopes `boca-main-controller-r247` y `boca-main-browser-r247`. R293 conserva
  exportación sólo del controller; el browser de CI usa el builder Docker
  nativo. Security conserva su caché histórica de browser como lectura
  opcional y su fallback; ningún hit es evidencia de revisión o publicación.
- `release-image.yml` hace **dos builds fríos separados** y dos Trivy
  antes de publicar digests; la prohibición de importar cachés a la
  release es **deliberada** (ADR 0253/R247), no una tarea olvidada.
  El propio release admite un único primer dispatch por SHA, sin
  reconstruir indefinidamente la misma release.
- El Dockerfile controller contiene `COPY src ./src`. Por tanto,
  incluso un cambio en `host_*.py` altera sus bytes y requiere la
  validación de imagen de ese SHA. Browser copia sólo subconjuntos
  browser/domain, pero el contrato de etiquetas y release dual también
  liga ambos a un SHA de repositorio. **No** se pueden clasificar los
  cambios R281 como «sin impacto de imagen» sin rediseñar y probar esa
  frontera de empaquetado. Los jobs de CI/seguridad/release crean
  artefactos efímeros distintos; sus conteos no significan 6 imágenes
  desplegadas en el droplet.

## Decisión R282 implementada, de riesgo acotado

Extraer el clasificador R245 a
`scripts/classify_exact_internal_pr_docs.py` y usar la misma lógica
en los tres jobs de CI. R293 lo ejecuta desde el blob regular autenticado
del **base** con `python3 -I -`: un helper modificado en el candidato no puede
autoeximirse, y sus módulos/imports locales no controlan el clasificador.
Si el base aún no contiene el helper, la primera integración usa FULL.
Únicamente un **PR interno contra main**, con
`GITHUB_SHA` igual al merge sintético de dos padres exactos
`[merge, base, head]`, base ancestro, historial presente y **solo**
archivos regulares `.md` bajo `docs/ADR/` o `docs/handoffs/`
puede omitir los pasos costosos del job `quality-and-tests`. ADR0159 queda
excluido porque es entrada de un test contractual. En esta ruta,
`fast-quality` comprueba `git diff --check HEAD^1 HEAD` y
`scripts/check_repo_policy.py` (incluye unicidad de ADR); los jobs requeridos
dependen de ese éxito y publican `BOCA_CI_SCOPE mode=DOCS_ONLY`.

Ante un fork, workflow_dispatch, push, SHA inconsistente, merge no
atestable, ruta fuera de la lista, symlink, ejecutable o
entrada vacía, el clasificador responde `false` y **ambos jobs
mantienen la ruta completa**. No confía en títulos/etiquetas del PR ni
en listados incompletos de API. `--no-renames` representa un traslado como
delete/add: sólo admite ambos paths si cumplen la misma lista estricta.
Las comprobaciones de código,
Compose, tipos, RCA, Linux IPC, systemd, política, imágenes y seguridad
siguen siendo obligatorias para cualquier cambio de fuente/workflow.
Este nuevo PR, al cambiar workflow y Python, pasará por **FULL**.
Los pushes a main, incluso de documentación, conservan los gates
habituales: esta decisión sólo acelera la iteración/revisión de
documentos estrictos y evita duplicar el detector.

### R282-B — gate rápido antes de imágenes y pruebas costosas

**Observación adicional:** el primer CI del PR de recuperación #513
[43494859810](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43494859810)
falló en `Format` cuando `image-build` ya compilaba Chromium; la
segunda iteración
[43495124342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43495124342)
falló en `Types` mientras `image-build` alcanzaba su escaneo. Ambos
trabajos de imágenes fueron cancelados tras consumir tiempo. La tercera
iteración
[43495555858](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43495555858)
superó las comprobaciones preliminares pero falló después en colección
de tests por importar `PyYAML` fuera del grafo bloqueado (sin ejecutar
casos); el PR R281 lo corrigió en la siguiente revisión, SHA
`665c193d`. Esto demuestra que **pasar formato y tipos todavía no
alcanza** para comenzar builds pesados. Un CI
anterior GREEN
[43488257927](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43488257927)
registró `quality-and-tests` de 2m43s e `image-build` de 5m30s en
paralelo. Eso permite medir el desperdicio en la ruta RED y advierte
que serializar un precheck puede prolongar la ruta GREEN.

Por ello, separar un trabajo `fast-quality` (checkout SHA, mismo
clasificador estricto, `uv sync --frozen`, Ruff, formato, mypy y
`pytest --collect-only` de la colección completa **sin ejecutar
pruebas**)
de `quality-and-tests` (Compose, tests completos, RCA, AF_UNIX,
systemd y Zizmor). Política corre temprano incluso en la ruta documental.
**Cada comprobación de Ruff/formato/mypy
se ejecuta una sola vez.** Tanto la compilación/escaneo `image-build`
como `quality-and-tests` dependen del éxito de `fast-quality`.
Cuando falla el gate rápido por formato, tipos o imports de tests,
`image-build` no empieza; el job
**obligatorio** `quality-and-tests` usa `if: always()` y un paso
inicial que falla explícitamente si `needs.fast_quality.result` es
distinto de `success`. Así no aparece un required check
«verde por skipped». El gate de documentación estricta opera en
`fast-quality` y el job `quality` hereda su resultado.

La implementación no presupone ahorro en la ruta GREEN: agrega un
runner/checkout/uv sync/colección secuencial. Se estima un coste de hasta
~1–2 minutos según colas y cachés, sujeto a medición exacta en Actions;
se acepta frente al coste comprobado de repetir builds Chromium
tras un error trivial. Si la medición demuestra regresión excesiva,
se revisará el diseño con evidencia real, sin eliminar el gate.
Un error de mypy, formato o repositorio no crea imágenes ni toca
el host. `Image Security` independiente en main y release frío
R247 permanecen intactos.

**Límite de efectos:** las pruebas locales son offline; Actions usa Docker
sólo en su runner descartable. No hay SSH, release ni operación de host,
credenciales o datos del titular. `SIMULATION_ONLY` y exclusión total de
Porota/PPI Watch/recursos ajenos.

## Mejora separada, pendiente de implementación revisada

1. **Recuperación primero — CERRADA:** R281 restableció CIDs/binding
   originales con un solo intento (#1095) y prueba física independiente
   (#1096). Conservar los recibos; no reutilizar leases de #1085 ni R186.
2. **Validar transiciones, no rutas fijas — INTEGRADO:** R280 demuestra
   `STAGED → PARKED → CREATE → COMMIT` y compensación cuando falla
   cada frontera, con identidad de inode en canonical/parked según
   fase. Una ruta ausente después de moverla no equivale a corrupción.
3. **Pre-PARK antes de afectar 8443:** además de hashes/digests, observar
   puerto libre, socket residual, CIDs exactos, unidad systemd,
   volumen/directorios y journal. El compensador no debe depender del
   guard de la fase posterior; una sola operación host serializada.
4. **Medir antes de optimizar más:** por SHA registrar segundos de
   cola, calidad, controlador/browser build, hits/misses de caché,
   Trivy, release y host PARK→postflight; separar tiempo de ingeniería
   entre fallos de minutos. Sin una medición no prometer ganancias.
5. **No forzar skipping de imágenes host-only** mientras el Dockerfile
   copie todo src y ambos roles tengan revisión SHA completa. Si
   se propone excluir módulos host del runtime, crear una arquitectura
   explícita de cierre de imports, packaging reproducible y tests
   sobre imagen; no cambiar la confianza de release R247 como atajo.
6. **Una release por SHA fusionado:** conservar CI focalizada durante
   desarrollo, checks aplicables exactos previos al merge y release
   controlada una sola vez. Nunca rehacer release #863 del SHA
   `3a933f0`; para fuente nuevo construir/revisar solo su pareja.
7. Registrar cada RCA en GitHub/ADR y, cuando exista el PR corrector
   aceptado, añadir sus selectores al registro ejecutable
   `docs/quality/rca-lessons.json`; requiere `fix_pr` real, no
   inventarlo en una rama no fusionada.

## R293 — línea base de Actions y optimización acotada

La auditoría usa `created_at` entre `2026-11-12T00:46:20Z` y
`2026-11-14T00:46:20Z`, ambos inclusive, mediante
[REST Actions](https://api.github.com/repos/mbalbo2023/boca-socios-assistant/actions/runs?per_page=100&page=1&created=2026-11-12T00%3A46%3A20Z..2026-11-14T00%3A46%3A20Z),
páginas 1–3, y los jobs/steps de los 263 runs de CI, Security, Release y
First Deploy. Los 272 runs tienen `run_attempt=1`. Duración de workflow =
`updated_at-created_at`; jobs/steps = `completed_at-started_at`. Las medianas
son de SUCCESS. Tiempo agregado de jobs no equivale a pared ni a dinero.

| Workflow / evento | Runs | Success | Failure | Cancelled | Mediana SUCCESS |
|---|---:|---:|---:|---:|---:|
| CI / push | 31 | 31 | 0 | 0 | 305 s |
| CI / PR | 52 | 42 | 2 | 8 | 337,5 s |
| Image Security / push | 31 | 31 | 0 | 0 | 130 s |
| Image Security / PR histórico | 12 | 11 | 0 | 1 | 111 s |
| Image Release / dispatch | 5 | 5 | 0 | 0 | 209 s |
| Image Release / PR histórico | 12 | 11 | 0 | 1 | 125 s |
| First Deploy / dispatch | 68 | 47 | 20 | 1 | 24 s |
| First Deploy / PR | 52 | 46 | 2 | 4 | 131 s |
| Panel Preview / PR | 8 | 8 | 0 | 0 | 10 s |
| Invocación inválida por ruta | 1 | 0 | 1 | 0 | — |
| Total | 272 | 232 | 25 | 15 | heterogéneo |

**Corrección a R292:** hubo cinco publicaciones exitosas sobre cinco SHA,
no dieciséis. Los otros once éxitos de Release fueron validaciones de PR.
Las cinco publicaciones suman 1032 s. Entre los 68 First Deploy manuales
hay seis intentos de upgrade (uno exitoso, cinco fallidos), un finalizador
R186 y una recuperación R281; el resto son observaciones o rechazos previos.
Los eventos PR de Security/Release son históricos: main ya eliminó esos
builds duplicados de PR antes de esta continuación, y R293 no los recrea.

### Cuellos de botella observados

1. **Intervalo de promoción:** commit `0ebecb6` a las 20:44:24 UTC;
   [CI1239](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43504324623)
   terminó 20:50:21. APPLY1102 se creó 00:27:55 del día siguiente:
   **217 m 34 s entre CI terminado y dispatch**, sin run esperando en ese
   intervalo. Commit→APPLY inicio fue 223 m 31 s; commit→APPLY fin,
   231 m 35 s. Release864 (209 s) se solapó con CI; no sumar ambos como
   etapas seriales ni atribuir el intervalo a una causa personal inferida.
2. **Camino de imágenes:** CI1239 duró 353 s; image-build 349 s y quality
   187 s (tests 164 s). Imágenes terminó último en 66/73 CI exitosos.
   El browser tardó 122 s y controller 16 s. El último
   [CI de PR1238](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43503291168)
   duró 385 s: imagen 382 s, quality 134 s, browser 117 s.
3. **Runner duplicado:** el
   [First Deploy PR1099](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43503291045)
   duró 128 s, con Cutover/ZIP/cleanup 48 s, observadores 32 s y dispatch
   boundaries 14 s. Sus 23 pytest seleccionaban 144 módulos ya cubiertos
   por CI completo; ocho mypy src seleccionaban diez archivos ya cubiertos
   por `mypy src`. Reducirlo ahorra runner; CI ya más largo determina el merge.
4. **Fallo temprano y cancelación:** siete de los ocho CI cancelados
   tenían un job fallido. Nueve runs con jobs fallidos sumaron 2213 s de jobs.
   Los cinco fallos de formato/tipos consumieron 706 s de imagen, 630 s
   después de fallar calidad. R282 evita iniciar esas imágenes, pero añade
   prechecks secuenciales a cada candidato sano; el ahorro neto sigue por medir.
5. **Iteraciones de publicación y APPLY opaco:** releases861–863 sumaron
   623 s; rechazos pre-SSH1074/1076/1081, 88 s; incidente1085, 183 s.
   APPLY1102 tuvo 7 s de espera, 476 s de job y 469 s en un solo paso.
   El log público no permite separar rigurosamente pull, PARK y POSTFLIGHT.
   Primero validar contratos de fase y cronología, después congelar una
   promoción; no fabricar tiempos internos ni repetir APPLY para medir.

### Caché: medir transporte además de hits

El [job de CI1239](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43504324623/job/132157888114)
declara capas `CACHED`, pero materializar 859,79 MB toma 65,6 s
(54,5 s de descarga y 9,8 s de extracción incluidos), exportar a Docker
33,5 s (incluye importar 22,6 s), y exportar GHA 12,8 s. En el PR anterior,
materialización 72 s y exportación a Docker 34 s. No sumar subtiempos dos veces.

| Mismo SHA, runners distintos | Browser CI GHA | Browser release nativo |
|---|---:|---:|
| `0ebecb6` | 122 s | 49 s |
| `3a933f0` | 88 s | 44 s |
| `85e6654` | 70 s | 44 s |
| `0b9820f` | 106 s | 54 s |

Comparaciones indicativas, sin control causal de runner/instante. R293
promueve el fallback browser existente a camino principal único de CI,
`docker build --builder default`, evitando el transporte GHA y la carga
desde un builder container separado. Docker documenta el
[builder nativo y la selección explícita](https://docs.docker.com/build/builders/).
Se conservan Dockerfile/pins, tags SHA de CI/release-validation/observer,
labels source/revision/run, ambos Trivy y todos los labs. No hay segundo
build de benchmark ni publicación. Controller mantiene GHA y fallback;
Security y release protegida no cambian. Su duplicación de builds/scans en
push queda identificada, pendiente de una revisión separada de confianza.

Medianas de los 73 CI exitosos: instalar uv 2 s, sync 1 s, mypy 5 s,
tests 105 s; lint/formato 0 s a resolución de segundos. No agregar caché
Python por esos 3 s. La reorganización de capas README se difiere porque
requiere medir frío/caliente; R293 no modifica ningún Dockerfile.

### Consolidación de validaciones PR sin alterar la operación manual

`first-deploy-pr-validation` conserva Compose BETA controller-only,
Compose browser IPC, generación del bundle protegido, el mypy exclusivo
de `scripts/check_worker_physical_dispatch.py`, política y barrera de
ausencia de recibos host. Se eliminan 23 pytest y ocho mypy src redundantes.
El CI requerido ejecuta una vez la suite completa; no se reemplaza por
selectores ni por un resultado histórico. `assert_required_ci_covers`,
helper sólo de tests en el archivo existente de contrato pytest, comprueba
comando real, testpaths, cuatro exclusiones autorizadas y descubrimiento de
cada módulo migrado. Los 27 contratos mantienen sus otras comprobaciones.

Todo el bloque manual `deploy:` permanece idéntico: 357148 bytes,
SHA256 `c5ee97ead6f5b870e1280c58f583fb5bdc90627bf1ee9fa32ab9d2d8285f48fc`.
No cambian runtime, algoritmos, Compose, publicación, permisos, protección,
SSH ni código de recuperación R280. El primer PR R293 usa FULL también
porque su base no contiene el helper; cualquier error del clasificador
mantiene la validación completa.

### Plan, medida posterior y límites de aceptación

Un único candidato revisado consolida R282, cierre de clasificación,
browser nativo y deduplicación de PR. Antes del push: regresiones focales,
formato/lint, política, revisión independiente y comprobación de integridad
del bloque manual. Después: checks requeridos del SHA exacto actualizado,
comparar fast-quality, browser, image-build, calidad, First Deploy y total
con PR1238/1099; después del merge comparar push con CI1239. No crear otra
release ni un commit sólo para registrar métricas: resultados y URLs en #417.

Se medirá el sobrecosto del gate por separado del build y el tiempo de
runner evitado por deduplicación. Un resultado puntual acredita esa
ejecución; no establece una mediana nueva ni aísla causalmente todos los
cambios. No prometer un porcentaje antes de Actions. La ruta documental
queda probada con Git sintético y se medirá cuando haya un PR documental
real; no fabricar uno para inflar métricas. Las funcionalidades R292 y la
aceptación del titular permanecen pendientes, fuera de esta fase.

### R285 — bloqueo de merge por rama atrasada, no por CI rojo

En la continuación de R280, el SHA `e06aa4c` tenía los jobs
`quality-and-tests` e `image-build` en SUCCESS (CI #1237, first-deploy
PR #1098). Sin embargo, GitHub devolvió HTTP 405 con «2 required status
checks are expected» al solicitar squash de PR #514. La comprobación
física de la UI aclaró la causa: **«This branch is out-of-date with the
base branch»**. El ruleset `protect-main` #26163295 exige checks estrictos
del HEAD **al día con** `main` y protege su integración. No era error SQL,
imagen Docker fallida, permiso de administrador ni necesidad de borrar
contenedores. Ver [checkpoint R285](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6864320151).

El operador actualizó la rama una única vez desde GitHub. El merge de
`main` produjo SHA `fc90aef71ab04bafbd96f4414b34b0d96d580344`;
los nuevos CI #1238 y first-deploy PR #1099 verifican ese **SHA exacto**.
De aquí en adelante, el procedimiento previo al merge es:

1. Leer reglas de rama y `base.sha`, `head.sha`, `mergeable`; cotejar si
   GitHub muestra «out-of-date». No inferir readiness del verde en un
   commit anterior.
2. Si está atrasado, incorporar `main` **una sola vez**, esperar las
   comprobaciones requeridas en el nuevo HEAD y verificar su origen
   GitHub Actions, sin cambiar el ruleset.
3. Fusionar solamente tras comprobar el nuevo SHA, sin reintentos ciegos
   de HTTP 405, y congelar `main` durante una release y un APPLY de
   riesgo hasta la verificación física de ambos.
4. Un cambio solamente de CI/documentación se tramita **por separado**,
   sin crear una release nueva ni desplazar el SHA de la promoción física
   mientras está en curso. Así no se consumen otro PARK o nuevas imágenes
   por una mejora de pipeline.

## Pruebas históricas de R282 y aceptación R293

TDD en `tests/test_r282_ci_quality_docs_only.py` y
`tests/test_r282_fast_quality_gate.py`; preservación de
las pruebas originales R245 y R247 en
`tests/test_ci_docs_only_fast_path.py` y
`tests/test_r247_buildkit_cache_trust.py`.
**Resultado histórico local de R282:** 60 PASS para documentación, caché,
workflow y gate rápido; un warning ambiental de `pytest`/AnyIO sin
fallo; Ruff check y formato de los archivos nuevos/modificados;
sin dependencia nueva de PyYAML; los tests ejecutaron la
propagación de failure/cancelled/skipped del required check.
La colección local `PYTHONPATH=src pytest --collect-only -q`
finalizó en **8271 tests recogidos en 10.64 s**, sin ejecutar casos.
Tras reenfocar exclusivamente los tres commits R282 sobre el `main` de
R281 (sin reintroducir R278), se verificaron además **32 tests focalizados
PASS**, Ruff check y formato PASS; **8291 tests recogidos en 10.08 s**
sin ejecutar casos. Estas cifras corresponden a dos árboles distintos,
no a un retroceso ni a un segundo despliegue.
R293 reproduce siete regresiones antes de corregir la clasificación base,
imports, ADR contractual y política (RED); el contrato de browser nativo
y el de invocaciones duplicadas también fallan antes de sus cambios.
Verificaciones focales posteriores: 70 PASS del integrador para clasificador,
gate, caché, identidad del par y política, más dos fixtures reales de
checkout shallow (depth 2 positivo, depth 1 FULL); 28 PASS del implementador de
deduplicación para las funciones migradas. La auditoría confirma cobertura
de los 144 módulos y diez archivos de tipos originales. Los resultados
revisados del árbol final y de Actions se registran en #417, sin atribuir
estos tiempos locales a CI alojado.

No ejecutar suite histórica completa ni crear imágenes
para esta comprobación local. La aceptación de R293 requiere revisión,
Actions GREEN del SHA exacto y comparación actual de tiempos por etapa.
La medición del atajo documental en un futuro PR documental real es un
seguimiento separado; no bloquea esta integración ni justifica un PR
artificial. **No se atribuye ahorro alojado a los resultados locales.**
