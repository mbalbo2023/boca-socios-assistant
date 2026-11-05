# ADR0173 — Telegram 4 GET READ_ONLY bajo sesión efímera inyectada (CODE_ONLY)

Fecha: 05-Nov-2026 ART · issue #315 / #357 · stacked DRAFT sobre #380,
sin modificación de Cutover/Compose/workflow.

## Qué resuelve esta tranche

El módulo `src/boca_socios/telegram_host_readonly_session.py` une, por primera
vez en un mismo contrato testeable, las evidencias del testigo WebAuthn owner
de #380 y el parser Telegram privado (getMe, getWebhookInfo, getUpdates,
getChat) **sin escribir custodia ni emitir mensajes**.

1. Verifica ante un lector rootless inyectable identidad de controller,
   volúmenes data/owner, credential pública y stage cifrado con ES256 UV fresco,
   bajo la misma `BocaJobLease` del host antes de abrir egress.
2. Abre **una** instancia de `session_factory()` como context manager (un solo
   helper efímero lógico); no crea ningún Docker container, socket o puerto.
3. Cada GET exige orden estricto, que el stage permanezca idéntico y un nuevo
   `HostRecheckReceipt` vinculando owner, lease, sender OFF y egress dedicado.
   La futura implementación *física* de ese callback debe comprobar el helper
   real exact-ID/labels/mounts/red/UID, no aceptar claims fabricados por la app.
4. El contexto se cierra siempre ante éxito/error; al cerrarse se vuelve a
   comprobar topología SIN helper y stage inmutable. Un error del transporte,
   context manager, provider o recheck se traduce a error fijo sin token/chat.
5. Solo se devuelve `READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED` con
   `methods=4, sender=OFF, custody=UNCOMMITTED, human_receipt=UNVERIFIED,
   host_go=false`. El `bot_id` público es la única identidad del proveedor
   en el recibo; nunca se divulga chat ID ni token.

El CLI de código ofrece `four-gets` pero **rechaza siempre** con
`HOST_BINDING_NOT_CONNECTED` antes de acceder a red o host. No ofrece
sendMessage, custodia ni activación.

## Qué NO certifica una CI verde

Los tests emplean `_FakeBotApi`, una lease y Docker I/O sintéticos, aserción
ES256 UV con clave ficticia, e inyectan un context manager de memoria. La
respuesta del mock representa un permiso de lectura, **nunca** un GO físico.
No se realiza GET a Telegram, no se monta un volumen real, no se inicia
contenedor ni se prueba recepción humana.

Continúan pendientes del P0 físico:
- Cutover A de core con SHA/image + ACK y limpieza Boca-only real.
- Observación de UID/subuid host, compatibilidad de cryptography entre imagen
  y ZIP host stdlib-only, red egress y todos los volúmenes.
- Implementación de la `session_factory` privilegiada dentro del **único**
  Actions protegido, con helper positivo Boca-only, canal anónimo delimitado,
  rechecks del host por cada GET y cleanup selectivo en `finally`.
- GO de GitHub Environment independiente y consumición de nonce O_EXCL para
  **activación**; esta etapa de 4 GET READ_ONLY no consume nonce ni escribe
  custodia, precisamente para no fingir aprobación. Custodia V2 y emisor
  OFF requieren una fase futura transaccional; envío y ACK humano siguen
  separados.

## QA / alcance

`tests/test_telegram_host_readonly_session.py` prueba happy path con cuatro
GET y una única apertura/cierre, webhook activo (corta en getWebhookInfo),
drift de owner/host antes de GET, fallo de cierre de helper, drift de
postflight y CLI no habilitado. Errores no filtran token ni permiten
`sendMessage`; ninguna suite toca servicios externos.

No modifica `.github/workflows/boca-first-deploy.yml`, Docker/Compose,
BLACKBOX `synthetic.py`/`ipc_worker.py`, Porota, otros contenedores,
SQLite legacy, puertos, secretos, backups ni compras/reservas reales.
Este PR es **DRAFT CODE_ONLY**, sin merge/deploy/Telegram hasta Cutover GREEN,
cierre de QA exact-SHA y nuevo GO específico. Regla84: estados del main,
PR y droplet se registran separados.
