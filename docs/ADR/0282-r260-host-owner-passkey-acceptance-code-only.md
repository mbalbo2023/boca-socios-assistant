# ADR 0282 — R260 WebAuthn owner post-install ligado al host Boca

**Fecha:** 13-NOV-2026. **Issue:** #417. **Estado:** CODE_ONLY / `DEPLOY NO_GO`.

## Brecha original

ADR0267 demostró que el login `/sesion` y una cookie Chrome de 400 días no
prueban una nueva ceremonia después de instalar otro SHA. El panel no conoce
de forma autenticada el intento, fuente y CIDs reales: el único socket
controller→host acepta comandos lifecycle UUID, no es un canal de lectura de
identidad ni de retos. Enviar esas coordenadas desde HTML, formularios o env
no sería evidencia de instalación. Una prueba de salud `/healthz` tampoco
certifica la clave del titular ni el monitor.

## Decisión de implementación aislada

`host_boca_owner_acceptance_v2.py` aporta **sólo un servicio host privado**
inactivo hasta que un futuro workflow protegido lo conecte. No incorpora
CLI, workflow_dispatch, endpoint HTTP, puerto, Docker mutante ni acceso al
sitio de Boca. La operación `issue` y la operación `accept` son separadas:
el usuario necesita tiempo en Chrome; la lease de APPLY no se prolonga
artificialmente. Cada operación requiere **su propia lease Boca** válida.

1. El host observa dos veces el par R177, el binding systemd autorizado y
   los **dos CIDs completos**, source SHA, intento e imágenes exactos. El
   worker debe estar `CREATED/PID0/Exit0`. Cualquier diferencia da `NO_GO`.
2. El verificador de dueño procede **sólo del volumen nombrado
   `boca-socios_boca_owner`** tras un inventario rootless Boca-only,
   `DockerRootDir` autenticado, driver/labels/mountpoint exactos y archivos
   públicos `credential_id`/`public_key.der` con lecturas acotadas,
   `O_NOFOLLOW`, UID/mode/inodes verificadas. RP y Origin están fijados a
   `localhost` y `http://localhost:8443`; el sujeto se obtiene de
   `BOCA_OWNER_SUBJECT` en `Config.Env` del **CID controlador autenticado**,
   validando configuración `simulation/off`, Origin y ambos paths públicos,
   con duplicados/datos ausentes rechazados, nunca un literal `owner` ni
   una variable HTTP. Se usa la misma implementación
   ES256/P-256 UP+UV ya probada para otros retos WebAuthn, pero sin ejecutar
   función Telegram ni aceptar una clave pública inyectada por HTTP.
3. El host genera UUID v4 y un nonce aleatorio de 32 bytes; deriva un reto
   de 32 bytes con dominio exclusivo R260, hash de coordenadas, hash de la
   clave pública vinculada, digest de boot_id, epoch y monotonic_ns. Persiste
   sólo el **digest del reto**, identidad/timestamps no secretos y hashes en
   un intent Boca privado `O_EXCL|0600|fsync/readback`. El reto bruto sólo
   existe en memoria; ningún cookie, challenge, assertion, CSRF, URL o clave
   privada entra al archivo.
4. `accept` reabre el intent bajo otra lease, reobserva el mismo par/clave,
   misma identidad de boot y frescura **máximo 120 segundos** por relojes
   epoch y monotónico. Consuma **una única vez** un `.claim` inmutable ANTES
   de verificar la assertion real ES256 con Origin/RP, UP+UV. Incluso una
   assertion inválida consume el intento; no hay replay ni overwrite. Tras
   verificar, vuelve a atestar par/clave y crea/relee recibo digest-only
   `.receipt` con estado `OWNER_PASSKEY_VERIFIED_PENDING_BETA` y
   `beta_deploy=NO_GO`.
5. `verify_readonly` es otro lector sin escrituras: revalida el par actual,
   clave pública, boot y los tres archivos O_NOFOLLOW canónicos. El archivo
   host rootless exclusivo es el **trust anchor**, no el SHA de datos públicos
   por sí solo; copiar el recibo sin ese path privado no lo autentica.

Las pruebas sintéticas contienen firmas ES256 reales de una clave de prueba
P-256, pero no son ceremonias del propietario ni prueban el droplet.

## P0 antes de cualquier promoción

- **No existe canal autenticado host→panel para entregar el reto al Chrome**
  ni retorno de la assertion al único workflow Boca protegido; se prohíbe
  sustituirlo por headers/query/env o agregar otro puerto/socket genérico.
  Hasta diseñar ese canal y obtener evidencia Chrome fresca, el adapter es
  CODE_ONLY y owner acceptance física **UNVERIFIED**.
- **Lectura del owner volume con subuid remapeado:** si los archivos son
  `0600` con UID subordinado, la cuenta host `boca-deploy/10001` no podrá
  abrirlos; se rechaza honestamente. Requiere un lector autenticado por
  custody rootless mapeada y una revisión de arquitectura separada. No
  `chown`, `chmod`, Docker exec, mount adicional ni acceso root para saltarlo.
- El receipt owner **no** termina por sí solo el postflight: siguen exact
  release/CI/merge, cleanup V2, technical postflight, 8443, SITE_URL,
  worker bajo demanda, SQLite y monitor autenticado. Las acciones R186
  históricas permanecen inmutables y no se reintentan. No tocar Porota,
  claves privadas, otro Docker, TLS, fila o reservas reales.

## TDD y QA

RED inicial por módulo inexistente y GREEN con fixtures de firma ES256 real
UP+UV, Origin/RP/credenciales alteradas, cookie sin assertion, challenge
modificado, par/CIDs distintos, lease incorrecta, expiración, reboot,
O_EXCL/duplicación, symlink, tamper y verificador independiente READ_ONLY.
Se agrega regresión RED→GREEN para `BOCA_OWNER_SUBJECT` efectivo desde el
CID real y rechazo de Environment ausente, duplicado, origen/ruta distintos
o sujeto inválido, sin imprimir ningún valor de Env.
Ningún PASS de estos tests establece estado físico en el droplet.
