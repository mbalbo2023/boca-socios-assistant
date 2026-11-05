# ADR0171 — Telegram: preflight físico del stage owner sin GO de egress

Fecha: 05-Nov-2026 ART · Issue #315, seguimiento #362/#45 · DRAFT satélite (FASE5) · Base #319 R21.21 `3cbe31703d74413f8de66ac8783ec68b1b7f8a87`.

## Decisión y alcance

Se implementa `src/boca_socios/host_telegram_owner_stage.py`, helper **solo lectura** para el host Boca existente. No extiende `.github/workflows/boca-first-deploy.yml`, no prepara token, no llama Bot API, no incorpora red/contenedor/puerto, no escribe HMAC/nonce ni activa sender. Las pruebas son exclusivamente locales simuladas en GitHub Actions.

Verifica bajo la **misma** `BocaJobLease` (intento/PID/UID/GID10001/FD con flock canónico comprobados por `verify_protected_boca_job_lease`):

1. Pins públicos del workflow `TelegramHostPins` + `CutoverCoordinates` coherentes con release, imagen, controller, owner digest, recipient y lease actual; esto por sí solo no es identidad confiable.
2. Revisión topológica física previa y posterior con `observe_telegram_host`: daemon rootless Boca, inventario exacto de controller/worker/sender detenido, sin servicio extranjero ni egress ocupado, imágenes, volúmenes, red privada y 127.0.0.1:8443.
3. Identidad de volúmenes nombrados `boca_data` + `boca_owner` por `Docker volume inspect` sobre el mismo `LifecycleDockerIO`; ambos mountpoints son directorios reales, hermanos, sin redirect. No se aceptan rutas privadas por argv.
4. Configuración *efectivamente instalada* `Config.Env` del controller detenido: `BOCA_PANEL_ORIGIN=http://localhost:8443`, staging `encrypted-only`, simulación, motor OFF, rutas exactas de las dos credenciales públicas del owner, subject sin ambigüedad ni variables duplicadas.
5. Lectura `O_NOFOLLOW` y comprobación de identidad/inodo/propietario/permisos de `credential_id` y `public_key.der` existentes en `boca_owner`; nunca se leen claves privadas.
6. Reconstrucción del mismo `PasskeyOwnerAuthentication` ES256 de `runtime.py` con las cinco permissions originales, RP `localhost` y origen HTTP loopback, seguida de lectura del `stage` O_EXCL mediante `read_encrypted_telegram_stage`, su frescura <=3600 segundos, firma ES256 + UV sobre ciphertext exacto y owner binding con `verify_stage_owner_witness`.
7. Relectura stage bajo la misma lease (identidad y contenido inmutables), revalidación final topológica y flock. Las observaciones se informan *sin* secretos ni identificador de chat.

El resultado único positivo es `OWNER_STAGE_VERIFIED_EGRESS_NO_GO` con `authorized=false`, `host_effects=false`, `sender_state=OFF`, `nonce_consumed=false`, `bot_api_reads=0`, `human_receipt=UNVERIFIED`. Ante cualquier fallo de identidad o tiempo se obtiene un código de error fijo sin trazas privadas.

## RCA: por qué esto aún NO permite activar Telegram físicamente

- `host_telegram_postcutover.observe_telegram_host` tiene de forma intencional `authorized=False` y exige que la red de Telegram tenga **cero** peers. Durante cualquiera de los cuatro GET reales la red de egress tendría un helper activo; la función actual no puede atestar esa fase sin contrato nuevo de egress.
- El helper legacy `host_first_deploy._telegram_test_container` existe con ambos volúmenes y red dedicada, pero no demuestra tener el **mismo PID host y la misma open-file-description con flock**; su reutilización necesitaría contrato de Docker/IPC Boca-only revisado y GO físico expreso. No se monta el lock ni se hace chmod para aparentar identidad.
- En Docker rootless es posible que UID10001 del container esté mapeado a **subuid host distinto**. Este helper exige metadata de owner/stage compatible con UID10001 host; si no existe la equivalencia, **fallará cerrado**. El mapeo real, las rutas de los volúmenes y dependencias Python del host deben certificarse tras el Cutover A antes de toda acción. Los tests CI no certifican ese host.
- El `owner_digest` y `cutover_receipt_sha256` del contexto son coordenadas públicas; hace falta probar el recibo de Cutover firmado/atestado bajo la fuente protegida, no basta con pasar strings válidos.
- Un recibo de owner WebAuthn es **autenticación del acto de stage**, no un permiso de activar sender ni prueba del destinatario/chat. La clave HMAC 32 bytes en el host puede generarse efímera bajo la misma lease *solo después* de que el host attestor pase, y `execute_staged_pairing_under_lease` exige consumir nonce O_EXCL, cuatro GET-only y custody V2 commit antes de un ACK de etapa. `human_receipt=UNVERIFIED` sigue hasta la recepción externa efectiva; sender requiere GO independiente.

### Decisiones pendientes específicas para destrabar

**A (preferida condicional):** definir/autorizar un único helper efímero Boca-only reutilizando `telegram-test`, `boca_data`, `boca_telegram`, `telegram_egress` y la lease **retenida en proceso host**. Un canal IPC estrictamente redacted deberá ligar cada uno de cuatro GET con recheck real de helper ID, PID/UID, imagen, volumen, red/poller, flock y nonce; protocolo auditado y cleanup selectivo garantizado en éxito/fallo. Requiere GO infraestructura protegido independiente. No crear ese helper antes de GO.

**B:** GET y descifrado directamente en proceso host UID10001 bajo flock sin IPC, pero primero probar egress dedicado, librerías, UID/subuid y custodia; no relajar el aislamiento ni conectar host a Internet genérico para evitar un helper.

**Estado:** `TELEGRAM_ACTIVATE_PHYSICAL=NO_GO`. No bloquear el Cutover/deploy de BETA core por una prueba offline GREEN. Solo una ejecución física aprobada post-Cutover con observador live, receptor y ACK de custodia puede levantar ese bloqueo; la recepción humana y el sender siguen separados.

## QA / Regla84

`tests/test_host_telegram_owner_stage.py` crea stage V2 real sintético, clave ES256 y WebAuthn UV firmados para un certificado ficticio, inspección Docker simulada; verifica que el stage permanece intacto y que no hay efectos, rechazos de staging legacy, owner subject alterno, symlinks, mountpoint foráneo, expiración, coordenadas falsas y Config.Env duplicado. No llama Docker, SSH, Telegram, WhatsApp, Boca ni ningún servicio de producción.

Cierre pendiente: registrar HEAD/TREE exactos y 4/4 Actions GREEN de DRAFT satélite, conservar manual físico/publish como SKIPPED. Sin merge, sin host, sin workflow, sin credenciales en argv/logs, sin cambios a BLACKBOX, Porota ni otros servicios.
