# ADR 0141 — Consulta privada de avisos oficiales observados

Fecha: 2026-11-04 ART  
Estado: **DRAFT / solamente código y pruebas / no desplegado**  
Alcance autorizado: opción #3 del propietario, issue #314, candidata integral #319.

## Decisión

El panel privado de Boca expone dos rutas **GET de solo lectura**, con la
misma autenticación de passkey/cookie y permiso `local-status:read`:

- `/avisos-oficiales`: sección HTML accesible, con enlace en la navegación y
  la portada del panel Samsung/Voice Access.
- `/avisos-oficiales.json`: proyección JSON con `live_feed=false`,
  `availability_verified=false` y `actionable=false`.

Ambas usan exclusivamente las funciones puras y acotadas de
`events.official_catalog` / `events.official_presentation` (#314). Los
`OfficialNotice` son inyectados explícitamente al construir la aplicación;
por defecto no hay ninguno. El panel **no navega Boca, no busca fuentes en
vivo, no agrega horarios inventados y no deduce elegibilidad o entradas**. Sin
un recibo oficial preobservado válido muestra «No hay avisos oficiales
observados cargados» y conserva la distinción entre publicado, observado y
verificado.

Las rutas no se conectan con `/comandos`, `TicketIntent`, los eventos
sintéticos ni la admisión de simulaciones. No tienen acciones POST; el control
de admisión permanece independiente. Sus respuestas usan `no-store`, CSP y
sesión privada, sin datos de socios, tokens ni WebAuthn en el documento JSON.

## Evidencia y límites

- Tests de autenticación, rutas GET, JSON vacío/non-actionable, HTML con
  escapado de títulos sintéticos, denegación POST y cero llamadas al host de
  comandos. No se visitan fuentes reales en pruebas.
- El catálogo #314 ya tiene sus checks y un límite de 20 observaciones; su
  contrato detecta el elemento 21 sin consumir un iterador infinito.
- Es una integración de **presentación offline**, no un feed oficial activo,
  prueba de vigencia del aviso ni permiso para navegación real. No se cerrará
  el pendiente de datos externos sin fuente/recibo autorizado y comprobado.
- El controller físico en `127.0.0.1:8443` sigue con el SHA histórico
  `cabce9f1e452e63ded115f447559a358dc0f4d1b`. Este código requiere
  PR DRAFT, CI exacta y posterior operación protegida con recibo independiente;
  no se hizo merge, instalación ni cambio en el host.

Quedan fuera los módulos BLACKBOX `synthetic.py` e `ipc_worker.py`, el
login/fila/reserva/compra de Boca, backups, Site y otros servicios del droplet.

## Incremento R11 — lectura de snapshot local sin vincular comandos

La candidata de integración agrega un callback de observaciones oficiales
**sólo en las dos rutas GET autenticadas**. La vista original con catálogo
inyectado en pruebas conserva su comportamiento; en el servidor de BETA el
callback podrá leer un snapshot JSONL acotado en el **volumen Boca existente**,
con el contrato de validación del issue #314. La lectura se repite al solicitar
la vista, sin reiniciar el controlador, sin red, sin base SQLite, sin crear
archivos ni alterar la sesión del dueño. No existe un feed automático ni una
herramienta aprobada para poblar el archivo físico todavía.

- Archivo ausente: vista vacía con aviso explícito de que no hay observaciones.
- Archivo presente válido: sólo información `SOURCE_OBSERVED_UNVERIFIED`,
  `actionable=false`, sin generar `TicketIntent` ni activar el bot.
- Snapshot inválido/inseguro: **503 únicamente** en `/avisos-oficiales` y
  `/avisos-oficiales.json`, con respuesta redactada y sin datos privados. La
  portada, socios, control y simulación siguen disponibles; una fuente externa
  degradada no se convierte en stopper de la BETA de simulación.
- Sin credenciales, token Telegram, navegación Boca/Queue-it, URLs arbitrarias,
  puertos o cambios en otros servicios/volúmenes.

El loader independiente y su QA exact-SHA pertenecen a PR DRAFT #316; la
inyección HTTP/runtime y las regresiones de aislamiento son alcance de PR
DRAFT #319. Ambos deben pasar sus propias Actions y la integración completa
antes de cualquier promoción. En particular, el código no acredita que exista
el snapshot ni que el dueño esté viendo avisos reales; documentar esa evidencia
por separado tras una carga protegida y verificada.
