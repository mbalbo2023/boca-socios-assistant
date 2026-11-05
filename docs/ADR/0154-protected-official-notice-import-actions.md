# ADR 0154 — importación protegida de una noticia oficial al volumen Boca

**2026-11-05 ART · #314 / A45-R24 · Estado: DRAFT / CODE-ONLY / NO HOST / NO GO.**

## Motivo y contrato de fuente

El candidato de #319 ya sirve `/avisos-oficiales` desde
`/data/boca_official_notices.jsonl` mediante lector de sólo lectura, y el
importador revisado de ADR0150 valida un ZIP íntegro de GitHub Actions antes
de publicar **una noticia y cinco ventanas no accionables**. Faltaba una
operación del **único** workflow Boca que pudiera conectar ambas piezas sin
pedirle a Tincho comandos de terminal, ni inventar una API de boletos.

Esta rama añade `official-notice-import` como opción manual del workflow
existente `.github/workflows/boca-first-deploy.yml` y el módulo nuevo
`host_official_notice_actions.py`. **No es instalación de imagen/servicio:**
es un escritor puntual de un archivo informativo bajo el volumen Boca ya
existente, sin nuevo contenedor, red, base de datos, puerto, backup ni
modificación de recursos Docker. Se puede ejecutar únicamente **después**
del Cutover A real, release validado y controller nuevo activo. No modifica
los módulos BLACKBOX de navegación del propietario.

## Preflight exclusivamente en GitHub runner

1. Requiere `workflow_dispatch` sobre `refs/heads/main`, actor
   `mbalbo2023`, servicio controller, source SHA actual, imagen GHCR digest
   y manifest de release exitoso exacto. No acepta segunda imagen/browser,
   legacy Cutover, Site, Telegram ni parámetros secretos por argv.
2. El usuario de la operación proporciona *coordenadas públicas revisadas*:
   ID 64-hex del controller Boca existente, run y HEAD de la Action de fuente
   pública, artifact ID, SHA256 del ZIP completo, SHA256 JSONL, SHA256 HTML
   observado y `observed_at_utc` exacto. Nunca acepta URL arbitraria ni
   comando de shell; el repositorio y endpoint GitHub están fijos.
3. **GO independiente y específico** proviene sólo de
   `vars.BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256` del environment protegido,
   **no** de `workflow_dispatch`. El hash canónico SHA256 de esquema v1 ata
   actor, repositorio/ref, run ID e intento 1, main, release+imagen,
   container ID y todos los pins de origen/destino. Un valor ausente,
   anterior, de otra ejecución o diferente da NO_GO antes de SSH.
   La aprobación de environment sigue siendo distinta de este digest.
4. El runner consulta **sólo GitHub API**: Action del workflow público
   `boca-official-news-receipt.yml` exitosa de un PR del **mismo repositorio**
   y workflow ID fijo, artifact metadata no caducada, digest anunciado,
   SHA/ID de repo y HEAD coincidentes. Descarga únicamente ese ZIP mediante
   el endpoint oficial de Actions (redirección HTTPS acotada). No consulta
   Boca Socios/Queue-it ni lleva credenciales de socio.
5. El helper vuelve a calcular SHA256 de los bytes ZIP y JSONL, valida
   receipt del único GET TLS/200, URL HTTPS fija del artículo público
   Boca–Defensa, HTML SHA declarado, observed UTC, cinco ventanas,
   `actionable=false`, sin disponibilidad ni feed. Los pins son
   **independientes** del ZIP; nunca se confía únicamente en su contenido.
6. Guarda un token de coordenadas **sin secretos** mediante O_EXCL/0600
   sólo en el directorio efímero privado del runner. Revalida HEAD de main
   inmediatamente antes del SSH; el token no transfiere autoridad si se
   omite GO.

El artefacto real R22 [#42029320757](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42029320757)
tuvo ID `13414624349` y SHA ZIP
`629e0b728057afb2f149efeec0126cc8697bfca67bbacd43dc6aa70e0843a958`;
son una **referencia de prueba**, no valores permanentes del workflow.
El archivo temporal expira a los 7 días; expirado debe rechazarse, sin
reintentar la importación física ni inferir datos de una fuente vieja.

## Transacción única de host, sin recursos externos

Sólo tras preflight positivo, el runner hace **un SSH** como `boca-deploy`
al host ya configurado, con el ZIP verificado como `stdin`. El comando
remoto es una función **Bash fija y testeada** construida por el helper,
sin código Python arbitrario enviado ni escrituras de script al host:

1. Exige UID **10001**, socket exclusivo
   `/run/user/10001/docker.sock`, lock canónico existente regular 0600,
   sin symlink, y adquiere un `flock` no bloqueante **por todo el efecto**.
   Rechaza el `Docker info` si no es rootless; sólo usa
   `docker --host unix:///run/user/10001/docker.sock`.
2. Inspecciona **únicamente** el exact controller ID 64-hex proporcionado:
   nombre `/boca-socios-controller-1`, proyecto Compose `boca-socios`,
   servicio `controller`, user `10001:10001`, running+healthy y montaje
   writable del volumen exacto `boca-socios_boca_data` en `/data`. Requiere
   que su **config image ID** coincida con `docker image inspect` sobre el
   GHCR **manifest digest** aprobado: no se comparan directamente hashes de
   dos capas Docker distintas. No inspecciona env ni mount metadata de
   contenedores ajenos y no escanea/escribe volúmenes de otros proyectos.
3. Invoca únicamente `docker exec -i --user 10001:10001` en ese ID, usando
   el módulo **ya incluido en la imagen nueva**. El ZIP de stdin se valida
   nuevamente y se llama a `import_reviewed_official_artifact` con
   `/data` fijo. Primera importación **CREATED** o repetición byte-idéntica
   **UNCHANGED**; un snapshot distinto es **NO_GO** (este workflow no
   proporciona lease de reemplazo). Cero escrituras a SQLite o tickets.
4. El módulo usa stage privado `O_EXCL`, publicación atómica sin clobber,
   `fsync` y lectura posterior del snapshot real; emite una única línea
   redactada con resultado, main SHA y digests exactos, cinco ventanas,
   `actionable=false`, `data=preserved`, `readback=PASS`. El host revalida
   ID/image/running **antes de liberar flock**.
5. Un paso final independiente con `if: always()` exige preflight y SSH
   exitosos y recibo byte-exacto. Ausencia, truncamiento, resultado ambiguo,
   runner/SSH/daemon lost o error de I/O significa **NO_GO/INDETERMINADO**;
   jamás reintenta ni borra recursos a ciegas. La lectura del panel desde
   Samsung Chrome+Termius sigue siendo la aceptación física pendiente.

No se añade `docker prune`, un segundo workflow privilegiado, otro
servicio/puerto, host-side backup, reanudación de compras, ni navegación
por Boca/Queue-it. El importador escribe un archivo de datos informativo,
**no instala/despliega/actualiza imágenes**; la limpieza Docker obligatoria
para instalaciones/updates sigue gobernada por Cutover A/ADR0153 y no se
omite mediante esta operación. Cualquier nuevo instalador sin finalizador
continúa bloqueado pre-SSH.

## Límites y evidencia necesaria antes de GO

- `CODE-ONLY`: los tests con **fake Docker** validan sintaxis Bash, UID,
  identidad positiva, aceptación y rechazo antes de `exec`; no demuestran
  que el socket, flock, imagen nueva, controller ID, volumen o Chrome real
  existan/sigan saludables en el droplet.
- El artefacto observado contiene sólo **una noticia con cinco ventanas**;
  no existe feed general demostrado, disponibilidad ni elegibilidad. El
  horario ART aplicado por el extractor sigue siendo **NO_VERIFICADO** según
  ADR0135; la importación nunca lo eleva a orden de reserva.
- El control de GO por run y el artifact de vida breve requieren un proceso
  protegido donde la variable independiente se configure para esa ejecución.
  Un PR verde, un token de coordenadas o un PIN de GitHub no son GO físico.
- `if: always()` es comprobación de recibos, **no garantiza** que el
  finalizador se ejecute tras pérdida física de runner/SSH. Si el archivo fue
  publicado pero se perdió el ACK, conservarlo y **observar Boca en modo
  read-only** antes de decidir un fix-forward, sin retomar a ciegas.
- No se ejecutó ningún SSH, Docker, llamada a Telegram, compra, reserva,
  importación al volumen real ni limpieza física en este desarrollo.

## QA, Regla 84 y coordinación

Tests nuevos `test_host_official_notice_actions_r24.py`,
`test_official_import_host_shell_r24.py`, `test_official_import_actions_r24.py`.
PR-only FirstDeploy ejecuta focales y verifica ausencia de recibo host;
el CI global y el workflow de imagen requieren un HEAD exacto verde antes
de integrar a #319. Registrar PR/SHA/árbol/focal/full/Actions exactos en
[#314](https://github.com/mbalbo2023/boca-socios-assistant/issues/314)
con limitaciones diferenciadas; parent integrador documenta #45.

**Seguridad extra P2 por decisión del dueño**, pero preservar aislamiento
de Porota, otros contenedores, volúmenes, claves, BLACBOX y 8443 único
es parte de la funcionalidad contractual y nunca se relaja.
