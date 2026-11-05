# ADR 0148 — Doble inventario de capacidad de limpieza Boca (#323)

Fecha: 2026-11-05 ART. Estado: **DRAFT / CODE_ONLY / host NO_GO**.

## RCA comprobado

La política aprobada en [ADR0138](0138-always-postdeploy-boca-docker-hygiene.md)
exige medir antes y después del finalizador tanto el área de staging Boca
como el **data root Docker rootless dedicado**. La implementación existente
`host_boca_cleanup._disk_inodes()` medía únicamente `/srv/boca-socios` (o
`/srv` si todavía no existía el directorio), almacenando sólo un par
`bytes_free/inodes_free`. Si Docker usaba otra partición, el recibo no podía
verificar su capacidad; la ausencia del segundo dato se confundía con un
inventario completo. Esto es un defecto de **observabilidad**, no prueba que
se hayan borrado recursos ajenos ni que el droplet esté sin espacio.

## Decisión de implementación acotada

- Se conservan `bytes_free/inodes_free` de staging. `DiskInodes` agrega pares
  `docker_bytes_free/docker_inodes_free`, junto con `(device,inode)` del
  staging y del Docker root para detectar cambios de topología. Los campos
  nuevos son opcionales únicamente para construir fixtures/recibos sintéticos
  históricos; **`capture_inventory()` real debe producirlos todos**.
- El root Docker se obtiene del **único socket rootless Boca** de UID10001
  usando el mismo CLI sin entorno de credenciales. `docker info` debe acreditar
  rootless, systemd/cgroup v2 y un driver de capas reconocido. Su
  `DockerRootDir` tiene que residir dentro de la home privada de UID10001;
  se verifica directorio por directorio con `O_DIRECTORY|O_NOFOLLOW`, dueño,
  grupo, permisos e identidad final antes de `fstatvfs` por descriptor.
  Ninguna ruta ajena se crea, abre para escritura o elimina.
- El finalizador acepta tanto **dos directorios en el mismo filesystem** como
  sistemas separados. Cada lectura guarda sus propias métricas. Un cambio
  de identidad de cualquiera de los dos directorios entre el preinventario
  y cada intento de eliminación es `NO_GO` y detiene nuevas eliminaciones.
  Los bytes libres pueden fluctuar legítimamente; no son un criterio de
  limpieza exitosa ni se exige que aumenten.
- El plan positivo de eliminación sigue siendo **sólo Boca exact-ID** con
  etiquetas de intento, referencias conocidas y ausencia comprobada. No
  se incorporó `prune`, ni eliminación de claves/owner/datos, ni inspección
  de contenedores, imágenes, volúmenes o redes de Porota/otros servicios.

## Verificación y límite

Pruebas nuevas: medición doble desde home Docker rootless sintética, rechazo
de `DockerRootDir` fuera de la home, cambio de inode de Docker antes de borrar
con cero comandos de eliminación, y aceptación correcta cuando ambas rutas
comparten o no comparten filesystem. Otras regresiones originales de
referencias activas, imágenes multitag y drift Docker se mantienen.

**No existe en este PR una ejecución en el droplet, publicación de release,
merge a main ni confirmación de bytes recuperados.** La operación de
`cutover-a-apply` y el `if: always()` del único GitHub Actions protegido
siguen sin cablear a este finalizador; ante falla de SSH/daemon o pérdida
del runner puede ser imposible ejecutar la limpieza. El resultado es NO_GO
hasta una nueva observación Boca-only de las identidades reales, sin retry
ciego. Referencias de QA/SHA de esta propuesta se registrarán en issue #323
y PR DRAFT al publicar el árbol exacto.
