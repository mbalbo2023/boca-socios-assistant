# ADR0137 — Una sesión persistente del dueño en Chrome, sin vencimiento rutinario (04/11/2026)

Estado: **DRAFT** del issue #321. Sólo código y pruebas, sin merge, Actions dispatch,
upgrade físico ni deploy. No constituye evidencia de la BETA instalada con esta política.

## Decisión explícita del propietario

Tincho ya autenticó el panel privado `http://localhost:8443` mediante passkey
desde Samsung Chrome/Termius. Solicita conservar la autenticación en **el mismo
perfil Chrome** entre cierres, días sin uso y reinicios del controller, sin
caducidad por 15 minutos inactivo ni por 8 horas absolutas.

- Sólo **una sesión activa del dueño globalmente**. Las pestañas del mismo
  perfil comparten cookie; **un nuevo ingreso con passkey revoca la anterior**.
  No se implementan múltiples sesiones durables ni navegación paralela: opción
  #4 expresamente descartada.
- El primer ingreso y toda reautenticación siguen exigiendo la verificación
  WebAuthn ES256, presencia/verificación de usuario, RP, challenge y origen
  exactos. No hay PIN, credenciales o tokens en chat, fuente, logs ni Actions.
- Se emite un token aleatorio de 256 bits exclusivamente como cookie
  `__Host-boca_session` con `Secure; HttpOnly; SameSite=Strict; Path=/`. La cookie
  **no** es session-only: usa `Max-Age=34560000` (400 días), y cada petición
  autenticada renueva ese período con `Set-Cookie`. El servidor **no impone**
  los antiguos TTL 15m/8h a esta modalidad.
- Chrome limita a **400 días** el vencimiento de cookies con Max-Age/Expires
  largo; no es una cookie literalmente infinita. La renovación permite uso sin
  reingreso **mientras el usuario conserve y utilice periódicamente el mismo
  perfil**. Borrar cookies/datos, incógnito, otro perfil/equipo o inactividad
  superior al límite del navegador requieren passkey nuevamente. Referencia
  primaria: https://developer.chrome.com/blog/cookie-max-age-expires

## Persistencia y revocación

1. El esquema `0008_owner_browser_session.sql` agrega únicamente la tabla
   `owner_browser_session`, con `singleton=1` obligatorio. SQLite guarda
   **SHA-256 del bearer aleatorio**, SHA-256 de la configuración pública del
   verificador WebAuthn y SHA-256 del sujeto propietario, más timestamp.
   No guarda cookie/token plaintext, CSRF, contraseñas, credenciales de socios,
   passkey privada, operation IDs, formularios, replay cache o permisos
   convertidos en autoridad persistente.
2. El binding de verificador abarca credential ID, clave pública DER, RP,
   origen, owner y permisos efectivos. En un reinicio, sólo el servidor con la
   misma configuración confiable puede reconstruir los permisos concedidos;
   una modificación o revocación de la passkey invalida la cookie previa.
3. Una segunda autenticación sustituye el único hash de sesión en una
   transacción `BEGIN IMMEDIATE`. El logout elimina el hash **si coincide**
   con el token actual y entrega `Max-Age=0`; un logout antiguo no puede
   revocar un login posterior. La fila ausente equivale a acceso denegado.
4. Cada petición consulta la autorización durable; las escrituras verifican
   vigencia nuevamente. Tras reiniciar, la primera petición con cookie válida
   crea **CSRF, fingerprint de operaciones, límites y formularios nuevos sólo
   en RAM**: un POST/formulario viejo no puede reproducirse. No se persiste
   exact-once de operaciones de negocio más allá de los mecanismos existentes.
5. Falta de tabla, checksum/esquema incorrecto, symlink o SQLite inaccesible
   se rechazan; no se fabrica una sesión válida en memoria. El panel no debe
   iniciar en versión nueva si no se realizó antes la migración 0008.

## Instalación/upgrade gobernado: 0006/0007 → 0008

La BETA controller-only en el droplet **no se presume migrada**. Telegram usa
su propio volumen y su versión 0007 es independiente; el DB controller puede
tener {1,2,3,5,6} y quizá 0004, sin 0007. `0008` es compatible tanto con un
ledger 0006 como con un ledger 0007 válido, y no exige migrar Telegram.

1. Integrar únicamente después de revisar PR DRAFT, CI y preflight por SHA;
   no desplegar este código contra la DB vieja por inferencia.
2. El adaptador sólo-código `panel.owner_session_upgrade` define
   `upgrade_existing_owner_schema_0008(ControllerStoppedEvidence)`. Una
   **implementación de evidencia host aún no disponible** debe inspeccionar
   de verdad el container Boca detenido y mantener exclusividad durante toda
   la transacción. Un booleano `stopped=True`, JSON, recibo histórico, clase
   de prueba o callback no autenticado **no son evidencia física**. Ni la
   existencia de este adaptador ni tests con prueba sintética habilitan su
   ejecución física.
3. El futuro paso GitHub Actions **protegido, explícito y Boca-only** deberá
   entregar el capability de parada anterior a un proceso sin red, con mount
   exacto `/data/boca.sqlite3`; exigir real/effective UID/GID **10001/10001**,
   archivo regular no symlink, `0600`, hardlink-count 1 y `(dev,inode)`
   invariable. `validate_existing_beta_storage` comprueba el ledger previo:
   0006 obligatorio, 0007 opcional con checksum real, 0004 opcional. El
   adaptador vuelve a validar dentro de `BEGIN IMMEDIATE`, usa SQLite
   `mode=rw` (jamás crea una DB ausente) y agrega **sólo tabla y ledger 0008**
   de forma atómica e idempotente. Comprueba postcondición/integridad e inode,
   sin recrear owner, clave, credenciales, datos ni volumen. El mismo host
   debe retener el controller detenido y el acceso exclusivo al volumen.
   No escribir tokens ni secretos en recibos.
4. **No invocar** `OwnerBrowserSessionStore.migrate()` contra controller ya
   instalado: ese initializer pertenece al primer alta explícita. La
   construcción del panel, login, healthcheck, consulta y startup **nunca
   migran** por su cuenta. La primera instalación nueva con owner configurado
   sí prepara 0008 mediante `initialize_beta` explícito; un fixture offline
   sin dueño no crea por inferencia una autorización.
5. Si falla, NO_GO sin iniciar la nueva imagen; limpieza Docker selectiva
   exclusivamente Boca. No borrar volúmenes, no tocar Porota ni otros servicios,
   no reinicializar passkey, no realizar backup/restauración como parte de BETA.
6. Con migración y código físicos verificados, el owner hace **una vez** el
   login WebAuthn para poblar el nuevo hash (la cookie vieja estaba sólo en
   RAM y no puede migrarse). Comprobar Chrome cerrar/abrir, mismo token
   renovado, reapertura tras reinicio controlado, logout y segundo login que
   invalida el anterior. Guardar únicamente recibos redactados en #321/#45.

## Límites y exclusiones

Esta cookie es un **bearer**: cualquiera con su valor íntegro podría reutilizar
la autorización dentro del túnel privado. El diseño no permite atribuir el
token criptográficamente a un dispositivo físico ni promete recuperarlo tras
borrado de datos Chrome. El usuario prioriza persistencia sobre reautenticación
periódica; la exposición queda circunscrita al panel privado SSH-local con
origen exacto, CSRF, SameSite, Secure y HttpOnly. Una sesión única limita
superficie, pero no vuelve imposible la copia de cookies.

No habilita sesiones múltiples, rotación/eliminación total de clave maestra,
login real/fila/reserva/compra Boca, backups, HTTPS adicional, Site ni operación
del worker/Telegram. `synthetic.py` e `ipc_worker.py` permanecen BLACKBOX
intocables.

## Evidencia necesaria para salir de DRAFT

- Migración explícita verificada, checksum exacto, DB anterior intacta,
  inicialización sin tabla, idempotencia y fallos cerrados.
- Verificación criptográfica WebAuthn con claves sintéticas en tests; cookie
  con atributos y rolling 400d, mismo
  Chrome tras restart sin WebAuthn, expiraciones 15m/8h anuladas, segunda
  autenticación revoca la primera, logout durable, CSRF/POST viejo rechazado,
  permiso/verificador cambiado invalida y cookies malformadas/duplicadas niegan.
- Ruff, MyPy, pytest integral y policy por SHA, PR DRAFT; sólo recibo físico
  posterior (Actions protegidas) puede cerrar el NO_GO de despliegue. Regla 84.

### Corte de QA del adaptador offline (04/11/2026)

- Sólo fuente/tests: DB sintética creada por el `initialize_beta` real **sin
  owner** para reproducir ledger 0006, con y sin 0007; prueba de idempotencia
  después de poblar el hash de owner, conservación de filas y clave sintéticas,
  mismo `(dev,inode,mode)` y rechazo de ledger/esquema parcial o alterado.
- `ControllerStoppedEvidence` es interfaz abstracta de *lease host*; no existe
  en este scope implementación de confianza ni `workflow_dispatch` que la
  produzca. Los tests usan un doble local para comprobar el contrato, **no
  simulan ni certifican la parada real de contenedores**.
- **NO_GO físico** hasta integrar y evidenciar el host-stop gate propietario,
  inventario exacto del volumen, source SHA, preflight, CI y ejecución gobernada
  en GitHub Actions. No se realizó ninguna migración ni deploy real en este PR.
- QA de branch aislada: `pytest -q` **2597 passed + 34 subtests**, Ruff check
  PASS, Ruff format PASS (405 archivos), MyPy PASS (90 archivos), repo policy
  `POLICY_PASS`. Son evidencias locales, no sustituyen los checks Actions del
  nuevo SHA remoto ni el recibo host físico.
