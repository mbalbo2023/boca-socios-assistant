# ADR 0015: Puertos integrados y límite de la observación real

Status: Proposed, 2026-10-28. Issue #24.

## Decisión

`OfflineSimulation` conecta los puertos ya propuestos en #20, #21, #22 y
#26, sin agregarlos al runtime del controlador. Exige una admisión sintética
vigente y de la misma identidad/evento. `Database.request_ticket` conserva
la única fila de cantidad 1. Después de una pantalla de prueba satisfactoria
se encola un aviso estático con UUID derivado del ID opaco de solicitud; no
incluye correo, contraseña, URL, cookie ni token. Finalizar la cola cierra
**sólo** la observación local. La fila de DB conserva `planned`.

Un fallo de navegador deja el intento local recuperable y no emite aviso de
éxito. Un reintento posterior recupera el mismo ID de solicitud. El outbox
en memoria pierde mensajes tras reinicio y no comparte transacción con la
base: no se promete entrega exactamente una vez ni atomicidad global.

## Frontera con Boca

La vista pública real mostró únicamente el formulario de inicio de sesión.
No se codifica un orden obligatorio entre login/cola, un selector de partido,
ni una confirmación inferida de la pantalla ficticia. El usuario priorizó la
web real: la navegación fake permanece sólo como prueba unitaria de contratos
y **no** sirve como gate de reserva. El adaptador real requiere aprobación
independiente, un único socio consentido, política de uso validada, manejo
humano de desafíos y reconciliación de resultado ambiguo antes de operar.

## Alternativas y consecuencia

Se evita conectar directamente el controlador a Playwright o Telegram sin
autenticación, presupuesto y datos de sitio verificados. Una observación
anónima de la portada puede probar accesibilidad del login, pero no la
reserva. Un contrato local no garantiza idempotencia en el checkout ajeno.
