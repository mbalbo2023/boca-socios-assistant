# ADR 0274 — R257 terminal técnico SUCCESS/FAILURE en la misma lease

**Fecha:** 13-NOV-2026. **Issue:** #417. **Estado:** CODE_ONLY; `DEPLOY NO_GO`.

## RCA y frontera

El grafo inerte R253 reúne la etapa, el `OneShotFinalCleanupBridge` SUCCESS
V2 y el `OneShotFailureTerminalSink`, pero este último rechaza todo terminal
`ACCEPTED` incluso si se produjeran evidencias técnicas auténticas. El
`SuccessorPostflightGate` previo verifica ingreso/monitor del propietario y
no sirve para representar `/healthz` técnico sin falsear aceptación. Un
`ACCEPT` textual no identifica el recibo real de limpieza o postflight.

Existe un bloqueo adicional **independiente y no corregido aquí**: el motor
actual ejecuta `commit_marker → retire_old → finalize → terminal_sink`. Por
lo tanto el par viejo **puede ya estar retirado** antes de comprobar el
postflight y persistir el terminal. Esta implementación NO afirma custodia
del par viejo en esa ventana, no reordena el motor y no habilita APPLY.

## Decisión acotada

Se crea `OneShotTechnicalTerminalBridge` desde el único
`InertSameLeaseAssembly` R253. Su preparación es inerte, revalida el grafo
por identidad y no adquiere lease. Expone dos fases obligatorias bajo el
**mismo objeto `BocaJobLease` y `SuccessorPairJournal`**:

1. Después del verdadero cleanup SUCCESS V2, el backend protegido *futuro*
   llamaría `attest_technical_success(expected, volume_attestor, lease)`. El
   método marca la operación consumida antes de cualquier lectura, exige
   `intent/evidence` del journal y el archivo de `commit` durable enlazado
   al hash exacto del intent. Acepta exclusivamente el atestador productivo
   R253 de volúmenes, la release/custodia del grafo y el productor oficial
   `OneShotDurableTechnicalPostflightV2.persist()`; no recibe certificados
   arbitrarios ni ejecuta de nuevo la limpieza.
2. El motor invocaría el mismo objeto como terminal sink. Para `ACCEPTED`,
   verifica `commit_started=true`, `cleanup=ACCEPT`, `old_restored=false`,
   fase `NONE`, IDs exactos de ambos CIDs, el mismo lease, el SUCCESS V2 y
   postflight `BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2` canónico. Reabre el archivo
   técnico O_NOFOLLOW y coteja bytes, SHA e inode; revalida journal y commit,
   escribe el único terminal O_EXCL y lo relee por bytes/SHA bajo la lease.
   Recién entonces publica `TECHNICAL_ACCEPTED_OWNER_PENDING`; siempre
   `beta_deploy=NO_GO`, `passkey_attested=false`, `apply_authorized=false`.
3. Para terminal distinto de `ACCEPTED`, delega **una sola vez** al sink
   FAILURE V2 existente. Si el postflight SUCCESS empezó pero falló, permite
   exclusivamente `NO_GO/commit_started=true/old_restored=false` con commit
   durable revalidado: el sink escribe el terminal rojo **sin rollback ni
   cleanup FAILURE**. Precommit/RECOVERED después de SUCCESS se rechaza. Una
   pérdida de lease que impida persistir el terminal conserva indeterminación.

No hay rutas de reintento, `unlink`, reemplazo de recibos, nuevo Docker,
port, navegador, SSH, URL externa, recurso Porota, cambio de TLS ni reservas.
La sesión Chrome WebAuthn y el monitor autenticado **no se consideran
atestiguados** por el esquema técnico; su recepción física independiente
sigue pendiente. El intento histórico R186 es immutable/no-replay.

## Tests, falta de wiring y próximos gates

TDD RED inicial por import del módulo inexistente; GREEN focal sobre
escritura real de archivos en directorio temporal privado e inyección de
snapshots **sintéticos** R253, sin tocar droplet ni Docker. Regresiones:
SUCCESS genuino anclado a commit/terminal, cleanup ausente, proof sin fase
previa, CIDs alterados, lease distinta, commit faltante, GET de login que no
puede sustituir `/healthz`, duplicado O_EXCL, postflight desaparecido,
fallo pos-SUCCESS con terminal rojo y sin segundo cleanup, FAILURE delegada
una vez; y rechazo de precommit después de una prueba SUCCESS comenzada.

**Todavía no está integrado al engine ni a la CLI**, el backend conserva
`requires_persistent_receipt=False` y su postflight gate está en `None`.
Antes de cualquier promoción física, arquitectura debe resolver el orden de
retiro viejo/postflight/terminal, ligar el `PostflightExpected` pre-PARK real
a los CIDs y cleanup postfinal, verificar UID remapeado SQLite, ampliar y
certificar la allowlist/capacidad del ZIP protegido, integrar un único actor
effectful revisado, pasar CI/revisión/merge, release dual exacta, preflight
genuino y el único Actions APPLY bajo lease Boca. Además son obligatorias
recepción 8443, passkey fresca del propietario, SITE_URL, monitor real,
worker bajo demanda y SQLite. **No ejecutar otro R186, no declarar BETA GO**.
