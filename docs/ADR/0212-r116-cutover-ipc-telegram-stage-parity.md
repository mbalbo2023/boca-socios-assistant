# ADR0212 — R116: paridad de stage Telegram cifrado en Cutover IPC

Fecha: 2026-11-08 ART. Issues #354, #417 y #45. **CODE_ONLY / NO_GO host**.

## Evidencia y RCA independiente

`main=f57173862df3143062a136452f2ffc7e3cc51d35` tiene en
`compose.beta.browser.yaml` el opt-in exclusivo del controlador IPC
`BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only`. Sin embargo, Cutover V3
usa `_cutover_candidate_create_argv` para crear el contenedor con `docker
create` directo; este builder omitía el opt-in. `Settings.from_environment` usa `off`
si falta esa variable y `_configured_telegram_pairing_stager` no configura
callback; el postflight inspeccionaba Config.Env sin exigir el selector.
Podía entonces certificar el contenedor con la etapa de Telegram desactivada.

El último Cutover físico [#42426260583](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583)
fracasó antes de crear ese controlador, en `PREPARE_WORKER/HEALTH_EXITED`,
`ExitCode=1`, `OOMKilled=NO`. Este defecto de configuración **no explica la
salida del worker**. La [observación READ_ONLY #42426527816](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426527816)
encontró el controlador legacy activo y ningún worker nuevo en ese instante;
no certifica cleanup integral de imágenes/IPC/stage.

## Decisión de integración

Se conserva el único Cutover V3 y el modelo Compose aprobado. El builder de
creación IPC entrega el valor literal `encrypted-only`, y el postflight lo
exige en **Docker Config.Env efectivo** junto a `ipc` y motor `off`. Valor
ausente, `off`, alterado o duplicado implica `PreflightError`, sin un nuevo
servicio, puerto, secreto, backend o flujo de despliegue. El Compose legacy
continúa sin esta habilitación; el worker no recibe stage ni token.

Se descartó modificar sólo Compose, pues ya estaba correcto, o crear un
segundo workflow. No se alteran los blackboxes protegidos, no se activa
Telegram Bot API/sender y no se habilita navegación o reserva real.

## Pruebas y límites de aceptación

- `test_candidate_argv_enables_only_encrypted_ipc_telegram_stage`: RED
  observado (0 opt-ins) antes del cambio; GREEN después (un opt-in, sin
  token/sender).
- `test_controller_postflight_requires_encrypted_stage`: RED observado para
  cinco configuraciones ausentes/incorrectas; GREEN para esos casos y dos
  duplicados; inspección real del contrato sobre fixture completo con
  `running=False`, sin afirmación de kernel o cgroups físicos.
- Suite focal inicial: 226 PASS antes del cambio; suite ampliada tras la
  corrección: 295 PASS. Los gates completos y Actions exactos deben
  registrarse con el PR, no inferirse de este documento.
- El ZIP protegido cambia de digest porque contiene
  `host_first_deploy.py`; se preservó el pin histórico R114 y se fijó un
  nuevo SHA256 R116
  `2e6eb49323be4edcbe427aee34c7f2801c8698f8ccf8ba46945907550749c14d`.
  El builder determinista midió 39 entradas, 869915 bytes de contenido,
  207699 bytes de payload comprimido y **213641 bytes de ZIP completo**;
  no cambia el allowlist ni los techos de 872000 / 512000 bytes. El test de
  pin falló RED durante la suite completa antes de
  actualizar este pin; se debe volver a correr la suite luego del cambio.
- Después de fijarlo, suite local completa `uv run pytest -q -n auto`:
  **5546 PASS +34 subtests**, cero fallos (25,50 s). Ruff check,
  Ruff format `706 files`, MyPy `136 source files` y policy PASS. Son pruebas
  en workspace local, no evidencia de Actions ni del droplet.

**Permanecen NO_GO** la BETA integral física, la causa interna del ExitCode1
del worker, las comprobaciones de arranque del blackbox que corresponden a su
dueño, `telegram-activate` (backend protegido aún desconectado), recepción
humana, ACK de lifecycle/sesión Samsung y limpieza final Boca-only. El
workflow de activación Telegram mantiene su `exit 1` intencional; quitarlo
sin attestor/lease/custody/egress/cleanup sería inseguro. Ninguna Action
física fue despachada por R116.

Diseño: [R116](../superpowers/specs/2026-11-08-r116-cutover-telegram-stage-parity-design.md).
Plan: [R116](../superpowers/plans/2026-11-08-r116-cutover-telegram-stage-parity.md).
