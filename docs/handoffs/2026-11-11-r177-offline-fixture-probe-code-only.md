# A45-R177 — prueba Chromium local y acuse IPC no transaccional

**Fecha:** 2026-11-11 (ART). **Alcance:** únicamente Boca browser IPC y tests.
**Estado:** desarrollo `CODE_ONLY`, no merge ni despliegue ni prueba física de Chromium.

## Alcance implementado en rama aislada

- Nuevo pedido constante `BOCA_SYNTHETIC_V1_PROBE_FIXTURE` y respuesta
  `BOCA_SYNTHETIC_V1_FIXTURE_OBSERVED`, diferentes de los existentes
  `BOCA_SYNTHETIC_V1_RUN`, `...RESERVED_IN_SIMULATOR` y `...NO_GO`.
- `BOCA_BROWSER_OBSERVE_MODE=offline-fixture` habilita exclusivamente en el
  proceso worker un `OfflineFixtureExecutor` existente: Chromium sobre HTML
  literal inventado, contexto `offline=True`, aborto de todo request y
  cierre acotado. El modo implícito `off` conserva el executor NO_GO.
- Con el modo fixture, un pedido normal de reserva `RUN` responde NO_GO
  sin ejecutar Chromium. Sin el modo fixture, `PROBE_FIXTURE` responde NO_GO.
  Un valor de modo desconocido impide iniciar el servidor.
- Cliente nuevo `UnixSyntheticBrowser.probe_offline_fixture()` separado del
  método transaccional. Su único valor positivo es `fixture_observed`; nunca
  representa una reserva. Rechaza `...RESERVED_IN_SIMULATOR` como respuesta
  al probe. Conserva misma autenticación AF_UNIX, comprobación de inode,
  single-flight, timeout, STOP y cierre de socket.
- No se incorporó endpoint HTTP, botón del panel ni conexión de la prueba
  al flujo de reservas. No cambian Dockerfile, Compose, infraestructura,
  secretos, SITE_URL, archivos protegidos ni flujos de GitHub.

## Evidencia CODE_ONLY y límites

- Ciclos TDD RED→GREEN en worker/opt-in/cliente.
- `pytest -q tests/test_r177_fixture_probe_client.py
  tests/test_r177_fixture_probe_transport.py
  tests/test_ipc_server_adapter.py`:
  **32 PASS, 1 SKIP**; skip explícito porque el kernel sandbox local
  devuelve `EPERM` ante `socket(AF_UNIX)`.
- Suite integral local `pytest -q -n 4 --tb=line`:
  **6835 PASS, 1 SKIP, 34 subtests PASS**, 0 FAIL.
- Ruff check y formato de los seis archivos modificados: PASS;
  mypy de los tres módulos fuente: PASS.
- No hay prueba física real del binario Chromium ni prueba cross-UID
  del nuevo PROBE en droplet. No declarar GREEN físico.

## Fase B / siguiente gate no implementado

1. Integrar/validar la rama mediante PR aislado, ejecutando el smoke AF_UNIX
   de prueba en Actions Linux real con usuario/identidad y confirmando que
   no se omite. No activar bandera de fixture en Compose por defecto.
2. Diseñar un comando separado `PROBE_SITE` de **observación únicamente**
   de `SITE_URL` HTTP(S) configurable, bajo START/STOP, con actividad
   categórica sin publicar URL ni tokens y sin interacción transaccional.
   Antes de implementarlo, definir política explícita de navegación de
   sandbox, timeouts, interrupción, identidad e interconexión por IPC.
3. Solo con aprobación de UX/QA, exponer una acción independiente de prueba
   de fixture en dashboard; jamás reutilizar POST de reserva ni encender
   automáticamente el fixture al iniciar el bot. La verificación requiere
   evidencia de passkey/panel 8443, worker físico y TELEGRAM sender OFF.
4. Ninguna fase incluye reservas reales, scripts de bypass de cola,
   exfiltración de tokens, cambios en Porota o limpieza de Docker ajeno.

Este handoff complementa
[R176](2026-11-11-r176-ipc-runner-fixture.md); no cambia la
trazabilidad ni la autorización del release R176 que el otro frente
estuviera realizando.
