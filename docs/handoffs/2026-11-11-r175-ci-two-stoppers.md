# A45-R175 — Corrección incremental de dos stoppers de GitHub Actions

**Fecha:** 11 de noviembre de 2026, ART. **Producto:** Boca Socios Assistant.
**Estado:** CODE_ONLY, acciones físicas pendientes, **NO_GO** droplet.
**Base protegida:** `main=361e3ff42c44e1b8699d7a3e2d158c9a367b2f86`.
**Candidato único:** [PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478), DRAFT.
**Último SHA físicamente medido (R174):**
`f58aaace9dd9d05760efad0797b182453a264c9a`.

## Evidencia verdadera, sin inferir GREEN

| Workflow R174 | Recibo / estado |
| --- | --- |
| [Panel #43052061689](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061689) | SUCCESS |
| [Telegram V2 #43052061267](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061267) | SUCCESS; sender OFF |
| [CI #43052061549](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061549) | FAILURE: imagen Chromium + nuevo smoke multi-UID |
| [Release #43052061357](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061357) | FAILURE: imagen Chromium; publish SKIPPED |
| [Security #43052061459](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061459) | FAILURE: browser; controlador Trivy SUCCESS |
| [First deploy #43052061447](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43052061447) | FAILURE: browser; PR validation SUCCESS; host SKIPPED |

La suite Python CI de R174 aprobó **6807 tests y 34 subtests**; Ruff,
formato, tipos, el smoke AF_UNIX anterior y el contrato PR Cutover pasaron.
**No** se declaró comprobado el droplet ni se ejecutó el censo.

### Stopper 1 — APT de Chromium

Cuatro builds idénticos registraron `Could not resolve` para los dos
servidores Ubuntu Noble. La alternativa firmada de R174 se activó pero
falló **antes** de contactar el espejo alternativo con
`BOCA_APT_FALLBACK state=NO_GO reason=SOURCES_SCHEMA`.
No se conoce qué diferencia de la fuente base disparó el rechazo; una
hipótesis concreta no equivale a RCA probado.

**Fix-forward R175:** el parser reconoce subconjuntos válidos de los
componentes Ubuntu con `main`, coincidencia de ambos pockets, comentarios
Deb822 y `Architectures: amd64` simétrico. Conserva únicamente URI Ubuntu
origen aceptadas, suites Noble, mismo `Signed-By`, mismos pins apt/libapt/
brotli y Trivy. Un rechazo ahora emite código fijo `detail=...`, sin
imprimir el contenido de archivos o secretos. Se excluyen fuentes extra,
`Trusted: yes`, suites desconocidas, arquitectura distinta y firmas ajenas.

**Prueba TDD:** cuatro casos nuevos RED antes de modificar parser y
GREEN después, más rechazo de campos arbitrarios. Se añadió prueba de
arquitectura permitida RED→GREEN. Total focal del ámbito APT **27 PASS**,
revisión independiente **cero P0/P1**, suite aislada con **6816 PASS +
34 subtests**, Ruff/mypy/policy PASS. Ninguno acredita que el repositorio
espejo sea accesible desde la ejecución real futura.

### Stopper 2 — IPC cross-UID en runner Linux

El nuevo smoke real de UID10001/10002/10003 falló en alrededor de 0,09s
con solo `BOCA_WORKER_IPC_LINUX state=NO_GO` mientras que el smoke AF_UNIX
previo aprobó. Por el recibo antiguo, no se sabe si falló el intérprete,
la creación del socket o el intercambio de mensajes.

**Hipótesis fuerte:** `actions/setup-python` configura un
`LD_LIBRARY_PATH` del Python toolcache que se elimina al utilizar `sudo`
y los procesos con UID separados. [RCA upstream
#871](https://github.com/actions/setup-python/issues/871) documenta el
mismo mecanismo; **no se atribuye la causa sin un recibo nuevo**.

**Fix-forward R175:** solo este laboratorio de GitHub ejecuta el Python
del sistema Ubuntu `/usr/bin/python3`, dueño root y dependencias stdlib,
con `PYTHONPATH` explícito; el runtime instalado del bot no cambia.
Si falla, emite solo `stage=SETUP|WORKER_SPAWN|WORKER_BIND|STRANGER|
CONTROLLER|STOP|CLEANUP`, sin rutas, errores internos, stderr de hijos,
URLs ni tokens. Se preservan los tres UID, SO_PEERCRED, socket y STOP
por PID exacto. Pruebas nuevas 3 RED→GREEN; rama IPC aislada completa
**6810 PASS +34 subtests** y Ruff/mypy/policy PASS. La prueba cross-UID
física se debe repetir en el próximo SHA de Actions.

**Integración completa tras unir ambos fixes:**
`uv run --frozen pytest -q -n 4 --tb=line` **6819 PASS +34 subtests,
0 FAIL (44,92s)**; Ruff check/format, mypy 154 fuentes y política PASS.
Revisión independiente R175: 36 pruebas focales PASS, **0 P0/P1**,
GO_CODE_ONLY, NO_GO físico.

## Cuatro frentes y gates que siguen abiertos

1. **IPC/worker:** el transporte y START/STOP en reposo quedan en revisión
   exact-SHA; producción usa `OfflineNoGoExecutor`. La corrección del
   smoke no es prueba de navegación ni resuelve por sí sola el ExitCode=1
   histórico. La ruta de simulación real requiere autorización técnica y
   aceptación independiente, **sin reservas reales**.
2. **SITE_URL/panel/actividad:** código R172/R173 permanece en PR #478:
   editor passkey puerto 8443, persistencia en volumen solo Boca, montaje
   URL-only RO, error 503 al START divergente, actividad redactada. No hay
   recibo de operación física del panel instalado con este SHA.
3. **Docker/volúmenes/Cutover/bundle:** fallo host previo
   [#42912586832](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42912586832)
   `LEGACY_SINGLETON`; no sabemos si inventario 0 o 2+. Paquete ZIP de
   `cutover-a-census`: 31.965 bytes comprimido / 126.978 fuente, bajo
   límites 64k/160k, pero **sin despacho**. No borrar, renombrar,
   reiniciar ni inspeccionar imágenes ajenas; solo protected main/rootless
   Boca y recibo censo antes de cualquier APPLY.
4. **QA/socios/Telegram:** no se cambian semánticas de socio ni reserva
   real; controles de calidad locales y runner no equivalen a negocio en
   host. Sender Telegram OFF por token previamente expuesto: requiere
   rotación del propietario y validación física separada. Se conserva
   la validación estricta de `getMe/getChat` para claves JSON duplicadas.

## Próximos pasos obligatorios

1. Consolidar una vez el lote R175 y su documentación en **el mismo PR
   #478** mediante actualización compare-and-swap; comprobar árbol remoto
   idéntico al local. No crear otro PR ni duplicar código.
2. Ejecutar suite completa, Ruff, mypy, política, diff-check y revisión
   independiente del árbol consolidado. Publicar el SHA exacto y documentar
   sus **seis** workflows de Actions. Ante un fallo, RCA de job/step y
   fix-forward selectivo. **No transferir checks del SHA anterior.**
3. Solo con workflows requeridos GREEN y revisión conforme, promover PR
   #478 por branch protection. Verificar main y ausencia de PR abiertos.
4. Ejecutar exclusivamente `cutover-a-census` READ_ONLY con titular,
   entorno protegido, `operation=cutover-a-census`, `service=controller`,
   `resource_budget=1.5cpu-1024m-192pids` y parámetros restantes vacíos;
   guardar los conteos y doble atestación de custodia Boca. Un censo de
   estado no autoriza Cutover automáticamente.
5. Solo después de resolver cardinalidad/identidad exacta, realizar Cutover
   V3 protegido y aceptación física de imagen, socket, STOP/START,
   SITE_URL, volúmenes, actividad, socios, Telegram separado y limpieza
   **únicamente Boca**. PPI Watch, Porota y todo Docker ajeno intocables.

La instrucción de relajar seguridad se interpretó como permiso para
**simplificar el harness aislado del runner**, sin debilitar la confianza
de Ubuntu, la imagen instalada, el socket del droplet ni la custodia de
credenciales. Estado general **NO_GO físico hasta evidencia nueva**.
