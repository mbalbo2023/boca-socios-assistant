# ADR 0255 — R248: observador físico sucesor, historia R188 y grafo 2→3→4

**Fecha:** 12-NOV-2026 ART. **Issue:** [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417). **Estado:** `CODE_ONLY / NO_GO`; sin SSH, sin Actions físicas nuevas, sin instalación ni permiso de hacer APPLY.

## RCA de la demora y defecto de identidad

El observador de lease `ProductionSameLeaseCapture` R244 exigía que el `installed_source_sha` y el `installation_attempt` del recibo histórico R188 fueran iguales a los del par instalado que se quiere actualizar. Esto sólo puede coincidir en la primera instalación. En una sucesión **R186 → B → C**, los CIDs, SHA, imágenes y el intento del par B son distintos, pero la procedencia de creación del IPC, SITE y egress debe seguir siendo la del R188 original. Reescribir el recibo antiguo, inferir etiquetas creadoras desde B o aceptar una Step Summary sintética sería una falsificación.

En el mismo actor, `_PairBoundIO.inventory` fijaba exactamente **dos** CIDs. La actualización sucesora exige ver dos originales, luego tres (dos originales y worker candidato), después cuatro (ambos pares) y finalmente dos del nuevo par; el controller viejo se encuentra detenido mientras el nuevo toma `127.0.0.1:8443`. El actor ya limita los IDs exactos, bajo una lease única, pero sin adaptar ese inventario la comprobación del grafo rechaza transiciones legítimas.

## Decisión acotada

Se introduce exclusivamente el módulo `host_boca_successor_physical_v2.py` y se conecta desde `host_boca_successor_integrations.py`, sin modificar R186/R179, el runner, el workflow ni Docker:

1. **`SuccessorCurrentPairCapture`:** usa el receipt del **par actual** y su run de observación V2 autenticados previamente, recaptura dos veces los CIDs/source/image IDs con `pair.observe`, coteja el binding systemd exacto, recursos IPC/SITE/egress de R188 e inode no-follow del directorio de control y devuelve `FreshPairWitness` sólo dentro de `BocaJobLease`. Reutiliza el journal R243 `O_EXCL`/`fsync`/readback, sin crear un segundo journal. Nunca identifica el par B con los contenedores históricos del testigo R188.
2. **`expected_transition_graph`:** forma una lista exacta de 2→3→4→2 CIDs desde el `PairCoordinates`, el receipt anterior y los IDs que el actor R179 **ya devolvió** después de crear cada candidato. No descubre contenedores por `docker ps`, nombre, patrón o etiqueta. Si existe un contenedor no previsto, ID ausente/duplicado o imágenes de fuente distinta, el inventario doble rechaza. Los volúmenes protegidos, montaje y red preservan sus IDs e intentos originales; el controller estacionado nunca puede estar activo a la vez que el nuevo.
3. **`PhysicalSuccessorIntegrations`:** recibe del backend R247 su fase (`NEW`, `STAGED`, `PARKED`, `WORKER`, `CONTROLLER`, `BOUND`, `RETIRED`, `RESTORED`) y valida el censo de 2–4 CIDs con `adapters.observe_retained` bajo la misma lease. Si un candidato quedó creado sin ACK, no aparece en los IDs reconocidos y bloquea la doble lectura. Al restaurar realmente el par viejo, los IDs de candidatos ya retirados permanecen en el objeto para auditoría, pero **sólo en fase RESTORED** desaparecen del grafo esperado; un candidato superviviente hace fallar el censo.
4. **Límite deliberado:** se pasan callbacks efectivos de sólo lectura; `final_cleanup` sigue lanzando NO_GO, la puerta postflight permanece `gate=None` y el tipo `PostflightGatedSuccessorBackend.requires_persistent_receipt` sigue siendo **`False`**. Por eso `run_pair_upgrade` rechaza **antes de adquirir lease, escribir journal o acceder a Docker**. No hay segundo motor ni ejecución de limpieza en este módulo.

## Pruebas y garantías de fallo

- TDD RED al faltar el nuevo módulo, GREEN después de implementar la separación de historia y par actual, transiciones `NEW/PARKED/WORKER/CONTROLLER/BOUND/RETIRED/RESTORED`, captura del B→C con R188 original e integrador de actor en 2/3/4 CIDs.
- Tests de rechazo de ID de candidato ausente o repetido, fuente/revisión alterada, CID/imágenes extraños, volumen relabel, egress con peer extranjero, worker activo, par observado distinto e inode de control desviado; doble captura bajo lease y journal `O_EXCL` one-shot con bytes idénticos tras intento de replay.
- No se leyó el contenido de los volúmenes, SQLite ni credenciales; el worker de navegador no se inicia ni contacta a Boca/Queue-it. La restauración R179 conserva sólo el camino de compensación precommit anterior, y no borra recursos de procedencia histórica. Todos los errores del nuevo adaptador exponen una categoría fija sin información sensible.

## Puertas que permanecen abiertas — no ampliar autorización

1. El bundle sucesor medido por el owner de Actions R247 contenía **8 miembros** y **1.287.795/1.300.000 bytes** de fuente ANTES del módulo de FAILURE V2 (aprox. 22 kB) y de este adaptador. **No cabe en el presupuesto actual:** no ampliar límites sin revisión del propio builder y prueba de consumo real; no omitir módulos necesarios para declarar GO. R248 no modifica bundler, CLI ni workflows, por ownership exclusivo.
2. Falta conectar y revisar la función `execute_durable_failure_cleanup(plan, lease, *, restored, receipt_dir, historical_retained)` de R247 con su propio recibo `NO_GO` de fallo, restauración física exacta y limpieza selectiva; `SUCCESS` y `FAILURE` no son el mismo circuito.
3. Falta instalar una fuente real de aceptación física del propietario vía Chrome/passkey y monitor, además del postflight durable, SITE_URL/worker/SQLite, antes de poder emitir `ACCEPTED`. La fuente R247 no inventa `owner_acceptance` ni `monitor_metadata`.
4. Faltan revisión independiente, PR/checks del SHA exacto, merge protegido/PR0, dos imágenes publicadas y observación fresca bajo Action autorizada; **la instalación antigua R186** continúa siendo el último estado físico observado. No repetir el APPLY fallido ni invocar acciones Docker fuera del workflow único.

**Veredicto:** el RCA de equivalencia histórica falsa y el grafo dinámico están cubiertos en código y pruebas offline; **el deploy BETA sigue NO_GO** hasta que todos los bloqueantes anteriores tengan evidencia física y la ruta protegida esté conectada sin motores duplicados.
