# ADR 0119 — Entrada privada y de un solo uso para piloto en Chrome del host

**Fecha:** 2026-11-03 ART. **Issue:** [#285](https://github.com/mbalbo2023/boca-socios-assistant/issues/285). **Estado:** código candidato **inerte**, sin listener ni Chrome conectado.

## Evidencia real y obstáculo

- [Run #347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167): Google Chrome Stable localizado bajo UID 10001 en el droplet.
- [Run #350](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41658478693): ese Chrome físico renderizó el formulario público; `FORM_VISIBLE cleanup=VERIFIED`. No hubo usuario, contraseña ni ingreso.
- En **Cloud Browser de ChatGPT**, separado del Chrome del droplet, el sitio oficial redirigió la pestaña de login a una **prefila Queue-it real** de Boca vs. Defensa y Justicia (partido 07/11/2026). La propia página indica apertura de fila a las **13:00 ART**; la portada Boca Socios anuncia venta prioritaria desde las **14:00 ART**. No se probó autenticación de Fernando ni lugar asignado. La sesión original se conservó, sin duplicar ni manipular posiciones; no se publica el identificador/URL de fila.
- [Run #345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41653887958) de red rootless alternativa ICC=true: `NO_GO unclassified` en el workflow, limpieza `VERIFIED`; no hay BETA instalada. El piloto del host debe ser independiente y no modificar Docker/otros servicios.

## Decisión de código, no de despliegue

`src/boca_socios/host_pilot_intake.py` agrega un **WSGI sin listener** y una interfaz `LoginDriver` inyectable. Sólo acepta origen exacto `http://localhost:8443` y petición por loopback, expone HTML accesible en `/piloto` y JS del mismo origen. La futura URL privada usaría un token aleatorio de **32 bytes en el fragmento** `#key=…`; el JavaScript lo borra de la barra antes de enviar. El servidor sólo recibe un SHA-256 de ese token como parámetro de arranque; nunca el bearer en un input de Actions. Una solicitud POST desde el origen fijo puede consumir el derecho **una vez**, con caducidad máxima de quince minutos, tamaño y campos acotados, y pasa usuario/contraseña únicamente al driver en memoria. Respuestas estandarizadas sin eco de credenciales. No hay cookies persistentes ni almacenamiento en la DB en este componente.

Si el driver no está configurado, el POST responde `UNKNOWN` y 503, sin registrar credenciales. Aunque un driver reportara `AUTHENTICATED` en un test, **no es evidencia de sesión real**: un adaptador futuro deberá establecer el estado por una señal positiva del sitio oficial, conservar el mismo contexto de fila autorizado y detenerse ante challenge. El alcance actual no inicia Chrome, no tiene servidor HTTP, no instala nada, no envía credenciales, no entra a la cola, no reserva y no compra.

## Riesgos y gates pendientes

1. Implementar y probar el driver real de Chrome del host, limitado a una cuenta y a navegación legítima, sin `--no-sandbox`, sin extracción de tokens, ni evasión de CAPTCHA/WAF/fila. Es necesario diferenciar login verdadero, prefila y errores.
2. Implementar envoltorio de servidor temporal UID10001, loopback 8443 sólo si el puerto está libre, operación en el workflow manual protegido existente, validación de SHA y limpieza en ese mismo run. **No** crear otro workflow de deploy, servicio permanente, systemd, cron ni puerto adicional.
3. Acordar la **entrega privada del bearer** fuera de GitHub, chat, logs y Actions; el hash no funciona como contraseña. El owner utilizará Termius SSH + Chrome de tablet con un solo enlace. Sin entrega comprobable, el piloto permanece NO_GO.
4. Validar una sesión real, una sola credencial, una sola entrada y resultado de cola, con pruebas de contención e idempotencia. No confundir CI sintético ni Chrome público con autenticación.

Las pruebas de esta etapa usan valores `.invalid`; no hay red, credenciales personales, dominio externo ni host side effect. Actualizar evidencia exacta de PR/SHA/checks en el issue #285 y el checkpoint #45 tras CI; no promover un candidato a instalación antes de revisión.
