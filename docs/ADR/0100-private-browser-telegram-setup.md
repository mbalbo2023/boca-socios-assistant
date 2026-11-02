# ADR 0100: configuración Telegram cifrada dentro del panel privado

**Estado:** candidato de [issue #252](https://github.com/mbalbo2023/boca-socios-assistant/issues/252).
Parte de la BETA de simulación; requiere revisión independiente y CI sobre el SHA
integrado. Las pruebas sintéticas no acreditan instalación, envío Telegram,
recepción humana, Chrome Android ni passkey reales. No modifica el droplet.

## Problema y alcance

El instalador existente `telegram_bootstrap` recibe un sobre X25519/HKDF/AES-GCM
pero no existía una pantalla que el dueño pudiera usar desde su tablet para
crearlo. Pedir un script, token o ID de chat por una conversación sería un
requisito innecesario y expondría material privado. Se reutiliza el contrato del
instalador: la nueva pantalla sólo prepara su entrada cifrada. No agrega API
Telegram, endpoint de instalación, listener, volumen ni permiso del servidor.

`GET /telegram/configurar` exige la sesión existente autenticada con passkey.
El servidor entrega HTML fijo; no renderiza datos de la solicitud. Una petición
POST a esa ruta se rechaza sin leer su cuerpo. Se conserva la comprobación del
origen y la prohibición de query strings. La ruta se incorpora al inicio privado.

## Recibo público y cifrado local

La operación protegida `telegram-prepare` ya devuelve `state`, `public_key` y
`fingerprint`. Tras verificar esa ejecución, se construye un enlace de la forma
`http://localhost:8443/telegram/configurar#recipient=<recibo-publico-base64url>`.
El recibo es JSON canónico ASCII, con exactamente esos tres campos; los estados
admitidos son `PREPARED` y `ALREADY_PREPARED`. No contiene token, chat, clave
privada ni capability de propietario. No existe un `recipientId` alternativo.

El script quita el fragmento del historial antes de habilitar los campos o
iniciar una operación criptográfica. Rechaza recibos fuera del límite,
base64url no canónico, JSON duplicado/no canónico, campos extra, fingerprint
incorrecto y puntos X25519 no utilizables. La coincidencia SHA-256 entre clave
pública y fingerprint prueba consistencia; **no autentica quién emitió el
recibo**. La confianza proviene del run protegido aprobado y comprobado.

Los campos no tienen `name`, no pertenecen a un formulario y están bloqueados
hasta comprobar recibo, origen exacto `http://localhost:8443`, contexto seguro
y WebCrypto X25519. Sólo acepta bot ID y destino decimal positivos, canónicos
y menores que 2^52, igual que el gate de chat privado del one-shot; no admite
grupos, ceros ni valores que el instalador pudiera guardar pero el test rechazaría.
La CSP propia permite sólo los hashes de los recursos
inline fijos y establece `connect-src 'none'` y `form-action 'none'`.
No hay `fetch`, logs, almacenamiento web ni endpoint de texto plano.

El cifrado implementa exactamente el formato existente, sin cambiarlo:

- X25519 efímero nuevo por sobre, clave privada no exportable.
- Sal aleatoria de 16 bytes, nonce aleatorio de 12 bytes.
- AAD igual al encabezado JSON canónico del instalador: versión, repositorio,
  propósito, UID10001, receptor/fingerprint, efímera, sal y nonce.
- HKDF-SHA256 con `info = "boca-telegram-bot-envelope-v1:" + SHA256(AAD)`.
- AES-256-GCM, tag de 128 bits, payload JSON canónico de token y destino.
- Sobre completo canónico, limitado a 4096 bytes y codificado en base64url
  sin padding para el input existente **`telegram_envelope`** de Actions.

El nombre del input no es `telegram_envelope_b64`. La pantalla no despacha
Actions. Calcula además localmente los dos pins ya exigidos por ADR0085:
el prefijo numérico canónico del token para `BOCA_TELEGRAM_EXPECTED_BOT_ID` y
`HMAC-SHA256(key=token, message=chat_decimal)` para
`BOCA_TELEGRAM_EXPECTED_CHAT_HMAC`. Los dos se copian directamente a Secrets
del entorno `boca-first-deploy`; el chat en texto plano nunca es salida. Estos
valores derivan del mismo par que se cifra, sin leer ni verificar Telegram.
Bot ID es identificación pública y HMAC es un compromiso opaco, no autorización
para enviar. El usuario copia el sobre a `telegram_envelope` en el run aprobado.
Cada salida tiene etiqueta y botón propio para evitar pegar un pin en el campo
del sobre o copiar accidentalmente el token. No se requiere una terminal.
El texto distingue preparación del sobre, instalación y activación real.
Los campos se vacían al empezar el cifrado, incluso ante un error; los arrays
con plaintext/shared secret se sobrescriben al finalizar. `pagehide` limpia
campos y salida, bloquea la vista restaurada y evita resultados tardíos tras
navegar. JavaScript no permite prometer borrado físico de cadenas inmutables
o del estado interno del motor; tampoco controla extensiones del navegador.

Si el portapapeles está bloqueado, se selecciona únicamente la salida cifrada o el pin elegido
para la acción Copiar. No hay fallback que muestre o copie el texto plano.
La pantalla usa etiquetas explícitas, controles de al menos 52 px y estado
anunciado por `aria-live` para manejo por voz.

## Secuencia de operación

La custodia del dueño y el enrolamiento con Chrome deben estar completos
antes del primer `beta-browser-install`. En esta etapa la BETA tiene que
estar aún sin simulaciones persistentes ni avisos pendientes.

1. Operaciones aprobadas de esquema y `telegram-prepare`; conservar el recibo
   público exacto. Cada operación Telegram termina deteniendo Boca.
2. Operación aprobada `beta-browser-start` para servir el panel sin worker
   Telegram. Abrir el túnel, ingresar con la passkey y abrir el enlace de recibo.
3. Crear el sobre y los pins en la pantalla. Copiar los pins a los dos Secrets
   indicados y el cifrado al input `telegram_envelope` del futuro
   `telegram-install`, con los demás valores exactos ya revisados.
4. Ejecutar `stop-test` antes de `telegram-install`: su `start-existing`
   exige inventario detenido. Instalar y verificar con el protocolo existente.
5. Ejecutar el `telegram-test` protegido y confirmar recepción humana antes
   de `beta-browser-telegram-start` y de la primera simulación persistente.

Las operaciones, variables/secretos y presupuestos exigidos por los workflows
no cambian. La aceptación BETA usa SQLite efímero en `/tmp`; no debe confundirse
con iniciar una simulación persistente. La prueba Telegram queda vinculada a
bot, destino y SHA; un reinicio del mismo SHA conserva esa prueba. Un upgrade
de SHA necesita su propio procedimiento revisado, no hereda el permiso anterior.

## Compatibilidad y evidencias

[Chrome 133](https://developer.chrome.com/release-notes/133) incorporó X25519
en `SubtleCrypto` para desktop y Android. Se detecta la capacidad real al abrir
la pantalla; no se decide por user-agent y no se implementa un algoritmo de
respaldo. La [guía oficial de cifrado local](https://developer.chrome.com/docs/modern-web-guidance/guides/security/client-side-encryption)
documenta la combinación efímera X25519/HKDF/AES-GCM usada aquí. La aceptación
física de la tablet depende de su Chrome actualizado y de su túnel; no se
marca aprobada mediante Node ni fixtures de escritorio.

`tests/test_telegram_setup_ui.py` ejecuta el **script servido sin modificaciones**
en Node con WebCrypto nativo y descifra su salida con el instalador Python
existente. Comprueba binding del encabezado, nueva aleatoriedad, limpieza,
recibos adversariales, contexto incorrecto, portapapeles denegado y acceso HTTP
privado sin lectura/reflexión de credenciales. Node es requisito explícito de
la prueba: si falta o no admite X25519, falla; no se omite ni se declara verde.

`scripts/run_telegram_setup_ui_offline_chromium.py` separa tres modos para CI:
renderizar fixture con stdlib del host; ejecutar Chromium sandboxed UID10002
bajo `--network none`, con sólo la interfaz `lo`; descifrar el recibo en la
imagen controller que ya contiene `cryptography`. El browser no recibe ni
instala esa dependencia. Se monta únicamente script y fixture sintéticos de
solo lectura. El único documento se satisface en memoria por Playwright en
el origen localhost exacto; no se levanta listener ni se solicita sitio externo.
Se verifica borrado de fragmento, tamaños de controles, CSP que bloquea POST,
cifrado real, pins derivados y copia de las tres salidas permitidas. El verificador independiente rechaza un
recibo omitido, falso, incompleto o cuyo sobre no descifre a los valores de
prueba. La limpieza del runner es selectiva por nombres del mismo run.
