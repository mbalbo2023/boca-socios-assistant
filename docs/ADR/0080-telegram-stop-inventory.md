# ADR 0080: reconocimiento seguro del worker Telegram al detener pruebas

**Estado:** integrada por PR #194 en
`451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`; candidato
`ba5f8b4cc42c47dc279a95222c6fff3b4d30748b`, CI 41275762284,
scan 41275762308, release/deploy 41275762296/41275762254 y revisión
5726581135. No hubo dispatch host con este cambio.
Fecha de diseño: 2026-11-01 (America/Argentina/Buenos_Aires).

## Decisión y verificación previa al efecto

El `stop-test` protegido de ADR0067 usa el daemon rootless dedicado, compara
el contador global con el inventario completo de hasta 12 contenedores y
valida todos antes de detener cualquiera. Se incorpora el servicio opcional
`telegram` de ADR0078 sin cambiar el reconocimiento histórico de `controller`,
`browser` o `proxy`. Para `telegram` exige además:

- proyecto Compose exactamente `boca-socios`, servicio `telegram`, número `1`
  y nombre `/boca-socios-telegram-1`, con ID íntegro del contenedor;
- usuario `10001:10001` y comando exacto
  `python -m boca_socios.notify.telegram_worker serve`;
- `Config.Image` como digest inmutable del repositorio único
  `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:<64 hex>` y `Image` como ID
  local `sha256:<64 hex>`;
- inspección **local y read-only** de ese ID: `Id` igual al del contenedor,
  `RepoDigests` incluye el mismo ref y la etiqueta de revisión SHA40 de la
  imagen coincide con la etiqueta heredada por el contenedor.

Si falta o contradice cualquiera de esos campos, si falla la inspección de la
imagen o existe otro contenedor desconocido en el mismo inventario, se informa
`unknown_container_preserved_no_stop` **antes del primer `docker stop`**. Un
contenedor conocido y en marcha no se detiene por adelantado cuando otro es
incierto. Se conserva la inspección posterior de todos los IDs y del contador
antes de parar el daemon. No hay pull, creación, eliminación, prune, migración
ni acceso al daemon rootful; datos, claves y volúmenes permanecen.

Esta identidad local reconoce sólo una imagen asociada a un digest del repo
Boca y a su revisión estampada; no prueba por sí misma que ese digest haya
pasado un release protegido o que el contenedor se haya instalado conforme a
un candidato aprobado. La activación futura debe demostrar esa procedencia,
los límites efectivos, origen de DB, red y custodia separadamente. El timeout
actual de `docker stop` es diez segundos; si el proceso termina forzadamente
durante una llamada de red, el marcador Telegram `prepared` sigue incierto y
no puede reenviarse automáticamente. Un gate de activación debe revisar su
plazo de parada y verificar que todos los servicios Boca queden detenidos.

## Evidencia y límites

La prueba de aceptación falló antes del cambio al rechazar `telegram`. La
regresión sintética cubre un controller conocido junto a un Telegram válido,
los campos de identidad falsos, digest/ID/revisión discordantes, fallo de
inspección de imagen y un desconocido después de un Telegram válido: ninguno
se detiene en un inventario incierto. RCA-192 conserva los selectores
ejecutados. CI/scan/revisión y SHA exactos se registran en PR #194. Son pruebas
con respuestas Docker falsas, no
evidencia de parada host ni de Telegram operativo. El último `stop-test`
protegido observado #156/41272785626 precede a este cambio y no valida su
nueva ruta. No se despachó ninguna operación, no hubo bot/destino ni envío real.
La documentación de estado/checkpoint la actualiza el escritor central al
integrar la evidencia conforme a la regla 84.
