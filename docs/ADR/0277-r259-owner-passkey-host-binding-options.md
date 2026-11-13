# ADR 0277 — R259: alternativas para atestación de aceptación WebAuthn del propietario

**Fecha:** 2026-11-12 ART / 2026-11-13 UTC. **Issue:** #417.
**Estado:** PROPUESTA DE DISEÑO; requiere decisión específica del titular.
**Base examinada:** `main c2b84429fe4c34140f784e3ba78c8b303f0e45af`.
**Sin cambios funcionales, protocolo, secretos, host, release ni deploy.**
`DEPLOY NO_GO` y aceptación WebAuthn física `UNVERIFIED`.

## RCA y frontera existente

- El controlador 8443 verifica un ES256 auténtico con RP y Origin exactos,
  user presence/verificación (UP/UV), desafío de un uso y vencimiento de
  120 segundos (`panel/passkey.py`). El cookie del propietario se restaura de
  SQLite durante hasta 400 días; una sesión existente **no** prueba un nuevo
  gesto WebAuthn posterior al upgrade.
- Telegram posee una prueba independiente aprovechable como *patrón*, no
  como permiso para reutilizar su propósito:
  `telegram_owner_webauthn.stage_owner_challenge()` liga un desafío a un
  transcript canónico y
  `PasskeyOwnerAuthentication.verify_public_telegram_stage_signature()`
  comprueba la firma pública en host. No demuestra par Docker ni lease.
- El `host_on_demand_service.verify_controller_peer()` ya comprueba
  `SO_PEERCRED`, `pidfd`, `uid_map/gid_map`, cgroup y CID exacto antes de
  admitir el frame fijo de **UUID + LF**. El controlador sólo puede enviar
  operaciones de lifecycle; el socket actual **no entrega** SHA/attempt/CIDs
  ni acepta pruebas WebAuthn.
- El host comprueba la identidad instalada bajo lease mediante
  `host_on_demand_service.read_installed_binding()`; el controller carece de
  esa información autenticada. Inyectar un SHA/CID desde un formulario,
  header, variable o JSON del cliente abriría una falsa certificación.
- `host_first_deploy._cutover_candidate_create_argv()` monta los volúmenes
  Boca de data, key, owner, IPC y SITE_URL; no monta Docker ni el directorio
  de binding. El `boca_data` compartido no es una autoridad de host:
  cualquier documento escrito allí por el controller debe tratarse como
  **candidato no confiable** hasta su verificación física independiente.

## Decisiones que no se pueden inferir

La autorización del deploy BETA no eligió aún un **canal autenticado y
antirreplay host→panel** para vincular la ceremonia de aceptación a un par
instalado. ADR0267 prohíbe introducirlo sin una revisión de autoridad. Ni
usar un digest SHA-256 de datos públicos como firma, ni reutilizar la clave
de cifrado de socios/Telegram como nuevo secreto de aceptación queda
autorizado. No hay justificación para un segundo puerto, un montaje Docker
socket o un workflow SSH alternativo.

## Opciones

### A — Extender semánticamente el socket Boca existente (recomendada para UX)

Mantener **exactamente** el frame `UUID + LF` y la única unidad systemd
revisada. Introducir exclusivamente tipos de operación de aceptación
identificados en el ledger Boca privado, con contratos independientes de
`BOT_START/STOP`:

1. Desde el panel autenticado y con permiso propio, un UUID de un uso
   solicita al host preparar la atestación. El ejecutor bajo demanda autentica
   `SO_PEERCRED` y CID como hoy, adquiere la lease Boca exclusiva, observa
   identidad completa y vigente de par/release/binding y emite un desafío
   aleatorio, de duración limitada, ligado al SHA, attempt, ambos CIDs,
   propósito `BOCA_OWNER_ACCEPT_V1`, operación y nonce. Registra su emisión
   en un journal host privado `O_EXCL` + `fsync`.
2. El controlador sólo presenta el desafío auténtico; no deja al cliente
   seleccionar CIDs. El dueño usa un **nuevo** `navigator.credentials.get`
   con UV requerida y POST same-origin/CSRF/operación de un uso. La firma
   ES256 es comprobada localmente y se almacena sólo como *candidato*, nunca
   como un recibo de instalación.
3. Un segundo UUID de operación de aceptación hace que el mismo ejecutor
   revalide peer/lease, challenge no vencido, firma ES256/UP/UV/Origin/RP,
   purpose, operación, instalación actual (incluidos dos CIDs), token aún
   sin usar, y directorio privado. Sólo entonces escribe **un** recibo
   host `O_EXCL`/`O_NOFOLLOW`/fsync/readback; fallos son NO_GO.
4. Un verificador READ_ONLY separado, dentro del **workflow Boca ya
   protegido**, vuelve a comprobar par y recibo físico, sin reparar ni
   producir evidencia en la lectura. La aceptación del dueño es distinta
   de la aceptación de SITE_URL/worker/monitor/SQLite; no declara BETA PASS
   mientras esas piezas sigan sin prueba.

**Ventaja:** un botón accesible en Chrome, sin terminal ni disparos manuales
por cada aceptación, usando peer identity y socket ya aislados. **Costo/riesgo:**
amplía la autoridad semántica del activador bajo demanda y exige un protocolo
finito nuevo, lifecycle journal separado, directorio host privado, pruebas
físicas de UID namespace y review adicional. Aunque conserva la forma de
frame, **no** puede presumirse aprobado por el uso previo del socket.

### B — Ceremonia de desafíos preparada/verificada por Actions

No ampliar el protocolo del socket ni crear un daemon. En el **mismo
workflow protegido Boca** agregar dos operaciones manuales estrictamente
acotadas: la primera observa par bajo lease y publica un desafío de corta
duración en un archivo Boca privado/copia pública con identidad exacta; el
propietario usa el panel para firmarlo; la segunda verifica pronto, bajo
nueva lease, la firma ES256 contra el marker host exclusivo, el par actual
y una sola operación, y emite/verifica el recibo según el contrato. El
archivo escrito por el controller sólo es un candidato no confiable. El
verificador final READ_ONLY es otra etapa sin mutación.

**Ventaja:** mantiene intactos el socket y el servicio residente; el
host sólo actúa desde la Action existente. Puede evitar una clave nueva
si el challenge y el registro host son genuinamente aleatorios, exclusivos
y ligan exactamente el intento/identidades. **Costo/riesgo:** varias
interacciones con GitHub Actions por instalación, coordinación estrecha del
vencimiento de 120 s y peor accesibilidad desde tablet. No usar un
challenge preemitido de duración indefinida para aparentar frescura.

### C — Certificar sólo estado técnico por ahora

No implementar firma de aceptación todavía. Permitir instalación técnica
sólo si el preflight físico, cleanup y postflight técnico son genuinos;
mostrar `OWNER_PASSKEY=NOT_ATTESTED` y `BETA_DEPLOY=NO_GO` hasta seleccionar
una de las dos alternativas. **No satisface** aceptación B7 ni cierre BETA.

## Amenazas y regresiones mínimas para A o B

1. Cookie de 400 días, GET 200 o healthz no producen aceptación; un desafío
   nuevo y una assertion real ES256/UP/UV son obligatorios.
2. Impedir firma de SHA/CID elegidos por formulario, query, header o una
   copia arbitraria del binding. Exigir dos CIDs completos, imágenes,
   tentativa de instalación, release y lease realmente observados.
3. Rechazar Origin/RP erróneos, `crossOrigin`/`topOrigin`, UV ausente,
   challenge vencido, operación duplicada y transcript de otro propósito.
4. Rechazar peer no controlador, PID/namespace/cgroup cambiado,
   rootless diferente, worker/candidate distinto, par caído o binding
   sustituido entre inicio/firma/consumo.
5. Prohibir directorio permisivo, symlink, hardlink, carrera de inode,
   recibo parcial, sustitución o repetición tras `O_EXCL`; fsync incierto
   conserva residuo y `NO_GO`, nunca reintenta destructivamente.
6. Nada de secreto, cookie, CSRF, assertion, URL, miembro o token en logs,
   issue o recibo publicable. Nunca reutilizar la clave maestra de socios.
7. Pruebas negativas de crash/reinicio entre emisión, firma y fsync;
   verificador posterior **sólo lectura** y revisión de cero cambios Docker
   ajeno, host networking o puertos nuevos.
8. El recibo de dueño no equivale a worker START/STOP, tokens reales, SQLite
   o limpieza V2; esas pruebas tienen aceptaciones propias.

## Pregunta exacta al propietario y camino posterior

**¿Aprobás ampliar las operaciones finitas del socket Boca actual para
permitir la confirmación con passkey desde el panel sin acciones manuales
extra (opción A), o preferís que cada aceptación utilice dos operaciones
manuales en el workflow protegido de GitHub Actions sin modificar el socket
(opción B)?**

Hasta esa elección, **sólo diseño**. El equipo puede terminar B0–B6 en
paralelo. Elegida la opción: especificar contrato y permisos, desarrollar
RED→GREEN con pruebas de identidad/antirreplay/fallos, review técnico,
merge exact-SHA, release dual final, instalación única protegida y
observación WebAuthn física por el propio titular. Nadie debe fabricar el
gesto de su passkey ni presentar un fixture como aprobación real.
