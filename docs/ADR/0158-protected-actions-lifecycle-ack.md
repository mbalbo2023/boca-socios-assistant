# ADR 0158 — puente protegido para ACK físico START/STOP (#351)

Fecha: 2026-11-05 ART. Estado: **DRAFT / CODE_ONLY / host NO_GO**.
Ownership exclusivo: `src/boca_socios/host_lifecycle_actions.py`,
`tests/test_host_lifecycle_actions.py`, lazy-imports estrictos en
`panel/lifecycle_intents.py` y `integration/engine_socket.py`, allowlist en
`build_protected_boca_bundle.py`, `boca_protected_memfd_bootstrap.py`,
`test_protected_boca_bundle.py` y este ADR. Ownership temporal ampliado
por el integrador a las 5 rutas de ADR0152: `host_boca_lifecycle.py`,
`host_lifecycle_rootless_adapter.py`, sus dos tests y ADR0152, para
corregir Chromium STOP degradado. En total el PR #356 modifica **13 paths**.
Base #319 R21.9
`3b3a2f884b4151b238d6c4772b72557bdd78266a`. Ningún workflow, puerto,
host ni BLACKBOX modificado.

## RCA y decisión

El panel privado ya escribe una sola intención `REQUESTED` en el audit log
SQLite legacy. El adaptador rootless `host_lifecycle_rootless_adapter.py` de
ADR0152 sabe ejecutar y verificar exactamente `bot/start|stop` por socket
AF_UNIX y `chromium/start|stop` por ID Docker, con `CLAIMED` y
`APPLIED|REFUSED|UNCERTAIN`. Faltaba una capa transaccional consumible por el
futuro workflow protegido, que eligiera **la solicitud actual** sin exigir
copiar un UUID desde la tablet y confirmara el ACK en el mismo ledger
antes de publicar éxito.

`apply_latest_owner_request` acepta sólo coordenadas de una instalación
independientemente revisada, el handle de la **misma lease activa** y un
transporte inyectable. Primero revalida identidad rootless y mountpoint Boca
por el adaptador #348 **antes** de leer SQLite; utiliza el lector canónico
`LifecycleIntentStore._current()` bajo la atestación de schema legacy
sin crear/migrar base. Exige `REQUESTED`, valida coordenadas SHA/digest/IDs y
pin de componente/objetivo; después delega una sola vez en el adaptador físico.
Este conserva la secuencia atómica dentro de una lease:
`REQUESTED→CLAIMED→effect→reobserve→APPLIED|REFUSED|UNCERTAIN`.
Antes de CLAIMED o de cualquier efecto, el puente **consume
irreversiblemente** el `prepare_run_id` aprobado: crea por O_EXCL/O_NOFOLLOW
un archivo de marca 0600 con ID de PREPARE, SHA, intento, UUID y acción,
dentro de un subdirectorio propio `.boca-lifecycle-go` modo 0700,
propiedad UID rootless del host y NO del UID mapeado de controlador,
exclusivamente en el volumen `boca_data` previamente atestiguado,
bajo la misma lease. Tras escribir exige fsync del archivo y directorio.
Si la marca ya existe o la escritura durable falla, NO_GO sin efecto. Nunca
se borra la marca, ni ante crash, REFUSED o UNKNOWN; un GO usado no autoriza
otra intención posterior. El marcador no contiene credenciales ni datos del
sitio. El runner valida la aprobación GO para ese PREPARE_RUN_ID antes de SSH;
la simple presencia del campo NO confiere GO.

El puente lee nuevamente el audit log, compara ID/componente/objetivo/ACK
terminal y sólo entonces emite JSON de recibo con campos públicos limitados
incluido `prepare_run_id`.

No hay fallback ante fallo, ambigüedad, ausencia de ACK o estado previamente
terminal: **NO_GO y nunca retry automático**. `REFUSED` se informa como
`physical_ack=false`, nunca se declara como operación aplicada. El adaptador
preexistente permite `bot/stop` aun si Chromium está detenido/UNHEALTHY,
pero impide `bot/start` sin worker sano y apagar Chromium con bot vivo.
El bridge no relaja esas condiciones.

## Integración operativa aún pendiente

Este PR agrega **únicamente un CLI host-only dentro del ZIP/memfd revisado**:
`lifecycle-apply <context_base64url>` y una prueba sin efectos
`lifecycle-bridge-selftest`. Un solo JSON público canónico (`version`, `kind`,
run attempt, **prepare_run_id obligatorio**, SHA, IDs, digests,
config hashes, data mount, componente y target) se codifica base64url sin
padding, límite 2 KiB. Requiere PREPARE positivo canónico de GitHub Actions
(`[1-9][0-9]{0,19}`) atestado por el runner, no input libre del panel. La validación del contexto
**NO equivale a GO**; el runner debe vincularlo con una aprobación protegida
e independiente. El CLI abre y cierra la lease canónica, emite únicamente
JSON redacted y falla `NO_GO` sin filtrar excepción remota. No existe CLI
expuesto en HTTP ni workflow que lo llame todavía. NO edité el workflow
`.github/workflows/boca-first-deploy.yml`, porque #352 tiene ownership único.

No hay automatismo desde Chrome ni nueva ruta de deploy; un clic del panel
produce `REQUESTED` y exige, por ahora, el dispatch independiente de Actions
para llegar a ACK real. El controller nunca obtiene un token GitHub ni
acceso directo al socket Docker. Pasar un objeto
`ReviewedLifecycleInstallation` **NO acredita** el GO por sí mismo.

El integrador #319 debe esperar #349/#350 y conectar este módulo bajo
una operación del **único workflow manual protegido** que:

1. Exija GO independiente de intento/actor/SHA/imagen y revalide `main`
   justo antes de un único SSH, con release y origen instalados exactos.
2. Ateste UID/GID rootless 10001, puerto de controller solamente
   `127.0.0.1:8443`, par controller/worker exact-ID, config hash Compose,
   source SHA, image ID↔RepoDigest, sender OFF/ON pinado si presente y
   SQLite legacy dentro del volumen Boca.
3. Abra lease canónica una sola vez, construya los pines de instalación desde
   recibo de release/host, no desde un JSON enviado por Chrome ni sólo labels,
   ejecute este bridge y capture su JSON redacted como recibo único.
4. Registre el resultado físico `APPLIED` o `REFUSED` o NO_GO ambiguo.
   No automatice reintentos, reinicios ni nuevos puertos. Tras reboot se debe
   conservar `bot/stop APPLIED` con #350, nunca arranque silencioso.
5. Pruebe START/STOP con worker sano/fallido, reinicio controlado,
   persistencia de sesión Chrome en SQLite lateral y Samsung+Termius reales.
   Sólo un recibo host demuestra la BETA funcional.

## Pruebas de propuesta y frontera

La suite sintética `tests/test_host_lifecycle_actions.py` cubre una sola
solicitud, matriz de cuatro comandos con scope pinado, prevención de replay
incluso tras una nueva REQUESTED, crash después de O_EXCL, marca 0600 sólo
dentro del volumen, NO_GO sin marcador y GO malformed; ACK terminal
redacted, ausencia de intención y estados pendientes,
pin incorrecto, digest/sha inválido, `REFUSED` sin falso GREEN, ACK perdido,
efecto UNCERTAIN sin retry, STOP, y cero creación/migración SQLite.
Son mocks **sin** Docker, SSH, Telegram, login, reserva o compra real.

Responsabilidad de #351: código/QA y documentación. Integración de workflow,
merge/release/instalación y pruebas físicas pertenecen exclusivamente al dueño
del candidato #319 después de GO. Seguridad adicional P2 por decisión de
Tincho; aislamiento real, cleanup Boca-only success/failure, BLACKBOX
intocable y Regla84 siguen vigentes.


## Empaquetado ZIP host stdlib-only

La ruta original de imports #348 acarreaba módulos del controlador y
`cryptography` incluso para consultar sólo el wire de control y ledger.
Se movieron **sólo los imports de tipo/instanciación** de `Database` y
`BetaCommandHost` al constructor donde efectivamente se usan; la lógica
de runtime sigue igual. El paquete ZIP incluye explícitamente los dos
módulos de host, el lector de ledger legacy, el motor wire stdlib, siete SQL
con checksum y sus `__init__` inertes exclusivos del host para los
subpaquetes `panel` e `integration`. No se incluye ni ejecuta la
implementación BLACKBOX, `command_host.py` o `credential_vault.py` en host.

La prueba end-to-end `lifecycle-bridge-selftest` ejecuta el ZIP bajo
`python -S` (sin site-packages), con HASH/entry allowlist y memfd;
`lifecycle-apply` sin contexto responde NO_GO antes de acceder al host.
Esto acredita sólo imports/contrato del runner descartable, nunca la salud
o el estado físico de Docker en el droplet.

## RCA replay GO PREPARE/APPLY y evidencia limitada

Un GO de PREPARE_RUN_ID no debe repetirse en otro APPLY antes de expirar:
la secuencia `REQUESTED` del ledger evita duplicar un mismo intent pero
podría autorizar **otro** intent creado después. Para cerrar el P0, el
`prepare_run_id` queda presente en el contexto y se consume por marca
filesystem exclusiva, sin TTL ni purga. La marca es **monótona**:
`unused→consumed` sin transición inversa ni posibilidad de repetir.
No se escribe nada en Porota, en otro Docker ni fuera del volumen Boca.
Si no se puede abrir/fsync el directorio de datos Boca con la identidad
rootless atestiguada, el resultado correcto es NO_GO; no se evita ese fallo
usando privilegios extras o montajes alternativos.

El workflow #352 realiza PREPARE y APPLY como actos separados: debe
demostrar actor/approval/release/SHA/run y que `prepare_run_id` corresponde
al PREPARE aprobado, independientemente del JSON pasado al host. Este
módulo sólo permite consumir GO una vez después de verificar el estado
físico del host. El marker persistente y los tests **no equivalen a un
GO real ejecutado ni prueban montaje físico de la BETA en droplet**.
