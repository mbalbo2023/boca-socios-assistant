# ADR 0084: custodia Telegram posterior a BETA, con parada en el mismo job

**Estado:** decisión candidata para PR de issue #201; aceptada sólo al integrar
el PR con checks y revisión exactos. Diseño: 2026-11-01
(America/Argentina/Buenos_Aires). No se ejecutó una operación host ni se
configuró un bot/destino real con este cambio.

## Decisión

El workflow protegido Boca existente añade cuatro operaciones manuales,
`telegram-migrate`, `telegram-prepare`, `telegram-install` y
`telegram-verify`. Permanecen separadas de `beta-install`, aceptación Site y
el panel. Cada dispatch exige dueño/repo/main, primer intento, entorno
`boca-first-deploy`, los marcadores BETA y Telegram protegidos, commit HEAD,
release run exitoso y manifiesto para el mismo SHA/digest GHCR, SSH fijado y
hash exacto del Compose BETA. La entrada opcional de `telegram-install` es
únicamente el sobre cifrado canónico de ADR0083, codificado base64url sin
padding. La operación no tiene entrada ni variable de token/chat en claro.

Un nuevo `start-existing` valida UID10001, home y runtime privados, bus y
socket de systemd, ausencia del socket rootful accesible, configuración y
unit originales byte por byte, enlace de habilitación exacto, unidad efectiva
sin drop-ins, linger y estado inactivo. Sólo entonces inicia la unidad del
daemon **existente**; no ejecuta `prepare-rootless`, no reescribe configuración
ni borra datos. Tras iniciar, comprueba socket, unidad activa, metadatos
rootless/cgroup/driver y el inventario global acotado: un contenedor desconocido
o en marcha bloquea la operación y no se detiene por adelantado. El paso
`always()` posterior al marcador de intento invoca el `stop-test` Boca en el
mismo job tanto en éxito como fallo, y requiere recibo positivo de parada o
ya parado. El inventario incierto queda NO_GO y se preservan los volúmenes.

La fase posterior exige exactamente un controller BETA parado, nombre,
etiquetas, comando, UID, imagen local cuyo ID/digest/revisión coinciden con el
release aprobado, presupuesto y puerto 127.0.0.1:8443, simulación/engine off,
mounts data/key/owner, ningún otro contenedor o volumen, red BETA exacta sin
peers y hash del archivo Compose ya instalado. Mide capacidad del filesystem
dedicado. Un contenedor nuevo de una sola ejecución, sin red, con digest local
fijado, límite 0.25 CPU/64 MiB/16 PID, cap drop y rootfs read-only comprueba
el SQLite existente; `telegram-migrate` permite el ledger completo y
checksums 0001–0006 para aplicar aditivamente 0007, o verifica 0001–0007
ya presente sin reescribirlo. Después exige 0001–0007 íntegros.
No crea una DB, no instala sobre una DB desconocida ni reanuda un controller.

`telegram-prepare` crea sólo el volumen privado nuevo y rotulado
`boca-socios_boca_telegram`, verifica driver/mountpoint y prepara el directorio
UID/GID10001 modo 0700 en un contenedor sin red con cap CHOWN. Invoca el
helper ADR0083 y emite únicamente clave pública/huella. `telegram-install`
acepta ciphertext por stdin del contenedor sin red, y `verify` lee montaje
read-only. Los recibos están acotados y redactados; no se reintenta
automáticamente un paso fallido o parcialmente escrito. Data, key, owner,
Telegram y archivo staged se conservan siempre. Este flujo **no** abre una
conexión Bot API, no inicia el worker ni envía un mensaje.

## Puerta operativa pendiente

El bot y el chat numérico privado aún no fueron aportados ni verificados.
La posesión del sobre cifrado y la validación de su formato no prueban que el
bot exista ni que el destino pertenezca al dueño. Se requiere un issue/PR
separado para comprobar `getMe`, `getChat`, afirmación de identidad/destino
por el dueño, procedencia de schema0007 y una sola notificación sintética
con fence duradero de ADR0066. La aceptación Bot API se distinguirá de
recepción humana; timeout o crash quedarán ambiguos, sin retry. El worker
opt-in de ADR0078 seguirá apagado hasta esa puerta. La operación host
continúa NO_GO sin release real, entorno protegido, bot y destino verificados;
este PR no despacha nada.

## Evidencia y límites

Las pruebas sintéticas cubren configuración/unit inalterados, daemon ya
activo o inventario desconocido, fuente/digest, contenedor parado, volumen,
red, checksum/schema/replay y orden del workflow con stop posterior. El primer
commit de tests falló por ausencia de `start_existing`; SHA candidato, gates
hosted y revisión se consignan en el PR de #201. Un smoke del PR usa un
contenedor y volumen desechables sin red con credenciales ficticias para
ejercitar prepare/cifrado/install por stdin abierto/verify. No constituyen prueba de
estado del droplet, token, destino ni entrega. El escritor central reconciliará
README, plan y checkpoint tras integrar el resultado conforme a la regla 84.
