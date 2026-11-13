# ADR0275 — R255: titularidad subuid efectiva en inodes privados Boca

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** CODE_ONLY,
sin integración al ZIP protegido; **DEPLOY NO_GO**.

## Evidencia y causa raíz

- La observación SQLite dedicada [#43350432873](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350432873)
  informó `VERIFIED_STABLE`: dos lecturas de `O_PATH` coincidentes, inode
  regular privado, modo `0600` y un solo hardlink. Su recibo deliberadamente
  **no verifica** que el UID/GID del inode sea el host UID/GID 10001 ni
  certifica la traducción efectiva de `subuid/subgid` del proceso del
  controlador. Un recibo exitoso no autoriza aplicar un cambio.
- `host_boca_postflight_sources_v2._structural_file_inode_sha256()` y
  `host_boca_upgrade_postflight_runtime._file_inode_sha256()` requieren
  literalmente `st_uid=st_gid=os.geteuid/getegid=10001`. En rootless Docker,
  el UID 10001 *dentro* del contenedor puede mapear a un UID/GID subordinado
  diferente *fuera*. El requisito existente puede producir falso NO_GO con
  datos válidos; no se demostró aún que eso ocurra físicamente en los tres
  archivos. No se modifica ese requisito antes de medir el mapeo real.
- [#43350251999](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350251999)
  acreditó binding de systemd y loopback, pero informó
  `sqlite_inode=UNVERIFIED`; el observer independiente posterior cubrió
  sólo continuidad del inode, no ownership.

## Decisión: atestador local de metadatos READ_ONLY y sin GO implícito

`host_boca_rootless_mapped_custody` es un callable nuevo, **no conectado**
a APPLY, al selector Actions ni al bundle. Sólo bajo el lease Boca existente:

1. Reutiliza la prueba de par vivo `R177`, systemd y CID exacto, y lee **sólo**
   `Docker inspect State.Pid` del controlador Boca identificado.
2. Sobre el único PID positivo autenticado abre con `O_NOFOLLOW` los archivos
   `/proc/<PID>/uid_map` y `gid_map`, de máximo 512 bytes. Rechaza mapas
   incompletos/solapados, out-of-range, ajenos al rootless UID10001, o que
   no representen el usuario del contenedor UID/GID10001. Recomprueba CID y
   PID al salir; no abre `/proc/<PID>/environ`, `cmdline`, `status`, ni otros
   procesos. Los IDs traducidos **no se serializan**.
3. Invoca el atestador ya revisado de los tres volúmenes Boca bajo el mismo
   lease, que valida proyecto, opciones `local`, mounts sin redirección y
   no-follow antes de cualquier consulta de archivo.
4. Con `O_PATH`, dirfd y `O_NOFOLLOW`, lee **sólo metadatos** de
   `boca.sqlite3`, `boca_master_key` y `boca_owner_session.sqlite3`. Exige
   inode regular, único hardlink, modo privado `0400/0600`, titularidad
   traducida exacta y ausencia de sustituciones/symlinks. Genera digests
   SHA256 privados de identidad, sin usar bytes de BD, secretos ni token.
5. Repite volúmenes, mapeo, archivos, par y lease; un cambio genera `NO_GO`.
   El único resultado público es `VERIFIED_MAPPED` o `NO_GO`, sin IDs, rutas
   internas, datos de sesión ni causa variable publicada.

El código crea **cero escrituras, operaciones Docker mutantes o conexiones de
red**, y no consulta Porota, contenedores ni volúmenes extranjeros. Es una
prueba de ownership y continuidad; no sustituye una ceremonia passkey,
monitor autenticado ni la validación integral del panel.

## Integración y aceptación futura (aún pendientes)

1. Revisar/mezclar el código tras CI, arquitectura, QA e inspección de
   seguridad del alcance. No debe añadirse automáticamente al ZIP actual:
   la cota de bytes del bundle protegido tiene margen limitado, y su cambio
   requerirá medir tamaño y demostrar las invariantes de integridad.
2. En un PR posterior, conectar sólo al mismo protected Boca Actions workflow
   y **bajo el lease de APPLY existente**, nunca abrir otro SSH de despliegue.
   Como paso exclusivamente metadata READ_ONLY para diagnóstico, el resultado
   debe quedar separado de cualquier autorización de APPLY. No se ejecuta
   este paso desde la rama CODE_ONLY.
3. Obtener un recibo físico genuino que pruebe la traducción para los tres
   archivos. Si hay mismatch, clasificarlo sin publicar números privados,
   mantener NO_GO y estudiar una corrección a lectores R247/R245 que use
   exclusivamente el `MappedOwner` derivado de este atestador **antes** de
   relajar comparación de owner, siempre con symlink/mount/lease/inode
   invariantes. No inferir el UID a partir de `/etc/subuid` solamente ni de
   `host_process_uid_map` del observador.
4. Sólo tras éxito independiente de preflight, release dual SHA/digest,
   instalación, cleanup V2 exacto, postflight y prueba real en 8443,
   passkey, SITE_URL, worker, monitor y SQLite declarar BETA instalada.

Tests sintéticos R255: traducción exacta con dos mapas separados, mapas
solapados/malformados/ajenos, tres inodes O_PATH, symlinks/hardlinks/modos,
reemplazo concurrente, lease/par y dos lecturas del PID Docker exacto. Ningún
test sintético equivale a observación física del droplet.
