# ADR0218 — R125: rootless Docker data-root 0710 es metadata, no error

Estado: **corrección CODE_ONLY R125** sobre R124 ya fusionado en PR #453.
Continuidad: #45 / #417. No modifica ni interroga el daemon Docker.

## Evidencia y RCA del falso positivo

El único workflow manual READ_ONLY `Boca first deploy` #890,
https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42559518453,
se ejecutó en `main=b7e7dd77531eaf6c967b439381edd152a7a8159b`.
Registró UID/GID 10001, `linger=YES`, home y runtime 0700, sockets
Docker/bus/systemd acotados, `subuid/subgid=VALID`, `newuidmap/newgidmap`
y user namespaces disponibles. El inspector independiente observó el
servicio rootless `docker.service` activo y `dockerd=available`; el helper
de linger reportó `data_root=UNSAFE data_uid=10001 data_gid=10001
data_mode=0710`. Ninguna operación cambió el droplet.

**Causa demostrada de la etiqueta errónea:** R124 llamó a `_dir(data_root)`
que requiere 0700 para los directorios *home* y *runtime*; ese predicado
no contempla que Docker/Moby prepara su directorio de datos con
`user.MkdirAllAndChown(config.Root, 0o710, curuid, gid)`:
https://github.com/moby/moby/blob/master/daemon/daemon_unix.go.
El modo 0710 permite al grupo únicamente atravesar el directorio y no
autoriza lectura/escritura a grupo ni terceros. Así que la etiqueta `UNSAFE`
**no era una prueba de permisos incorrectos**. Además, `data_root` ya era
informativo, no formaba parte de `METADATA_CANDIDATE`; no causó el gate.

## Decisión y límites

- Introducir `_docker_root_dir` **separado de** `_dir`.
  UID/GID10001 y modo 0710 -> `OWNER_0710`; modo 0700 -> `PRIVATE`;
  dueño, tipo o permisos distintos no se reinterpretan como aceptables.
- El nuevo nombre `OWNER_0710` describe **metadatos del objeto observado**:
  no asegura que `~/.local/share/docker` sea el `DockerRootDir` activo,
  pues Docker documenta esta ruta solo como *predeterminada*:
  https://docs.docker.com/engine/security/rootless/tips/.
- Reforzar el verificador runner-side: nueva etiqueta solo con UID/GID
  10001 y modo 0710 exactos; rechazar UID/GID/mode forjados, mantener
  estados `UNSAFE` auténticamente inseguros, esquema fijo de seis líneas y
  fail-closed. **Excepción histórica explícita:** el recibo #890
  `UNSAFE/10001/10001/0710` fue verificado por el código R124 del SHA
  ejecutado, y permanece como evidencia inmutable del run. El verificador
  **R125 no lo revalida retroactivamente**, porque ahora esa tupla con etiqueta
  `UNSAFE` es una contradicción y se rechaza. No existe migración de recibos
  antiguos ni un nuevo despacho por ese motivo.
- **No** flexibilizar home/runtime0700, socket Docker, subids ni gates.
  No sumar `data_root` al gate porque la lectura no certifica la ruta
  efectiva del daemon. No modificar workflows, ZIP protegidos, BLACKBOX,
  `host_first_deploy.py`, puertos, Docker, Porota ni otras aplicaciones.
- Ningún `chmod`, `chown`, `enable-linger`, Docker restart, Cutover,
  Telegram, limpieza ni re-dispatch de la Action para una mera etiqueta.

**El `ExitCode=1` histórico de #878 sigue sin RCA causal interna:** el
worker salió con `OOMKilled=false`, sin logs/traceback persistidos. Ni
`linger=YES` observado después ni 0710 retrospectivamente lo explican.
La aceptación física Cutover/BETA permanece **NO_GO**.

Pruebas requeridas: TDD RED->GREEN para 0710, 0700, 0711, 0750, 0720,
0777, UID/GID ajenos, objeto no-directorio; validador de recibos forjados;
suite completa, Ruff, formato, MyPy y workflow CI exact-SHA antes del merge.
