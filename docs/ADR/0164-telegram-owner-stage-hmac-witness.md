# ADR 0164 — Telegram owner-stage witness: prueba HMAC parcial, WebAuthn POST ausente

Fecha: 05/11/2026 ART · Issue #362 · Telegram #315 · Canónico #45.
**DRAFT / CODE_ONLY / NO_GO físico / 0 Bot API**. Owner exclusivo:
`telegram_host` FASE3 R28. Este cambio no contiene issuer, ruta HTTP, key
loader, caller de host, contenedor ni workflow. Seguridad P2 adicional sigue
postergada; estas precondiciones son **integridad funcional P0**.

## Hallazgo verificado: el POST actual no ejecuta WebAuthn

En `panel.private_http.PrivatePanelApplication`:

- `_login` llama `OwnerSessions.authenticate(proof)`, cuyo verifier
  `PasskeyOwnerAuthentication.verify` valida criptográficamente firma ES256,
  challenge único con expiración 120s, RP/origen exactos, user-present y
  user-verified. **Este challenge sólo se ejecuta al login.**
- El POST `/telegram/emparejar` (líneas ~392–436) verifica únicamente
  cookie/sesión, CSRF, `operation_id` one-shot y sobre V2 cifrado; llama
  `telegram_pairing_stager(envelope)`. No recibe `PasskeyAssertion`, no
  llama al verifier, no exige challenge nuevo. La sesión se mantiene en la
  SQLite independiente Opción B, deliberadamente sin vencimiento.
- `telegram_pairing_staging.stage_private_telegram_pairing` escribe la
  estructura `stage_id/staged_at/envelope_sha256/recipient_fingerprint/
  envelope_base64url` 0600/O_EXCL, **sin firma del acto POST ni clave de
  autoridad independiente**. Un archivo correcto y una cookie persistente
  no equivalen a WebAuthn verificado en ese momento.
- `telegram_pairing_issuer.issue_owner_pairing_receipt` exige una clave HMAC
  32 bytes y `CutoverCoordinates` ya atestados: no provee material de firma ni
  auth de host. La clase `OwnerPairingReceipt` ligada a la lease posterior
  tampoco puede reemplazar una prueba de origen del stage sin issuer auténtico.

**Resultado:** no es legítimo modificar hoy el POST/stager ni crear
`owner_authenticated=True` a partir de booleanos, de `stage_id` o de
cookie/CSRF; no hay caller para autenticar una firma WebAuthn fresca en ese
POST ni secreto HMAC de propósito Telegram fuera DB/repositorio. Cambiar
la sesión permanente o pedir PIN periódicamente no forma parte del alcance.

## Contrato puro implementado

Nuevo `src/boca_socios/telegram_owner_witness.py`, sin import de runtime,
socket, Docker, WebAuthn verifier ni key loader:

1. `OwnerStageContext` espera seis pins **externamente comprobados**:
   `stage_id`, `staged_at` registrado por servidor, `envelope_sha256`,
   `recipient_fingerprint`, `owner_digest`, fingerprint del verificador
   passkey público. Esos datos NO son credenciales ni GO.
2. `OwnerStageWitness` sólo es objeto para verificar HMAC de un futuro
   **issuer aún inexistente**. Firma con dominio exclusivo
   `boca-telegram-owner-stage-witness-v1` todos los pins anteriores, el
   digest de challenge WebAuthn, digest de operación, timestamp de prueba
   reciente, fecha de emisión y nonce 256 bits. El MAC y nonce se omiten
   del `repr`; token, chat ID, challenge raw y firma WebAuthn nunca aparecen.
3. `review_owner_stage_witness(... owner_witness_key: bytes, trusted_now: int)`
   recibe una clave 32B **inyectada exclusivamente por un futuro host
   protegido**; no la crea, lee de archivo, envía ni almacena. Rechaza claves
   ausentes, longitud mala y todo cero; comprueba HMAC constant-time,
   formato canónico de hashes, igualdad completa con pins aportados por
   relector real de stage, timestamps `proof<=staged<=issued<=now`, prueba
   ≤45s antes de stage, emisión ≤30s después de stage y stage ≤3600s.
   No modifica stage ni consume nonce.
4. Aun con MAC correcto retorna **`HMAC_VALID_ONLY` /
   `authorized=False` / `passkey_proven=False` / `sender=OFF`**: el HMAC
   **no demuestra quién controlaba la clave de firma** ni que el issuer
   ejecutó realmente `PasskeyOwnerAuthentication.verify`. Nunca se debe
   convertir este review en `HostRecheckReceipt`/GO/custody.
5. Tests sintéticos test-first: MAC bueno no autorizante, tampering de cada
   campo, stage/owner/verifier distintos, nonce/clave inválida, tiempos
   incoherentes/expirados, no publicación de material secreto en repr.
   Ninguna llamada HTTP/WebAuthn de usuario/Telegram ni credencial real.

## Plan de integración futura: decisión pendiente, no effect-code

**Paso 1 — issuer con autenticación real:** el owner de panel debe elegir
una UX de assertion ES256 puntual para el **acto Telegram** (no cada minuto):
el backend genera challenge nuevo con `PasskeyOwnerAuthentication.challenge`,
Chrome WebAuthn firma, el mismo `PasskeyOwnerAuthentication.verify`
consume el challenge y sólo entonces un issuer de custodia privada
podría firmar hash de stage/operación/release. Un cookie duradero solo
no cumple esta condición. Toda reactivación futura requiere distinguir
witness de stage antiguo y rearm legítimo #telegram_rearm.

**Paso 2 — clave dedicada 32B:** aún no hay fuente aprobada para el MAC.
Crear material criptográfico específico en uno de los volúmenes Boca
existentes requiere dueño/GO y análisis de la exposición: no reutilizar
silenciosamente `boca_master_key` ni montar Docker socket en contenedor
con egress. Evitar clave en SQLite, GitHub, runner argv/logs, URL, navegador,
respaldo o volumen nuevo. Si secreto no disponible, abortar ANTES del
primer GET, sin commit de estado.

**Paso 3 — same lease en egress:** el patrón viejo
`host_first_deploy._telegram_test_container` posee data+Telegram y red
dedicada, pero no UID/PID+flock host ni atestación por fase. Para la Opción A
(arquitectura [#362](https://github.com/mbalbo2023/boca-socios-assistant/issues/362))
hay que demostrar con pruebas offline de rootless UID-namespace un
contrato de lease **dentro del proceso GET** y un IPC Unix de sólo
atestación host, sin delegar Docker socket al proceso conectado a Internet.
No ejecutar contenedor ni consultar Bot API hasta revisar y autorizar
ese diseño; Go/ACK y sender permanecen pasos separados.

## Alcance y condición de entrega

Sólo tres rutas nuevas: módulo, tests y este ADR. **No se editó**
`panel/private_http.py`, `telegram_pairing_staging.py`,
`telegram_same_lease_stage.py`, `telegram_pairing_cutover.py`,
BLACKBOX, Compose, workflow, GitHub protected runner ni SQLite legacy 0008.
No modificación del droplet, backup, Porota, puertos, servicios ajenos ni
compra/reserva real. Regla 84: SHA/TREE, CI PR-only, RCA y blockers en
PR/issue #362, #315, canónico #45.
