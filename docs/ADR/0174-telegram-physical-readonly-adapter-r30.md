# ADR0174 — Telegram: lector rootless real y método GET efímero de solo lectura (DRAFT)

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

## Límite central: todavía NO es una activación física

Este PR **no crea el contenedor helper, no ejecuta Docker, no llama Telegram,
no modifica workflows/Compose y no habilita GO**. El modo `get` no es
autorización por sí solo: la siguiente tranche debe construir el único
runner protegido con lease PID/FD/flock persistente, comprobar el Cutover A
físico, atestar la identidad exacta del helper/imagen/labels/volúmenes/red
dedicada/UID **antes de cada GET**, transportar secretos solo por FD/STDIN y
limpiar el helper por ID positivo tanto en éxito como falla.

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
frames ambiguos. No alcanzan la API real, no se abren sockets ni se escriben
recibos. SHA/TREE y resultados Actions pertenecen al PR apilado final,
no se heredan de #380/#382. Mantener DRAFT y separar code-only de deploy.
