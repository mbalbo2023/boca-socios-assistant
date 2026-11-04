# ADR0133 — Admisión local gobernada por el dueño y retiro de Site (04/11/2026)

Estado: **DRAFT**, propuesta de #313; no representa un merge, cambio físico ni despliegue.

## Motivo y autoridad

El dueño confirmó desde Samsung Chrome, mediante Termius y el controlador privado
`127.0.0.1:8443`, que su passkey funciona. Autorizó explícitamente controlar el
bot desde el panel y retirar la referencia al Site complementario. Rechazó las
sesiones múltiples, la rotación/eliminación total de la clave maestra, la
navegación real de login/fila/elegibilidad/reserva/compra y cualquier backup.
El controlador instalado es **controller-only**; el browser/worker aún no tiene
un cutover físico validado. Por eso una pausa de admisión no debe llamarse
«detener bot» ni atribuirse la detención efectiva de procesos o trabajos.

## Decisión de alcance exacto

1. El panel presenta «Pausar/Reanudar nuevas simulaciones» en `/control`, con
   un estado consultable por el dueño autenticado, un mensaje accesible del
   alcance exacto y enlaces para detener individualmente simulaciones existentes.
2. Los cambios son **sólo de admisión de nuevos comandos sintéticos** del
   controlador local. No detienen el servidor HTTP, la sesión del dueño,
   Telegram, Chromium, Docker ni trabajos ya iniciados. Un `POST` de parada
   individual `/comandos/{id}/detener` conserva su ruta existente.
3. La transición exige `simulation:write`, sesión de dueño, origen exacto,
   CSRF, UUID de operación y deduplicación/fingerprint del comando. Un candado
   local ordena inicio de comando frente a transición en el mismo proceso.
4. La decisión queda durable en `audit_events` del esquema SQLite **0001
   existente** mediante acciones independientes
   `owner_simulation_intake_resumed` y `owner_simulation_intake_paused`.
   `ORDER BY rowid DESC` obtiene la última; `BEGIN IMMEDIATE` serializa las
   transiciones; repetir la misma decisión no agrega evento. No hay nueva
   tabla, migración ni modificación a otras familias de eventos. Si no existe
   una decisión, la admisión está **PAUSADA**. Si falla la lectura, el comienzo
   se niega con **503**, sin atribuir un estado desconocido.
5. Los nuevos comandos consultan la decisión registrada antes de ingresar
   al host. Los comandos sintéticos admitidos pueden terminar o detenerse
   individualmente; ningún control cancela automáticamente trabajo en curso.
6. Se elimina del panel el ítem Site complementario **sin modificar recursos
   externos**. Las funciones declinadas figuran fuera de alcance, nunca como
   tareas abiertas; backup queda expresamente excluido.

## Límites reales — NO_GO que no se debe maquillar

- **Iniciar/Detener Bot integral** exige implementación y evidencia de cutover
  browser/worker con señal de `stop` al worker, confirmación observable de cese,
  congelación de nuevos trabajos y recuperación segura. Es trabajo aparte y
  sigue **NO_GO**, no sustituido por este botón.
- SQLite conserva estados entre reinicios, pero el candado de admisión es
  intra-proceso. Una combinación de varios controladores simultáneos o
  carreras entre procesos distintos requiere orquestación única de worker y
  handshake; la persistencia no se debe interpretar como ack de parada global.
- El servidor nunca ejecuta tráfico real a Boca en esta operación. Se conserva
  `synthetic.py` y `ipc_worker.py` como BLACKBOX intocables, sin tocar sus
  imports, código o pruebas.
- No hay merge, deploy, dispatch de Actions, cambios de host ni autorización
  implícita a habilitar navegación real.

## Evidencia exigida

- Tests de primera admisión pausada, reanudación, pausa, acceso al panel y
  detalle de comandos mientras está pausado, lectura persistida tras
  reinstanciar el controlador, idempotencia sin escrituras repetidas, negativa
  con host averiado, origen/CSRF inválido y falta de sesión.
- Los casos de aceptación HTTP y la sonda sintética de host antes arrancaban
  comandos inmediatamente después del passkey. Sus expectativas cambian de
  forma explícita: primero esperan HTTP **409** bajo admisión pausada, después
  hacen **POST de reanudación autenticado**, esperan la cuota de escritura de
  sesión, comprueban simulación/historial y finalmente **pausan otra vez**.
  No se omiten tests ni se desactivan gates por esta transición.
- Ruff, formato, MyPy, pytest y política de repositorio deben pasar con SHA
  exacto de PR DRAFT; conservar evidencia en #313 y checkpoint canónico #45
  conforme a regla 84.
- Sólo un cutover físico posterior, autorizado y medido, puede cerrar el
  faltante de Iniciar/Detener Bot real. El botón de admisión no autoriza a
  afirmar que el bot completo está operativo.
