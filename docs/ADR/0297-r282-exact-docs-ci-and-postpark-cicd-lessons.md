# ADR 0297 — R282: realimentación CI selectiva y lecciones del reemplazo post-PARK

**Fecha:** 13-NOV-2026 (ART). **Estado:** candidato CODE_ONLY reenfocado sobre
`main=43aaefe` en rama `fix/417-r282-ci-focused`; pendiente de PR/revisión/merge. No es una
instalación ni una certificación física. **Autoridad:** titular, issue
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
servicio anterior; **la versión nueva no está instalada**. El guard por fase
R280 permanece en el PR #514 pendiente de integración. Este ADR no autoriza
reejecutar #1085, R186 ni la recuperación #1095.

## Qué construye realmente CI/CD

- CI tiene `quality-and-tests` y `image-build`. En código, la segunda
  prueba una pareja local controller/browser. Para PRs Markdown internos
  ya se omiten imágenes por un clasificador estricto R245.
- `Image Security` en main tiene dos builds/escaneos independientes con
  caché Buildx **sólo de lectura**. CI y ese workflow comparten scopes
  `boca-main-controller-r247` y `boca-main-browser-r247`;
  únicamente main puede **exportar** los scopes desde CI. Si Buildx o su
  caché fallan, se usa build frío obligatorio.
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
en los dos jobs de CI. Únicamente un **PR interno contra main**, con
`GITHUB_SHA` igual al merge sintético de dos padres exactos
`[merge, base, head]`, base ancestro, historial presente y **solo**
archivos regulares `.md` bajo `docs/ADR/` o `docs/handoffs/`
puede omitir los pasos costosos del job `quality-and-tests`. En
esta ruta, el job obligatorio comprueba `git diff --check HEAD^1 HEAD`
y publica `BOCA_CI_SCOPE mode=DOCS_ONLY`.

Ante un fork, workflow_dispatch, push, SHA inconsistente, merge no
atestable, ruta fuera de la lista, symlink, ejecutable, rename o
entrada vacía, el clasificador responde `false` y **ambos jobs
mantienen la ruta completa**. No confía en títulos/etiquetas del PR ni
en listados incompletos de API. Las comprobaciones de código,
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
systemd, política y Zizmor). **Cada comprobación de Ruff/formato/mypy
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

**Sin efectos externos:** ningún Docker, SSH, release, volumen, secreto,
puerto, navegador ni host tocado. `SIMULATION_ONLY` y exclusión total
de Porota/PPI Watch/recursos ajenos.

## Mejora separada, pendiente de implementación revisada

1. **Recuperación primero — CERRADA:** R281 restableció CIDs/binding
   originales con un solo intento (#1095) y prueba física independiente
   (#1096). Conservar los recibos; no reutilizar leases de #1085 ni R186.
2. **Validar transiciones, no rutas fijas:** R280 debe demostrar
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

## Pruebas y aceptación

TDD en `tests/test_r282_ci_quality_docs_only.py` y
`tests/test_r282_fast_quality_gate.py`; preservación de
las pruebas originales R245 y R247 en
`tests/test_ci_docs_only_fast_path.py` y
`tests/test_r247_buildkit_cache_trust.py`.
**Resultado local del corte final:** 60 PASS para documentación, caché,
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
No ejecutar suite histórica completa ni crear imágenes
para esta comprobación local. La aceptación definitiva requiere PR,
Actions GREEN de SHA exacto y observación comparativa de tiempos en
una futura documentación-only PR; **no se atribuye ya un ahorro medido**.
