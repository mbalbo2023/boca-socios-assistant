# ADR0175 — Telegram: lector rootless real y método GET efímero de solo lectura (DRAFT)

Fecha: 05-Nov-2026 ART · #315/#357/#45 · DRAFT apilado sobre #382.

## Evidencia y defecto reproducible

La observación física de Telegram en #380/#382 usa
`ProductionRootlessDockerIO.field` para campos de contenedor detenido como
`Config.Image`, `HostConfig.PortBindings`, `HostConfig.RestartPolicy` y
`State.Restarting`. El lector heredado delega a
`host_boca_cleanup._inspect_field`, cuyo allowlist global deliberadamente no
incluye esos campos. Los tests con `FakeIO` no detectan la diferencia. Por
lo tanto, el preflight **no puede declararse ejecutable en producción** sin
un lector dedicado. NO expandir la inspección genérica de cleanup.

## Implementación contenida

- `host_telegram_production_reader.py` agrega un lector READ_ONLY para una
  lista cerrada de campos ya requeridos por los testigos Telegram, limitado a
  UID/GID 10001, identificadores exactos de contenedor y nombres exactos de
  volúmenes Boca persistentes. Usa únicamente el socket Docker rootless Boca
  preexistente; no modifica `host_boca_cleanup` ni otro proyecto.
- `telegram_readonly_exec.py` agrega un ejecutable del contenedor exclusivo
  que permanece **inactivo** en modo `idle` y en modo `get` acepta por STDIN
  un JSON canónico de un método: `getMe`, `getWebhookInfo`, `getUpdates`
  o `getChat`. Rechaza `sendMessage`, cuerpos no canónicos, operadores sin
  identidad UID 10001 y ambiente distinto de simulación/engine OFF.
  Devuelve la respuesta del proveedor codificada por STDOUT **privado del
  proceso Docker exec**, nunca como receipt público de Actions. El futuro
  consumidor debe redirigirla, limitarla y no registrarla.
- `host_telegram_egress_helper.py` agrega una factoría **sin CLI**, para un
  futuro único caller ya autorizado bajo el *mismo* lease físico. Cuando ese
  caller la invoque, crea el helper rootless efímero por imagen de digest
  exacto, solo en la red Boca Telegram existente, UID10001, memoria/PIDs
  acotados, `read-only`, cero mounts/puertos, sin emisor; exige inventario
  y atributos de Docker reales al abrir y **antes de cada GET**, intercambia
  los mensajes por STDIN/STDOUT privados y remueve exclusivamente el ID
  positivo creado en `finally`. Si `run` pierde su ACK, falla cerrado sin
  borrar recursos por nombre o tocar aplicaciones externas. El cleanup
  final falla cerrado ante ACK dudoso.

## Límite central: todavía NO es una activación física

Este PR **no ejecuta la factoría ni crea el contenedor helper ahora, no llama
Telegram, no modifica workflows/Compose y no habilita GO**. El modo `get`
no es autorización por sí solo. La siguiente tranche debe conectar el único
runner protegido con el lease PID/FD/flock persistente, demostrar Cutover A
físico y asegurar que las pruebas físicas de receptor y owner estén unidas a
`recheck_host` **para cada fase**. La factoría por sí misma no puede suplir
esas pruebas ni otorgar autorización; si un ACK Docker fue incierto se debe
investigar bajo el owner antes de reintentar.

El caller futuro usará `four_gets_under_existing_lease` de #382, que termina
en `READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED`; el emisor sigue OFF,
custodia UNCOMMITTED y recibo humano UNVERIFIED. Un GET real no reemplaza
un GO de custodia ni un ACK de entrega. Ni datos del usuario ni credenciales
se incluyen en este PR o en sus pruebas.

No hay cambios a BLACKBOX, sitio Boca/Queue-it, Porota, otros Docker,
puertos, HTTPS, backups, SQLite legacy ni compras/reservas reales.
Cutover A #42096941815 y observación #42097454923 fallaron; el estado
físico sigue indeterminado hasta la reconciliación Boca-only del dueño de
Cutover. NO disparar helper ni activar Telegram mientras eso no se aclare.

## QA y Regla 84

Tests nuevos de lector físico con Docker simulado verifican allowlist exacto,
rechazo de campo ajeno, identidad rootless y respuesta acotada. Tests de
helper prueban cuatro GET ficticios y rechazo de acciones mutadoras y
frames ambiguos; tests nuevos de factoría prueban lectura tras revalidación
por GET, mismo lease, cierre positivo del ID y rechazo de desvíos. No alcanzan
la API real, no se abren sockets ni se escriben recibos. SHA/TREE y resultados Actions pertenecen al PR apilado final,
no se heredan de #380/#382. Mantener DRAFT y separar code-only de deploy.
