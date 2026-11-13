# Boca Socios Assistant

## R259 — consolidación CODE_ONLY y diagnósticos (12/11/2026 ART; 13/11 UTC)

Base verificada: `main c2b84429fe4c34140f784e3ba78c8b303f0e45af`;
[#501](https://github.com/mbalbo2023/boca-socios-assistant/pull/501) ya
fusionado, sin otros PR abiertos al iniciar R259. Su CI exacto
[#43353616060](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43353616060)
aprobó **8016 tests y 34 subtests**; el CI de `main`
[#43354400245](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43354400245)
y su escaneo [#43354400279](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43354400279)
también fueron SUCCESS. Los dos labs solapados tardaron 23 s en el CI de
`main`, pero el job de imágenes aún tardó aproximadamente seis minutos.

R259 mantiene cuatro frentes de alcance exclusivo: SITE_URL sin valor
predeterminado ([ADR 0274](docs/ADR/0274-r259-unconfigured-site-url-technical-proof.md));
diagnóstico 8443 exact-origin **sólo lectura** dentro de la Action Boca
existente, sin certificar subuid/volumen ni iniciar worker
([ADR 0275](docs/ADR/0275-r259-exact-origin-and-site-metadata-readonly.md));
recibo terminal persistido y releído, más clasificación correcta de fallos
**anteriores** a commit ([ADR 0276](docs/ADR/0276-r259-terminal-readback-and-prelease-classification.md));
y alternativas de aceptación con passkey ligada al par físico, **diseño
solamente pendiente de decisión del titular**
([ADR 0277](docs/ADR/0277-r259-owner-passkey-host-binding-options.md)).
Ninguno de estos candidatos está desplegado. El CLI mantiene APPLY NO_GO;
el postflight técnico NO autoriza BETA, la release dual final sigue pendiente,
y R186 es irrepetible. Porota, reservas reales, fila y TLS están fuera de alcance.

## R259 — SITE_URL vacía hasta configuración del titular (12/11/2026 ART; CODE_ONLY)

Por decisión expresa de Tincho, un panel BETA recién instalado **no** trae
`SITE_URL` precargada. El formulario privado 8443 ya muestra el campo vacío
y permite guardarlo bajo passkey; el worker sigue impedido de iniciar hasta
que exista una URL válida, sincronizada en su volumen y consumida en el
próximo START explícito. Si el titular ya guardó una URL válida, se conserva
sin borrarla ni sustituirla.

R259 corrige el contrato de **postflight técnico schema 2** para permitir
probar controlador, volumen, worker inactivo y `/healthz` cuando ambos
archivos URL se encuentran genuinamente ausentes: evidencia
`NOT_CONFIGURED`, huellas `null`, nunca SHA ficticio. Archivo alterado,
symlink o divergencia continúan NO_GO; el postflight legacy y la aceptación
Chrome/passkey siguen sin permitir ausencia. Es un cambio de código y tests,
**no prueba física ni autorización de deploy**. Véase [ADR 0274](docs/ADR/0274-r259-unconfigured-site-url-technical-proof.md).

## R258 — reconciliación de #501 con #500 (12/11/2026 ART; 13/11 UTC; CODE_ONLY)

El [PR #501](https://github.com/mbalbo2023/boca-socios-assistant/pull/501)
fue reconciliado sobre `main=7b19924aea1a25b195da733f95b8f7147df43f1e`
tras el merge de [#500](https://github.com/mbalbo2023/boca-socios-assistant/pull/500)
y luego fusionado como CODE_ONLY en `main c2b8442`.
Conserva el único par BuildKit del CI y solapa dos laboratorios descartables;
acota a cinco minutos cada carga de manifiesto de la release protegida;
y añade al motor una `backend_factory` invocada **después** del intent durable
y bajo la misma lease. Los ADR nuevos se identifican como
[0266](docs/ADR/0266-r254-parallel-disposable-ci-labs.md),
[0272](docs/ADR/0272-r254-bounded-release-artifact-upload.md) y
[0273](docs/ADR/0273-r255-inert-single-lease-actor-plumbing.md),
sin sustituir los ADR de #500.

Validación local del árbol reconciliado: **8015 PASS, 34 subtests PASS y
1 SKIP AF_UNIX EPERM del sandbox**; Ruff, formato, mypy y política PASS.
El ZIP `PAIR_UPGRADE` conserva exactamente 78 entradas y mide 361.206 B
comprimidos / 1.397.022 B descomprimidos (límite 1.400.000 B).
Las Actions del SHA final, revisión y merge constan en [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6842311375). Este código **no conecta el CLI APPLY**,
no publica un nuevo release ni certifica el droplet: **DEPLOY NO_GO**.
El único upgrade R186 fallido no se repite, y Porota permanece fuera de alcance.

## R253 — recibos SUCCESS independientes por intento (13/11/2026)

Se corrigió en código el bloqueo por nombres globales del journal de
limpieza SUCCESS: cada intento tiene ahora su propio `intent` y `receipt`,
con `O_EXCL`, fsync, readback y rechazo de reejecución. El postflight V2
lee únicamente el recibo del mismo intento, manteniendo intacto el esquema 2
`TECHNICAL_PROOF_ONLY` y la separación de la passkey del propietario.
No se borran archivos históricos ni se ejecuta Docker desde esta modificación.
**CODE_ONLY / DEPLOY NO_GO**; falta la instalación física certificada.
[ADR0263](docs/ADR/0263-r253-per-attempt-success-cleanup-journal.md).

## R251 — preflight tipado, sin autorización de instalación (13/11/2026)

El `main` **verificado al iniciar R251** es
`0007d8c4100c8d9e37103f0a2bac149cfb6edf29`: PR
[#496](https://github.com/mbalbo2023/boca-socios-assistant/pull/496)
fusionado, ningún PR abierto en ese instante, CI
[#43336041508](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43336041508)
y escaneos
[#43336041506](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43336041506)
**SUCCESS** exactos. Incluye la caché BuildKit y la corrección P1 de
limpieza selectiva, pero no una nueva instalación. La última pareja física
observada sigue en `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72` mediante
las Actions READ_ONLY R188 y par actual; no se ha acreditado un postflight
BETA completo.

Esta rama **R251 CODE_ONLY aún no integrada** hace que el preflight entregue
las coordenadas del par y los tres archivos de etapa, tipados y con huellas
comprobadas, para una integración posterior. La ruta CLI `apply` **continúa
NO_GO antes de la lease y de Docker**, sin permiso para repetir el APPLY R186.
El bloqueo decisivo es R252: único actor same-lease, SUCCESS/FAILURE cleanup
V2, journal y postflight físico auténtico. La aceptación técnica de salud
8443/SQLite/SITE_URL/worker preparado no sustituye la prueba posterior del
propietario con passkey, START/STOP, monitor y sesión persistente. Véanse
[ADR 0256](docs/ADR/0256-r251-typed-successor-preflight-without-effects.md)
y [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6839929267).
**DEPLOY NO_GO** hasta evidencia real en el droplet; Porota intocable.

## R245 — consolidación BETA, release y aceleración CI (12/11/2026)

El candidato R245 reúne las pruebas de aceptación del panel privado, la
autenticación previa a extraer los **dos** artefactos de release, controles
*same-lease* y limpieza selectiva exclusiva de Boca. El trabajo de velocidad
mantiene los dos contextos CI requeridos y sólo permite una ruta rápida para
PR de documentación estrictamente clasificados; un cambio de código, workflow
o `main` continúa recorriendo el pipeline completo. **Un menor número de
builds no prueba menor latencia** y la release protegida sigue construyendo
sus dos imágenes desde el SHA exacto, sin reutilizar material no autenticado.

El `main` inicial de esta revisión era `3e0d6e6adbf372316aa07685575a3ed3cf3c1a98`
con cero PR abiertos; sus CI y escaneos fueron exitosos. La **última
instalación atestiguada** es `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`
(intento protegido `43217075287`); el estado físico actual exige una nueva
observación. No se considera instalada la BETA R245.
El CLI sucesor **continúa NO_GO** por falta de conexión effectful y evidencia
física durable, y el observador de recursos R188 todavía fija la instalación
histórica R186; hace falta versionarlo antes de poder afirmar despliegues
sucesivos repetibles. No disparar el APPLY antiguo R186, no tocar Porota y no
declarar GREEN por una prueba sintética. [RCA y puertas físicas](docs/ADR/0248-r245-consolidated-gates-and-followup.md).

## R187 — compatibilidad de POST desde el panel privado (12/11/2026)

Tras el reporte físico de `Origen no autorizado` al guardar `SITE_URL`, el
panel corrige la interacción entre su encabezado `Referrer-Policy` y los
formularios HTML nativos. El código candidato emplea `same-origin` para
las páginas privadas con controles, conserva `no-referrer` en la configuración
de Telegram sin formulario nativo y **no** elimina la comprobación de origen,
passkey, CSRF ni operaciones de un uso. Un envío autorizado sigue guardando la
URL sin navegarla y redirige a `/configuracion`. La aplicación efectiva y el
resultado en Chrome permanecen **pendientes de prueba física**; no confundir
TDD local con un despliegue. [RCA y decisión: ADR 0237](docs/ADR/0237-r187-mobile-origin-post-compatibility.md).

El análisis separado para acelerar CI/CD de cambios pequeños no altera aún
la promoción protegida ni la evidencia requerida para una nueva imagen.

## R186 — Cierre de instalación postcommit, 12/11/2026

Tras la reparación R185 [PR #487](https://github.com/mbalbo2023/boca-socios-assistant/pull/487),
las lecturas físicas [par #43229793525](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43229793525),
[binding #43230025523](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43230025523)
y [SQLite #43230212167](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43230212167)
certificaron el par instalado, pero el APPLY original continúa
`NO_GO/RETIRE_OLD/INDETERMINATE` con su respaldo histórico. **No repetir
el upgrade.** R186 agrega la opción manual `boca-postcommit-finalize` a la
Action Boca ya aprobada: lease nueva, journal original probado, claim de
un solo uso y eliminación exclusiva del respaldo antiguo con postflight.
[RCA y handoff detallado](docs/handoffs/2026-11-12-r186-postcommit-finalizer.md).
No hay declaración GREEN de instalación antes de CI, Action real y pruebas
del panel/passkey. El código de tokens #12 se incluye sin validar sus URL
externas por ahora.

## Transferencia de ownership y despliegue único — 12/11/2026 ART

Tincho asignó al agente activo la integración conjunta de #12 y #417,
debido al bloqueo del chat anterior. [AGENTS.md](AGENTS.md) y
[política de desarrollo](docs/DEVELOPMENT_POLICY.md) registran que el
PR funcional [#484](https://github.com/mbalbo2023/boca-socios-assistant/pull/484)
puede integrarse y desplegarse en una **única BETA con reservas
SIMULATION_ONLY** sin esperar disponibilidad real de Queue-it, un endpoint
de login Boca o validación de tokens. Por aclaración posterior del titular,
los dos flujos
reales de tokens **se incluyen y no se bloquean por falta de fuente ni por
una aprobación adicional de activación**; sin productor/transporte configurado
mostrarán su indisponibilidad y no podrán acreditar resultados reales;
el lateral de sectores requiere activación SQLite explícita posterior.

**Actualización física R183:** #484 ya fue fusionado a
`b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`; CI y seguridad de ese
commit están aprobados y la release dual
[#43215180354](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43215180354)
publicó ambos manifiestos. El primer APPLY físico autorizado
[#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287)
alcanzó el commit y falló en `RETIRE_OLD`, con limpieza INDETERMINATE.
El nuevo controlador tiene panel HEALTHY, y el nuevo worker permanece
CREATED/STOPPED sin motor, pero **no existe aceptación final del upgrade**.
Los diagnósticos READ_ONLY [R183 #43224539079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43224539079)
y [R184 #43227066989](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43227066989)
aislaron el bloqueante a **`WORKER_HEALTH_UNAVAILABLE`**: lectura del
estado Docker `Health` de un worker en `CREATED/PID0`, donde el estado puede
no existir aún. Ambos CIDs nuevos están, los antiguos no, y el respaldo
histórico conserva sus archivos. La [reparación R185](docs/handoffs/2026-11-12-r185-created-worker-health-fix.md)
propone una lectura nula segura y pruebas regresivas; **todavía falta su
verificación física y el finalizador postcommit**, sin reintentar APPLY ni
tocar Porota o Docker ajeno.

## Issue #12 — desarrollo funcional aislado (12/11/2026; CODE_ONLY, NO_GO externo)

Se recuperaron los contratos previos de **perfil/sectores del socio** y
**observación privada de Queue-it** de las ramas de #12, sin volver a incorporar
infraestructura ya presente en `main`. Esta rama agrega dos circuitos
independientes al panel privado en `/monitor/tokens`:

- **Queue-it:** observa únicamente una URL completa ya obtenida por una fuente
  autorizada, con un único parámetro genuinamente suministrado `queueittoken`;
  permite copiar el token y la URL exacta de forma privada. **No consulta,
  valida ni utiliza** la URL o el token.
- **Boca:** un contrato de autenticación bajo demanda lee las credenciales
  cifradas de un socio existente en SQLite, las descifra mediante el vault
  original y admite exclusivamente la respuesta `token`/`refreshToken`
  devuelta por un transporte explícito. **No existe endpoint inventado,
  transporte por defecto ni sesión real acreditada**.

La vista requiere passkey, permisos, origen y CSRF, presenta inicialmente solo
metadatos sin valores secretos y exige una revelación privada de un solo uso
antes de copiar. Es independiente de la navegación legacy: **no inicia el bot,
  Chromium, fila ni reserva**. Los monitores son volátiles y no guardan tokens
en SQLite. Las pruebas utilizan solamente respuestas ficticias offline.

**Stoppers de activación real — no del deploy SIMULATION_ONLY (enmienda R182):**
no hay fuente Queue-it real conectada ni
transporte/respuesta de Boca certificado; el servicio externo está indisponible
para validaciones. El perfil de sectores requiere provisión separada de su
SQLite auxiliar. Esta rama **no modifica Docker, workflows ni despliegue**.
La integración y certificación física quedan ahora bajo el mismo agente
responsable de [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
por transferencia expresa del dueño el 12/11 (sección R182 anterior);
no se exige que las fuentes reales estén disponibles para instalar la BETA
ni para incorporar y habilitar su código.

[Diseño funcional](docs/superpowers/specs/2026-11-12-issue12-functional-token-flows-design.md)
· [plan TDD](docs/superpowers/plans/2026-11-12-issue12-functional-token-flows.md)
· [handoff técnico](docs/handoffs/2026-11-12-issue12-functional-code-only.md).

## R181.2 — Cierre de imports protegidos y ruta BETA (11/11/2026 ART; corte premerge)

El [PR #483](https://github.com/mbalbo2023/boca-socios-assistant/pull/483)
corrige exclusivamente el empaquetado `PAIR_UPGRADE` tras el único intento
físico R180 [#43085794885](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43085794885),
que terminó `RECOVERED` en `REPLACE_BINDING`. El código técnico R181
`1e702669245d5ff2509902d63724aae36ac900d2` añadió cuatro dependencias
canónicas al ZIP sin modificar Cutover original ni navegación. En ese SHA,
los cuatro workflows de PR fueron SUCCESS: 7052 tests y 34 subtests
PASS, cero SKIP, RCA gate y ensayos offline IPC/systemd PASS.
**Cualquier commit documental posterior requiere sus propios checks exact-SHA**.

La [recuperación del par original](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6805276340)
fue observada por cuatro Actions READ_ONLY: controlador previo healthy en
`127.0.0.1:8443`, worker previo `EXIT1/PID0`, binding y SQLite
verificados; **no es aceptación de la nueva BETA**. Antes de desplegar:
PR READY/merge protegido, PR0 y CI/seguridad postmerge, release dual manual
nueva del main fusionado, cuatro observadores físicos frescos y una sola
`boca-pair-upgrade-apply` con SHAs/digests/release exactos. La ruta de
upgrade de par ya existente es distinta del histórico `cutover-a-apply`.
El recibo final de éxito del nuevo par exige `state=ACCEPTED`,
`cleanup=ACCEPT`, `commit_started=true` y postflight; no equivale a
`state=COMMITTED`. El [RCA y plan actual](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6805649939)
manda ante cualquier divergencia.

La aceptación real sigue pendiente hasta comprobar panel con passkey,
`SITE_URL` persistente y aplicación al worker al iniciar, controles
START/STOP del titular, IPC/PID/actividad, DNS+HTTPS del worker en red
rootless Boca aislada, socios sintéticos y SQLite. El motor no reserva
entradas reales ni ejecuta navegación del sitio; Telegram sender queda OFF
hasta rotar/custodiar el token. Multisesión por perfil corresponde a otro
scope/autor, no se duplica aquí. Ningún recurso Porota ni Docker ajeno
forma parte del despliegue.

**Las secciones R176 y anteriores que siguen son cortes históricos de
ingeniería**, no el estado actual del PR, main o droplet; verificar siempre
GitHub Actions y el issue #417 antes de cualquier efecto.

## R176 — corrección de acceso cross-UID del runner (11/11/2026; NO_GO físico)

El candidato continúa en el **único** [PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478),
sin tocar `main`. El HEAD R175 `a829b0022` confirmó **5/6 workflows
SUCCESS**: panel, contrato Telegram, escaneo Chromium/controlador, release
PR y primer despliegue de laboratorio. El sexto, CI, aprobó 6819 pruebas
Python más 34 subpruebas, Ruff/mypy y el socket anterior, pero el nuevo
ensayo multiusuario registró `BOCA_WORKER_IPC_LINUX state=NO_GO
stage=WORKER_BIND` en 0,2 segundos. Ningún host fue modificado.

El stopper APT **ya se resolvió con evidencia del runner**: tras fallar
DNS Ubuntu, el fallback R175 cambió al espejo firmado de Linux Kernel,
descargó `InRelease` de cuatro pockets Noble, compiló Chromium y pasó
Trivy. No se relajaron pins, firmas ni escaneo.

R176 trata el único rojo restante: el workspace GitHub pertenece al UID
del runner y puede no ser legible/traversable para UID10002. El smoke
descartable prepara un directorio temporal root-owned, copia **exactamente
11 archivos IPC revisados byte por byte**, con directorios 0555 y archivos
0444, y ejecuta allí `/usr/bin/python3`. Se excluyen los módulos blackbox,
credenciales y sitios; no altera los tres UID, el `SO_PEERCRED` ni el
contrato de STOP. Si falla otra vez, separa CHILD_EXIT/INODE/TIMEOUT.

La rama R176 aislada y el lote integrado aprobaron **6826 tests +34
subtests**, Ruff, mypy y política. Falta certificar el SHA final en Actions
antes de merge, censo,
release instalado o Cutover. [Handoff R176](docs/handoffs/2026-11-11-r176-ipc-runner-fixture.md).

## R175 — dos stoppers físicos confirmados en Actions; fix-forward (11/11/2026)

El candidato continúa **únicamente** en el
[PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478),
sin merge ni despliegue. El HEAD R174 real `f58aaace9` terminó con **dos
workflows aprobados de seis** (panel y contrato Telegram) y cuatro fallidos:
CI, seguridad de imagen, publicación de imagen y first-deploy. La suite
Python **6807+34** de ese mismo SHA, lint, formato, tipos, el smoke AF_UNIX
anterior y el preflight PR de first-deploy sí aprobaron. Ninguna Action
tocó el droplet ni acreditó un navegador operativo allí.

Dos bloqueantes específicos, documentados en
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6800531294),
se abordan en ramas aisladas y un único refresh del PR:

- **APT/Chromium:** cuatro runners registraron DNS Ubuntu fallido y el
  fallback R174 devolvió `SOURCES_SCHEMA`. Se toleran solo variantes
  preservadoras de fuentes Noble firmadas y se añade un código de rechazo
  sin datos sensibles; el formato exacto del fallo anterior no puede
  atribuirse sin una nueva captura física. Mantener pins y Trivy.
- **IPC entre UID reales:** el smoke nuevo devolvió `BOCA_WORKER_IPC_LINUX
  state=NO_GO` sin etapa; la librería dinámica del Python de Actions bajo
  `sudo` y otro UID es una causa probable, **todavía no comprobada**.
  R175 usa `/usr/bin/python3` solo en el runner, fuera del toolcache, y
  añade recibos de fase fijos, sin ampliar permisos del worker ni habilitar
  navegación. Sigue requiriendo confirmación exact-SHA de GitHub.

La suite local con el ajuste APT R175 dio **6816 tests PASS +34 subtests**;
la suite **combinada APT+IPC R175 dio 6819 PASS +34 subtests** y revisión
independiente sin hallazgos P0/P1. No heredar resultados a GitHub:
el candidato final todavía exige nuevas Actions exact-SHA, revisión,
protección de merge, censo rootless Boca-only y Cutover seguro. El sender
Telegram sigue OFF y **no hay reservas reales**.

## R174 — desbloqueo del CI, AF_UNIX Linux y Telegram (11/11/2026; NO_GO físico)

El único candidato continúa en el
[PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478).
El último HEAD **publicado** antes de esta corrección, `0ae6bf04`,
registró 1 de 5 workflows SUCCESS: cuatro builds de Chromium fallaron por
resolución DNS de fuentes Ubuntu antes de ejecutar smoke o escáner.
El [reporte contemporáneo de los runners](https://github.com/actions/runner-images/issues/15296)
corrobora el síntoma, sin identificar definitivamente la causa de la ruta DNS
de BuildKit. El equipo prepara un fallback **solo de build** al espejo
Ubuntu firmado de Linux Kernel Archives, conservando versiones APT corregidas
y bloqueo Trivy. Hasta verificarlo en el SHA final, **image-build es NO_GO**.
Ver [ADR0231](docs/ADR/0231-r174-browser-apt-signed-mirror-fallback.md).

Dos mejoras de alcance independiente fueron integradas **localmente**:

- Telegram rechaza identidades JSON con claves duplicadas en `getMe` y
  `getChat` usando el parser estricto existente; sender permanece **OFF**
  hasta rotar la credencial expuesta y comprobar la custodia en el host.
- Un smoke Linux de Actions comprueba socket AF_UNIX real para UID10002,
  rechazo UID10003, cliente UID10001 y STOP con cero socket; **no ejecuta
  navegación ni reservas**. El sandbox local prohíbe AF_UNIX (`EPERM`),
  de modo que el recibo real del runner sigue pendiente.

El último Cutover protegido falló en `LEGACY_SINGLETON` antes de efectos.
El `cutover-a-census` solo lectura permanece en el candidato, no en main:
hasta correrlo en el droplet desconocemos si había cero o más de un
contenedor original. La BETA integral **no se declara instalada**; no se
tocaron Porota, otros Docker ni sitios de reservas.

## R173 — candidato único en revisión; CODE_ONLY y NO_GO en el droplet

La recuperación del parche R172 y la integración de IPC, configuración
dinámica `SITE_URL`, actividad Chromium y Cutover rootless están reunidas en
el [PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478).
Cinco workflows de GitHub Actions pasaron en el primer HEAD del PR;
correcciones posteriores requieren los **cinco checks por SHA exacto**.
En el segundo HEAD `05ca4703`, la calidad Python y el panel pasaron, pero
cuatro builds de la imagen Chromium quedaron ROJOS por DNS de los repositorios
Ubuntu en runners (también en el único reintento); no se relajaron pins ni
se afirmó GREEN. El siguiente lote añade un censo rootless Boca-only de
solo lectura y un smoke de la imagen final antes de publicarla.
Los cuatro PR Dependabot #474–#477 se clasificaron y cerraron individualmente,
sin merge ni eliminación de ramas, según el [consenso de tres disciplinas en
#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6797512465).

El entrypoint de imagen es `ipc_server`, no el orquestador legacy
`ipc_worker.py`. **No se ejecutan reservas reales**: el servidor de producción
rechaza trabajo no aprobado y el nuevo simulador DOM ficticio se prueba sólo
en contenedor offline separado. Si el cierre ficticio de Chromium no puede
verificarse, el listener IPC se cierra; el panel distingue START de simulación
y URL almacenada de navegación. El panel conserva la URL en un volumen
exclusivo, impide START sin sincronización y no vuelve a usar valores por
defecto; un verificador host independiente exigirá la URL verificada antes de arrancar
el worker. La instalación V3 deja al navegador creado pero apagado, y no
demuestra navegación ni reserva. El Cutover físico anterior falló con
`LEGACY_SINGLETON` (inventario rootless sin un único controlador) y necesita
un censo **solo lectura de Boca** antes de otro APPLY. Sender Telegram OFF
hasta rotación del token comprometido.

Guía operativa vigente: [R173 en OPERATIONS](docs/OPERATIONS.md) ·
[RCA y evidencia R173](docs/handoffs/2026-11-11-r173-integration-code-only.md).
Las secciones R162/R150/R140 siguientes son antecedentes históricos, no el
estado de despliegue actual.

## R162 — `krb5-libs` estable para desbloquear la imagen del controlador (CODE_ONLY)

El escaneo de la imagen del controlador del `main=713fb9a...` detectó
`CVE-2026-107364` HIGH en `krb5-libs=1.22.2-r1` y bloqueó la publicación.
El titular propuso la versión corregida `1.22.3-r0` desde `edge`, pero Alpine
3.24 `main` ya publicó esa misma versión estable el 10/11/2026. Se incorpora
un pin específico **solo en la etapa runtime del controlador** y se conservan
los controles Trivy, SHA exacto, BLACKBOX y despliegue protegido. La corrección
en código no demuestra imagen publicada, instalación o arranque del worker:
requiere nuevas Actions y recibos físicos. [ADR0230](docs/ADR/0230-r162-controller-krb5-stable-security.md) ·
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

## R150 — W1 identificó el nombre `synthetic`; corrección de imagen en revisión

La única prueba física autorizada del worker, [Action #934](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42841239384),
confirmó `MISSING_BARE_SYNTHETIC`, `missing_module=synthetic`,
`ExitCode=1`, `OOM=false`. Docker rootless Boca pudo iniciar el proceso:
el rechazo ocurrió en la resolución del módulo Python. El recibo final
informó `controller=HEALTHY`, `engine=STOPPED`, `post_pid=0`,
`cleanup=VERIFIED`; no hubo Cutover ni intervención sobre Porota.

El candidato R150 añade al `PYTHONPATH` de `Dockerfile.browser` el directorio
del navegador, que ya estaba incluido byte a byte en la imagen. Un test RED
antes del cambio y GREEN después prueba la resolución del nombre mediante
`importlib.util.find_spec`, **sin ejecutar ni inspeccionar** `synthetic.py`
o `ipc_worker.py`. El build comprueba también el nombre bare tras el COPY.
Esto demuestra la corrección de empaquetado **solo en código e imagen**:
no acredita todavía un nuevo arranque físico del worker, IPC ni bot operativo.
No repetir el W1 #934. [RCA y recibo](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6771065839) ·
[diseño acotado](docs/superpowers/specs/2026-11-10-r150-bare-synthetic-module-design.md).

## R140 — ajuste de CI en revisión (CODE_ONLY)

El último `image-build` de CI falló en el primer intento por timeout externo
de `apt-get` y terminó GREEN al repetir únicamente ese job en el mismo SHA.
R140 permite ese reintento autenticado del CI sin flexibilizar el único
despacho del Cutover, que sigue siendo de primer intento y sin reintentos.
La BETA nueva aún no está aceptada físicamente; el `ExitCode=1` histórico
del worker no está causalmente resuelto. [ADR0228](docs/ADR/0228-r140-ci-rerun-provenance.md)

## Control del bot desde Chrome

En el perfil de operación bajo demanda, el panel privado permanece disponible en el puerto local 8443. La sesión con passkey puede pedir **Iniciar** y **Detener** en el control del bot. La pantalla distingue una solicitud recibida de un arranque comprobado. En reposo, el contenedor de navegador no tiene procesos. Las instalaciones y actualizaciones se realizan con la Action protegida.

El panel histórico volvió a quedar operativo al finalizar #921. Antes de ese intento, #920 retiró la imagen pendiente y el staging de #904. En #921, el panel candidato pasó las primeras comprobaciones, con el worker en reposo. La prueba de reinicio rechazó la respuesta de Docker al detener el candidato. La lectura del registro físico confirmó la restitución del controlador original y la limpieza aceptada. Queda por acreditar la instalación de la BETA revisada y el inicio desde Chrome. [Recibo físico de #921](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42755537951/job/129628946264) · [Ciclo de reinicio del panel](docs/ADR/0227-r139-acuse-de-parada-del-panel.md).

En #899 se capturó un error de importación interno del navegador. En #904 el panel candidato dio su primera respuesta HTTP sana con el navegador apagado y se detuvo en la fase posterior de aceptación. El laboratorio de #1095 confirmó que el activador acepta el socket de Boca después de que systemd lo crea y lo vuelve a crear. [Captura y operación bajo demanda](docs/ADR/0223-bot-bajo-demanda.md) · [Prueba en Ubuntu](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42750160590/job/129611715383).

## Diagnóstico del arranque del worker

El intento #893 terminó con código 1 antes del primer healthcheck. El laboratorio R131 reprodujo fallos distintos y comprobó la captura previa al arranque en Docker. R132 incorpora esa captura al Cutover protegido y exige verificar desde el controlador la identidad del socket del worker. La evidencia de cada ejecución física se registra en [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45). [ADR0222](docs/ADR/0222-r132-worker-start-custody.md).

## R127 — captura preparada para ExitCode=1 del worker (CODE_ONLY, no Cutover)

El #878 dejó `ExitCode=1`/OOM false y journal de shim desconectado sin
excepción interna recuperable. R127 instrumenta el **mismo** `docker inspect`
previo a la compensación para conservar cuatro categorías finitas V4
(`State.Error` presente/ausente, estado, duración y healthcheck), sin logs
privados ni lectura/ejecución BLACKBOX. El intent del workflow existente se
prepara antes del `docker start`; no hay otro host workflow ni retry.

Código en revisión; **NO_GO físico** hasta PR, tests, CI exact-SHA, release
y única transacción protegida. Véase [ADR0219](docs/ADR/0219-r127-worker-exit-v4-finite-capture-before-compensation.md).

## Histórico R125 — modo 0710 del data-root rootless: etiqueta corregida (CODE_ONLY)

La lectura auténtica de [Action #890](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42559518453)
en `main=b7e7dd77531eaf6c967b439381edd152a7a8159b` verificó
`linger=YES`, UID/GID10001, home/runtime0700, Docker rootless activo,
rangos de IDs subordinados y binarios de mapeo presentes. R124 emitió
`data_root=UNSAFE` para UID/GID10001/modo0710: es **una clasificación
equivocada**, porque Moby usa modo 0710 para la raíz del daemon.
R125 distingue `OWNER_0710` de los directorios privados 0700 y valida
la coherencia del recibo; esto **no demuestra** cuál es el data-root efectivo,
no identifica el ExitCode1 histórico ni autoriza el Cutover. No cambiar
permisos ni repetir la inspección por esta etiqueta. [ADR0218](docs/ADR/0218-r125-dataroot-mode0710-false-positive.md).

## R124 — diagnóstico READ_ONLY de `linger` y rootless Boca (CODE_ONLY)

R122 quedó **fusionado** mediante [PR #452](https://github.com/mbalbo2023/boca-socios-assistant/pull/452)
en `main=70e91f0884e054c5494c034dbe6445fc0f931160`, con cuatro workflows
del SHA previo al merge en verde. La causa interna del ExitCode1 en #878
continúa `UNKNOWN`. R124 es una ampliación **ya integrada en PR #453 y
ejecutada únicamente como lectura en Action #890** de la
inspección `inspect-prerequisites` existente: medir el estado actual de
systemd `Linger` para UID10001 y metadatos acotados de home/runtime/sockets,
configuración rootless y rangos `subuid/subgid`, sin ejecutar Docker ni
habilitar servicios. Va en un helper independiente porque el ZIP de worker
preflight tenía solamente 362 bytes de margen; no se tocan sus límites.
El home se restringe a `/home/boca-deploy`; un runner valida toda salida
remota antes de publicarla y un fallo SSH no provoca un segundo intento.
El socket Docker con escritura pública es NO_GO; el modo systemd `0666`
de sus sockets de usuario bajo runtime privado 0700 es informativo.

El `linger=YES` observado prueba solo la política actual, no la causa del
worker desaparecido. Un GID del socket distinto al GID del usuario es
informativo bajo user namespaces. **La lectura física confirmó el estado
actual de linger; Cutover/BETA/Telegram siguen NO_GO.**
[ADR0217](docs/ADR/0217-r124-linger-rootless-readonly-metadata.md).

## R122 — ExitCode=1: inferencia tipada, causa interna no recuperada (08/11/2026 ART)

El Cutover V3 histórico [#878](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583)
registró `HEALTH_EXITED`, `ExitCode=1`, `OOMKilled=false` y compensación
verificada. El supervisor había obtenido el CID exacto de `docker start` antes
de observar el proceso detenido; **eso no identifica la excepción interna**.
El stderr SSH fue descartado y no quedó traza del proceso antes de la
eliminación selectiva del worker. R122 quedó **integrado** como CODE_ONLY
tras [PR #452](https://github.com/mbalbo2023/boca-socios-assistant/pull/452):
incorpora al reporte de error de GitHub Actions una inferencia explícitamente
no causal y `worker_internal_cause=UNKNOWN`, sin cambiar Docker, SSH, el
protocolo terminal ni los dos módulos BLACKBOX. Otro Cutover y la BETA integral siguen **NO_GO**;
el diseño R123 de telemetría prospectiva no está implementado.
[ADR0216](docs/ADR/0216-r122-worker-exit-one-diagnostic-classification.md).

## R119 — Recuperación positiva no equivale a Cutover GO (08/11/2026 ART)

[R118/PR #450](https://github.com/mbalbo2023/boca-socios-assistant/pull/450)
se integró en `main=6a0aa2ea72f61e4bb6178e3cd12e9194f760d0d8`,
CI/Security postmerge GREEN y PR0. El diagnóstico físico único
[#883](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42531818647)
confirmó **RECOVERED/ACCEPT** del incidente #878: legacy Boca saludable,
worker/candidato ausentes, Stage ausente; su segundo planificador falló por
`CLEANUP_V3_ORIGINAL_UNVERIFIED`. R119 prepara un gate **solo CODE_ONLY**
para que el planner READ_ONLY admita esa compensación auténtica y exacta
sin modificar Docker, reservar, activar Telegram ni repetir Cutover. El
inventario de imágenes/volúmenes, RCA interna ExitCode1, BETA y Cutover
siguen **NO_GO**. [ADR0214](docs/ADR/0214-r119-recovered-terminal-readonly-inventory.md).

## R118 — Diagnóstico post-Cutover V3 del incidente #878 (08/11/2026 ART, CODE_ONLY)

`main=ad2ba371b2ab4d26348717f52dcd37e945ba7714` contiene el PR #449
fusionado, con CI/Security postmerge SUCCESS y cero PR abiertos al checkpoint
A45-R117. El incidente físico V3
[#42426260583](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583)
continúa `NO_GO`; `ExitCode=1/OOMKilled=NO` no prueba su causa interna.
La instrumentación **R118, fusionada en PR #450**, extendió el
observador y el inventario READ_ONLY Boca-only existentes al incidente exacto,
incluyendo el parser de recibo terminal v3. Después se ejecutó únicamente la
Action diagnóstica #883 (sin cleanup ni segundo Cutover). BLACKBOX intocado,
Telegram sender OFF, BETA integral NO_GO. [ADR0213](docs/ADR/0213-r118-readonly-inventory-after-terminal-v3.md).

## Histórico R116 — Paridad de Telegram cifrado en controlador IPC (08/11/2026 ART)

[PR #449, fusionado en R117](https://github.com/mbalbo2023/boca-socios-assistant/pull/449)
del frente #354 mantiene el único Cutover V3 y agrega a su
`docker create` del controller el `BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only`
que ya exigía el overlay Compose. El postflight ahora verifica el valor
**efectivo** en Docker Config.Env y rechaza ausencia/alteración/duplicados.
Pruebas focales antes del cambio: 226 PASS; regresiones RED observadas antes
del fix y 295 PASS tras el cambio. Suite local completa tras fijar el nuevo
pin ZIP: **5546 PASS +34 subtests**; Ruff, formato, MyPy y policy PASS.
Los controles Actions/PR exactos se encuentran GREEN en el checkpoint R117;
este resumen histórico fue redactado antes de la fusión. La regresión queda registrada en
`docs/quality/rca-lessons.json` como `RCA-354` / PR #449.

El último Cutover V3 [#42426260583](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583)
sigue `NO_GO PREPARE_WORKER/HEALTH_EXITED` con ExitCode1/no OOM, **ajeno a
esta paridad**. El legacy se observó RUNNING y el worker ausente
[#42426527816](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426527816).
No hay BETA integral instalada, ni Telegram activado; no se tocaron host,
BLACKBOX, Porota ni otros Docker. [ADR0212](docs/ADR/0212-r116-cutover-ipc-telegram-stage-parity.md)
y [continuidad #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## R114 — Evidencia de salida del worker previa al cleanup (CODE_ONLY)

El Cutover físico V3 [#42422235097](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42422235097)
falló `PREPARE_WORKER/HEALTH_EXITED`. R114 agrega al **mismo** inspect ya
existente `ExitCode` entero 0..255/`UNKNOWN` y `OOMKilled`
`YES`/`NO`/`UNKNOWN` antes de compensar, los propaga tipados por recibo
terminal v3/CLI/parser estricto y conserva `NO_GO`, no retry y limpieza
selectiva, incluso si falla la compensación. No divulga logs, Env, Mounts
ni errores Docker. Contratos v1/v2 intactos. El ZIP sigue con allowlist
exacta, digest y techo comprimido 512k; el límite descomprimido pasa de
868k a 872k sobre 869791 bytes medidos en el candidato. Ningún host fue
modificado; BETA integral **NO está acreditada como instalada**. [ADR0211](docs/ADR/0211-r114-worker-exit-before-compensation.md),
[continuidad #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## R108 — Cutover V3: imagen histórica en cuarentena probatoria (CODE_ONLY)

El inventario físico READ_ONLY [#862](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42415370909)
confirmó legacy sano, stage ausente y una imagen Boca histórica sin referencias
ni etiqueta OCI `source`. El retiro histórico específico
[#746](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42261978336)
ya falló sin recibo de borrado, por lo que no se reintenta. El cambio R108
establece una **excepción exacta y visible**: retener sólo ese artefacto
histórico, exigir la prueba de identidad en precommit y cleanup bajo lease,
y emitir `retained_attested` en un recibo V2 verificado por el runner. Todos
los demás recursos desconocidos siguen NO_GO. Se conservará deliberadamente
una imagen histórica, no se afirmará limpieza total de imágenes antiguas.

La revisión del código/CI y una nueva release dual todavía no significan
instalación. La BETA integral requiere el único Cutover V3 por Actions,
terminal físico y validación en el droplet. [ADR0209](docs/ADR/0209-r108-attested-historical-quarantine.md)
y [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

## R103 — Inventario Docker post-Cutover V3 (candidato CODE_ONLY)

El observador #858 dejó `cleanup=INDETERMINATE`: ver legacy saludable y
cero trabajadores no demuestra ausencia de imágenes ni volumen IPC. Este
censo Docker sigue pendiente aunque #860 ya acreditó `STAGE_CLEARED`; la
recuperación de Stage no es una limpieza de imágenes/IPC. El
candidato enlaza el **planner READ_ONLY existente** a V3 sin PREPARE,
derivando el CID original desde el recibo v2 y el SHA de #853 autenticado en
GitHub. Conserva el mismo workflow y selector `cutover-a-reconcile`, sin
Docker writes, eliminación de datos, nuevo alias ni cambio de controles.
Incluso una observación satisfactoria mantiene `go_for_retry=false`; un
Cutover posterior requiere evidencia y aceptación independientes. La rama,
los tests y [ADR0207](docs/ADR/0207-v3-postapply-readonly-docker-inventory.md)
son **código no desplegado** hasta su integración y recibo físico.

## Recuperación Stage V3 — propuesta CODE_ONLY

La operación existente `cutover-a-stage-recover` propone recuperar un Stage
no comprometido de un incidente V3 autenticado por GitHub; el ID numérico es
solo selector, no contraseña ni aprobación. El código propuesto exige PR0,
antirreplay por incidente, dos snapshots idénticos bajo lease y comprobación
de recibos, marcador, archivos e inode, seguidos de ACK físico. Conserva la
ruta histórica `cutover-a-stage-recover-844`. Sin escrituras Docker, navegación
ni tickets. #858 es evidencia histórica READ_ONLY, no un artifact de autorización.

Esto no acredita recuperación ni despliegue. Un Stage eliminado no autoriza
reintentar #853 ni otro Cutover; `cleanup=INDETERMINATE` requiere inventario
Boca-only separado de imágenes, IPC y capacidad. La fase reportada #853 fue
`PREPARE_WORKER`; la subcausa sigue desconocida, y las dos entradas del Stage
no la explican. Véase [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md).

## Cutover V3 — un despacho del propietario (2026-11-07 ART, CODE_ONLY)

Por instrucción del propietario, `cutover-a-apply` sustituye el antiguo
PREPARE→GO_B manual→APPLY por **un solo despacho** en Boca first deploy desde
`main`: `service=controller`; todos los SHA, imágenes, runs, legacy y
`protected_action_context` vacíos. El presupuesto revisado se fija internamente.
No copiar hashes ni solicitar correos/códigos. El workflow conserva Environment,
release dual exacta, PR0, lease rootless UID10001, passkey/loopback8443 y exige
ACK terminal más limpieza detallada del mismo intento. No hay login ni tickets.

**Esto es un cambio de código; no acredita despliegue ni resuelve por sí solo
un incidente físico anterior.** Un run fallido no se reintenta: inventario Boca
fresco y fix-forward revisado. Las instrucciones GO_B de Cutover en los
checkpoints históricos siguientes quedan sustituidas por
[ADR0206](docs/ADR/0206-single-dispatch-cutover-v3.md) y el procedimiento actual
de [operaciones](docs/OPERATIONS.md). Official-import/lifecycle no cambian.

## Histórico A45-R97 — fase Cutover todavía no probada (07/11/2026 ART)

La recuperación protegida [#848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42397473346)
desde `main=43edb1ae786b58ea832feb9e758fb99edc967d98` informó
`STAGE_CLEARED`, ACK físico `ACCEPT`, `docker_writes=0` y ninguna intervención
en servicios ajenos. La reconciliación **READ_ONLY**
[#849](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42397628309)
confirmó stage #844 **ausente**, controlador legacy único RUNNING/healthy,
binding exclusivo `127.0.0.1:8443`, cero worker/candidato, sin promoción,
`commit_started=false`, original recuperado y terminal #844 en `NO_GO`.
El marcador PREPARE `UNREADABLE/DIRECTORY` es una lectura distinta al
consumidor protegido; no prueba que el GO haya fallado.

**La BETA integral sigue NO INSTALADA.** El fallo físico del Cutover
[#844](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42388694186)
permanece sin fase causal demostrable. R97 propone una corrección estricta
**sólo al diagnóstico de Actions**: reconocer la línea legítima OBSERVE que
precede al recibo `NO_GO` para no ocultar un `FAILURE_PHASE` posterior. El
contrato, los riesgos y las regresiones están en
[ADR0205](docs/ADR/0205-r97-cutover-failure-phase-claims.md). Este trabajo
**no** autoriza reintentar #844 ni acredita otro Cutover. Sigue vigente
terminar instalación mediante release, GO exacto, operación única protegida
y aceptación física, sin tocar Porota ni los blackboxes.

---

## A45-R96 — stage exacto #844, CODE_ONLY (07/11/2026 ART)

R95 quedó publicado en `main=e3cbd38856a2aa75e9ec5e276335da0be6ed520b`
y release dual [#746](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42380223398)
SUCCESS. El único Cutover A [#844](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42388694186)
**falló** con `ssh_rc=3`, y la reconciliación READ_ONLY
[#845](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42388994569)
comprobó legacy saludable en `127.0.0.1:8443`, cero candidatos/workers,
promoción ausente, stage #844 presente y `cleanup=INDETERMINATE`.
**Nueva BETA integral NO instalada.** Nunca reintentar #844 ni reutilizar
PREPARE #843.

R96 preparó exclusivamente la **recuperación exacta del stage #844**, sin
operaciones Docker ni efectos sobre Porota/otros servicios. Nuevo alias de
un solo uso `cutover-a-stage-recover-844` fijado a #843/#844/#845,
verificador de evidencia R95, histórico REST paginado completo, antirreplay
entre commits, PR0 y ACK físico obligatorio. En aquel checkpoint R96 era
**CODE_ONLY**; la ejecución física posterior #848 figura arriba.
Contrato y siguientes comprobaciones:
[diseño](docs/superpowers/specs/2026-11-07-r96-stage-844-exact-recovery-design.md),
[plan](docs/superpowers/plans/2026-11-07-r96-stage-844-exact-recovery.md),
[operación](docs/OPERATIONS.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

---

## A45-R95 — compatibilidad STOP Docker, sólo CODE_ONLY (07/11/2026 ART)

**R94 ya fue recuperado físicamente y no debe repetirse.** El PR
[#436](https://github.com/mbalbo2023/boca-socios-assistant/pull/436) quedó
fusionado en `main=24417e457a93887a1def955aa2a283eff64c170a`, con
PR0, cuatro verificaciones PR GREEN y CI/Security postmerge GREEN. La única
Action [#839](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42379062317)
devolvió `BOCA_WORKER_RECOVERY state=CLEANED cleanup=VERIFIED` para el probe
detenido #834; legacy `RUNNING_HEALTHY`, puerto local 8443 y
`foreign=UNTOUCHED`. Artefacto `boca-worker-recovery-42375050546`,
ID `13576344307`, digest ZIP
`f0ea16f5c901854ef43e47f30c0edc5a8ac607a7ebbaeeb9eb30cd7ab0dfa28a`.

R95 propone cambiar sólo el argumento Docker STOP `--time 5` por `-t 5`,
manteniendo ACK idéntico al CID completo, cero RM ante respuesta inesperada,
un STOP y NO_RETRY. La causa física de `ACK_MULTILINE` aún no se demostró.
La nueva regresión está seleccionada en First Deploy CI. **Ningún nuevo
preflight/Cutover/GO_B/BETA integral/Telegram está ejecutado o autorizado
por esa corrección de código:** exige PR/4 checks/merge/2 postmerge/PR0,
release dual nueva, evidencia fresca y evaluación técnica independiente.
[ADR0204](docs/ADR/0204-r95-portable-docker-stop-flag.md).

---

## Histórico A45-R94 — recovery exacto del #834 ejecutado (07/11/2026 ART)

El único preflight R92 [#834](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42375050546)
falló `CLEANUP/STOP/ACK_MULTILINE` y no ejecutó RM. La inspección
[READ_ONLY #836](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42376876875)
en `main=6e75c020001c7de00faad2fcecfa171ac22e361f` confirmó CID exacto
`b2312004b4fc4e789fb58ce0c40eb2dc14ab132150d0da420657c4d29ef326d3`
detenido, seccomp ausente y legacy saludable. R94 **diseñó** sólo un RM
no forzado de ese CID, después de dos atestaciones completas y un gate
GitHub/PR0/anti-replay. Esa recuperación se **ejecutó exitosamente en #839**;
no instaló la BETA integral. La hipótesis de `--time`/ACK es independiente;
la corrección `-t` queda para R95. Sin retry del #834 ni GO para Cutover,
BETA, Telegram o terceros.
[ADR0203](docs/ADR/0203-r94-worker-834-stopped-only-recovery.md).

---

## Histórico A45-R93 — inventario protegido exacto del #834 (07/11/2026 ART)

El preflight R92 [#834](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42375050546)
falló físicamente al validar un ACK **multilínea** de STOP; `docker rm` no se
ejecutó, y el estado actual del worker/legacy permanece **NO VERIFICADO**.
La release dual R92 #741 estaba publicada y la observación previa #833 fue
READY, pero **no hay nuevo deploy, Cutover, aceptación BETA ni Telegram**.
El mismo SHA no se reintenta. R93 extiende únicamente el inspector READ_ONLY
para el contexto exacto #834: no toca Docker ni autoriza recovery. Sólo después
del PR/checks/revisión y merge podrá obtenerse un recibo físico del mismo
incidente. Véase [ADR0202](docs/ADR/0202-r93-worker-834-exact-readonly-inventory.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[continuidad #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

---

## Histórico A45-R92 — diagnóstico de STOP sin reinterpretar ACK (07/11/2026 ART)

La única recuperación R91 [#831](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42372284155)
informó `CLEANED/VERIFIED` del residuo detenido #827, manteniendo el
controller original sano. No determina qué bytes emitió `docker stop` en el
preflight fallido. R92 distingue formas de ACK (`ACK_EMPTY`, `ACK_SHORT_ID`,
`ACK_NAME`, `ACK_MULTILINE`, `ACK_OTHER_ID`, `ACK_MISMATCH`) sin imprimir
stdout/stderr privado y conserva `docker stop --time 5`; toda anomalía sigue
**NO_GO**, un solo STOP, ningún RM y ningún retry. Un PASS exige el mismo
ACK de CID completo y no ha cambiado. Ningún nuevo preflight físico,
PREPARE/GO_B/APPLY, Cutover ni Telegram se autorizan por este cambio.
[ADR0201](docs/ADR/0201-r92-worker-stop-ack-evidence.md) y
[OPERATIONS](docs/OPERATIONS.md).

---

## Histórico A45-R91 — recuperación exclusiva del probe #827 detenido (07/11/2026 ART)

La [inspección #829](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42370005970)
probó que el residuo temporal del preflight #827 está detenido y tiene CID
exacto `0ae6b61d97ccae77e8373a597f617df52b28ed63f6e49cae1df57f368e46e8e5`;
el controller original sigue sano en loopback 8443, sin seccomp residual ni
escrituras del observador. R91 **extiende el mismo recuperador R87** con
identidad fija, QA, gate GitHub #827/#829/#737/PR0/anti-replay y dos
inspecciones frescas bajo lease antes de un único `docker container rm`
no-forzado sobre ese CID. No repetir #827 ni tocar otros Docker.
**BETA integral, Cutover y Telegram siguen NO INSTALADOS/NO_GO.**
[ADR0200](docs/ADR/0200-r91-worker-827-stopped-only-recovery.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

---

## Histórico A45-R90 — #827 falló al detener el probe; inventario exacto CODE_ONLY (07/11/2026 ART; sustituido)

El único preflight R89 protegido [#827](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42368541950)
falló físicamente con `CLEANUP/STOP/ACK_MISMATCH/INDETERMINATE`, sin
`docker rm` y sin recibo de instalación. Partió de
`main=8a69d155354362e0712dab1229f7d7e4b3e24dd6`, release dual
[#737](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42361009081).
El estado del probe, seccomp y controlador original después de ese fallo **es
desconocido**. No repetir #827, no eliminar a ciegas, no PREPARE/GO_B/APPLY.

R90 **sólo propone**, desde el mismo inspector `cutover-a-worker-inspect`,
agregar el run #827 con SHA/browser digest inmutables y compuerta exclusiva
READ_ONLY. No hay inspección física #827 realizada por este código hasta
PR, checks, revisión, merge y Action específica. No se habilita recuperación
ni nuevo Cutover automáticamente; BETA integral y Telegram **NO_GO**.
Contrato, RCA, tests y siguiente paso en [ADR0199](docs/ADR/0199-r90-worker-827-exact-readonly-inventory.md),
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Histórico A45-R89 — guía de inputs para preflight único; host NO_GO (07/11/2026 ART; sustituido)

R88 quedó fusionado por [PR #430](https://github.com/mbalbo2023/boca-socios-assistant/pull/430)
(`main=15b25e753528651069323dc499b353359a5bc304`, tree
`840b6ea15c13cc33286af59c4f3e46a0e689ee24`) con CI/Security
postmerge SUCCESS. No autoriza una operación física. La guía R89
explica los **ocho inputs obligatorios** del futuro
`cutover-a-worker-preflight` y su antirreplay: incluso un despacho inválido
PRE-SSH consume la única oportunidad del SHA. **No usar el formulario
hasta verificar release dual, manifests, legado actual, PR0 y GO físico
independiente.** PREPARE de GO_B es otra operación con esos inputs
vacíos; Cutover, browser IPC real y Telegram permanecen NO_GO.
Véanse [OPERATIONS](docs/OPERATIONS.md) y [ADR0198](docs/ADR/0198-r89-one-shot-preflight-ui-guidance.md).

## Histórico A45-R88 — residuo #819 recuperado; Cutover aún NO_GO (07/11/2026 ART; sustituido)

El [PR #429](https://github.com/mbalbo2023/boca-socios-assistant/pull/429)
de R87 fue fusionado en `main=b4b72526d144f58d7577e49a32591ed304c1414d`;
CI [#1014](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42357586447)
y Security [#895](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42357586607)
pasaron sobre el SHA exacto, con **cero PR abiertos** al cierre de R87.
La única recuperación física protegida
[#823](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42357920597)
terminó **SUCCESS**: `CLEANED cleanup=VERIFIED` del contenedor temporal
detenido #819, controlador Boca original `RUNNING_HEALTHY` en
`127.0.0.1:8443`, aplicaciones externas `UNTOUCHED`. Artefacto
`boca-worker-recovery-42353468231`, id `13568895158`, SHA-256 ZIP
`c664842b8b0141961178b4bf513cd724ed950fe7b6123fc126cc133dc2efedb7`.
Los recibos y el consenso técnico previo 3/3 están en
[#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6704813361)
y [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6704813526).

**Esto NO es un despliegue de la BETA integral.** El preflight anterior
[#819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231)
falló durante `STOP` de cleanup, cuyo mecanismo preciso no está demostrado.
R88 prepara diagnósticos tipados de STOP, pruebas de carrera/ACK y una
captura privada/acotada del runner, además de eliminar comprobaciones
de aislamiento anulables con Python optimizado. Es trabajo de código y QA,
**sin otro preflight ni GO_B/APPLY autorizados por la recuperación**.
Véase [ADR0197](docs/ADR/0197-r88-worker-preflight-evidence-and-runner-hardening.md).

## Histórico A45-R87 — #819 observado detenido; recuperación acotada CODE_ONLY (07/11/2026 ART; sustituido)

R86 se integró mediante [PR #428](https://github.com/mbalbo2023/boca-socios-assistant/pull/428),
`main=2859b9d31621e3cbec70b1aec649cc281ba130f5`, con checks de PR,
CI y seguridad posteriores **GREEN y PR0**. Su única observación física
[Actions #821](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42355552701)
terminó **SUCCESS de diagnóstico `READ_ONLY_NO_GO`**, con cero escrituras:
el worker fallido #819 sigue presente **pero detenido** (CID exacto
`4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547`),
seccomp temporal ausente y controlador Boca original sano en `127.0.0.1:8443`.
No explica retrospectivamente la falla en STOP de [preflight #819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231).

**R87 CODE_ONLY** propone recuperar **sólo ese contenedor detenido** por una
única ruta protegida `cutover-a-worker-recover-819` usando recovery existente,
dos inspecciones completas y un `docker container rm` sin fuerza condicionado
a los pins exactos, finalizer y no retry. Requiere PR/CI/certificación,
consenso independiente y Action único antes de declarar limpieza física.
No equivale a BETA instalada ni autoriza PREPARE, GO_B, APPLY, navegador real
o Telegram. Véanse [ADR0196](docs/ADR/0196-r87-exact-stopped-worker-819-recovery.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Histórico A45-R86 — #819 NO_GO, diagnóstico exclusivo de lectura (07/11/2026 ART; sustituido)

El [PR R85 #427](https://github.com/mbalbo2023/boca-socios-assistant/pull/427)
fue fusionado en `main=0538b3fb29cc0245a8387b7023c394883d0ea9a8`, con
CI y seguridad postmerge GREEN, cero PR abiertos y publicación dual protegida
[#732 / 42352641660](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42352641660)
SUCCESS. Las imágenes publicadas no equivalen a una instalación.

El observador READ_ONLY [#818](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353081082)
terminó `READY`: controlador legacy original `RUNNING`, worker ausente,
`effects=none` en ese instante. El **único preflight físico posterior**
[#819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231)
**falló** con `CLEANUP/INDETERMINATE`, `primary_failed_phase=NONE` y
`cleanup_failed_stage=STOP`; el runner registró `host=UNVERIFIED`. El
`docker rm` del probe temporal **no llegó a ejecutarse** después del STOP
indeterminado. La salud y los residuos actuales **NO están verificados**:
no repetir #819, no PREPARE, GO_B, APPLY ni eliminación Docker a ciegas.

El candidato R86 extiende **sólo** el inspector protegido `cutover-a-worker-inspect`
con los pins inmutables de #819, sin instalar imagen, activar navegador ni
autorizar limpieza. Conserva el recibo `READ_ONLY_NO_GO` y refuerza la captura
privada acotada del runner. Hasta PR/CI/revisión/merge y un Action de lectura
exclusivo, **no existe inventario físico nuevo**. Referencias:
[ADR0195](docs/ADR/0195-r86-worker-819-exact-readonly-inventory.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
La BETA integral y Telegram **no están instalados/aceptados**.

## Histórico A45-R85 — QA del observador antes del próximo Cutover (07/11/2026 ART; sustituido)

En GitHub, [PR #426](https://github.com/mbalbo2023/boca-socios-assistant/pull/426)
quedó fusionado en `main=03a901d6a4415378ef581032a800bc431586d55b`,
con CI y seguridad postmerge GREEN y cero PR abiertos al corte. La publicación
dual protegida [#730 / 42349621015](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42349621015)
terminó SUCCESS con dos manifiestos asociados a ese SHA; **publicar imágenes
no significa instalar BETA**.

El único observador `cutover-a-observe`
[#815 / 42350024273](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42350024273)
terminó NO_GO en su SSH sin publicar razón tipada: el motivo físico **sigue
INDETERMINATE**. Una inspección READ_ONLY diferente
[#816 / 42350561170](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42350561170)
confirmó `original=RUNNING_HEALTHY`, `probe=ABSENT` (#807),
`socket=PRESENT_OWNED`, `seccomp=ABSENT` y `observer_writes=0`; su propio
recibo fue `READ_ONLY_NO_GO`, **no READY ni autorización de Cutover**.

**Defecto P1 adicional comprobado en TDD:** el recibo READY del host mide
**710 bytes exactos**, pero el runner sólo aceptaba hasta 640: un READY
auténtico hubiera fallado igualmente, *después* del SSH; no explica #815.
R85 es un **candidato de código aún no integrado** que exige 710 bytes
exactos, todas las comparaciones de SHA/CID/digests intactas, y clasifica
sólo códigos acotados de error del SSH/host sin publicar stderr bruto. No
cambia el observador remoto, los paquetes de Cutover/preflight, BLACKBOX,
GO_B ni Docker. Véanse [ADR0194](docs/ADR/0194-r85-cutover-observer-failure-provenance.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
**BETA integral, preflight R84, PREPARE, GO_B, APPLY, Telegram y aceptación
Chrome siguen NO_GO** hasta pruebas y recibos físicos propios. El próximo SHA
necesita su PR/4 checks/merge/PR0 y nuevo release antes de un solo intento
físico distinto; no repetir #815 ni #816.

## Histórico A45-R84 — corrección preventiva antes del Cutover (07/11/2026 ART)

La recuperación protegida [#811 / 42344899979](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42344899979)
**retiró solamente el worker detenido #807** y dejó el controller legacy
sano en `127.0.0.1:8443`, sin tocar otros workloads. R83 fusionó
[PR #425](https://github.com/mbalbo2023/boca-socios-assistant/pull/425)
en `main=f709508c64c821a5452224fb4ce7bc23d5c909a7`, con diagnóstico
dual para no ocultar la falla primaria por cleanup. La publicación protegida
dual [#727 / 42347255399](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42347255399)
terminó GREEN con dos manifests, **pero no instaló la BETA integral**.

La revisión de Infra/QA/Arquitectura/CI detectó que ese preflight R83 omitía
los límites de espacio e inodos aprobados para las dos imágenes. El diseño
R84, **candidato CODE_ONLY en este corte pre-merge**, reutiliza el helper R50 de 4 GiB
inicial, 1 GiB residual y 50.000 inodos en ambos filesystems, y exige
un solo workflow_dispatch por SHA antes de SSH. No modifica GO_B ni el
Cutover completo. Un nuevo SHA R84 requiere QA/PR/merge y **otra release
dual propia**; #727 no puede reutilizarse como imagen de ese código.
Sin observación/preflight físicos aprobados, **Cutover, PREPARE y APPLY
siguen NO_GO**. Continuidad canónica [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45),
RCA [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
y [ADR0193](docs/ADR/0193-r84-worker-storage-admission.md).

## Histórico A45-R82 — recuperación quirúrgica #807 (07/11/2026 ART)

El observador protegido R81 [#809 / 42342822240](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42342822240)
acreditó por recibo canónico que el probe temporal exacto del preflight #807
(`CID=06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d`)
**estaba detenido** (`PRESENT_PIN_MATCH`, `probe_running=false`, JSON completo
bajo límite), el seccomp temporal **ausente** y el controlador original **sano**
en `127.0.0.1:8443`. La Action fue READ_ONLY, con cero escrituras;
**no equivale a una autorización de borrado ni a un deploy**.

R82 incorpora una operación protegida distinta `cutover-a-worker-recover-807`,
un único marcador anti-replay y el recuperador R80 reutilizado con dos perfiles
estáticos. Antes de un único `docker container rm` no forzado exige cero PR,
evidencias GitHub exactas, dos inspecciones completas y lease Boca; después
verifica ausencia del ID/nombre y salud del controlador original. Cualquier
evidencia incompleta, error o ACK ambiguo resulta NO_GO/INDETERMINATE **sin
reintento**. La operación no cambia Cutover/PREPARE/APPLY ni toca otras apps,
imágenes, volúmenes o BLACKBOX. Véanse [ADR0191](docs/ADR/0191-r82-exact-stopped-worker-807-recovery.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417) y
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

**Este era el estado CODE_ONLY anterior al merge R82 y al recibo físico #811.**
La aceptación física de BETA y GO_B siguen **NO_GO**.

## Histórico A45-R81 — #807 NO_GO físico antes de #809 (07/11/2026 ART)

La recuperación protegida R80 [#806](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42340750343)
**sí eliminó y verificó únicamente el antiguo probe detenido #795**, con
`BOCA_WORKER_RECOVERY state=CLEANED cleanup=VERIFIED`, legacy sano en
`127.0.0.1:8443`, `foreign=UNTOUCHED`. El nuevo release dual
[#723 / 42340930071](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42340930071)
publicó ambos digests y manifiestos inmutables desde
`main=1199c46fee8053e637b220ad9365ce3af15eb8e5`, tras escaneos GREEN.
No se repiten ni la recuperación #806 ni el release #723.

El único preflight del nuevo par de imágenes
[#807 / 42341290485](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42341290485)
**FALLÓ** (`exit 3`) con
`state=NO_GO host=UNVERIFIED phase_claim=CLEANUP cleanup_claim=INDETERMINATE`.
La fase CLEANUP puede ocultar una falla anterior o un error de verificación
final del legacy; no demuestra que el nuevo contenedor haya quedado ni que
se haya limpiado. **Estado físico posterior de probe, seccomp y legacy:
UNVERIFIED**. No hay GO de PREPARE, APPLY ni Cutover.

R81 propone extender el observador protegido `cutover-a-worker-inspect`
**solo READ_ONLY**, con identidades exactas del nuevo intento #807 y del
histórico #795 separadas, sin nuevas primitivas Docker. La lectura acotada
comprobará nombre/CID/labels/digest del probe, tamaño del JSON sin contenido,
archivo seccomp por `lstat` y salud/loopback del legacy. Incluso un resultado
limpio permanece `READ_ONLY_NO_GO` y no autoriza reintento ni borrado. El
observador actual está fijado al #795 y **no sirve para #807 sin este cambio**.
La implementación candidata exige QA/arquitectura/infra, PR, CI y merge antes
de una sola lectura física por Actions. [ADR0190](docs/ADR/0190-r81-exact-worker-807-readonly.md),
[RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6702632026),
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6702631888).

## Histórico A45-R80 — RCA del gate pre-SSH y única continuación (07/11/2026 ART)

R79 fue fusionado como `main=d9100c6c4666c61ba66fbbefa48e61102a20ce5d`,
con CI y seguridad postmerge GREEN y cero PR abiertos. Su único dispatch
protegido [#804](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42339451485)
**falló ANTES del SSH**: el gate #37 devolvió `NO_GO reason=UNVERIFIED`, el
paso #38 de recuperación física quedó `skipped` y el verificador terminal #39
falló por ausencia de recibo. **No se eliminó el probe ni hubo Cutover**.

El RCA identificó un error en la representación de un metadato: el REST real
de GitHub entrega `run.path` sin `@main`; el validador R79 sólo aceptaba
rutas con sufijo. R80 mantiene todas las identidades históricas y añade
prueba independiente de #804 por run, job y 154 estados de pasos del REST.
Sólo se admitirá un nuevo dispatch con el título
`BOCA-R80-WORKER-RECOVER-ONCE`, después de CI, QA, Arquitectura, seguridad,
merge y cero PR abiertos; un segundo R80 o evidencia incompleta bloquea SSH.
El ejecutor, CID, presupuesto, lease y aislamiento del host **no cambian**.

R80 **no** es un re-run de #804, no es permiso de Cutover y no autoriza
Telegram ni reservas reales. Ver [ADR0189](docs/ADR/0189-r80-github-rest-pre-ssh-recovery.md),
[issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
y el checkpoint de continuidad [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Histórico A45-R79 — recuperación exacta del probe detenido (07/11/2026 ART)

La [Action #802 / 42337103473](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42337103473)
confirmó bajo el socket Docker rootless Boca que el contenedor temporal del
preflight fallido #795 **existe, está detenido**, tiene identidad histórica
coincidente y JSON bajo el límite de inspección; su seccomp temporal está
ausente. El controlador anterior conserva el CID atestado, salud y el puerto
único `127.0.0.1:8443`. El diagnóstico fue **READ_ONLY_NO_GO**, no hizo limpieza.

R79 desarrolla una operación manual separada `cutover-a-worker-recover`,
protegida por GitHub Actions, para **un solo** `docker container rm` del CID
histórico completo, únicamente tras dos inspecciones frescas de identidad,
aislamiento y legacy saludable. Todo fallo previo impide tocar el contenedor;
un resultado posterior ambiguo prohíbe reintentar a ciegas. Un identificador
único de ejecución y su historia de Actions bloquean un segundo dispatch, aun
desde otro SHA. El transporte es
un ZIP mínimo SHA256/memfd con allowlist separada, sin agrandar el bundle de
Cutover. [ADR0188](docs/ADR/0188-exact-stopped-worker-recovery.md) define
alcance, límites, evidencia y siguiente cadena de gates.

**Resultado R79:** código, revisiones y CI certificados; ejecución física
rechazada por el gate pre-SSH del run #804. No hay limpieza verificada,
Cutover autorizado ni BETA instalada.
La autorización previa del propietario continúa vigente; no se alteran otras
aplicaciones, Docker ajenos o los dos módulos de navegador BLACKBOX.

## Histórico A45-R78 — observación diferencial candidata (07/11/2026 ART)

`main=0f5f0542364777a2926583f2c5dbd3fd25dfa31f` era la referencia al
iniciar R78; **este párrafo no certifica el SHA actual ni un deploy nuevo**.
El último diagnóstico físico verificado, [run #800](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42332735732),
continuó en `READ_ONLY_NO_GO`: CID temporal candidato identificado, pero
`docker inspect` del probe falló y la limpieza de #795 sigue indeterminada.
El controlador anterior fue visto en loopback 8443 en ese momento; no se
presupone que su estado siga igual.

R78 propone **sólo** observar el mismo intento fallido mediante cuatro
consultas rootless acotadas: nombre exacto, campos compactos del probe sin
HEALTHCHECK, tamaño —nunca contenido— del inspect JSON completo y lectura
independiente del controlador anterior. El diagnóstico siempre emite
`READ_ONLY_NO_GO`, incluso si todas las consultas son exitosas; los límites
de `stdout` y `stderr` se aplican durante el proceso. Un fixture de Docker
sin iniciar verifica los formatos únicamente en un runner descartable de
GitHub Actions. No hay permiso implícito para borrar, reintentar Cutover,
acceder a otras aplicaciones o declarar la BETA instalada.

Fuentes de trabajo: [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417),
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6701580297)
y [ADR0187](docs/ADR/0187-failed-worker-preflight-readonly-diagnosis.md).
Los 85 issues abiertos requieren cierre individual contra evidencias; no
equivalen a 85 implementaciones faltantes. Cero PR abiertos al comenzar R78.

## Estado físico A45-R77 — diferencial READ_ONLY posterior al recibo #798

El diagnóstico [#798 / run 42331553991](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42331553991)
corrió en `main=ff64eb4af52629fa4344d008d58bec83c01489be` y registró
`socket=PRESENT_OWNED`, `seccomp=ABSENT`, `probe=PRESENT_UNVERIFIED`,
`docker=READ_FAILED`, `original=UNVERIFIED`, `observer_writes=0`.
**No acredita limpieza ni la caída del controlador anterior.** El inventario
confirmó que la búsqueda por nombre exacto de probe devolvió un candidato,
pero una inspección posterior falló sin distinguir si ocurrió en probe u
original: ambos estaban dentro del mismo bloque `try`.

**Corrección candidata R77:** dividir los tres pasos de lectura (lista del
probe, metadata del probe e inspección del controlador legacy) en observaciones
independientes con estados/exit codes acotados, conservar CID candidato
**no autoritativo**, y consultar únicamente `docker inspect --format '{{.Id}}'`
por el **mismo CID** si el inspect completo devuelve `CalledProcessError`.
El resultado del formato mínimo **no demuestra RCA de plantilla** ni habilita
limpieza, retiro de imágenes o Cutover. Ver
[ADR0187](docs/ADR/0187-failed-worker-preflight-readonly-diagnosis.md),
[issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

## Estado físico A45-R76 — incidente preflight worker (06/11/2026 ART)

La certificación previa del candidato [PR #415](https://github.com/mbalbo2023/boca-socios-assistant/pull/415)
incluyó 4036 pytest +34 subtests, cuatro perspectivas técnicas con dictamen
GO CODE_ONLY y cinco checks PR verdes. Se fusionó como
`main=92624ed6b7e75c6010f59670c866df00a29766dd` (0 PR abiertos) y
publicó el par de imágenes en
[#42329201039](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329201039).
Es evidencia del **código y release**, no de instalación física.

El **primer preflight físico de ese par**
[#42329475083](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329475083)
terminó `CLEANUP=INDETERMINATE`; el observador de APPLY histórico
[#42329673385](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329673385)
no pudo producir un inventario físico. No hay aceptación del nuevo Cutover,
ni prueba de limpieza ni de nuevo Chrome/Telegram. El controlador anterior
es el último comprobado sano y **no se declara su salud actual sin medición**.

**Candidato de corrección de observabilidad R76:** un único diagnóstico
`cutover-a-worker-inspect` READ_ONLY para el intento exacto #42329475083,
con taxonomía separada de Docker rootless, seccomp, probe y controlador viejo,
sin acciones Docker mutantes. Hasta CI/merge/ejecución no existe resultado de
esa nueva observación. [ADR0187](docs/ADR/0187-failed-worker-preflight-readonly-diagnosis.md)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6701097095).
No repetir preflight/APPLY ni tocar Porota, otras aplicaciones o BLACKBOX.

## Histórico A45-R70 — RCA Cutover y ciclo de ingeniería (06/11/2026 ART)

**Código verificado:** PR [#413](https://github.com/mbalbo2023/boca-socios-assistant/pull/413)
fusionado en `main=cc7f90d531df36d04b821d6e85cd1e7f56ba8559`.
Sus cuatro pipelines PR pasaron y los controles post-merge
[CI #42323067910](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42323067910)
y [Security #42323067907](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42323067907)
son GREEN. **La BETA NO está desplegada**: Cutover #778 terminó NO_GO
sin recibo final ACCEPT. Stage #778 fue limpiado puntualmente en
[#788](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42319964660)
y observado ausente por
[#789](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42320122399).
El controlador anterior sigue sano en `127.0.0.1:8443`; ~39,77 GB
libres, sin repetir cleanup de otro frente.

**RCA comprobado:** el exit3 de Cutover #763/#770/#778 NO demuestra una
falla de transporte SSH ni identifica su causa física. #413 informa
`SSH_255/TIMEOUT/EXIT_NONZERO` y `host=UNVERIFIED` cuando falta el ACK.
R70 propone tipificar también la **etapa reportada**, con vocabulario fijo
y sin secretos: es solo diagnóstico, no recibo físico. GO, singleton,
lease, imagen exacta y aceptación final siguen intactos. Se requiere
un preflight rootless/worker reversible antes de intentar otro APPLY.

**Backlog (foto R69):** 59 PR abiertos, 56 DRAFT y 41 con base distinta
de `main` (33 sobre rama integral divergente). #4, #302, #309 y #3
se cerraron con motivos auditables, sin borrar sus ramas. #412 reconstruyó
`Dockerfile.browser` en cuatro workflows paralelos (~295 s sumados de runner).
Reducir esa redundancia exige benchmark de cache o artefactos inmutables,
con aislamiento de confianza PR/main. La autorización general del titular
sigue vigente. No tocar los dos módulos BLACKBOX, Porota ni otros servicios.

Regla 84: [#45 R68](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6700063353),
[#45 R69](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6700225904)
y [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md).

## Histórico — R62 antes de recuperar físicamente Stage #778 (06/11/2026 ART; corte sustituido)

El `main=a8b577161288fe653fef65d3d5890f3661fb15d4` publicó release
dual [#704](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42309505084)
y PREPARE [#776](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42309967399)
ambos GREEN. El Environment protegido fue vinculado al SHA256
`27c24d339110241992c23fbbc8d443957cdf146af37e4b300e2341594fe5a89f`.
El único Cutover A [#778](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42317092809)
pasó GO_B pero el host SSH terminó exit 3, sin aceptación de BETA nueva.
**No reintentar #778 ni usar PREPARE #776 otra vez.**

La reconciliación Boca-only READ_ONLY
[#779](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42317342897)
confirmó `stage=PRESENT`, `STAGE_ROOT_ENTRIES` (dos entradas),
`intent/result=PRESENT`, `cleanup=INDETERMINATE`,
`commit_started=false`, `original_restored=true`, sin candidato,
worker ni promoción. Continúa saludable el único controlador legacy exacto
`27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
en `127.0.0.1:8443`. Disco 39.770.513.408 B e inodos 7.437.094
libres; el cuello de botella previo de capacidad está resuelto.
`prepared_go_marker=UNREADABLE/DIRECTORY` describe la identidad/permisos
del **directorio padre** de un volumen rootless desde el host, no el tipo
real del marcador ni la causa comprobada de exit3.

El [PR R62 #412](https://github.com/mbalbo2023/boca-socios-assistant/pull/412)
propone **solo** reasignar los tres pins del Stage recovery #778/#776/#779
y añadir al observador READ_ONLY dos booleanos derivados del recibo durable
(`worker_id_recorded`, `candidate_id_recorded`), para acotar la fase
anterior a la falla sin exponer IDs ni operar Docker. Hasta CI, revisión,
merge, observación de fase y ACK físico `STAGE_CLEARED`, Stage sigue
en cuarentena. No tocar imagen histórica incierta (`sha256:a44453ab...`);
su intento de retiro exclusivo #746 ya falló y no se repetirá. Prohibidos
cleanup amplio, BLACKBOX, navegación real, Porota u otros servicios.
**La BETA integral aún NO está desplegada.** Nuevo APPLY requiere RCA y
nueva release/PREPARE/GO del SHA definitivo.
Ver [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md)
y [Regla84 #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6699518071).

## R57 — recuperación de Stage del Cutover #770 (06/11/2026 ART, CANDIDATO CODE_ONLY)

La recuperación R55 del Stage del incidente #763 quedó completada físicamente
por la ejecución protegida #766; su observer independiente #767 confirmó
`stage=ABSENT` antes del nuevo intento. El PREPARE
[#768](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42277201326)
terminó `success`; el APPLY protegido
[#770](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42307268117)
pasó el GO_B pero su único SSH remoto devolvió código 3 sin ACK terminal
aceptado. **No repetir #770 ni declarar instalada la BETA integral.**

La reconciliación física READ_ONLY independiente
[#771](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42307426818)
terminó `success`: Stage presente (`root_entries_count=2`),
`commit_started=false`, sin promoción, candidatos ni workers, y controlador
legacy CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`
`healthy` en `127.0.0.1:8443`, con servicios externos intactos. Dos entradas
no autentican el contenido del Stage ni prueban la causa del `exit3`.

R57 solo reasigna los tres IDs protegidos de `cutover-a-stage-recover` a
#770/#768/#771 y añade pruebas/documentación. Conserva pins de image-retire,
lease, doble observación, autenticación de hashes/markers y ACK físico. Hasta
PR, CI, revisión, merge y recibo `STAGE_CLEARED`, **Stage continúa en cuarentena**.
La limpieza de disco tiene otro dueño; esta rama no crea operaciones Docker,
no toca el instalador, BLACKBOX ni servicios externos. Un futuro Cutover
necesita release/PREPARE/GO_B nuevos y evidencia de admisión propia.
Véase [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Histórico — R55, Stage del Cutover #763 (06/11/2026 ART)

La ruta de recuperación R53 [#760](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273287046)
dejó `STAGE_CLEARED`/`physical_ACK=ACCEPT` para el incidente #757, con cero
escrituras Docker y sin afectar Compose ni servicios ajenos. La observación
[#761](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273489927)
comprobó `stage=ABSENT`, controlador legacy original sano y solo el puerto
`127.0.0.1:8443`.

El release dual [#700](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42273375991)
publicó ambos digests desde `main=bc2d31669da5f360a659de896041ac3619ce2ce9`.
GO_B PREPARE [#762](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274019739)
produjo `READY`, con SHA256 independiente `f8291f8d9033fc4bf83ef22649f27db1c1b1afd588d4ed55790c00571a1689d7`
configurado y comprobado en el Environment protegido. El APPLY
[#763](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274349061)
pasó ese preflight pero volvió a terminar con salida SSH 3 y sin ACK físico
`ACCEPTED`. **No reintentar #763: la BETA integral no está instalada.**

El nuevo observador independiente READ_ONLY
[#764](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42274552585)
registró `stage=PRESENT`, `root_entries_count=2`, `commit_started=false`,
sin promoción, sin candidato ni worker y sin tocar recursos extranjeros. El
controlador original `27ef39ed49d2…` permanece `healthy/running` en loopback
8443. La causa precisa del remoto `exit3` **sigue sin probarse** por los
recibos disponibles; la observación de capacidad no identifica por sí sola
el punto de fallo. Por indicación del propietario, la limpieza de disco tiene
otro dueño: este PR **no ejecuta ni amplía** operaciones de limpieza.

R55 cambia solo los pins exactos `cutover-a-stage-recover` a #763/#762/#764
para efectuar una única recuperación bajo lease, identidad de Stage y
postverificación física. No modifica los tres pins de image-retire, los gates
de instalación, imágenes, datos, BLACKBOX o recursos externos. Hasta CI,
revisión, merge y un nuevo recibo físico `STAGE_CLEARED`, el Stage permanece
en cuarentena. **La recuperación no autoriza reintentar ese APPLY**; un
Cutover futuro necesitará release/PREPARE/GO nuevos del `main` definitivo.
Véase [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Histórico — R53, recuperación exclusiva del Stage de Cutover #757 (06/11/2026 ART)

El Stage de #750 fue recuperado físicamente por [#754](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269139909):
`STAGE_CLEARED` y `physical_ACK=ACCEPT`, sin cambios en Docker ni en otros servicios.
La reconciliación [#755](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269530227)
confirmó `stage=ABSENT` y el controlador original sano. Tras publicar la
pareja de imágenes [#698](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42269631510)
para `main=70f374e273093007319b007e7ca22aff7cb75c4f`, el PREPARE
[#756](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270247581)
fue `READY` y el GO_B independiente verificado; el APPLY
[#757](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270552485)
volvió a salir con código 3 sin ACK `ACCEPTED`. **La BETA nueva aún no se instaló.**

La auditoría independiente [#758](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42270841732)
registró `stage=PRESENT`, sin promoción, sin candidato ni browser worker,
`commit_started=false`, un único controlador original `healthy/running` en
`127.0.0.1:8443` y ningún efecto extranjero. La capacidad observada fue
3.370.475.520 bytes; el piso previo a descargar el par de imágenes sigue
siendo 4 GiB. La relación temporal es compatible con rechazo de admisión,
**no prueba por sí sola el RCA del exit 3**. El usuario indicó que la limpieza
de disco se trabaja por otro frente: Boca no tocará esos recursos.

Este cambio mueve **solo** los pins de recuperación `cutover-a-stage-recover`
a #757/#756/#758, sin flexibilizar el contrato del instalador, ni modificar
las rutas de retiro de imágenes o el navegador protegido. Requiere CI,
revisión, merge y **un único** ACK de recuperación; no reintentar #757 ni
ejecutar operaciones de Docker globales. Para el próximo Cutover será
necesario un release/PREPARE/GO nuevos del SHA que quede en `main`.
Véase [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md).

## R51 — recuperación exacta de Stage del Cutover fallido #750 (06/11/2026 ART, CANDIDATO)

El release dual inmutable [#696](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42257733717)
quedó publicado para `main=96cd69518488e9dabdec9af15c50915e6b4c136e`.
El PREPARE [#748](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42262494064)
y el GO_B independiente pasaron; el APPLY [#750](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42266188095)
alcanzó el droplet pero devolvió código 3 sin ACK final. **La BETA integral
NO está instalada.** La reconciliación física READ_ONLY
[#752](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42267016352)
confirmó original sano en `127.0.0.1:8443`, ningún candidato/worker,
`commit_started=false`, y Stage del intento presente con limpieza
`INDETERMINATE`. Sus dos entradas en el directorio raíz son posteriores al
fallo; **no identifican su causa**. Hay 3.370.577.920 bytes libres (3,14 GiB),
menos que el piso de 4 GiB para comenzar un nuevo pull, y el Docker rootless
solo reporta 17,11 MB recuperables, insuficientes para cubrir la diferencia.

Este candidato cambia **únicamente** los tres pins exactos de la operación
protegida `cutover-a-stage-recover` a #750/#748/#752. Reutiliza la autenticación
de Stage por marcador/hashes, el lease exclusivo, el runtime healthy y la
verificación postoperación; nunca efectúa Docker writes ni afecta otros
servicios. Hasta PR, CI, revisión, merge y un ACK `STAGE_CLEARED` real,
**no recuperar ni repetir APPLY**. La ruta de borrado de imagen histórica
mantiene sus pins propios y `NO_GO`; debe resolverse la capacidad y la fase
inicial de fallo por evidencia antes de otro release/GO. Véase
[ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md) y
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6691861925).

## R50 — corrección candidata de admisión dual y estado físico (06/11/2026 ART)

El Stage abandonado del APPLY [#740](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42249350458)
**ya fue recuperado**, con ACK `STAGE_CLEARED` en el run protegido
[#743](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254252830).
El observador posterior [#744](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254498237)
confirmó `stage=ABSENT`, Compose original inalterado, **único controller
legacy sano en 127.0.0.1:8443, sin worker ni candidato**, y cero escrituras
Docker de la recuperación. La limpieza histórica Docker sigue indeterminada;
el APPLY viejo permanece NO_GO y **no debe repetirse**.

R50 corrige en código `_browser_pull_both`: el par controller + browser
requiere **4 GiB antes del primer pull** y **1 GiB + 50.000 inodos entre
los dos pulls y después del segundo**, siempre en ambos paths validados y
con verificación de identidad de filesystem. Antes se reimponían 4 GiB
antes del segundo, aunque ya se hubiera descargado el controller. La
contradicción está reproducida por test; **no está probado que sea la
causa física de la salida 3** del run #740. El fix sigue sin PR/CI/release
ni despliegue en este corte; consultar [ADR0183](docs/ADR/0183-postpull-boca-beta-emergency-residual.md)
y [RCA #386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386).
No se modifican módulos BLACKBOX, sesión/DB, imagen instalada, otros Docker
ni puertos. Solo una nueva secuencia exact-SHA y un ACK físico pueden declarar
la BETA integral instalada.

## Histórico — Cutover A #740 y preparación R49 antes de recuperar Stage

El `PREPARE` físico [#739](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42246824073)
pasó con source `f3a8841817307daa084fe0472720f4444235c9bb`. Su `APPLY`
[#740](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42249350458)
superó el GO protegido, pero el SSH terminó con código 3; **NO hay BETA
integral instalada ni aceptación Chromium**. El observador READ_ONLY
[#741](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42250420345)
encontró el controlador original sano en `127.0.0.1:8443`, sin worker ni
candidato, `commit_started=false`, Stage del intento presente, resultado
`NO_GO` y limpieza `INDETERMINATE`. Hay 4.833.996.800 bytes libres, dos
imágenes en Docker Boca y ninguna autorización para borrar la histórica
incierta. El valor `prepared_go_marker=UNREADABLE/DIRECTORY` **no acredita
que el marcador sea un directorio**: la inspección host del volumen exige
UID 10001, pero el directorio rootless se observó con UID host 175536.

El candidato R49 cambia **solo el gate protegido** de recuperación Stage
para los tres runs exactos #740/#739/#741, con comprobación independiente
de identidad, recibos y SSH/ACK; conserva el retiro histórico de imagen
con sus pins propios. Hasta CI, revisión, merge y ACK físico `STAGE_CLEARED`,
no recuperar ni reintentar Cutover. Aun después habrá que diagnosticar la
fase anterior a la creación del worker y resolver la imagen incierta antes
de un PREPARE/GO/APPLY **nuevos**. Sin borrar datos/volúmenes, BLACKBOX,
Porota ni otros Docker. Ver [ADR0184](docs/ADR/0184-exact-incident-uncommitted-stage-recovery.md)
y [RCA #386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386).

## Histórico — Candidato R40, reemplazado en la admisión dual por R50

El propietario autorizó levantar **solo el piso de 4 GiB después del pull**
de Playwright completo. El cambio propuesto desde `main=d4d2b2a6769d867097d31c08364ac33829354da7`
mantiene **4 GiB antes de cada imagen** y exige **1 GiB restante + 50.000
inodos** después de cada descarga, al terminar Cutover/BETA y durante el
ciclo de la BETA instalada. La identidad y topología Docker rootless,
sha/digests, BLACKBOX, puerto 8443 y limpieza selectiva permanecen. No es
instalación real: faltan PR/QA final, nuevo release de SHA exacto, PREPARE,
GO B independiente, APPLY y ACK del droplet. Véase [ADR0183](docs/ADR/0183-postpull-boca-beta-emergency-residual.md)
y [capacidad #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).
Los cortes R21 siguientes son históricos y no representan el HEAD actual.

## Corte de entrega A45-R21.21 — 05/11/2026 ART (CÓDIGO CONSOLIDADO; NO DEPLOY)

- **Candidato único:** [DRAFT #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319), HEAD `3cbe31703d74413f8de66ac8783ec68b1b7f8a87`, TREE `208a75e0c7310ea25db55ca509563f0b57972f42` verificados; conserva los overlays previos y ahora incorpora #372 (postflight cleanup Boca **solo Cutover A**), #375 (observadores host READ_ONLY Cutover/import), #374 (WebAuthn UV fresco Telegram, **sender OFF**), #376 (GO_B Cutover/import de dos despachos). Las fuentes satélite tienen 4/4, 4/4, 6/6, 4/4 Actions verdes respectivamente, **no heredables al SHA #319**.
- **QA del corte #319:** **7/7 GitHub Actions COMPLETED SUCCESS exact SHA R21.21**: [CI 42064964129](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964129) **3718 pytest PASS +34 subtests**, Ruff/format547/MyPy128/image-build PASS; [FirstDeploy 42064964223](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964223) PR-validation + runtime-smoke SUCCESS, **host SKIPPED**; [Release 42064964145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964145) validación SUCCESS, **publish SKIPPED**; [Panel 42064964232](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964232), [News 42064964239](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964239), [Telegram 42064964156](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964156), [Security 42064964402](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964402) SUCCESS. Artifacts de CI/FirstDeploy/Release consultados: **0**; no recibo físico ni imagen publicada. Predeploy del SHA definitivo, revisión de artefactos, merge único, publicación de release inmutable y operación física **NO ejecutados**. `main=cabce9f1e452e63ded115f447559a358dc0f4d1b` sigue controller legacy instalado/aceptado 04/11 y accesible Samsung Chrome+Termius+passkey; la BETA integral **no** está instalada.
- **Funciones disponibles SOLO EN CÓDIGO:** Cutover/official import GO B por [workflow Boca único](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml): PREPARE con una observación host READ_ONLY Boca, artifact y GO independiente; APPLY posterior con **únicamente ID corto PREPARE**. Para START/STOP bot/Chromium se exige REQUESTED→PREPARE→GO→APPLY con UUID/ACK físico exacto. Telegram ya exige passkey WebAuthn fresca para stage cifrado, pero activación real/egress y ACK **NO_GO, sender OFF**. Import oficial solo informativo (no actionable).
- **Limpieza:** #372 transporta bytes/inodos e IDs exactos en ACK postflight de Cutover A PASS/FAIL/RECOVERED; **no** demuestra cleanup del droplet ni habilita las otras seis instalaciones legacy (bloqueadas pre-SSH). La regla del dueño exige limpieza selectiva Boca-only después de cualquier deploy futuro PASS o FAIL, preservando todos los recursos ajenos/compartidos.
- **Puertas NO_GO:** faltan GO físico específico de merge/release/Cutover/Telegram y variables Environment configuradas/comprobadas sin exponer secretos, PREPARE/ACK reales, release digest, aceptación sesión Chrome persistente/alta simulada, lifecycle y recibos de Docker. **No pedir terminal ni PIN**: [pasos Samsung](docs/OPERATIONS.md), [matriz Rule84](docs/BETA_INTEGRATION_STATUS.md) y [plan de entrega](docs/BETA_DELIVERY_PLAN.md). Seguridad adicional P2.
- Sin reservas/compras reales, backups, migración legacy SQLite a 0008, BLACKBOX, Porota, otros Docker/puertos ni HTTPS; solo `127.0.0.1:8443`. Este documento es **foto CODE_ONLY exacta R21.21**, no release ni autorización de host; todo commit siguiente exige QA nueva.

## Histórico — Corte verificado A45-R21.17 — 05/11/2026 ART (CÓDIGO, NO DEPLOY)

- **Instalación física actual:** solo controller legacy `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`, aceptado 04/11. Tincho verificó Samsung Chrome + Termius + passkey para ESA versión. No acredita la BETA integral ni la persistencia de sesión del candidato.
- **Candidato único:** [DRAFT #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319), HEAD `82c7c3edf75911805218149d4907ecb37b374a66`, TREE `d6ca906f517571c0025cce7780b674cdc3956fc3`. Incluye las mejoras CODE_ONLY #349/#350, #353/#355, #356/#358, GO de ciclo #359/#361, observador #369, flujo móvil #370 y consumidor GO B #368; **ninguno está integrado en main ni desplegado**.
- **QA exacta R21.17:** **7/7 GitHub Actions COMPLETED/SUCCESS**, [CI 42056912053](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056912053) **3645 pytest PASS +34 subtests**, Ruff/format (530 archivos), MyPy y build offline; [FirstDeploy 42056911736](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911736) PR-validation/runtime-smoke PASS con host **SKIPPED**; [Release 42056911857](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911857) validación PASS con publicación **SKIPPED**; [Panel 42056911656](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911656), [News 42056911678](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911678), [Telegram 42056911612](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911612), [Security 42056911673](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911673) SUCCESS. Ningún artifact de CI/FirstDeploy es recibo de host.
- **P0 NO_GO físico:** [#371](https://github.com/mbalbo2023/boca-socios-assistant/issues/371) prepara el enlace GO B de Cutover A/import oficial PREPARE→APPLY, aún sin PR al corte; [#362](https://github.com/mbalbo2023/boca-socios-assistant/issues/362) exige prueba real de passkey/attestor + egress Telegram bajo lease; START/STOP bot/Chromium requieren PREPARE, GO independiente y ACK físico exacto. La validación final de SHA, merge/release, Cutover, import, Telegram y aceptación Chrome/Termius/Docker queda pendiente.
- **Operación:** sin nuevo GO de merge/release/deploy, SSH effectful, compras/reservas, backups, migración legacy SQLite a 0008 ni hardening extra P2. BLACKBOX intocable, ningún servicio/volumen Docker ajeno y únicamente `127.0.0.1:8443`. Limpieza Docker posterior a cualquier deploy PASS o FAIL exclusivamente Boca, con inventario/recibo.
- **Guía de GO y entrega:** [plan de aceptación](docs/BETA_DELIVERY_PLAN.md), [operaciones Samsung sin terminal](docs/OPERATIONS.md) y [matriz Rule84](docs/BETA_INTEGRATION_STATUS.md). Este es **un corte histórico exacto de código**: si #319 cambia, exigir nuevas Actions terminales y actualizar evidencias antes de overlay/release.

## Histórico — Corte operativo vigente — 05/11/2026 ART (A45-R12 / R21.11 provisional)

- **Estado real del host:** la versión **legacy** de `main` (`cabce9f1e452e63ded115f447559a358dc0f4d1b`) fue instalada y aceptada el **04/11**, con validación de **Samsung Chrome, Termius y passkey**. Esto **no equivale** a la BETA integral desplegada.
- **Candidato único:** [DRAFT PR #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319), corte de desarrollo **R21.11 provisional**, HEAD `5903ded0790ab7254bf68572af47fe75c6e08889`. **No fijar este SHA como release**: quedan integraciones posteriores.
- **Evidencia verificable del corte:** **3.437 pruebas PASS +34 subtests**; **7/7 Actions GREEN**: [CI 42044959831](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959831), [Imagen 42044959889](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959889) (publicación omitida), [Seguridad 42044959974](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959974), [Noticias 42044959895](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959895), [Panel 42044959814](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959814), [Telegram 42044959805](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959805) y [FirstDeploy 42044960073](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044960073) (etapa host manual omitida). Verde de CI **no es ACK físico del host**.
- **Integrado en código, aún no validado en host:** [#349](https://github.com/mbalbo2023/boca-socios-assistant/pull/349) importación oficial por Actions y [#350](https://github.com/mbalbo2023/boca-socios-assistant/pull/350) STOP persistente; correcciones P0 asociadas a [#353](https://github.com/mbalbo2023/boca-socios-assistant/issues/353) Telegram y [#355](https://github.com/mbalbo2023/boca-socios-assistant/issues/355) Compose. Verificar los overlays siguientes de #356/#358/#352 en el HEAD definitivo.
- **Pendiente de aceptación:** ACK físico de controles bot/Chromium [#356](https://github.com/mbalbo2023/boca-socios-assistant/issues/356), workflow protegido [#352](https://github.com/mbalbo2023/boca-socios-assistant/issues/352), y activación de Telegram tras despliegue, incluyendo backend, egress y custodia; QA/predeploy del candidato consolidado y GO específico para merge, release y deploy.
- **Gobierno:** sin GO nuevo, sin SSH ni release/deploy nuevos. Seguridad adicional **P2**. BLACKBOX `synthetic.py` y `ipc_worker.py` intocables; sin migración legacy a esquema 0008, compras/reservas reales, backups, nuevos puertos o HTTPS. Solo `127.0.0.1:8443`; no interferir Porota ni otros servicios. Limpieza Docker **selectiva** tras cualquier deploy exitoso o fallido.
- **Regla 84:** priorizar el [checkpoint canónico de #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6660565397) y reconciliar esta fotografía documental cuando las integraciones siguientes cambien el HEAD. Las secciones anteriores, rotuladas **Histórico**, no describen necesariamente el estado vigente.

## Histórico — Nuevo corte de desarrollo — 04/11/2026, después de las 19:20 ART

El propietario **confirmó acceso exitoso en Samsung Chrome** al panel privado
`http://localhost:8443` mediante Termius y passkey. Es una observación humana
puntual: **no** demuestra persistencia de sesión al reiniciar Chrome ni la
salud de un worker navegador. El controller-only instalado permanece anclado
al `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`; los avances siguientes
son **candidatos de código, no desplegados**.

Autorizadas: **Telegram privado** (#315, [PR DRAFT #317](https://github.com/mbalbo2023/boca-socios-assistant/pull/317)),
**pausa/reanudación general de simulaciones** y retiro de Site del panel
(#313, [PR DRAFT #318](https://github.com/mbalbo2023/boca-socios-assistant/pull/318)), y **fuentes oficiales de eventos/categorías/horarios**
(#314, [PR DRAFT #316](https://github.com/mbalbo2023/boca-socios-assistant/pull/316)).
La transición del controller hacia el worker navegador sigue en #227
([PR DRAFT #310](https://github.com/mbalbo2023/boca-socios-assistant/pull/310));
el [PR DRAFT #320](https://github.com/mbalbo2023/boca-socios-assistant/pull/320)
agrega observación de identidad histórica y compensación modelada, pero **no**
existe cutover físico aprobado ni instalado. La candidata integral conecta
`/telegram/emparejar` a la sesión autenticada y añade resolución privada de
chat por Bot API, pero exige recibo público de custodia y un workflow protegido
de instalación V2; **no** recibió token real ni envió aviso. Esta ruta tampoco
está desplegada en el panel actual. El catálogo oficial dispone de vistas
informativas offline, sin conectar categorías a reservas ni admisión.

**Nuevo requisito [#321](https://github.com/mbalbo2023/boca-socios-assistant/issues/321):**
mantener una sola sesión del dueño en el mismo Chrome al cerrar/reabrir pestaña
y reiniciar controller, sin reingreso rutinario de passkey. Código de custodia
y migración en desarrollo; el servidor físico aún usa sesión temporal.

**Regla permanente de limpieza Docker del dueño (04/11):** después de
**cualquier** instalación/despliegue/actualización Boca, exitosa o fallida,
el mismo workflow protegido deberá inventariar y limpiar selectivamente
artefactos de intento e imágenes Boca antiguas **que ningún contenedor use**.
Debe verificar espacio/inodos y ausencia exacta de residuos, mantener la
imagen activa y todos los volúmenes owner/clave/DB, y declarar NO_GO si la
limpieza es incierta. **Sin Docker prune global ni otras aplicaciones.**
El contrato está en desarrollo DRAFT; no equivale a limpieza física realizada.

**Descartadas por el propietario:** varias sesiones del navegador, rotación de
clave maestra y eliminación completa, login/fila/elegibilidad/reserva/compra
reales en Boca y backup/restauración. No reactivar ni presentar estas funciones
como pendientes para BETA. El Site complementario se retira **de la interfaz**,
sin modificar infraestructura ajena. Ningún PR de esta ola fue fusionado ni
desplegado; [checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6644301519).

## Estado operativo comprobado — 04/11/2026, 16:33 ART

**Controlador BETA instalado, aceptado y arrancado; BETA integral pendiente.**
GitHub `main=cabce9f1e452e63ded115f447559a358dc0f4d1b` (PR #308,
RCA #307 resuelto) publicó el par de imágenes en
[release #41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078).
El [install #41896871289](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41896871289)
registró `BOCA_BETA_INSTALL state=PASS`, controlador únicamente y HTTP
loopback verificado. La
[aceptación #41897278258](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897278258)
pasó 24 peticiones sintéticas en el contenedor, con 1 socio, 1 intención,
1 aviso local, p95 de 24,17 ms y pico de proceso de 43.648 KiB; sin contacto
con Boca ni envío Telegram. El
[start #41897569928](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897569928)
observó `BOCA_BETA_START state=RUNNING` en `127.0.0.1:8443`, datos/clave/owner
preservados y motor `off`. Este es un recibo puntual, **no** una prueba de
disponibilidad continua ni de acceso desde la Samsung.

Próximos cierres: Chrome Samsung por túnel SSH a
`http://localhost:8443/ingresar`, autenticación y cookie, panel/alta/SQLite
persistentes, navegador opt-in
(imagen publicada, worker no instalado ni activo), Telegram (off, sin recibo
de entrega), y aceptación integral/reinicio. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
sigue abierto para capacidad del conjunto; [issue #285](https://github.com/mbalbo2023/boca-socios-assistant/issues/285)
y [draft #287](https://github.com/mbalbo2023/boca-socios-assistant/pull/287)
no son un piloto autenticado aprobado. Módulos BLACKBOX y navegación real
reservados al dueño. Estado con evidencia y operaciones posteriores:
[checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355).
La passkey de Chrome ya fue registrada en el owner-enroll físico; la sesión
servida es temporal (15 min de inactividad, 8 h máximo, inválida tras restart).
Ninguna de esas propiedades acredita por sí sola la persistencia observada
en la tablet.

## Historial anterior al despliegue exitoso (NO es el estado vigente)

### RCA del primer beta-install físico — 04/11/2026 (issue #307)

`main=3c5a0da3df527cfe58a98442ea471be81f9f06ab` (PR #306) produjo un
release inmutable [#41873165726](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41873165726).
El dueño completó el alta de Chrome con PIN en el paso protegido
`owner-enroll` [#41887635433](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41887635433).
El primer `beta-install` [#41889141825](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41889141825)
fue rechazado por la variable de entorno vacía. Con el gate `ready`, el
segundo [#41890280818](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41890280818)
superó validaciones de SHA, release, daemon, owner, staging, configuración y
puerto `127.0.0.1:8443 FREE`. El `beta-preflight` observó 931.808 y luego
914.340 KiB de MemAvailable; el `beta-apply` posterior devolvió
`BOCA_NO_GO: insufficient available host memory` sin registrar su cifra final.
Las tres etapas de detención/limpieza selectiva pasaron, con volúmenes del
dueño preservados; sus recibos detallados no son públicos.

**BETA no instalada.** La causa de rechazo es el veto fijo de 768 MiB que
quedó en `validate_snapshot`, pese a la decisión del dueño de considerar la
holgura un dato observado y medir consumo real después de instalar. El veto
de 512 MiB/0,25 CPU en aceptación requiere la misma reconciliación. El
[issue #307](https://github.com/mbalbo2023/boca-socios-assistant/issues/307)
contiene RCA y propuesta fix-forward; hasta PR, CI, revisión, merge, nuevo
release y recibo protegido, **no repetir `beta-install`**. Límites estrictos
del contenedor, identidad rootless, almacenamiento, limpieza y aislamiento
siguen obligatorios. La sesión autenticada en GitHub se verificó en el
navegador interno para futuros despachos manuales; no se lanzó un reintento.

## Concurrencia del candidato de BETA #306 — 04/11/2026

[PR #306](https://github.com/mbalbo2023/boca-socios-assistant/pull/306)
incluye un ajuste de **validación de PR, no de despliegue**: las ejecuciones
anteriores del mismo PR en Image Release y First Deploy pueden cancelarse al
cambiar el SHA; las operaciones manuales `workflow_dispatch` siguen
serializadas. CI, escaneo de imágenes, revisión técnica, SHA exacto, ambiente
protegido y controles del droplet se conservan. Véase
[ADR0129](docs/ADR/0129-controller-only-beta-resume.md).
**No existe evidencia nueva de BETA instalada**; verificar cuatro checks
del candidato y seguridad postmerge antes de cualquier release físico.

## Contrato vigente para corrección del bloqueo rootless — 04/11/2026

**Actualización 04/11/2026 (Regla 84, RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)):** El [run protegido #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848) verificó `module=absent`, `nf_call_iptables=unavailable`, `index=listed`, `modules_disabled=0`, `write_ops=none` en `main=41fc15e261d002dc614124ac0f2d2e1bea81f896`; fue una **lectura exitosa**, no un deploy.

El propietario ordenó flexibilizar el obstáculo y llegar a BETA. [PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) / [ADR0128](docs/ADR/0128-boca-only-owner-enroll-icc-compat.md) implementan el cambio **solo en la red temporal de `owner-enroll`**: `ICC=true`, UID rootless Boca, cero masquerade, exactamente un peer autorizado, host loopback `127.0.0.1:8443`; limpieza positiva con opciones concordantes. El `network-probe` histórico ICC=false y la variante diferencial ICC=true siguen separados; **no** se cargan módulos ni se modifica kernel/firewall global, Porota u otros servicios. Riesgo residual: menor aislamiento entre potenciales contenedores de esa única red; ningún segundo contenedor está autorizado.

**Estado físico vigente: BETA NO instalada.** PR/CI, release dual exacto, alta Chrome real, `beta-install`, aceptación, recursos y Telegram todavía requieren evidencia. Además [issue #305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) rastrea arranque del daemon antes de instalación y reanudación controller-only después de aceptación. Nunca reutilizar `beta-install` para reanudar, ni activar el navegador BLACKBOX desde agente. Los apartados anteriores del 03/11 abajo son **cortes históricos**, no la instrucción operativa actual.


## Checkpoint rootless físico — 03/11/2026 (RCA #275)

El PR #298 fue **fusionado** en
`main=a83e105d4ccec2cc59dfabce77142750de733630`. Su diagnóstico protegido
[run #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589)
fue exitoso **como inspección de solo lectura** y emitió
`BOCA_KERNEL_BRIDGE state=OBSERVED ... module=absent nf_call_iptables=unavailable write_ops=none`.
La red temporal [ICC=true #41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622)
pasó sólo en modo diagnóstico; la red real de `owner-enroll`, con `ICC=false`,
[falló #41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453)
con `reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`. No se
instaló BETA. El módulo no está cargado o visible, pero todavía se desconoce
si está disponible para el kernel activo. [ADR0126](docs/ADR/0126-readonly-kernel-module-availability.md)
propone una **nueva candidata read-only**, no ejecutada ni fusionada en ese
corte, para distinguir disponibilidad de carga. No existe autorización para
cargar módulos, modificar kernel/firewall global o relajar `ICC=false`.
[Issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
son los registros de evidencia operativa.

## Nueva frontera de titularidad — 03/11/2026

El dueño se reservó en exclusiva la programación de
`browser/synthetic.py` y `browser/ipc_worker.py`, y toda navegación por el
sitio de Boca. Los agentes no pueden interpretar ni modificar esos dos
módulos sin autorización explícita posterior, ni navegar Boca desde el
droplet. Los dos archivos recibidos se preservan **byte por byte** en
[PR #289](https://github.com/mbalbo2023/boca-socios-assistant/pull/289)
con huellas SHA-256. Posteriormente el propietario los declaró **caja negra
validada externamente**, sin exigir a los agentes certificación funcional ni
permitirles inspección. Autorizó fusionar y desplegar con exclusiones
específicas de Ruff, Mypy, Pytest y el recorrido Chromium sintético que
dependía de esos módulos. Las pruebas de los demás componentes, controles de
seguridad y gates físicos siguen vigentes; no se declara un despliegue sin
recibo real. La BETA del controlador mantiene backend `off` y navegación
exclusivamente a cargo del dueño.

Ver [ADR0121](docs/ADR/0121-owner-controlled-browser-navigation.md) y
[ADR0123](docs/ADR/0123-owner-blackbox-rca-exception.md).

## Histórico sustituido el 03/11: Chrome físico y login público

El titular había priorizado la prueba del sitio real antes de las 12:00 ART. La autenticación de Fernando en Cloud Browser no quedó verificada pese a la confirmación del titular de que las credenciales son correctas. El bot de este repositorio **todavía no inicia una sesión real ni reserva entradas**. El [run físico #347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167) en main `4f9718d` confirmó **`google-chrome-stable` presente para UID 10001** con el PR #282 integrado. El [issue #283](https://github.com/mbalbo2023/boca-socios-assistant/issues/283) proponía un único GET público contra login, pero la nueva decisión reserva **toda navegación del sitio** al propietario. Los agentes no lo ejecutarán. Véanse [ADR0117](docs/ADR/0117-host-chrome-readonly-inventory.md) y [ADR0118](docs/ADR/0118-one-shot-public-login-chrome-smoke.md), como referencias históricas; no equivalen a sesión autenticada ni BETA instalada.

## RCA #275 — red Docker rootless, recibo real #342 (2026-11-03 ART)

El [run protegido #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050), sobre `main=d9ad6d492592c403eed70ae85af63f8b1821a67d` (PR #279 integrado), confirmó **`BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`**. La limpieza independiente y la parada del daemon exclusivo de Boca pasaron. Es más preciso que #337 (`firewall_unsupported`), #329 (`firewall`) y #317 (`network_create`), pero no prueba por sí solo el estado global del módulo `br_netfilter`. No se instaló BETA, Chrome ni Telegram. [CI postmerge](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640180891) y [seguridad](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640181029) pasaron.

El código del alta privada usa `enable_icc=false`; [Moby #50635](https://github.com/moby/moby/issues/50635) documenta una falla rootless compatible al faltar `bridge-nf-call-iptables`. El titular aprobó una **prueba diferencial nueva y exclusivamente diagnóstica** con `icc=true` en una red transitoria sin contenedores, puertos ni imágenes. Es sólo un candidato de código hasta contar con checks y recibo físico; la configuración real de `owner-enroll` permanece `icc=false`. No tocar kernel, Docker/firewall global, otras apps ni PPI Watch. Ver [ADR0116](docs/ADR/0116-rootless-icc-true-differential-probe.md) y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45). No habilitar BETA ni publicar release hasta acreditar los gates.

## Decisión vigente sobre recursos (2026-11-02, PR #273 integrado)

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](docs/ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 fue integrado y verificado en `main=0e830e3eed941de1da70cef8b42bda9f20258b65` con CI y seguridad postmerge GREEN. La decisión sigue vigente.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

La reiteración del dueño está registrada, pero la revisión automática volvió a bloquear el dispatch antes de ejecutarlo; no existe un nuevo run. Véase el [bloqueo actualizado](https://github.com/mbalbo2023/boca-socios-assistant/issues/27#issuecomment-6591174050). La captura sigue pendiente por ese control de plataforma.

Public, simulation-first engineering project for a consent-based Boca Juniors
membership and ticket-assistance workflow. This repository is owned by
**mbalbo2023** and remains isolated from **all unrelated applications and
infrastructure**.

> **SIMULATION ONLY. Code evidence and deployed acceptance remain separate.**
> Historical baseline `032de0ebb923b4f80154e93cee3dfd1b254687ed` already integrated
> #224/#226/#229 and #237/#239/#242–#249; do not redo those implementations.
> PR #254 merged as `b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8`; PR #255
> merged as `dada569a2d71ad4411a73ebdaca1186ed3be6936`. The latter adds the
> private Telegram setup form, browser-local encryption and owner pins.
> [PR #255 CI 41481913145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913145)
> passed 1663 tests plus 31 subtests and the real offline Chromium UI proof;
> [security 41481913075](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913075)
> passed. These are the PR's receipts, not a substitute for final-main checks.
> PR #253 integrated lifecycle/recovery and durable Telegram gates in
> `5ddfba568d0b53168f51c0e5b33c363ba24c505e`. PRs #261/#263/#266/#269/#270
> are integrated in main `fe70271f940dbc6fc1f422907f5e7254eb2ae508`:
> [postmerge CI 41544296010](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544296010)
> and [security 41544295980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544295980)
> passed. The five #270 candidate checks passed, including 2283 tests plus
> 31 subtests; they are code/runner evidence, not host acceptance.
> [Status](docs/BETA_INTEGRATION_STATUS.md) preserves earlier cuts and failures.
> New candidates require their own checks; operational receipts belong in
> [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836).
> The owner-authorized preflight and public capture both ran. Infrastructure
> [41537794166](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166)
> failed its initial read-only check, before any marker, start, observation or
> restoration. RCA #268 records the lost diagnostic; its historical reason cannot
> be recovered. PR #269 integrated bounded, read-only `infrastructure-inspect`
> ([ADR0109](docs/ADR/0109-readonly-infrastructure-diagnostics.md)). Its authorized
> [run 41542349197](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017)
> at 20:03 ART returned `NO_GO`, `rc=1`, `transport=confirmed`,
> `reason=effective_preflight_unit_unverified`, `start_attempted=no`.
> [RCA #271](https://github.com/mbalbo2023/boca-socios-assistant/issues/271#issuecomment-6590959214)
> reproduces the parser's rejection of empty Exec arrays omitted by systemd's
> v255 renderer even with `--all`. The exact omitted host fields were not
> captured; this compatible defect does not prove the complete host cause.
> Historical RCA #271 was integrated by PR #272, with postmerge CI/security
> success on `main=ea753ccab29d112b374a07b167d92e68c714cddd`.
> Protected `infrastructure-inspect` #289 then PASSed with daemon stopped;
> infrastructure-preflight #290 subsequently failed its observation step,
> while the mandatory daemon stop succeeded. The resource decision is now
> tracked in issue #274/PR #273; BETA installation remains unverified.
> [Public capture 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470)
> fetched 25 permitted GETs, all HTTP 200. Chromium remained UNKNOWN after a
> denied script GET outside the exact accepted origin, with query redacted and
> no path disclosed; its host and function are unknown. Isolation and cleanup
> passed. The owner reaffirmed continuation of the same 25-GET diagnostic;
> no new capture result is established at this cut. No map expansion or automatic retry;
> see [the report](docs/quality/public-source-validation-2026-11-02.md).
> PR #270 integrated [ADR0110](docs/ADR/0110-public-denied-authority-metadata.md),
> adding bounded `scheme`/`authority`/`host_kind` metadata to the first denial,
> without DNS lookup, contact or a wider capture map. It cannot identify the
> authority omitted from 41537796470; the authorized continuation still needs its own receipt.
> [Read-only inspection 41538696464](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41538696464)
> at 19:36:40 ART found the daemon inactive/dead and its socket absent, with
> capacity not evaluated. It does not identify the earlier failed condition.
> [port check 41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298)
> saw `127.0.0.1:8443 FREE reserved=no`
> only at that instant. No BETA install, current dual release, real private
> activation URL, Chrome/GPM persistence or Telegram delivery is established.
> Finish documentation before release and freeze main through activation and
> recovery; subsequent operational evidence belongs in #45, without moving SHA.
>
> Historical preparation and release evidence follows; it does not validate
> the current candidate:
> The manual Boca workflow inspected the host and prepared its dedicated
> rootless service (#120), then passed a read-only preflight for the dormant
> controller (#124). The protected stop-test #156/41272785626 subsequently
> stopped the dedicated daemon, with no Boca container left running and data
> preserved. Its `containers=0` field counts containers stopped in that run;
> exited containers, if any, remain preserved.
> None of these receipts is application readiness.
> The protected [image release 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820) published `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
> for the pre-change #214 main `8fdbec97262a525821eb87f3fbc27f1841a5d2ec`
> (manifest 13086161844). Earlier releases 41301618285/#208 and
> 41302342233/`3ef7aff8...` are historical. This is GHCR publication only,
> with no droplet pull/install. This code change requires a new exact-main
> release before a future host install; recheck the [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
> The controller was never installed; no live login, Queue-it client or automated
> checkout is enabled. See [current integration status](docs/BETA_INTEGRATION_STATUS.md)
> and [continuity issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Non-negotiable product rules

1. One requested ticket per verified member, **per match**. Database constraint:
   unique member + event, with ticket quantity exactly 1.
2. The database may store membership usernames and recoverable passwords, but
   password values are **AES-256-GCM encrypted** with a key held **outside**
   the database, GitHub repository and image. No credentials from chat are
   committed or imported automatically.
3. Multiple browser sessions are a future configurable capability, not proof
   of multiple Queue-it positions or a way to bypass admission rules.
4. No scraping spikes, Queue-it token fabrication, CAPTCHA bypass, proxy
   rotation or unauthorized endpoint testing. A simulator is used until a
   specifically authorized live observation is possible.
5. The dedicated manual GitHub Actions workflow is the only host-operation
   channel. Release/install code exists; its exact image and host gates must
   pass before an installation can be considered validated.
6. No other project is a dependency, Compose service, networking peer, image
   registry, volume, credential source or deployment target.

## Architectural overview

- Runtime: Python 3.12, typed modules, no unsafe live action implementation.
- Persistence: dedicated SQLite WAL database with migrations and DB-level
  uniqueness. Compose configures `/data/boca.sqlite3` in the persistent
  `boca-socios_boca_data` volume; this describes the intended mount, not proof
  that a Boca database or volume already exists on the droplet.
- Security: AES-256-GCM credential vault with per-record random nonce,
  authenticated member-specific binding, external key volume, and key version.
- Default dormant runtime isolation: Compose project **boca-socios**; named volume
  and bridge network; nonroot, read-only container, dropped capabilities,
  CPU/memory caps, no exposed ports and no host Docker socket. A separate
  beta Compose candidate #171 and protected `beta-install` #191/
  `beta-acceptance` #200 contracts were tested on disposable runners. The
  model was integrated in PR #224/ADR0091 with certificate-free HTTP only
  on Boca host loopback behind SSH, with a private owner volume; no droplet
  install occurred. The isolated one-use browser enrollment #225/PR #229
  uses a separate disposable named Docker staging volume for encrypted
  envelopes, not the private owner volume. Its protected host operation is
  integrated **in code only**;
  no real owner link, Chrome passkey or host installation has been verified.
- CI: pinned checkout/setup actions, frozen dependency lock, lint, format,
  strict typing, tests, image build and repository-isolation checks.
- Delivery: small PRs, recorded agent technical review, exact-SHA status
  checks and immutable release artifacts. Boca-only host operations
  use the manual Actions workflow under the [current scoped authorization](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
  and proof of exact-input and isolation gates. Infrastructure and business
  choices outside the approved delivery plan require options, a recommendation
  and the owner's decision; routine work within that scope proceeds.

## Functional BETA being prepared

The [delivery plan](docs/BETA_DELIVERY_PLAN.md) makes private member enrollment
(**Socios > Agregar socio**) part of acceptance, together with simulation
start/stop/status, durable local notices and restart/idempotency tests. Reuse
the existing encrypted enrollment service; tests use synthetic credentials.
The own-application panel, entrypoint, owner preflight #189, and local
runtime libraries are integrated in code, without application installation.
PR #208 integrated protected owner custody; #224/#229 added the current
SSH-only HTTP and public-passkey-only enrollment path. Historical TLS tests
do not establish tablet access, and no certificate is required for this BETA.
The protected `port-check` choice in the manual workflow tests only the fixed
host-loopback `127.0.0.1:8443` by a short bind/close; a FREE receipt does not
reserve a port or establish tablet access.
The later protected [run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d` reported
`FREE reserved=no` at that instant. The owner chose a private tablet forward
to the local panel on 8443. **Merged PR #224/ADR0091 supersedes
the HTTPS-localhost route:** the only proposed BETA Compose origin is
`http://localhost:8443` (WebAuthn RP `localhost`) through Termius SSH, with
**no device certificate/CA installation**. At that historical checkpoint, the
forward and physical passkey remained untested; **on 04/11/2026 Tincho
subsequently confirmed Samsung Chrome + Termius + passkey access to the
controller-only deployment**, not to the integral BETA or a persistent session.
the single stored credential also needs cross-device proof for Android/iOS.
The former tablet-local TLS WebAuthn emitter (#215, ADR0089) remains only as
historical code and is **not** the owner's enrollment procedure. The requested
one-time activation URL must instead be served from the droplet on the same
isolated Boca port, with a privately delivered single-use key. The integrated
#225/PR #229/ADR0092 code implements the **unserved** `/activar#key=…` flow and
WebAuthn proof, producing a v2 encrypted envelope in a separate disposable
staging volume without mounting the owner's X25519 private key. The #225
`owner-enroll` operation, positive rootless/volume checks, offline
`install-staged` and mandatory same-job selective cleanup after attempted
staging were integrated in PR #229 into the **existing** protected Actions
workflow, with disposable-runner smoke tests. This code is not evidence of a
completed host run: the single-use private URL has **not** been delivered,
nor has physical Chrome passkey creation, private handoff, iOS use or owner
install been verified.
The #217 correction requires a discoverable passkey during local enrollment.
The chosen Android credential manager holds its private key, not a Chrome
cookie. **The still-installed legacy controller** uses a temporary cookie
(15-minute idle, 8-hour absolute limit and revocation on process restart).
**DRAFT #319 / Option B #321/#322**, not yet deployed, instead records one
owner authorization in a dedicated sibling SQLite and issues a rolling
400-day Chrome cookie without the old daily/session idle expirations; logout,
new owner login or verifier change revokes it. Persistence through a physical
Samsung Chrome/controller restart, Android storage/sync and iOS use remain
acceptance gates. Safari support remains unverified. No renewal
or generation of TLS certificates is required for the chosen SSH-only route.
Site decommission is deferred until the local replacement is validated.
Merged PR #220 (RCA #219) strengthens the existing Boca-only failed
deploy recovery: a failed staged `beta-install` invokes immediate selective
cleanup via the same protected Actions job. It can remove only verified
disposable controller/network/image/staged-Compose artifacts, while preserving
owner/key/data volumes and retaining the failed deploy status. This is
integrated code/test behavior, **not** proof of a cleanup or BETA installation on the droplet;
unknown or interrupted cleanup remains NO_GO and forbids blind retries.
The lifecycle integrated in PR #253 adds explicit existing-container start,
restart, status and acceptance, plus optional Telegram start and recovery;
see the [operation table](docs/OPERATIONS.md#protected-browser-lifecycle-contract).
The pair budget is `1.5cpu-1024m-192pids`; owner-ready Telegram lifecycle uses
`1.75cpu-1152m-224pids`. Neither is a claim of available host capacity.
This version implements #261/ADR0103: it separates aggregate observations
from numeric reserves, which remain unchanged. Its reviewed CPU criterion uses the container branch's
structural `cpu_ceiling`; load is advisory, not free CPU. ADR0104 measures the
existing CI workloads. Missing counters remain UNKNOWN and three-service
concurrency is unmeasured. Exact-SHA checks and the protected host operation
require their own receipts in #45.
Complete Telegram setup/test before the first persistent simulation; the
BETA acceptance probe uses temporary SQLite. The authenticated
`/telegram/configurar` form from PR #255 produces only ciphertext and the
protected bot/destination pins. It does not install or enable a sender.

The entirely synthetic Chromium journey (#25) and its on-demand and Unix IPC
contracts (#227, ADR0093/0094) are integrated for offline tests, never real
Boca navigation. The integrated optional `BOCA_BROWSER_BACKEND=ipc` uses a
separately isolated, UID10002 Browser Worker with a local Unix socket;
**the default `off` keeps the existing in-process simulation stub**. The
opt-in setting has no usable worker until a separately reviewed image,
Compose/host isolation and selective cleanup are approved, released and
installed. It never enables real tickets or login. Chromium sandboxing,
network isolation, 30-second coordinator budget and worker identity gates
are code-level safety requirements, **not** proof of deployed safeguards.
The command/restart/notification regression suite (#228/PR #231) is merged
and synthetic; Telegram #168 still needs dedicated bot custody, verified
destination and a protected one-message host/owner receipt. Both are
operationally unverified, and no other droplet workload may be affected.
The private Site v10 has a disabled D1 bridge and fails closed while host
credentials/poller are absent. PRs #181/#196 integrated protected ciphertext
custody and global daemon inventory checks, but no Site host phase ran.
Telegram's opt-in worker #188, safe stop recognition #194, sealed helper #199,
protected schema/custody #203 and one-shot Bot API test #204 are integrated,
with no host dispatch, configured bot, verified destination or real send.
The offline #25 Playwright CI smoke (PR #232), #227 synthetic adapter and
IPC/STOP guards (PRs #233/#236), #228 restart/notice regressions (PR #231),
and #168 Telegram identity pinning (PR #230) **are merged as code/tests**.
The Browser Worker runtime/image #237, security #242, dual release #239 and
Compose/install/cleanup #243–#249 are integrated. They do not prove a
running browser sidecar, real Telegram dispatch or BETA installation on the
droplet; see the [status table](docs/BETA_INTEGRATION_STATUS.md).

`/data/boca.sqlite3` in `boca-socios_boca_data` is the delegated logical storage
decision for this BETA, not proof that a database exists on the droplet. Actual
global location remains UNVERIFIED; existing data must never be replaced by
inference. Real credentials and Boca actions remain outside this delivery.

## Read before contributing

- [AGENTS.md](AGENTS.md): binding instructions, including Rule 84: keep affected
  documentation factual and current in the same PR and reconcile continuity
  before closing the task.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): modules and threat boundaries.
- [docs/DEVELOPMENT_POLICY.md](docs/DEVELOPMENT_POLICY.md): branch/PR/CI gates.
- [docs/SECURITY.md](docs/SECURITY.md): password, key and session policy.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): Docker isolation and deployment gate.
- [docs/ROADMAP.md](docs/ROADMAP.md): bounded development backlog.
- [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md): branch rulesets and GitHub settings.
- [docs/QUEUEIT_AUDIT.md](docs/QUEUEIT_AUDIT.md): known vs. unknown Boca infrastructure.

## Development check

The canonical CI command sequence (from a separate development environment):

~~~sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python scripts/check_repo_policy.py
~~~

No manual terminal commands on a production host are required by these
instructions. Host operations use only the gated Boca Actions workflow.

## Lifecycle

**Foundation → simulation → controlled test → recorded technical review →
gated Actions operation.** Offline and local components and the private Site
are integrated in different scopes, but the installed controller remains
absent. The Compose controller still initializes storage and waits with
its engine off. A green CI run is necessary but **not sufficient**
evidence for deployment or a functional BETA.

**Public-repository governance:** GitHub Free supports enforced branch rules
and free standard GitHub-hosted Actions runners on public repositories. The
ruleset must be **created and verified in GitHub Settings**; the existence of
this documentation never proves it is active. See GITHUB_SETUP.md.

