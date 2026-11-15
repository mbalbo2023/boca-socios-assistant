# R301 — Monitor de eventos y navegación observada — Implementation Plan

## Corte posterior: integrado en Q, pendiente de promoción

Las tres tareas y la corrección focal RCA523 se integraron por PR521 en main
Q `7112a4878097bc1696a60a7b1056cd1e7b559ce5`, árbol
`3e328752468895f7c712a9ec9f7630e47e585b91`. CI1268/Security1088 SUCCESS;
9564 pruebas y34 subtests. Las capturas tablet/móvil del artifact14155279204
son OFFLINE_SYNTHETIC_ENGINE_UI, network none, host_checked=false y
physical_device_checked=false. El instalado continúa en M/release866.
R303/#524 corrige el STOP de Telegram antes de evaluar la migración pendiente
y una promoción consolidada del main final. No se repiten estas pruebas ni
se convierten las capturas en aceptación del panel privado instalado.
Las tareas y gates escritos abajo conservan su formulación previa al código;
este corte registra su resultado posterior.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. La raíz asigna autores y revisión; este documento no autoriza al autor a aprobar su propio código ni a operar el host.

**Goal:** Mostrar en el monitor privado el evento y motivo que ya recibe el sistema, distinguir configuración, último intento real y última URL final recibida, y hacer visible la llegada de tokens por sesión usando el polling y el reveal existentes.

**Architecture:** Extender la inspección privada existente con un último intento de navegación acotado; instrumentar únicamente los tres `goto` ya autorizados. El coordinador proyecta esa evidencia y los campos existentes de `QueuePageObservation`; el renderer conserva las filas, controles, permisos, polling y reveal actuales. No habrá otro monitor, historial durable, cursor, base, vault, listener, emisor ni acceso nuevo al proveedor.

**Tech Stack:** Python y dataclasses del proyecto; IPC privado existente; WSGI; HTML y JavaScript nativos bajo la CSP existente; SQLite sin modificaciones; fronteras inertes y harness Node ya disponibles para la futura verificación.

**Spec:** [Requisito registrado antes del código y cuatro GO de diseño, #521](https://github.com/mbalbo2023/boca-socios-assistant/issues/521); `docs/ADR/0302-independent-owner-engines.md`; `docs/superpowers/plans/2026-11-15-r297-independent-engines.md`; requerimientos de URLs/monitor en https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886159599 y contrato DUAL https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886406162. Revisión independiente complementaria: `../specs/2026-11-15-r301-monitor-qa.md`.

## Ejecución autorizada y coordinación

Worktree aislado `boca-r301-monitor`, rama `fix/417-r301-observed-monitor`, base candidata R300 `e6c76e731d2418825a6313e763dca276012f77b3` / árbol `d387f23d26d4ee46ed48b55c827b96400f3e4922`. R300 sigue su aceptación separada; raíz reconciliará main y equivalencia de árbol antes de publicar R301. Arquitectura/QA/Operaciones/Producto-Seguridad aprobaron este diseño; esos votos no sustituyen la revisión final. Autores no aprueban su propio código. Ningún autor despacha Actions ni opera el host.

Task 1 produce los tipos/inspección. Después Tasks 2 y 3 pueden realizarse con archivos disjuntos sobre ese contrato, integrando antes de revisión final. Root posee plan, RCA, cabeceras y publicación. La promoción posterior del nuevo delta requiere su propio SHA y gates; ninguna prueba/certificación anterior se repite sin una dependencia concreta del cambio.

## Base y deduplicación

Lectura realizada el 2026-11-15 UTC en `/workspace/scratch/88b811004084/boca-r298-status`, HEAD O `f16db1008418889ffdd9b35a57bf77f1238ec659`. El diff de los siete archivos de monitor leídos contra producto instalado M `5281efae7dafe89be047073796b3e0a7e19785ed` está vacío. R300 es mantenimiento separado y no acredita aún esta mejora.

`PrivateOwnerApp._token_monitor_page` ya devuelve `_engine_page` cuando hay `engine_control` y el titular tiene `simulation:write`. Por tanto, en el producto instalado `/monitor/tokens` ya usa `/control/motores.json` y `engine_view.updateSessions`: inserta/actualiza/retira filas por UUID cada cinco segundos, sin recarga manual. El detalle GET prepara la operación de reveal; el POST existente aplica Origin, CSRF y un solo uso; copiar requiere un clic. **No volver a implementar esas funciones.**

El fallback de `private_token_view` y `/monitor/tokens.json` conserva cantidades y horas y exige sólo `local-status:read`. Ampliarlo con IDs/URLs/capacidades elevaría la exposición de otra ruta. Queda intacto. Tampoco se modifica `QueuePageObservation.metadata()`, que alimenta proyecciones redactadas.

## Global Constraints

- `SIMULATION_ONLY` continúa vigente; ninguna reserva, foto, envío Telegram, compra o confirmación de entrada pertenece a R301.
- No leer ni modificar `browser/synthetic.py` ni `browser/ipc_worker.py` (BLACKBOX).
- No tocar Porota/PPI, perfiles Docker, seccomp, caps, recursos, timeouts de proveedor, ritmo de apertura ni el límite global de 50 contextos.
- `SessionInspection` conserva 32768 bytes; `MAX_ENGINE_REQUEST=33792` y `MAX_ENGINE_RESPONSE=98304` permanecen intactos. La fixture visual conserva 160000 bytes.
- No secretos en JSON de polling, HTML previo al reveal, repr, stdout/stderr o diagnóstico. URLs visibles sin query/fragmento/credenciales; nunca enlaces externos clicables.
- Poll de cinco segundos con `pending`, pestaña oculta y actualización al recuperar visibilidad, sin reemplazar forms/inputs ni alterar foco/valores del titular.
- No nuevo nonce/capacidad/POST de reveal desde polling; no copia ni selección automática del portapapeles.
- No nuevas migraciones, escrituras de DB, almacenamiento durable de tokens ni prueba de disponibilidad del proveedor.
- La implementación futura usa TDD focal y revisión independiente; raíz controla la publicación consolidada. No commits, dispatch, host, suites certificadas ni navegador local durante esta fase de diseño.

## Review Focus

1. Un `goto` que falla antes de la primera muestra debe conservar el intento local; si no vuelve una inspección al controller, la UI debe decir dato no recibido. Casos de Task 1 y Task 2.
2. Un intento nuevo fallido no puede heredar la URL final, hora o estado HTTP de uno anterior. Casos de Task 1 y Task 2.
3. Una señal de evento o ausencia no puede aumentar de autoridad al traducirse; ID observado no es ID local ni entrada. Casos de Task 2 y Task 3.
4. Query/token/fragmento, Unicode y forma JSON adversa deben conservar privacidad y cotas, sin relajar el decoder. Casos de Task 1 y Task 3.
5. La llegada de un token cambia la fila y su enlace privado sin reemplazar controles/foco ni emitir un reveal/copia. Casos de Task 3.

---

## Contrato decidido

### Evento y última muestra

Agregar a cada fila de `EngineSessionCoordinator._session_metadata` `event_state`, `event_id` y `reason`, copiados de `item.observation` o `null` si no existe. Usar los enums y el identificador ya validados por `QueuePageObservation`; no modificar parser, selector DOM ni métodos de metadata global. La etiqueta de `event_id` será **«ID de evento observado en la página»**. No se crea ni consulta un evento local para completar este campo.

Mantener `display_url` como URL final saneada. Agregar `final_url_observed_at`, procedente de `inspection.observed_at` sólo si existe `inspection.final_url`. No usar `item.observed_at` para fechar una URL anterior: una observación fallida puede ser más reciente que esa muestra.

La fila conserva una última muestra por sesión. Un cierre/fallo deja esos datos como históricos. Texto común de la sección: «Cada fila conserva la última muestra recibida. Si la sesión falla o se cierra, esos datos son históricos.» Un fallo del poll mantiene el aviso existente de actualidad no verificada.

### Navegación: último intento, no historial nuevo

Interfaces propuestas en `browser/engine_protocol.py`:

```python
NavigationPurpose = Literal["SITE_URL", "QUEUE_BRIDGE", "RECEIVED_TARGET"]
NavigationResult = Literal["STARTED", "RETURNED", "FAILED", "CANCELLED"]


@dataclass(frozen=True, slots=True, repr=False)
class NavigationAttempt:
    sequence: int
    purpose: NavigationPurpose
    display_url: str
    started_at: datetime
    result: NavigationResult
    http_status: int | None = None

    def to_value(self) -> dict[str, object]: ...
    @classmethod
    def from_value(cls, value: object) -> NavigationAttempt: ...


# Campos adicionales de SessionInspection, al final y con defaults:
configured_url: str | None = None
navigation_attempt: NavigationAttempt | None = None
```

- `sequence`: entero exacto 1..3, sin aceptar booleanos. Hay como máximo una carga inicial, un puente y un target en el flujo actual; no imponer un orden adicional entre puente/target que el código no garantice.
- `configured_url`: `self._destination` validado, fijado al construir el observer de esa sesión, máximo 512 bytes. No sustituirlo por una configuración posterior del controller. `null` significa que no se recibió ese dato, no que SITE_URL esté vacía.
- `display_url` del intento: `scheme + netloc + path`, sin query/fragmento; rechazar credenciales y aplicar la validación base existente `require_site_url`, que limita a 512 bytes. Nunca truncar una URL y presentarla como exacta.
- `started_at`: datetime con zona, normalizado a UTC. Es el instante de inicio del `goto` real, no el de guardar configuración o crear la fila.
- `result`: lista cerrada. `RETURNED` significa que retornó la llamada, incluso si recibió HTTP 4xx/5xx; no acredita acceso ni evento. `http_status` es un entero exacto 100..599 o `null`; sólo puede estar presente en `RETURNED`.
- `repr` omite los valores privados. El objeto y su JSON usan forma exacta; no aceptar claves desconocidas, duplicadas, arrays, floats/bools como secuencia/HTTP ni fechas sin zona.
- `SessionInspection.from_payload` acepta exactamente la forma antigua completa o la forma nueva completa con estos dos campos. No aceptar combinaciones parciales ni diccionarios abiertos. `to_payload` emite la forma nueva y serializa la fecha anidada con `to_value`. Los request/reply exteriores permanecen en versión 2, sin comandos nuevos; cliente antiguo ante reply ampliado falla cerrado. Se conserva la promoción conjunta de controller/worker; no certificar pares mezclados.
- Verificar el máximo codificado con Unicode/escapes en campos existentes más los nuevos: 32768 continúa siendo una cota real, no un límite por campo. Si el caso extremo falla, volver con el hallazgo; no elevar caps ni borrar evidencia en silencio.

El agregado privado de motores incorpora `configured_url` y `navigation_attempt` con esta misma forma, fecha ISO UTC y sólo la URL ya saneada. No incluir la URL cruda del intento. La URL/token completa sigue en los mecanismos de reveal que ya existen; R301 no crea una revelación de historial de navegación.

### Captura en los tres puntos existentes

Agregar en `AutomaticQueueObserver` un único helper privado:

```python
async def _navigate(self, page: _Page, url: str, *, purpose: NavigationPurpose) -> int | None: ...
```

El helper se llama sólo después de las guardas actuales. Incrementa la secuencia y guarda `STARTED` inmediatamente antes del único `await page.goto(url, wait_until="domcontentloaded", timeout=12000)`. Retorna el status recibido o `None`. Actualiza la misma marca a `RETURNED`, `FAILED` o `CANCELLED`; excepciones y cancelación se relanzan preservando la causa original, sin texto de excepción ni nuevo cleanup.

El estado de última navegación pertenece al observer, separado de `_inspection` y `_facade`, para que un fallo o el cierre del facade no lo borre. `inspect()` sólo copia `configured_url` y ese estado sobre la inspección cacheada; no evalúa, navega, lee cookies ni abre un contexto.

Integrar el helper en: (1) `_PageFacade.goto`, mediante un callable privado pasado a `_BrowserFacade`, propósito `SITE_URL`; (2) `_snapshot`, en el único enlace de cola ya admitido, propósito `QUEUE_BRIDGE`; (3) `prepare_boca_login`, en el target ya recibido/admitido, propósito `RECEIVED_TARGET`. Conservar los flags de una sola navegación y `navigation_completed`. No instrumentar peticiones de recursos, redirects internos, POST de auth ni otra red como nuevos `goto`.

**Límite real de recepción:** los fallos ordinarios iniciales y de puente que `observe_queue` convierte a `CHECK_FAILED` pueden llegar con el `inspect` posterior existente. Un fallo del target en `prepare_boca_login` se relanza; el registry cierra/cerca la sesión y puede impedir una inspección posterior. R301 registra el intento en el observer pero no promete que ese dato llegue al panel en ese caso. La UI conserva `SESSION_FAILED` y datos históricos/no recibidos. No agregar un inspect, ampliar NO_GO envelopes ni reabrir la sesión para ocultar esa limitación. `STARTED` tampoco garantiza progreso en vivo: la operación IPC puede estar ocupada hasta terminar.

### Presentación compacta y tokens

Agregar cinco entradas a `_SESSION_LABELS`: `event_state`, `event_id`, `reason`, `configured_url`, `navigation_attempt`. La última se formatea como texto compacto con propósito, URL, hora, resultado y HTTP. La entrada existente `display_url` pasa a rotularse **«Última URL final recibida»** y muestra su propia hora; no crear seis filas nuevas de navegación. Reutilizar `_time`/`formatPrivateTime` y URLs saneadas. Los campos nuevos faltantes en un snapshot anterior se muestran como no recibidos.

Mapas cerrados compartidos por el HTML inicial y el script, como ya se hace con `_PHASES`:

| Código | Texto mínimo decidido |
| --- | --- |
| `EVENT_ANNOUNCED` | Identificador de evento recibido; faltan señales de cola o acceso |
| `EVENT_VERIFIED` | Evento identificado en la observación de la página |
| `NO_EVENT_CONFIRMED` | La página informa explícitamente que no hay eventos |
| `UNRECOGNIZED` | No se pudo identificar un evento con esta muestra |
| `VISIBLE_CHALLENGE` / `CHECK_FAILED` / `HTTP_FAILURE` | Intervención requerida / Comprobación fallida / Respuesta HTTP de error |
| `INVALID_OBSERVATION` / `CONTRADICTORY_EVIDENCE` | Muestra no interpretable / Señales contradictorias |
| `RECEIVED_TARGET` / `OBSERVED_IDLE` / `OBSERVED_PREQUEUE` / `OBSERVED_QUEUE` | Enlace de acceso recibido / Cola inactiva observada / Prefila observada / Cola observada |
| `EXPLICIT_NO_EVENTS` / `EVENT_ID_OBSERVED` / `NO_RECOGNIZED_EVIDENCE` | Ausencia declarada por la página / ID recibido sin otras señales / Sin señales reconocidas |
| propósito `SITE_URL` / `QUEUE_BRIDGE` / `RECEIVED_TARGET` | Carga de SITE_URL / Enlace de cola recibido / Enlace de acceso recibido |
| resultado `STARTED` / `RETURNED` / `FAILED` / `CANCELLED` | Inicio del intento registrado / La llamada de navegación retornó / El intento falló / El intento fue cancelado |

Los valores desconocidos no se convierten con `str()` en etiquetas de estado; se muestran como dato no recibido/no reconocido. El ID debe cumplir el patrón existente de 1..128 caracteres. Todas las inserciones DOM usan `textContent`; HTML inicial usa `escape`; no `innerHTML`.

**Tokens:** mantener una fila por UUID y sus flags actuales, sin cache/historial/revisión nuevos. Cambiar sólo el texto del enlace de inspección existente según `has_target_url` y `has_auth`: «Ver token de cola de la sesión N», «Ver tokens de autenticación de la sesión N», «Ver tokens de cola y autenticación de la sesión N» o la etiqueta actual si no hay ninguno. Incluir el nombre del motor para distinguir por voz. El href siempre es `/control/sesiones/{UUID}`. El GET de detalle sigue preparando el reveal; el POST sigue revelando el último dato disponible de esa sesión. No prometer una observación histórica inmutable ni la vigencia del token. Un UUID histórico retenido puede mostrar historia; un UUID perdido devuelve 404 y nunca se remapea al actual.

## Archivos y tareas

Sólo cinco fuentes productivas previstas: `browser/engine_protocol.py`, `browser/automatic_observer.py`, `integration/engine_sessions.py`, `panel/engine_view.py`, `panel/private_ui.py`, bajo `src/boca_socios/`. No modificar `private_http.py`, parser, `private_token_view.py`, runtime, pool, registry, cliente, socket ni workflows para este diseño.

### Task 1: Inspección acotada y navegación observada

**Files:** modificar las dos fuentes `browser/engine_protocol.py` y `browser/automatic_observer.py`. Ampliar `tests/test_engine_sessions.py`, `tests/test_automatic_observer.py` y `tests/test_boca_auth_continuation.py` usando sus fronteras de Page/contexto existentes.

**Interfaces:** produce `NavigationAttempt`, los dos campos opcionales y `_navigate` definidos arriba; consume las mismas Page, `require_site_url`, clock y guardas actuales. No cambia firmas públicas de observar, preparar login, cerrar o inspeccionar.

- [ ] Escribir casos focales de ida/vuelta antigua/nueva y rechazo de forma/tipos/cotas; el caso extremo codificado conserva todos los campos existentes y los nuevos bajo 32768.
- [ ] Escribir casos con Page inerte que observen la marca `STARTED` al entrar en el goto real, `RETURNED`/HTTP al finalizar, y `FAILED` sin URL final fabricada. Cubrir puente y target con sus fixtures reales existentes, sin abrir proveedor.
- [ ] Cubrir un segundo intento fallido conservando URL final/hora anteriores, cancelación preservada, y `inspect` posterior sin nuevos goto/evaluate/cookies. No exigir recepción IPC del target fallido, por la limitación explícita.
- [ ] Ejecutar sólo los selectores nuevos/afectados y registrar RED por la ausencia del comportamiento, no por import o fixture rota.
- [ ] Implementar el contrato y los tres puntos de llamada, sin alterar destinos, condiciones, flags, timeout ni cleanup.
- [ ] Ejecutar esos mismos selectores y registrar GREEN. Revisor comprueba cotas, conservación del primario y ausencia de cambios de autoridad. No ejecutar full3/capacidad.

Nombres propuestos para los casos: `test_navigation_attempt_round_trip_and_legacy_inspection`, `test_navigation_attempt_rejects_invalid_shape_and_values`, `test_inspection_maximum_encoded_payload_remains_bounded`, `test_goto_records_real_attempt_before_await`, `test_failed_navigation_preserves_attempt_and_prior_final_sample`, `test_inspect_keeps_navigation_evidence_without_new_io`. El caso de target amplía `test_queue_completion_follows_only_received_target_in_same_page`.

### Task 2: Proyección de evidencia sin nuevos accesos

**Files:** modificar `integration/engine_sessions.py`; ampliar `tests/test_engine_session_coordinator.py`.

**Interfaces:** consume `QueuePageObservation` y la inspección de Task 1; produce los cinco campos nuevos del agregado (`event_state`, `event_id`, `reason`, `configured_url`, `navigation_attempt`) más `final_url_observed_at`, preservando todos los campos anteriores. `PrivateSessionDetails` conserva su forma: ya contiene observación e inspección.

- [ ] Escribir casos que recorran el coordinador real con worker inerte: evento/precola, ausencia explícita, error y UNKNOWN mantienen enum/motivo/ID observado; no sustituyen el ID por un miembro/evento local.
- [ ] Cubrir un intento fallido recibido junto a una URL final anterior y verificar las dos horas distintas; la navegación ausente queda `null` y no se completa con SITE_URL/final_url.
- [ ] Adaptar únicamente los campos nuevos en la fixture de inspección existente; no agregar un doble alternativo del algoritmo ni una nueva DB.
- [ ] Observar RED, añadir la proyección dentro del camino actual de publicación y obtener GREEN de esos selectores. No añadir inspect, consultas de red ni callbacks de DB a `publish_if_current`.

Casos propuestos: `test_metadata_projects_observed_event_without_local_identity_inference` y `test_metadata_keeps_attempt_distinct_from_last_final_sample`. Inspeccionar que el fence de STOP/generación no se haya modificado; no repetir una suite de cierre certificada si su código no cambió.

### Task 3: Vista privada y recepción visible por sesión

**Files:** modificar `panel/engine_view.py` y `panel/private_ui.py`; ampliar `tests/test_engine_view.py` y, sólo para los nuevos campos privados, `tests/test_private_engine_controls.py`.

**Interfaces:** consume el agregado de Task 2 y `PrivateSessionDetails`; HTML inicial, polling y detalle privado usan los mismos mapas/formatos. El enlace local conserva su UUID, la ruta y el POST de reveal existentes.

- [ ] Escribir los casos de mapas cerrados, ID observado, escape, tiempos separados y fallback de campos ausentes; verificar que query/fragmento/token/error privado no aparezcan en el HTML ni en la proyección del poll.
- [ ] Ampliar el harness Node del script real con una fila existente y snapshots sin token → token de cola → auth → ambos. Exportar el texto del enlace y los campos nuevos; exigir la misma fila/form/operación, href local, cero clipboard/reveal y únicamente fetch del snapshot. No reimplementar inserción de filas ya cubierta.
- [ ] Registrar RED, añadir formato compacto y texto dinámico del enlace existente mediante `setText`, y actualizar el detalle privado para mostrar la misma evidencia. No reemplazar formularios ni añadir otro polling.
- [ ] Registrar GREEN de los selectores nuevos/afectados y de `test_token_monitor_reuses_live_session_inventory_instead_of_a_static_count` si su frontera se tocó indirectamente.
- [ ] Ejecutar el contrato inerte existente `tests/test_engine_dashboard_ui_offline.py::test_fixed_fixture_uses_actual_renderer_and_ignores_runtime_environment` una vez para el cambio de renderer: fixture ≤160000, CSP/hash coherentes. No elevar el cap si falla: reportar el exceso concreto y ajustar la presentación dentro del alcance, sin nueva arquitectura visual.
- [ ] Entregar fuentes estables y hashes para revisión independiente; raíz incorpora documentación factual y decide el CI/candidato exacto. No publicar ni operar el servidor desde esta tarea.

Casos propuestos: `test_event_and_navigation_labels_remain_closed_and_private`, `test_actual_poll_relabels_received_tokens_without_replacing_controls` y `test_private_session_detail_separates_configuration_attempt_and_final_sample`. El harness existente sólo necesita exponer nuevos campos/link; no se introduce navegador local.

## Verificación futura y cierre

Usar el entorno congelado autorizado: `PYTHONPATH=$PWD/src /workspace/scratch/0bbcce5b467b/boca-ci-r293/.venv/bin/python -m pytest <selectores>`; Ruff/formato sólo sobre archivos cambiados. Ejecutar cada ciclo RED→GREEN una vez por cambio concreto y conservar evidencia. Los diez bloques de la matriz QA son condiciones de revisión; agruparlos en los casos que cruzan fronteras reales y no convertirlos en diez suites repetidas.

No existe bloqueo de proveedor para implementar esta proyección y el último intento local. Hay límites de evidencia, declarados: último intento y última observación por sesión, no archivo de todos los tokens; una respuesta IPC fallida puede impedir recibir el diagnóstico local; los tokens sólo se revelan deliberadamente; ausencia de datos no significa ausencia de evento. La cuenta regresiva, DOM autenticado, reserva/entrada, cancelación por ganador, fotografía y aviso al socio quedan fuera y pendientes. Tampoco se certifican cincuenta sesiones físicas.

Self-review: los tres requerimientos de monitor tienen tarea; tipos/nombres coinciden entre contrato y tareas; los cinco riesgos de revisión tienen un caso asignado; no se duplica polling/reveal ni se amplían permisos del fallback. Este archivo es el único entregable escrito por Arquitectura. No se ejecutaron pruebas ni se modificó producto, GitHub o host para prepararlo.

## Incidente de validación CI1266 — fixture de diagnóstico

El head `73288d5e2cb0423d433ab6f5bc982b02d7e89d24` pasó formato, tipos,
contratos y construcción de imágenes. Su suite obtuvo 9563 pruebas y 34
subtests aprobados, con un único fallo en
`test_browser_assertion_reports_only_its_allowlisted_reason`. El fallo y el
alcance de la corrección se registraron en
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6892201591)
antes de modificar la prueba.

La preparación de ese test escribía `json.dumps` por defecto: 163325 bytes,
por encima del límite de 160000. El serializer real del CLI produce 159220
bytes, o 159221 con el salto final emitido por `--make-fixture`; ambos JSON
representan exactamente los mismos datos. El lector rechazaba el tamaño antes
de llegar al stub de `run_offline`, por lo que la prueba comprobaba otra fase.

La corrección queda limitada al setup de ese selector en
`tests/test_engine_dashboard_ui_offline.py`: escribir los bytes del serializer
real y afirmar que el stub previsto fue alcanzado. Conservar la aserción
exacta del diagnóstico saneado, los datos, el cap, el producto y el ZIP.
Reproducir únicamente ese caso RED y luego GREEN; no repetir la suite local
ni el navegador real. RCA-523 retiene el selector como regresión ejecutable; RCA-521 se conserva
íntegra con sus ocho selectores anteriores.
Los tres revisores independientes deben verificar el delta y raíz completar
el cuarto voto antes de publicar el nuevo head del mismo PR521.
