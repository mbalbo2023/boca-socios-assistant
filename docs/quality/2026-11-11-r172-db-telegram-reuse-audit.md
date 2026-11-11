# R172 — Reutilización de SQLite de socios y Telegram (CODE_ONLY)

**Fecha:** 2026-11-11 ART.

**Referencia auditada:** `origin/main=361e3ff42c44e1b8699d7a3e2d158c9a367b2f86` (R171).
**Alcance:** lectura de contratos de código y políticas; ningún host, GitHub
Actions, base real, token, credencial, sitio Boca ni API de Telegram fue
consultado. Este informe no acredita el estado físico presente del droplet.

## Veredicto contra duplicación

La base de socios **ya existe** en el código revisado. **No** importar el
adaptador SQLite/contraseñas en claro del ZIP V3 ni desarrollar un segundo
repositorio de usuarios. Tampoco corresponde crear otro transporte Telegram:
hay una cadena explícita de emparejamiento cifrado, outbox durable,
coordinación de entrega, transporte y worker opt-in. El ZIP V3 suministrado
contiene un **token Telegram expuesto** según `AGENTS.md`; su dueño debe
**revocarlo y rotarlo** antes de cualquier futura activación. No inspeccionar,
repetir, registrar ni distribuir su valor.

| Capacidad existente | Rutas concretas | Estado demostrable |
|---|---|---|
| Esquema de socios y una intención por socio/evento | `storage/migrations/0001_initial.sql`, `storage/database.py` | Código SQLite con claves y unicidad; no inventario host |
| Bóveda AES-256-GCM, nonce individual, AAD por `member_id`, clave externa | `security/credential_vault.py`, `security/key_custody.py` | Código; no lectura de claves |
| Alta, rotación y revocación atómicas, con auditoría | `security/enrollment.py`, `integration/operational.py` | Integración del servicio ya presente |
| Panel privado: alta/listado/detalle de socios, acciones sobre credencial | `panel/enrollment_http.py`, `panel/private_http.py`, `panel/private_ui.py`, `panel/members.py` | Rutas y renderizado implementados; aceptación física nueva pendiente |
| Outbox y aviso generado por simulación | `storage/migrations/0002_notification_outbox.sql`, `notify/sqlite_outbox.py`, `integration/offline.py`, `integration/beta.py` | Código durable compartido; avisos sin datos personales |
| Setup privado y stage Telegram cifrado con firma passkey | `panel/telegram_setup_ui.py`, `panel/telegram_pairing_staging.py`, `panel/private_http.py`, `runtime._configured_telegram_pairing_stager` | Etapa opt-in con resultado `STAGED_PENDING_PROTECTED_CUTOVER`; **no activa sender** |
| Entrega Telegram con cerca previa, resultado ambiguo sin reenvío | `storage/migrations/0007_telegram_delivery.sql`, `notify/telegram_delivery.py`, `notify/telegram_transport.py`, `notify/telegram_worker.py` | Sender explícito independiente del controller, limitado a textos sintéticos; **no hay recibo físico de envío** |
| One-shot/host protegidos | `telegram_one_shot.py`, `host_telegram_postcutover.py`, `host_telegram_owner_stage.py`, `host_telegram_active_helper_topology.py` | Abstracciones de custodia/atestación; no son instalación ni aprobación |

El runtime ya construye `MemberEnrollmentService`, conserva su ruta de
clave externa, y el controlador usa `MemberDirectory` en `GET /socios`.
El coordinador de simulación incorpora `StaticOutboxAdapter` para encolar
avisos; `notify/telegram_delivery.py` puede consumir **ese mismo** outbox
mediante el proceso optativo separado. No hace falta reimplementar ninguna
de estas tres piezas para integrar el bot bajo demanda.

## Bloqueantes concretos y propietarios

1. **IPC/Chromium — dueño de integración worker:** `AGENTS.md` registra que
   el entrypoint protegido `ipc_worker.py` no proporciona el servidor Unix IPC
   esperado. Corregir `MISSING_BARE_SYNTHETIC` únicamente resuelve un import:
   no basta para arrancar el protocolo ni justifica navegar el sitio real.
   Se requiere adaptación de transporte limitada a simulación, sin tocar
   algoritmos de navegación ni ensayar con Boca/Queue-it. Este worker **no
   es** `notify/telegram_worker.py`.
2. **Datos — dueño de persistencia/infra Boca:** el destino lógico es
   `/data/boca.sqlite3` en el volumen Boca y la clave está fuera de la DB.
   Deben verificarse *físicamente* identidad, esquema, montajes y custodia
   mediante el flujo protegido antes de cualquier migración o aceptación;
   código y tests offline no acreditan su existencia actual.
3. **Telegram — dueño de integración/custodia:** el workflow existente
   `.github/workflows/boca-first-deploy.yml`, operación `telegram-activate`,
   publica `BOCA_TELEGRAM_POSTCUTOVER state=NO_GO ... sender=OFF` y ejecuta
   `exit 1` deliberado. Falta cerrar el enlace físico protegido *same lease*,
   destino verificado, custodia privada, egress, pruebas de API y recibo
   humano. No suprimir la barrera para conseguir un verde aparente.
4. **Secreto Telegram — titular:** el token del ZIP V3 debe rotarse antes de
   configurar la identidad efectiva del bot; el stage cifrado no demuestra
   rotación y el correo, GitHub, CI y los logs nunca deben recibir el token.
5. **Operación — arquitectura/QA:** el proceso `telegram_worker.py` es un
   despachador periódico **separado** de la operación `bot` START/STOP del
   panel. Si se exige emisión estrictamente bajo demanda, evaluar el enlace
   con el lifecycle existente o el mecanismo `telegram_one_shot.py` antes
   de habilitar un proceso permanente. No crear otro worker por defecto.

## Regresión incorporada en R172

`tests/test_r172_db_telegram_reuse_contract.py` comprueba **solo el código**:

- El esquema revisado de `credentials` contiene identificador, versión de
  clave, nonce y ciphertext, sin columna de contraseña en claro; el alta
  llama a la bóveda AES-GCM y persiste únicamente el sobre sellado.
- El runtime conserva el stage privado opt-in, y el coordinador y el sender
  siguen compartiendo la cola durable de avisos sintéticos sin importar el
  emisor directamente al controlador.
- `telegram-activate` conserva `NO_GO`, `host=untouched`, `sender=OFF` y el
  `exit 1`; `AGENTS.md` mantiene la obligación de rotar el token comprometido;
  el panel no convierte `STAGED` en `connected=true`.

**Límites del test:** inspección selectiva del esquema, AST y contratos de
fuente; no pretende escanear secretos fuera del repositorio, verificar
rotación efectiva, demostrar que todos los adaptadores futuros son seguros,
ejecutar la Action ni validar Telegram, Docker o la base real.

**Verificación local de este trabajo:** `test_r172_db_telegram_reuse_contract.py`
obtuvo **3 PASS**; baseline focal de alta/Telegram **35 PASS +5 subtests**;
`ruff check .`, `ruff format --check .` (809 archivos), `mypy src` (150
archivos) y `scripts/check_repo_policy.py` quedaron **PASS**. El full suite
`uv run pytest -q` registró **6630 PASS +34 subtests y 1 FAIL**;
`uv run pytest -q -n 4` reprodujo **exactamente el mismo FAIL** con
**6630 PASS +34 subtests**. Es
`tests/test_worker_start_capture.py::test_stream_returns_only_its_terminal_category[total-quota]`,
que recibió `BrokenPipeError` al enviar el bloque grande al socket durante
la prueba. Su repetición individual obtuvo **1 PASS**. La intermitencia
depende del contexto de ejecución, pero este informe **no atribuye una causa
raíz definitiva**; se deriva a ownership de captura/IPC y no se debilita ni
se edita ese test desde R172. El full suite permanece **NO_GREEN**.

**Evidencia base leída:** `AGENTS.md`, `README.md`,
`docs/DEVELOPMENT_POLICY.md`,
`docs/ADR/0147-private-telegram-v2-encrypted-staging.md`,
`docs/ADR/0212-r116-cutover-ipc-telegram-stage-parity.md` y
`docs/ADR/0223-bot-bajo-demanda.md`. Las pruebas existentes de referencia
incluyen `test_member_enrollment.py`, `test_credential_vault.py`,
`test_database_migration_preflight.py`, `test_telegram_delivery.py`,
`test_telegram_pairing_panel_handoff.py` y `test_telegram_owner_lease_e2e.py`.

**Regla 84:** esta rama R172 sólo incorpora documentación y regresión
estática. No modifica infraestructura, red, Docker, artefactos, secretos,
blackboxes ni producción; no constituye un GO, release, instalación, alta
física ni envío real. El dueño de integración debe reconciliar su commit
y las pruebas del SHA definitivo en el checkpoint canónico #45/#417.
