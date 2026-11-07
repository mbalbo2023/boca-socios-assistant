# R110 — Evidencia tipada de salud del worker V3

**Motivo.** Cutover físico #42418718190 concluyó `PREPARE_WORKER/HEALTH` sin
permitir distinguir arranque, salud, timeout o postflight. La observación
READ_ONLY #42420135614 acreditó controlador histórico RUNNING y worker ausente;
el preflight rootless #42420515286 fue verde pero expresamente no ejecuta
`ipc_worker`. Ninguno prueba la causa del fallo del proceso propietario.

**Objetivo.** Que un siguiente fallo, si ocurre, conserve una categoría segura
y suficientemente específica para orientar un RCA sin leer código de la caja
negra ni publicar stdout, stderr, secretos, rutas o IDs adicionales.

**Decisión.** Extender el enum existente `worker_primary_phase` — no agregar
workflow, nueva operación o recibo — con `HEALTH_WAIT`, `HEALTH_EXITED`,
`HEALTH_UNHEALTHY`, `HEALTH_TIMEOUT`, `HEALTH_POSTFLIGHT`. Mantener `HEALTH`
para recibos históricos. El reloj de salud sigue acotado a 90 s; la compensación
selectiva y el terminal NO_GO siguen sin retries. Los otros operadores sólo
reciben excepciones compatibles con `PreflightError`.

**Alternativas descartadas.** Aumentar el timeout o relajar aislamiento sin
evidencia; imprimir logs crudos de un proceso propietario; abrir otro flujo de
despliegue. Todas arriesgan repetir intentos o cambiar límites aprobados.

**No objetivos.** No corregir a ciegas el programa propietario; no activar
navegación real, tickets, Telegram o un nuevo servicio; no tocar Porota ni
contenedores ajenos. Un recibo más preciso no prueba por sí solo instalación.

**Aceptación.** Pruebas deterministas para las categorías y compensación; el
formato del terminal v1/v2 y el analizador de GitHub conservan rechazo de
categorías inválidas, duplicados y cualquier dato libre. Commit exacto,
revisión, CI y publicación de imágenes antes de un nuevo intento físico.
