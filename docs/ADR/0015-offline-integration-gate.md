# ADR 0015: Puertos integrados y límite de la observación real

Status: Proposed, 2026-10-28. Issue #24.

## Decisión

`OfflineSimulation` conecta los puertos integrados por #20, #21, #22 y
#26, sin agregarlos al runtime del controlador. Valida sesión e identidad
antes de adelantar el reloj compartido y exige una admisión sintética vigente
para el mismo evento. Rechaza tiempos de notificación no finitos o negativos
antes de usar DB o navegador. `Database.request_ticket` conserva la única
fila de cantidad 1. Después de una pantalla de prueba satisfactoria se
encola un aviso estático con UUID derivado del ID opaco de solicitud; no
incluye ID de socio/evento, correo, contraseña, URL, cookie ni token.
Finalizar la cola cierra **sólo** la observación local. La fila de DB
conserva `planned`.

Un fallo de navegador deja el intento local recuperable y no emite aviso de
éxito. Un reintento posterior recupera el mismo ID de solicitud. El outbox
en memoria pierde mensajes tras reinicio y no comparte transacción con la
base: no se promete entrega exactamente una vez ni atomicidad global.

## Frontera con Boca

La vista pública real mostró únicamente el formulario de inicio de sesión.
No se codifica un orden obligatorio entre login/cola, un selector de partido,
ni una confirmación inferida de la pantalla ficticia. El usuario priorizó la
web real: la navegación fake permanece sólo como prueba unitaria de contratos
y **no** sirve como gate de reserva. El adaptador real requeriría un único
socio consentido, revisión técnica por agente y gates específicos de seguridad,
política de uso y reconciliación de resultado ambiguo. Un diagnóstico público
de fuente por Actions es informativo y no bloquea por sí solo el despliegue
seguro de componentes de simulación, conforme a ADR 0038 y 0040.

## Alternativas y consecuencia

Se evita conectar directamente el controlador a Playwright o Telegram sin
autenticación, presupuesto y datos de sitio verificados. Una observación
anónima de la portada puede probar accesibilidad del login, pero no la
reserva. Un contrato local no garantiza idempotencia en el checkout ajeno.
