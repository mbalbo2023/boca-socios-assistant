# ADR 0062: BETA operativa autorizada, continuidad y parada final

**Estado:** Accepted on merge; autorización del dueño ya vigente en
[#45, recibo6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326).
Issue documental #154. Este documento registra la instrucción, no acredita
que la aplicación, el Site conectado o Telegram ya estén desplegados.

## Cambio respecto de la etapa anterior

El dueño autoriza continuar autónomamente hasta desplegar y validar la BETA
operativa en el droplet, conectar el Site existente y completar Telegram y
todas las funciones documentadas. Reemplaza la reserva de otro GO genérico
para decisiones de implementación, infraestructura/acceso, release e instalación
de ADR0055/0056 dentro de este alcance. Las decisiones concretas se documentan,
se prueban y se revisan; no se vuelve a pedir el mismo permiso. La autoridad no
se extiende a otros proyectos ni a efectos externos expresamente excluidos.

La aplicación y UI deben estar conectadas y demostrar alta/consulta/ciclo de
credenciales, eventos/sesiones/límites, comandos y estado durable, avisos y
Telegram, diagnóstico/trazabilidad e integración Site→sistema. La matriz del
[plan](../BETA_DELIVERY_PLAN.md) conserva todos los requisitos y cada evidencia;
no sustituir aceptación con maqueta, mocks o cobertura de código. Lo todavía
no definido se explicita; no inventar modalidades comerciales ni nuevas cuentas.

El Site existente es privado del dueño y su audiencia se conserva. Dentro de
la autoridad delegada, el integrador eligió autenticación ChatGPT del Site sin
passkey adicional y un puente saliente HTTPS a un buzón temporal cifrado
RSA-OAEP + AES-GCM. Es diseño elegido pendiente de implementación/revisión y
prueba; no un canal operativo. SQLite del droplet sigue canónica. SQLite/clave/socket/SSH
siguen exclusivos del backend Boca; no acceso directo del Site al archivo DB.
Los módulos concretos registran permisos, transporte, expiración, idempotencia,
redacción, fallos, límites y prueba de acceso denegado antes de activarse.

## Navegación designada y límites

Login y navegación real de testing están autorizados únicamente para la cuenta
designada en el adjunto privado del dueño. No transcribir identificadores ni
credenciales a GitHub. Conservar la bóveda cifrada existente y clave externa;
la custodia temporal autorizada no implica backup ni datos en plaintext.
Los tests automatizados siguen usando datos sintéticos. La evidencia de
navegación real se captura/redacta en canal privado; no subir screenshots de
la sesión autenticada, cookies, URLs sensibles, HAR ni datos personales al repo
público. En GitHub sólo recibos sanitizados y referencias sin capacidad de acceso.

**No confirmar reservas, comprar ni modificar la cuenta Boca.** Esos efectos
siguen simulados y deben distinguirse de navegación real. No usar otras cuentas,
eludir CAPTCHA/WAF/colas ni probar acceso no autorizado. Un bloqueo externo se
registra sin reintentar ciegamente ni presentar una pantalla falsa como evidencia.
Una intención/cantidad1 por socio/evento sigue siendo invariante; varias sesiones
no demuestran ni habilitan posiciones Queue-it independientes.

## Instalación, datos y parada obligatoria

PR/revisión/CI/scan sobre SHA exacto, imágenes inmutables, procedencia,
aislamiento y presupuesto de recursos siguen siendo gates. Sólo el operador
coordinado usa el workflow protegido Boca; merges y operaciones host seriales.
Nunca repetir primera preparación #120 ni un run fallido. Datos encontrados
se preservan e identifican; no reemplazar una DB ni usar first-install como
upgrade por inferencia. El destino lógico sigue `/data/boca.sqlite3` en
`boca-socios_boca_data`, clave separada; ubicación global previa UNVERIFIED.

Después de las pruebas, incluso si la aceptación falla, detener y verificar
todos los servicios, contenedores, workers, Chromium, puentes y daemon dedicado
Boca usados para la prueba. Implementar/probar el procedimiento acotado de stop
antes de activar la prueba; no afirmar que hoy ya existe. Preservar datos,
claves y configuración; no borrar para conseguir una marca verde. La evidencia
debe distinguir recurso detenido de desconocido y comprobar que no quedó otro
proceso propio ejecutándose o reactivándolo. Si la verificación falla, la fase
STOP queda BLOCKED, con acción de recuperación inmediata, nunca DONE.

El Site muestra última observación, fecha/origen y backend detenido; no finge
disponibilidad ni éxito para nuevos comandos. Backup/restore permanece diferido
hasta versión productiva fiable. Porota/PPI Watch intocables.

## Recuperación y mantenimiento

[RESUME_PROCEDURE](../RESUME_PROCEDURE.md) define checkpoints antes y después
de cada fase/PR/ejecución, estados RUNNING/DONE/BLOCKED, SHA/branch/paths/owner,
evidencia sanitizada, decisiones y siguiente acción idempotente. Una nueva
sesión con «continúa» debe poder retomar desde #45 y su checkpoint anterior,
revalidando antes de efectos y evitando duplicar operaciones. No se promete
supervisor nocturno, actualización automática ni ejecución si la sesión termina.

Al iniciar: main213be4903669c6e88122a536ad8fee6785c997ac, documentos de #153
integrados, 699 pruebas+29 subtests en su checkpoint; último recibo host #120
SERVICE_READY sobre6be606, sin app/DB instalada por esa operación. Es un corte
histórico preciso, no evidencia de nueva entrega ni STOP final. Los receipts
posteriores sustituyen sólo los hechos que realmente vuelvan a comprobar.
