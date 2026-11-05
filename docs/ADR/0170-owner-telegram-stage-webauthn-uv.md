# ADR 0170 — WebAuthn fresco de propietario ligado al stage Telegram V2

**Estado: DRAFT CODE_ONLY / Telegram host físico NO_GO.** 05-nov-2026.
**Contexto:** issues #315, #362; #365 (verificador HMAC puro, no integrar);
candidato único #319 R21.17 `82c7c3edf75911805218149d4907ecb37b374a66`.
**Alcance:** solo panel Boca, ciphertext V2 y evidencia WebAuthn; ninguna credencial ni Bot API real.

## RCA comprobado

La sesión passkey persistente del panel prueba un inicio de sesión anterior, no
una intención nueva del mismo propietario de vincular **este** token cifrado.
El POST legacy de `/telegram/emparejar` recibía cookie+CSRF+operación y
guardaba ciphertext sin un nuevo `navigator.credentials.get` vinculado al
SHA-256 del sobre. El caller posterior no encontraba ninguna firma pública
duradera para revalidar la intención tras detener el controlador. El esquema
`OwnerPairingReceipt` HMAC por sí solo no consigue autenticación WebAuthn:
faltaba el emisor autenticado, la clave y el host real bajo la misma lease.

## Decisión (CODE_ONLY)

1. El controlador ya autenticado crea una operación one-use y recibe únicamente
   `envelope_sha256` del sobre cifrado en
   `POST /telegram/emparejar/desafio`. Autentica cookie/CSRF/origen, compara
   operación pendiente y emite nonce secreto **impredecible** de 32 bytes,
   timestamp del controlador y challenge SHA-256 con dominio explícito
   `boca-telegram-owner-webauthn-stage-v1`, binding de verificador público,
   UUID de operación y SHA del ciphertext. Solo registra un challenge que expira
   a 120s; no toca contenedor, host, Telegram ni SQLite adicional.
2. Chrome/Termius, en el único origen `localhost:8443`, invoca **WebAuthn**
   `navigator.credentials.get` con `userVerification=required`, challenge
   del servidor, ID de credencial configurado y RP `localhost`. Sin prueba
   reciente la UI se detiene; el token jamás sale en claro de Chrome.
3. El POST final contiene el envelope cifrado + assertion pública. El
   controlador valida firma ES256 (origin exacto, RP SHA256, UV+UP, ID de
   credencial y challenge one-shot) **sobre el mismo SHA**, consume operación
   existente y persiste atómicamente O_EXCL/fsync un solo archivo privado 0600
   que incluye envelope y `owner_witness` público. No hay sidecar vulnerable
   a carrera, token en logs ni una segunda base SQLite.
4. El lector Telegram same-lease acepta el campo opcional
   `owner_witness` como dato **no autorizado**, nunca como GO. El futuro
   helper físico deberá ejecutar `verify_stage_owner_witness` de nuevo con
   la configuración pública passkey vigente, la hora de stage confiable y la
   **misma lease + PID/UID/rootless + atestación host REAL antes de cada GET**
   y antes de cualquier efecto. Un stage legacy sin witness NO alcanza.
5. Se conserva `OwnerPairingReceipt` HMAC del contrato de cutover: solo el
   futuro caller host con autoridad explícita podrá generar su clave efímera
   de 32B en memoria **después** de verificar WebAuthn bajo lease, emitir
   receipt y consumir nonce durable; no se introduce clave persistente/secret
   en SQLite, código, argv, logs, ni Chrome. No se conecta ese caller hoy.

## Condiciones NO_GO y QA

- El hecho de que `UV_VERIFIED_ONLY` exista no prueba host PID/lock/lease,
  exclusividad de egress, recipient custody, cutover A, GET reales de
  `getMe/getWebhookInfo/getUpdates/getChat` ni ACK humano single-use.
- Requiere antes de autorización física un helper Boca-only revisado que
  ateste volúmenes y containers exactos en Docker ROOTLESS sin socket Docker
  expuesto a internet, demuestre UID 10001 + **misma lease/único PID para
  HMAC/nonce/los cuatro GET**, y entregue recibo irreversible con cutover GO.
- `telegram-activate` sigue NO_GO/NOT_DISPATCHED, sender OFF, compras reales
  prohibidas, sin puertos nuevos ni HTTPS, sin backups, sin modificar BLACKBOX,
  Porota o Docker de otras aplicaciones.
- Tests sintéticos deben demostrar: ES256 genuino, UV, origen/RP, digest,
  nonce, UUID, replay, expiración, parse estricto, atomía O_EXCL y browser JS.
  GREEN de PR aislado **no** equivale a BETA Telegram activado.

## Compatibilidad y ownership

La firma general de login WebAuthn y la cookie persistente **no cambian**.
Stager `stage_private_telegram_pairing(path, bytes)` conserva lectura legacy
para tests/históricos; el panel instalado bajo `encrypted-only` solo envía
`PairingStageRequest` con prueba WebAuthn válida. Contrato del futuro workflow
Telegram es independiente del trabajo #371 Cutover A + import oficial.
