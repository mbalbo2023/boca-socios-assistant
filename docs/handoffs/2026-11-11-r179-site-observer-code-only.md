# A45-R179 — Observador SITE_URL con Playwright, sólo CODE_ONLY

Fecha: 2026-11-11 ART. **Propietario:** paquete `browser` y pruebas locales.
Este trabajo no modifica Compose, host, Actions, panel, sockets instalados,
Docker, Porota ni cuenta de socios. Tampoco ejecuta navegación real.

## RCA y decisión de no reutilizar el blackbox

El `SyntheticBrowserEngine` previo (`browser/synthetic.py`) contiene múltiples
contextos simultáneos, cambia el User-Agent, usa una opción de Chromium de
ocultación de automatización y busca cookies de Queue-it, cuyo valor puede
salir en sus resultados. Esa arquitectura no cumple observación segura de un
documento y **no se conecta** al IPC nuevo. Los bytes de ese módulo y los
de `browser/ipc_worker.py` quedan intactos.

Se reutilizan el worker `browser.ipc_server`, el protocolo AF_UNIX/peer,
el único presupuesto de operación, el STOP y la rutina de cierre Chromium
acotado que ya usa la fixture R177. Se añade sólo un adaptador
`browser.site_observer.SiteReadOnlyExecutor`, no otro bot transaccional.

## Contrato nuevo, desactivado por defecto

1. `BOCA_BROWSER_OBSERVE_MODE=site-readonly` crea un único observer con el
   `SITE_URL` verificado del volumen Boca leído al arrancar. `off` continúa
   con `OfflineNoGoExecutor`; `offline-fixture` continúa con el DOM inventado.
   Modos y factories incompatibles fallan cerrado.
2. La llamada nueva `UnixSyntheticBrowser.probe_site_readonly()` emite sólo
   el frame fijo `PROBE_SITE`; no incluye URL, socio, credencial ni token.
   Responde exactamente `site_http_ok` (código HTTP 2xx) o
   `site_http_non_ok` (3xx–5xx). Transporte, timeout, cancelación, respuesta
   inválida o falta de activación producen `NO_GO`/error redactado.
3. En modo site-only, la orden transaccional anterior `REQUEST` y la fixture
   `PROBE_FIXTURE` **siempre son NO_GO**; no ejecutan navegador. Un resultado
   de observación nunca se interpreta como `RESERVED_IN_SIMULATOR`, compra,
   token de cola ni aceptación de una reserva.
4. El adaptador lanza sólo un Chromium ordinario con `chromium_sandbox=true`,
   User-Agent nativo y sin stealth. JavaScript, service workers y descargas
   están deshabilitados; TLS valida certificados. Se registra el filtro de
   rutas ANTES de abrir una página; deja salir un único GET `document` a
   la URL exacta autorizada (normaliza únicamente la barra final de raíz).
   POST/PUT, recargas, subrecursos y redirects quedan abortados. Nunca se
   consulta `context.cookies()`, DOM de tokens, headers ni cuerpos para
   publicarlos; el único metadato observado es la categoría HTTP.
5. START/STOP siguen bajo la autorización de host existente; el cierre
   cancela activas, verifica cierre de contexto y navegador. Un teardown
   indeterminado envenena el worker y no permite respuesta positiva tardía.
   La actividad Chromium conserva sólo etiquetas verdaderas de
   lanzamiento/contexto/cierre; se evita `page_ready` porque su texto actual
   dice incorrectamente «página sintética».

**Límite conceptual:** GET no garantiza ausencia absoluta de efectos en un
servidor mal diseñado. El dueño debe elegir un sandbox; este código no
certifica que el DNS de una URL pública señale efectivamente a un sandbox.

## Verificación local sin red

- Base reconciliada antes de editar: `origin/main` = `ce77979` (R178).
- TDD: primero fallaron 7 casos por falta de `PROBE_SITE`, frames, statuses
  y observer; después quedaron verdes las pruebas con puertos falsos.
- **Suite completa:** `uv run --frozen pytest -q -n 4 --tb=line` =
  **6959 passed, 1 skipped, 34 subtests passed, 0 failed (46,68 s)**.
  Único SKIP AF_UNIX kernel EPERM local; no es aprobación del socket físico.
- Ruff check/format de seis archivos modificados, mypy de cuatro módulos
  del browser y `scripts/check_repo_policy.py` = PASS CODE_ONLY.
- Tests `tests/test_r179_site_observer.py` y
  `tests/test_r179_site_observer_ipc.py` usan páginas/transportes/motores
  artificiales; ningún request externo se origina. Incluyen ruta exacta,
  rechazo de POST, redirects, subrecursos y reintentos; opciones honestas
  del navegador, estados HTTP, URL inválida, timeout, STOP y cierre incierto.
- La suite de IPC anterior también se ejecuta para que `REQUEST`/fixture
  mantengan sus contratos. AF_UNIX real y Chrome real quedan para Actions.

## Integración física pendiente R180 (no llamar GREEN todavía)

1. Reconciliar SHA/imagen dual y probar primero la instalación protegida
   del nuevo par Boca sin tocar Porota. Certificar UID10002, IPC AF_UNIX,
   SITE_URL volume/inodes y egress desde el worker en marcha.
2. Autorizar explícitamente un modo `site-readonly` sólo en configuración
   del worker Boca después de revisar allowlists de Compose, host y contrato
   de release; hoy el overlay normal **no contiene** ese flag, por diseño.
3. Añadir una acción owner autenticada, distinta de `/comandos` y de cualquier
   reserva, que invoque `probe_site_readonly()` sólo después de START vigente,
   permita leer el estado categórico y respete STOP. El método cliente existe
   pero **no está conectado al panel/host** por esta rama.
4. Hacer una prueba física con una URL sandbox propia y autorizada, nunca
   contra el sitio productivo de socios: observar un único GET y su categoría
   en recibos sin URL, tokens ni credenciales; STOP posterior. Registrar
   evidencia de SHA, timestamp, CID y browser real.
5. No declarar que el sistema obtiene tokens, sortea colas, reserva o compra:
   **ninguna** de esas capacidades pertenece a este adaptador.
