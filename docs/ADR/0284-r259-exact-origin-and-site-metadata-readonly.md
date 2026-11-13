# ADR 0284 — R259 diagnóstico del origen 8443 y archivos SITE_URL (CODE_ONLY)

**Fecha:** 12-NOV-2026 ART (13-NOV UTC). **Issue:** #417. **Estado:**
`CODE_ONLY / DEPLOY NO_GO`; ningún despacho físico forma parte de este PR.

## RCA y decisión del propietario

Una lectura externa de `GET http://127.0.0.1:8443/healthz` devolvió HTTP 503,
pero no envió necesariamente el encabezado `Host: localhost:8443` que exige
el panel privado configurado. El valor 503 **no demuestra caída** del
controller. El propietario también estableció que `SITE_URL` debe empezar
**vacío** y permanecer así hasta guardarlo desde Configuración con su passkey.
El panel puede instalarse sin URL; el worker no puede iniciar hasta que la
URL esté guardada y aplicada por el control Boca; el monitor no debe inventar
una URL, un token ni una sesión.

## Observador propuesto (única Action protegida existente)

Se agrega el selector manual `boca-panel-exact-origin-observe` a
`.github/workflows/boca-first-deploy.yml`. Su único programa remoto es
`host_boca_panel_exact_origin_readonly.py`, transmitido **desde el checkout
exacto de main** mediante SSH de usuario fijo `boca-deploy` con host key
anclada; el runner revalida main inmediatamente antes del SSH y verifica una
respuesta canónica limitada a 512 bytes. El selector no permite coordenadas
de host, puerto, URL, CIDs, imágenes ni intentos introducidos por el usuario.

1. Se hacen dos GET (uno por captura) exclusivamente a
   `127.0.0.1:8443/healthz`, enviando literalmente
   `Host: localhost:8443`, `Connection: close`, timeout de dos segundos. Sólo
   `200`, `Content-Length: 15`, tipo textual exacto y los 15 bytes fijos
   `BOCA_BETA_READY` equivalen a `HEALTH_HTTP_200`.
2. Con `O_PATH|O_NOFOLLOW`, sin abrir contenidos, se observa **sólo** si
   existen los archivos de URL del volumen privado de datos y del volumen
   exclusivo del worker. `BOTH_FILES_ABSENT` significa ausencia de ambos
   inodes en esos paths exactos; `PRESENT_UNVERIFIED` no significa URL
   configurada, válida ni utilizada. Un symlink, modo inseguro, ruta o inode
   inestable rechaza el test. Se repiten las capturas y se comparan.
3. Se leen únicamente inodes, modos y propiedad de los tres archivos Boca
   de SQLite, clave y sesión privada, sin bytes, secrets ni DB connection.
   `UID_DIFFERS_FROM_HOST` es una observación de identidad numérica distinta,
   **no** prueba mapeo válido de subuids. `namespace_map` y
   `volume_provenance` permanecen obligatoriamente `UNVERIFIED` hasta un
   test separado del namespace **efectivo** y las etiquetas/mounts Docker
   bajo la lease protegida. Ni `/etc/subuid` ni una conjetura de rango son
   prueba suficiente de custodia.
4. El recibo publica exclusivamente las categorías anteriores, run ID,
   SHA exacto de main y `state=OBSERVED_NO_GO`, `observer_writes=0`,
   `deploy=NO_GO`. El verificador rechaza claves extra, formatos distintos,
   duplicación, SHA/runs inválidos y cualquier texto no canónico; no recibe
   URL, fingerprint, cookie, token, datos SQLite, nombres privados ni paths.

## Frontera y consecuencias

No hay Docker socket, `docker exec`, sudo, systemd, start/stop, imagen,
cleanup, cola, Internet, login, reserva o navegación pública. Los únicos
efectos transitorios son el proceso SSH/Python, dos GET locales sin sesión y
lectura de metadatos, sin escrituras persistentes en el host. La ausencia
observada del archivo no autoriza que un worker arranque ni sustituye los
futuros recibos físicos de postflight, el binding exacto de contenedores o
la aceptación del titular. Una respuesta HTTP 200 confirma únicamente salud
del endpoint técnico en ese instante; no demuestra passkey, SITE_URL ni
sesión persistente.

**Verificación:** tests TDD local en
`tests/test_boca_panel_exact_origin_readonly.py` cubren encabezado Host exacto
con servidor HTTP real descartable, 503 sin promoción, SITE_URL ausente,
archivo presente no verificado, symlink, recibo restrictivo y selector manual
sin operaciones mutantes. Ruff, mypy, policy y suite completa deben pasar en
SHA exacto antes de PR/merge; una Action física exige dispatch posterior
revisado y un recibo auténtico. R186 no se repite. Porota está fuera de alcance.
