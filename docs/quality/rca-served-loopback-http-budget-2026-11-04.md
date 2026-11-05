# RCA #331 — timeout del cliente HTTP de aceptación sintética

**Fecha de análisis:** 2026-11-04 ART. **Alcance:** pruebas offline de
`tests/test_beta_served_acceptance.py`, sin efecto sobre BETA operativa,
Chromium, Telegram ni droplet.

## Síntoma y evidencia que no se debe confundir

- Durante A45-R17, la suite local de aproximadamente 3062 tests arrojó
  fallos intermitentes `TimeoutError` del **cliente** HTTP al leer respuesta
  (`http.client.HTTPConnection.getresponse`), principalmente en los tests de
  navegador sintético fallido y recuperación tras reinicio. Un intento
  aislado del caso fallido pasó; una ejecución del módulo completo desplazó
  el fallo a otro escenario, y otro subset de 39 tests con los tests previos
  pasó por completo. Una suite local completa adicional **sin corrección**
  tuvo 3062 PASS + 34 subtests. Esta variabilidad impide atribuir el timeout
  a un defecto específico del adaptador o de la persistencia por sí sola.
- El cliente de `_request` esperaba como máximo **3 segundos**, mientras
  `BetaCommandHost._submit` conserva un presupuesto de respuesta **5 segundos**
  (`integration/command_host.py`) y las conexiones SQLite del controlador
  tienen `busy_timeout=5000`. La WSGI de aceptación es monohilo; ADR0069 ya
  registra las limitaciones de simultaneidad. El timeout del **fixture** era
  menor que una operación permitida por el contrato de servidor.

## Reproducción determinista RED → GREEN

Se agregó `test_loopback_http_fixture_waits_for_bounded_synthetic_backend_latency`
al mismo test de aceptación. Utiliza únicamente un servidor WSGI descartable
en `127.0.0.1` y una respuesta sintética deliberadamente diferida **3,25 s**,
por debajo del límite de petición de 5 s; no usa browser ni Boca real.

1. Con `HTTPConnection(timeout=3)`, el nuevo test **FALLÓ** en
   `socket.recv_into` → `getresponse`, tras 3,55 s totales. Es exactamente la
   clase de error de los fallos intermitentes de la suite completa.
2. Se cambió **sólo el timeout del cliente de este archivo de pruebas** a
   **8 s**, dejando intactos los timeouts productivos, el servidor, SQLite y
   los límites de polling de estados de cada caso. El mismo test pasó en
   4,12 s, con respuesta HTTP 200 y bytes exactos.

Este test reproduce la **insuficiencia del presupuesto del cliente** de
forma concluyente; no demuestra que todos los timeouts previos tuvieran una
única causa interna. Si reaparecen con los 8 s, hay que preservar traza de
la ruta concreta y revisar bloqueo de servidor/SQLite/host de comandos como
incidente separado, no volver a ampliar el tiempo de espera a ciegas.

## Decisión acotada, gates y límites

- Mantener el servidor WSGI en su contrato existente, la transacción y la
  protección contra replay en el código productivo, el browser BLACKBOX y la
  política de cero tráfico real. No se cambia ninguna seguridad/operación.
- Aceptar 8 s sólo para el cliente HTTP del harness, para permitir el
  presupuesto del backend de 5 s más sobrecarga SQLite/planificación local,
  manteniendo un límite finito. Los tests de resultado siguen exigiendo
  confirmación `completed`, `failed` o `stopped` con deadline propio de 3 s
  una vez recibida la respuesta de admisión.
- Antes de fusionar, exigir full pytest, Ruff/formato, MyPy/policy y hosted CI
  del SHA final, más comparación de diferencias limitada al fixture y este
  RCA. No sustituir un CI rojo por evidencia local. Se mantiene el único
  candidato integral #319, sin merge/deploy individual ni operaciones host.

Referencia de continuidad: issue #45 y [#331](https://github.com/mbalbo2023/boca-socios-assistant/issues/331).
