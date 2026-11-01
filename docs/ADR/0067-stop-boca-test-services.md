# ADR 0067: parada verificable de servicios de prueba Boca

**Estado:** aceptada; PR #165 integrado en
`1441d55a632d4a545b21ee7f6f2b0a4140ab2320`. Su ejecución protegida
#156/41272785626 se registra abajo.

## Decisión y frontera

El dueño ordenó detener los servicios y contenedores Boca al terminar las
pruebas, conservando datos y claves. La preparación rootless #120 dejó
`docker.service` dedicado activo, sin aplicación instalada. `stop-test` se
incorpora al **mismo** workflow manual protegido `boca-first-deploy.yml`.
Comparte mutex fijo, actor dueño, `main` exacto, ambiente, SSH con clave de
host fijada y `BOCA_DEPLOY_ENV_READY=ready`; no exige digest ni release para
detener. Revalida `main` inmediatamente antes del efecto. No hay segundo
canal de acceso al host.

El helper transmite sólo el SHA y un recibo acotado. Valida UID/GID dedicados,
directorios/socket privados, ausencia de acceso al socket rootful, contenido
y permisos exactos de su unidad/configuración sin seguir symlinks, y unidad
efectiva sin drop-ins. Si ya está inactiva con PID cero y socket ausente,
informa `ALREADY_STOPPED` sin iniciar Docker.

Si está activa, verifica socket y daemon rootless, cgroup v2/systemd,
overlay2 y raíz de datos propia. Compara el contador global de contenedores
del daemon dedicado con el inventario completo y acotado (máximo 12). Cada
contenedor debe tener ID íntegro, nombre y labels Compose exactos del proyecto
`boca-socios` y servicio `controller`, `browser` o `proxy`. Cualquier identidad
desconocida bloquea la parada **antes** del primer efecto. Sólo los IDs
positivamente reconocidos y en ejecución reciben `docker stop`; se verifica
que todos quedaron detenidos y que el inventario no ganó otros IDs. Luego
detiene únicamente el `docker.service`
del usuario dedicado y comprueba unidad inactiva, PID cero y socket ausente.

## Fallo, límites y verificación

Un error de inventario, parada o verificación conserva el estado como NO_GO;
no se afirma éxito parcial. No se borran contenedores, imágenes, volúmenes,
redes, unidad, configuración, enablement, SQLite, clave o backups. No se
aplican `prune`, sudo, daemon compartido ni comandos host desde shell local.
El enablement existente permanece: un reinicio futuro del usuario/host podría
iniciar otra vez el daemon y necesitar nueva inspección. El recibo STOPPED no
demuestra persistencia futura, entrega Telegram ni disponibilidad de BETA.
La nueva consulta de inventario reduce pero no elimina una carrera con otro
actor que cree contenedores entre la consulta final y `systemctl stop`; el
mutex de host Boca y la exclusividad del daemon siguen siendo necesarios.

Pruebas sintéticas cubren contenedor desconocido y conteo inconsistente antes
de efectos, transporte rootless falso, contenedores reconocidos, fallo de
stop, daemon sólo, idempotencia, symlink de configuración y gate manual con
coordenadas vacías. El [run protegido #156/41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626),
attempt 1, sobre `main` `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163`
terminó SUCCESS y emitió
`BOCA_STOP_TEST state=STOPPED ... containers=0 data=preserved`. El campo
`containers=0` cuenta los contenedores en ejecución detenidos en este run,
no el inventario total; el helper verificó que ninguno quedara en ejecución,
preservando los ya detenidos si existían. CI no sustituye este recibo host.

Autorización: [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326).
