# ADR 0078: proceso Telegram opt-in para avisos sintéticos

**Estado:** decisión integrada por PR #188 en
`1bdc80b7f50021227cd798e655844b157198ea93`; candidato
`2e1ee9339b6c2ec83ba235deb2a81699c8c928b9`, CI 41274848402,
scan 41274848345, release/deploy 41274848336/41274848461 y revisión
5726534430. El host y el envío real siguen sin probar.
El código del PR no instala, configura ni arranca el proceso en el droplet.
Fecha de diseño: 2026-11-01 (America/Argentina/Buenos_Aires).

## Decisión

El proceso `python -m boca_socios.notify.telegram_worker serve` es una entrada
separada del controlador y del panel. Exige cinco valores exactos de ambiente:
`staging`, `simulation`, engine `off`, DB `/data/boca.sqlite3` y
`BOCA_TELEGRAM_DISPATCH_MODE=explicit`. Sin comando y contrato exactos devuelve
un único error público fijo, sin imprimir excepciones, token, chat ni payload.
El controlador servido no lo importa ni lo inicia.

`compose.telegram.json` es un archivo Compose independiente en formato JSON,
con el mismo proyecto dedicado `boca-socios` y sólo el servicio `telegram` bajo
perfil `telegram-opt-in`. El perfil y `restart: no` impiden arranque implícito.
Deshabilita el healthcheck heredado de la imagen, que sólo verifica SQLite y
confundiría DB legible con recepción Telegram; una futura prueba host debe
inspeccionar el proceso y el resultado del intento por separado.
No hay puerto, host mount, Docker socket, modo privilegiado ni red compartida
con el controlador. El proceso UID/GID 10001 usa un bridge dedicado de egress,
raíz de sólo lectura, capacidades retiradas, `no-new-privileges`, límite de
0,25 CPU, 128 MiB y 32 PID. Ese presupuesto es **propuesto**, no medido en el
droplet ni aprobado como capacidad restante de una instalación conjunta.
Su red permitiría sólo el envío saliente de este proceso; no constituye una
política de firewall que limite el destino a `api.telegram.org`.

El volumen de datos externo existente debe ser exactamente
`boca-socios_boca_data`; el volumen de configuración externo, diferente de la
clave maestra y del owner, debe ser `boca-socios_boca_telegram` y se monta
read-only en `/run/telegram`. Ninguno es creado por este Compose. Los únicos
archivos esperados son `/run/telegram/bot_token` y `/run/telegram/chat_id`,
regulares, no symlinks, legibles por UID10001 y sin bits de grupo/otros. El
adaptador ADR0066 verifica ambos en el preflight y justo antes de enviar. El
token y destino **no** son variables de ambiente, inputs de dispatch, imagen,
DB, Site, issue, PR ni logs. Su origen, propiedad y recepción siguen sin
provisionar; la definición de mounts no demuestra custodia.

El worker no crea DB ni aplica migraciones. Antes de reclamar un aviso exige la
migración 0007 ya aplicada con checksum válido. La preparación exige revisión
separada de procedencia de la DB y operación protegida; nunca se infiere de un
path vacío. Cada tick reclama como máximo un aviso. El marcador `prepared`
se confirma antes de red. La espera del resultado de red tiene límite de cinco
segundos; SQLite y el ciclo completo tienen sus propios plazos. Si falla,
expira, se cancela o recibe respuesta no verificable, queda `ambiguous` o
`needs_review`; el worker sale con fallo en la
primera ambigüedad y no reintenta automáticamente ese UUID. Una señal de parada
detiene nuevas reclamaciones después del tick actual, cuyo resultado puede
seguir siendo incierto. El Bot API puede aceptar un mensaje sin acreditar
entrega o lectura humana. No se habilita una reserva ni una compra Boca.

## Integración pendiente y evidencia

El workflow protegido `beta-install` #182 conserva sólo el controlador y no
selecciona este archivo. Una operación Telegram futura dentro del **único**
workflow manual Boca necesita release/digest exactos, propiedad segura del
bot/destino verificados, migración 0007 sobre DB conocida, cupo agregado,
comprobación de red/mounts efectivos y envío sintético acotado (#168). El
`stop-test` integrado por #165 sólo reconoce labels de servicio `controller`,
`browser`, `proxy`; **antes de activar** `telegram` deberá extenderse y
revisarse su inventario/parada para preservar la orden de dejar todos los
servicios Boca detenidos. No usar etiquetas de otro servicio para eludirlo.
Ninguna operación host o mensaje real forma parte de #185.

Las pruebas locales usan SQLite temporal, transportes falsos, configuración
inválida, schema ausente, ambigüedad y parada; los tests de contrato verifican
el Compose estructurado. CI hospedada valida además que Docker Compose resuelva
su sintaxis, con digest ficticio y sin levantar un contenedor. Evidencia exacta
del candidato, checks y revisión consta en PR #188/issue #185. El código está
integrado, pero Telegram externo permanece NO-GO hasta sus gates operativos.
