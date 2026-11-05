# Plan de entrega y aceptación de la BETA funcional

## Ruta de release A45-R21.21 — 05/11/2026 ART (CODE_ONLY / NO DEPLOY)

**Corte fuente:** [#319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319) DRAFT HEAD `3cbe31703d74413f8de66ac8783ec68b1b7f8a87`, TREE `208a75e0c7310ea25db55ca509563f0b57972f42`; overlays #372 cleanup Cutover, #375 inventario, #374 Telegram stage fresh WebAuthn y #376 GO_B dos despachos, fuentes 4/4, 4/4, 6/6 y 4/4 GREEN (3652/3682/3668/3702 pytest +34 respectivamente). **QA #319 exacta:** **7/7 GitHub Actions COMPLETED SUCCESS exact SHA R21.21**: [CI 42064964129](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964129) **3718 pytest PASS +34 subtests**, Ruff/format547/MyPy128/image-build PASS; [FirstDeploy 42064964223](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964223) PR-validation + runtime-smoke SUCCESS, **host SKIPPED**; [Release 42064964145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964145) validación SUCCESS, **publish SKIPPED**; [Panel 42064964232](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964232), [News 42064964239](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964239), [Telegram 42064964156](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964156), [Security 42064964402](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964402) SUCCESS. Artifacts de CI/FirstDeploy/Release consultados: **0**; no recibo físico ni imagen publicada. La instalación legacy `main=cabce9f1e452e63ded115f447559a358dc0f4d1b` aceptada 04/11 y Chrome Samsung comprobado **no** equivalen a BETA integral.

1. **Cerrar QA PREDEPLOY en SHA final:** confirmar 7/7 Actions terminales exactas, Ruff/MyPy/Chromium offline/política, fuente/branch/árbol, jobs de PR host y publicación SKIPPED, artifacts genuinos y ownership liberado. Cambiar HEAD reinicia esa verificación; no extrapolar tests de fuentes verdes.
2. **GO de código/release separado:** revisión técnica de #319, merge único autorizado a main; crear release por imágenes controller+browser y digest inmutables de **main**, manifiestos y evidencia de GitHub. Sin GO concreto de merge/release/host, no despachar nada. PR source ni doc-only no publican imágenes.
3. **GO_B Cutover A accesible desde Samsung:** en el MISMO workflow Boca `cutover-a-apply` con `protected_action_context` vacío para PREPARE (runner deriva release/digests/legacy, una observación Boca READ_ONLY sin mutar app); artifact `boca-protected-legacy-go-prepare` y recibo exacto; GO protegido **independiente** `BOCA_CUTOVER_A_GO_BINDING_SHA256`; segundo `cutover-a-apply` con **solo PREPARE run ID** en `protected_action_context`. Validar actor/main/source/release/manifests/ZIP/TTL24h, O_EXCL, ACK host y dos líneas de postflight de limpieza solo Cutover. Un resultado incierto es NO_GO sin reintentos a ciegas.
4. **Aceptación funcional:** Termius UI tunel `8443` y Samsung Chrome `http://localhost:8443/ingresar`; comprobar persistencia del mismo Chrome tras reinicio, **Socios > Agregar socio** en modo simulado, control bot/Chromium `REQUESTED` → PREPARE → GO → APPLY → ACK físico (nunca suponer un botón como efecto) y rendimiento real del conjunto. Import oficial `official-notice-import` también requiere PREPARE/GO/APPLY y un único `official_news_run_id` PR-only auténtico; únicamente información, no admisión/reservas.
5. **Telegram solo tras habilitar backend físico:** #374 asegura stage con passkey WebAuthn UV fresca, **no sender**. Falta caller atestado bajo misma lease/PID/UID, custodia Bot API egress/recipient, HMAC/ACK y GO específico; mantener OFF/NO_GO sin pedir token/PIN hasta resolverlo. `telegram-activate` aún no es vía operativa aceptada.
6. **Postflight y Rule84:** registrar receipts reales de Cutover A con bytes/inodos antes/después y recursos de Boca por ID exacto, otros Docker intocables; la política general de cleanup tras **todo** deploy PASS/FAIL sigue, pero #372 solo implementó finalizador Cutover A (seis instaladores legacy NO_GO). Completar checkpoint [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45) y actualizar docs #363 al HEAD definitivo antes de overlay. Guía sin terminal/PIN en [OPERATIONS](OPERATIONS.md).

**No procede hoy ejecución host:** no GO, no release publicado, no Cutover ni ACK físicos; sólo localhost:8443, sin compra/reserva real, backup, BLACKBOX, migración legacy SQLite a 0008, otros sistemas Docker, HTTPS o seguridad P2 extra.

## Histórico — Plan de cierre actual A45-R21.17 — 05/11/2026 ART (NO_GO físico)

**Baseline comprobado:** [#319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319) DRAFT HEAD `82c7c3edf75911805218149d4907ecb37b374a66`, TREE `d6ca906f517571c0025cce7780b674cdc3956fc3`. **7/7 Actions SUCCESS** [CI 42056912053](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056912053) 3645 tests +34 subtests; [FirstDeploy 42056911736](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911736) host SKIPPED, [Release 42056911857](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911857) publish SKIPPED. El main físico sigue legacy `cabce9f1e452e63ded115f447559a358dc0f4d1b` (Samsung Chrome+Termius+passkey 04/11), **no BETA integral**.

**Ruta para llegar a deploy — todas las puertas deben tener recibo exacto:**

1. **P0 workflow GO B #371:** concluir PR source-only para Cutover A e import oficial de [ADR0163](ADR/0163-prepared-go-single-use-host-cutover-import.md), autenticar PREPARE previo SUCCESS y artifact por GitHub API, verificar source/actor/owner, digest ZIP/manifests, TTL24h y GO independiente. Dos despachos humanos del único workflow, segundo con ID PREPARE corto para Voice Access, sin JSON/PIN, nunca GO desde input. Al 05/11 el issue existe y PR todavía no.
2. **P0 Telegram y lifecycle:** #356/#369/#370 dan contrato de ACK físico, sin evidencia host; [#362](https://github.com/mbalbo2023/boca-socios-assistant/issues/362) mantiene Telegram OFF por WebAuthn fresco, HMAC/attestor y caller same-lease/egress faltantes. No usar #365 como autorización ni repetir la instalación legacy.
3. **Predeploy técnico final:** integrar únicamente commits revisados, comprobar HEAD/TREE, PR/ownership, suite de 7 Actions **terminales del SHA final**, artefactos auténticos de release y PR reviews. Revalidar release by digest y aislamiento de `127.0.0.1:8443`, Cutover GO_B, SQLite Option B **independiente**, anti-replay, one-member/one-ticket y cleanup Boca-only sin activar sitio real.
4. **GO/operación separados:** documentar GO concreto de merge, release y Cutover/operaciones; merge único a main, publicación de imágenes inmutables y operaciones por [Actions Boca protegido](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml). No host SSH ni Docker desde el agente; ningún GO nuevo consta ahora. Guía Samsung paso a paso en [OPERATIONS](OPERATIONS.md).
5. **Aceptación real pos-Cutover:** dueño comprueba Termius tunnel+Samsung Chrome, única sesión persistente tras reinicio, **Socios > Agregar socio** (simulado), STOP/START bot y Chromium con ACK exacto, import oficial informativo y Telegram solo cuando su backend/GO esté verificado; registrar métrica de recursos y recibo de limpieza Docker selectiva tanto PASS como FAIL. Hasta esos recibos **NO_GO BETA INTEGRAL**.

**No adelantar pasos:** el código/CI verde no acredita host; no comprar/reservar, no backups, no BLACKBOX, no tocar legacy SQLite a 0008, Porota, otros Docker/puertos, HTTPS ni seguridad extra P2. Documento #363 DRAFT independiente; sincronizarlo en #319 solo tras el corte exacto siguiente. [Checkpoint Rule84 #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6662182710).

## Histórico — Actualización de entrega — 05/11/2026 ART (R21.11 provisional)

**Objetivo de aceptación:** BETA integral con evidencia funcional, predeploy y despliegue protegido en `127.0.0.1:8443`. Todavía **no está desplegada ni validada integralmente**. Lo aceptado en Samsung Chrome/Termius/passkey el 04/11 corresponde al **legacy `main cabce9f1e452e63ded115f447559a358dc0f4d1b`**, no al candidato nuevo.

**Candidato único:** [DRAFT #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319) R21.11, HEAD provisional `5903ded0790ab7254bf68572af47fe75c6e08889`, con **3.437 PASS +34 subtests y 7/7 Actions GREEN**. CI [42044959831](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959831); las otras seis: [42044959889](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959889) (imagen, sin publicación), [42044959974](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959974), [42044959895](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959895), [42044959814](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959814), [42044959805](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959805), [42044960073](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044960073) (host omitido).

**Ruta P0 restante, con ownership por componente:**

1. Integración/QA exacta de los P0 posteriores al corte: #349 importación Actions y #350 STOP persistente ya incorporados **en código**; #353 Telegram y #355 Compose preparados en candidato, no asumidos como verificados en runtime.
2. Consolidar overlays de #356 (ACK físico bot/Chromium), #358 y #352 (workflow protegido), con SHAs, pruebas y recibos. El HEAD anterior no es un release fijo.
3. Preparar QA/predeploy final de #319 ya consolidado y comprobar persistencia/arranque/parada sin impactos colaterales.
4. Con **GO específico** para merge/release/deploy, ejecutar el proceso protegido y verificar Samsung Chrome + Termius, ACK del host y Telegram backend/egress/custodia/activación posterior.
5. Documentar resultados en GitHub (Regla84) y limpiar Docker **solo recursos pertenecientes a Boca**, tanto tras deploy exitoso como fallido.

Restricciones: seguridad extra P2; sin hardening adicional P0, compras/reservas reales, backups, cambios a BLACKBOX, migración legacy SQLite 0008, Porota/otros servicios, nuevos puertos ni HTTPS. Sin nuevo GO, SSH, release ni deploy. Referencia: [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6660565397).

## Histórico — Estado actual de la entrega — 04/11/2026, 16:33 ART

La primera fase física se completó: controller-only instalado y arrancado en
`127.0.0.1:8443`, motor apagado, misma fuente
`cabce9f1e452e63ded115f447559a358dc0f4d1b`.
Recibos: [release #41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078),
[install #41896871289](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41896871289),
[aceptación sintética #41897278258](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897278258),
[start #41897569928](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897569928).
El controller tuvo 24 peticiones locales PASS pero **el objetivo BETA integral
no está aceptado**: falta Chrome/Termius, sesión, alta y DB desde la tablet,
browser-worker (imagen publicada; no instalado), Telegram (off), pruebas
de reinicio/capacidad conjunta/avisos/voz. El arranque sólo acredita ese
instante. Respetar BLACKBOX, sin tráfico real Boca ni reservas/compras.
Para sesión nueva en Chrome: `http://localhost:8443/ingresar` mediante el
forward de Termius. La passkey física ya fue enrolada, pero la cookie del
panel expira tras 15 min de inactividad/8 h y se invalida al reiniciar;
persistencia efectiva en la Samsung aún no probada.
[Checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355).

## Decisión de recursos histórica — 2026-11-02, candidato #273

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 sigue **candidato, no integrado**:
ningún documento atribuye esta conducta a main hasta merge y checks.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

La reiteración del dueño está registrada, pero la revisión automática volvió a bloquear el dispatch antes de ejecutarlo; no existe un nuevo run. Véase el [bloqueo actualizado](https://github.com/mbalbo2023/boca-socios-assistant/issues/27#issuecomment-6591174050). La captura sigue pendiente por ese control de plataforma.

## Alcance y fuente de verdad

El dueño aprobó comenzar las recomendaciones del plan y mantener su avance en
GitHub. [ADR0056](ADR/0056-approved-simulation-beta-delivery.md) registra las
decisiones de esta etapa. La BETA objetivo es **privada y funcional en
simulación**, con **alta de socios obligatoria**; un controlador dormido sano
no basta. Este documento es un plan mantenido con las entregas, no evidencia
de funciones ya desplegadas ni un servicio automático de seguimiento.

El [plan inicial #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551577529)
fue una propuesta anterior. Su lenguaje de decisiones pendientes no revoca la
aprobación posterior de los frentes aquí registrados. El [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
registra autorización vigente, HEAD, decisiones y evidencia de cada cierre.
Revalidar esos hechos antes de actuar; no interpretar autorización del trabajo
como evidencia de éxito o permiso para operar datos reales.

[Autorización vigente ampliada](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
para completar la BETA sintética, Site conectado, Telegram y deploy validado
por Actions, sin reservas ni compras reales. El alcance anterior de preparación
queda como historial; ninguna autorización es evidencia de instalación.

## Corte comprobado 2026-11-02 y siguiente dependencia

El baseline histórico032de0 ya integró HTTP/owner, simulador, IPC, publicación
dual, seguridad e instalación/cleanup; no se vuelven a desarrollar.
PR #254 se integró en `b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8` y PR #255
en `dada569a2d71ad4411a73ebdaca1186ed3be6936`. Este último incorpora el
formulario Telegram privado; CI 41481913145 pasó 1663 pruebas + 31 subtests y
Chromium real offline para cifrado/pins/copia; seguridad 41481913075 pasó.
Son recibos de ese PR, no checks del siguiente main.

PR #253 integró ciclo completo, sender y recuperación en `5ddfba5`.
El corte actual main `fe70271f940dbc6fc1f422907f5e7254eb2ae508` incluye
#261/#263/#266/#269/#270. CI postmerge 41544296010 y seguridad 41544295980
PASS; los cinco checks del candidato #270 también pasaron, incluyendo
2283 pruebas +31 subtests. Sus recibos y pasos posteriores se conservan en
[checkpoint vigente #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836)
y [estado de integración](BETA_INTEGRATION_STATUS.md). No rehacer código integrado
ni presentar estos checks como despliegue o aceptación física.

La captura autorizada más reciente 41537796470 completó 25 GET/200, aislamiento
y cleanup PASS, pero Chromium quedó UNKNOWN por un script externo denegado.
Su host y función no se conocen. #270 integró metadata de autoridad para una
observación futura. Tras un intento bloqueado antes del dispatch, el dueño
reafirmó continuar el mismo diagnóstico de 25 GET sin confirmación repetida.
No hay recibo nuevo en este corte ni ampliación del mapa. El [informe público](quality/public-source-validation-2026-11-02.md)
conserva los recibos históricos y sus límites.

La inspección sólo lectura #269/41542349197, 20:03 ART, obtuvo
`effective_preflight_unit_unverified`, `rc=1`, transporte confirmado y
`start_attempted=no`. RCA #271 demuestra que el parser rechaza arrays Exec
vacíos omitidos por el renderer oficial de systemd v255; no se capturaron los
campos exactos del host. La corrección candidata requiere revisión y checks.
Engine, capacidad, datos globales, instalación, forwarding y passkey físicos
siguen sin comprobar. El port-check 41497093298 observó 8443 libre a las
15:04:45 ART sin reservarlo. No hubo residuos de instalación por estas inspecciones.

El orden operativo actual, una vez integrado y verificado el candidato #273,
es: comprobación de identidad/rootless/almacenamiento/puerto y observación de
recursos **sin veto por holgura no medida** → release dual inmutable del
`main` congelado → validación de imágenes/aislamiento → custodia owner y alta
privada Chrome bajo SSH (intervención física del dueño) → instalación BETA
aislada → pruebas y **medición real de uso/latencia en el host** → Telegram
(custodia, prueba API y confirmación humana) → simulación persistente,
reinicio y segundo acceso passkey. La aceptación detiene sólo Boca y se
reanuda con `beta-browser-start`, nunca repitiendo instalación new-only.
Toda decisión de dimensionamiento posterior depende de los recibos reales;
la autorización de continuar el alcance ya fue otorgada por el dueño.

El ciclo ofrece start/restart/status/acceptance, sender-start y
`beta-browser-telegram-recover`. Par: `1.5cpu-1024m-192pids`; ciclo con owner
Telegram listo: `1.75cpu-1152m-224pids`. Recovery verifica el run fallido exacto,
solo limpia su sender/egress y termina detenido; SSH/identidad inciertos son
INDETERMINADO, sin reintento ciego. Ver [contrato operativo](OPERATIONS.md#protected-browser-lifecycle-contract).

La pantalla `/telegram/configurar` cifra localmente token/chat y produce los
pins esperados. Sólo ciphertext va al input `telegram_envelope`; bot ID y
HMAC van a los dos Secrets protegidos indicados. No se pide CLI ni credenciales
por conversación. La prueba Telegram liga token/destino/SHA; un upgrade no la
hereda. La aceptación sintética usa SQLite temporal y no sustituye recepción
humana ni Google Password Manager/Chrome reales.

Cerrar los commits antes de publicar y **congelar main durante toda activación
y recuperación**. Los SHA/checks/recibos finales se añaden a #45 sin commits
operativos posteriores. Si main avanza tras un fallo incierto, recovery queda
bloqueado hasta un procedimiento distinto revisado. Los secretos SSH existentes
se reutilizan; las variables/secretos de activación se verifican separadamente.

## Historial de decisiones e integración anterior

Los cortes siguientes se conservan como antecedentes. Sus estados de candidato,
ausencia de integración o TLS no sustituyen la secuencia vigente anterior.

**Decisión posterior 2026-11-01:** el panel Boca local en el droplet es la
interfaz principal de la BETA. Usa el puerto ya configurado
`127.0.0.1:8443` y forwarding privado desde la tablet; no se crea puerto
9000. El Site #113 deja de ser dependencia de aceptación de esta BETA;
permanece privado/sintético y su baja se posterga hasta validar el reemplazo.
Telegram conserva su gate propio, sin atribuir recepción a código integrado.
**Corrección integrada #224/ADR0091:** la ruta elegida pasa a
`http://localhost:8443` exclusivamente bajo forwarding SSH Termius,
sin certificados ni CA en Android. `127.0.0.1:8443` es el **único** puerto
publicado por Boca en el host, jamás una interfaz pública; se prohíbe tocar
servidores web, proxies, otros contenedores o puertos existentes. El port-check
BUSY/ERROR detiene la instalación sin intervenir al ocupante. El emisor local
TLS descrito abajo (#215/ADR0089) queda histórico, no es un paso para el
dueño. El candidato #225/ADR0092 contiene el servidor temporal HTTP y el
enlace con llave de un solo uso en código, sin acceso al volumen privado de
owner; cifra exclusivamente un sobre temporal v2. **Faltan** la integración
al workflow protegido, la limpieza Docker inmediata tras fallos del intento,
la instalación offline y la prueba física; no existe una URL de activación
real ni hay servicio nuevo en el droplet.
El [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6558572360)
registra la ejecución protegida 41310958281 sobre
`main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`: 8443 FREE
`reserved=no`, sin arrancar servicio ni instalar aplicación. PR #214/ADR0088
integró el origen exacto `https://localhost:8443` en
`main=8fdbec97262a525821eb87f3fbc27f1841a5d2ec`: CI 41312228362 y
scan 41312228548 SUCCESS. La [release protegida 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820),
intento 1 SUCCESS, publicó sólo la imagen
`ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
con manifiesto 13086161844 para ese SHA; no hubo pull ni instalación en el
droplet. Este cambio (#215/PR #216/ADR0089) incorpora en código un emisor
local de un solo uso, con pruebas sintéticas, no credencial física. La confianza TLS,
forwarding, WebAuthn Android/iOS y entrega privada del sobre siguen sin
prueba (#209). Una nueva HEAD tras este PR exige release propio antes del
host. Owner custody, instalación, aceptación y parada final requieren sus
recibos exactos por Actions.
La corrección #217 exige credencial WebAuthn descubrible durante el alta y
aclara que la llave privada pertenece al administrador de credenciales elegido
en Android. La cookie del panel dura 15 minutos inactiva, 8 horas como máximo
y se invalida al reiniciar el proceso. Persistencia/sincronización real, iOS y
renovación TLS siguen pendientes de prueba/diseño; este cambio no instala
credencial ni aplicación en el droplet.

**Corte de integración previo a esta actualización documental 2026-11-01:**
`main` `6d3007a3ca1dfdba428cb7595486b1166a1d02b6` incorpora loop persistente
#161, Telegram durable opt-in #162, stop-test #165, ciclo de vida local #164
y panel owner passkey #163, aceptación HTTP sintética #170 y entrypoint
TLS explícito #173, prueba de registro WebAuthn #174 y corrección
de lectura con schema Telegram0007 #176, paquete beta separado #171,
helper cifrado #178, cliente Site opt-in #179, custodia host #181 y RCA #196;
además RCA de comandos #187, preflight owner #189, worker Telegram #188,
probe sintético #190, `beta-install` #191, parada Telegram #194,
`beta-acceptance` #200, custodia cifrada Telegram #199 y fases protegidas
de migración/custodia posterior #203, prueba Bot API de un solo intento #204
y PR #205 de reconciliación documental, además del corte base descrito abajo.
La [publicación protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638) generó `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:ab0745a840e35a6d713fed14ec0761512fdc90284c133f2c321c9ffe2d3c9284`
para ese SHA y el manifiesto ID 13079654802; no instaló la aplicación.
Una modificación posterior de `main` necesita release propio antes de install.
[Estado actual y runs exactos](BETA_INTEGRATION_STATUS.md).
El Compose/primer install aún son dormidos y no hay aplicación en el droplet.
El stop-test protegido [#156/41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626)
emitió STOPPED, `containers=0` (ninguno detenido en esa invocación) y datos
preservados tras las pruebas de preparación. Verificó que no quedaran
contenedores Boca en ejecución; podría conservar contenedores ya detenidos.
No es evidencia de instalación BETA.
La custodia Site, `beta-install` y `beta-acceptance` están integrados en
código, sin dispatch al host; acceso privado y aceptación host requieren
pruebas propias. El Site privado v10 #113 publicó cola D1 sintética
desactivada y proxy/recibos fail-closed; existe release de imagen para el
SHA de corte; revalidar digest coincidente con la HEAD al operar. Faltan
bypass+HMAC host y E2E.
Telegram tiene worker, helper cifrado y fases host de custodia/prueba en código,
pero no tiene
bot/destino ni recepción
comprobada (#168). La [parada protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) observó
`ALREADY_STOPPED containers=not_queried data=preserved` sobre el SHA de corte.
Antes de otro uso se revalida el daemon y el main actual.

El [release protegido 41301618285](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41301618285)
publicó el digest `sha256:6f067e5078081760dec27f81d95792a4423ff9c1d9cb3bef19ef70dbfc8cf889`
para el corte #208 `58f57822e95da9574c0a9d5122607616da4a024a`,
con manifest 13082030761. Sigue siendo sólo una imagen: no se instaló BETA.
PR #208/ADR0086 integró la custodia cifrada de cinco archivos owner por
Actions, con 942 pruebas locales y smoke desechable del candidato
`465deba9456d9ace5a2cddbcdab25a5310f3d095`; no hubo efecto host.
Ese corte quedó histórico al avanzar `main`; cada HEAD final exige release
exacta antes de operar. Continúan pendientes
el alta física WebAuthn, origen/ruta HTTPS tablet, DNS/certificado y decisión
de acceso privado (#209); no inferirlos de la custodia.

## Base histórica comprobada de este plan

Punto de partida documentado: `4922e45b5e2e38242263b6ba10969a8190aa939a`,
después de #142. No se confunde ese baseline con una integración posterior.
[CI 41259139901](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139901)
y [scan 41259139886](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139886)
exitosos; 594 pruebas y RCA12/32 en ese corte. Los checks de una nueva entrega
se registran sobre su propio SHA; estas cifras no se trasladan a otro candidato.

El corte histórico de preparación fue `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`: incluye
#130/#128/#134, el análisis146, alta148, comandos149, preparación150 y pruebas
de composición152. [CI main41262581358](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262581358)
y [scan41262581422](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262581422)
verifican ese SHA; los cambios posteriores tienen checks propios.

En aquel corte, el runtime de `compose.yaml` validaba clave, inicializaba
esquema base y esperaba con engine=off; no servía panel ni conectaba
coordinador/avisos. Ese Compose conserva sólo el controlador sin puertos.
#128/#130/#134 eran candidatos separados en el corte inicial.
La primera integración incorporó #130 (coordinador durable opt-in), #128
(adaptador WSGI de lectura default-deny) y #134 (dispatcher sintético). Eran
componentes que entonces carecían de wiring runtime, listener, identidad real,
TLS y transporte externo. #148 agregó formulario/handler y sesiones de alta;
#149 integró el servicio de comandos durable. En ese corte ambos carecían de
servidor autenticado y wiring del runtime. El dispatcher conserva el límite de crash entre llamada sintética y
settlement: no prueba entrega exactamente una vez. La imagen y
smoke Chromium offline no prueban navegación Boca ni forman parte de ese Compose.
El Site #113 es una demo privada sintética; la versión v10 publicada incorpora
cola D1 desactivada y proxy/recibos fail-closed, aún sin conexión efectiva a
DB ni comandos.

La [preparación #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418) ejecutó
prepare-rootless sobre `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`, attempt1, y terminó
SERVICE_READY: daemon propio creado/arrancado/habilitado, rootless/cgroupv2-
systemd/overlay2/data root privado y namespace Boca vacío verificados.
Application_database=not_accessed y application=not_installed: no se creó
SQLite, imagen/contenedor, volumen de app/clave ni clave. Capacidad informativa,
application_budget=not_checked; no prueba presupuesto del candidato BETA.
[Recibo y marcador DEPLOY en entorno protegido](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).
No reejecutar primera preparación: la configuración existente debe preservarse.

La inspección histórica98, sobre5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e,
había hallado DB/WAL/SHM candidate-absent sólo en tres rutas fijas; ubicación
global sigue UNVERIFIED. #120 resuelve el servicio ausente de aquel corte, no
prueba dónde existe o no existe toda DB previa. No hubo SQLite abierto/creado/
trasladado/migrado. El workflow de primera instalación todavía presupone
namespace vacío y controlador dormido: adaptarlo al candidato funcional antes
de usarlo. Preparar el daemon no instala ni acepta la aplicación.

## Decisiones aprobadas y fronteras

| Tema | Decisión de preparación/desarrollo | Límite |
| --- | --- | --- |
| Datos | Destino lógico futuro `/data/boca.sqlite3`, volumen `boca-socios_boca_data`, clave en volumen externo separado | Existencia global actual UNVERIFIED; no sobrescribir una DB hallada ni migrar datos reales por inferencia |
| Docker | Preparar servicio rootless dedicado Boca y comprobar recursos | No reinstalar Docker por inferirlo de una unidad ausente; único canal Actions protegido |
| Panel | Propia aplicación Boca sirve panel privado y accede localmente a SQLite | Probar identidad, sesión y acceso SSH por `http://localhost:8443`; el navegador no recibe DB/clave/SSH/socket |
| Alta | `Socios > Agregar socio` obligatorio, sobre servicio cifrado existente | Sólo datos/credenciales sintéticos en esta BETA; alta local no verifica identidad ni elegibilidad Boca |
| Coordinación | Comandos y estado persistente; pausa visible en ambigüedad | No reejecución ciega ni éxito externo inventado |
| Avisos | Estado/avisos locales funcionales; ensayos del dispatcher sintético | Transporte #162, worker #188, helper #199, custodia #203 y prueba única #204 integrados opt-in; bot/destino, provisión host y recepción siguen pendientes |
| Site | Complemento #113 preservado | Versión privada v10 con D1 desactivado; no cuenta como panel operativo conectado |
| Operación final | Candidato concreto, imágenes/digests, preflight y aceptación verificables | Release/instalación final por decisión del candidato; no login/cola/reserva real ni backup |

Las decisiones ya aprobadas no se vuelven a preguntar para cada implementación,
prueba o reconciliación rutinaria. Desviaciones materiales fuera de este alcance
se presentan con opciones, recomendación e impacto. Backup/restore sigue
diferido; no se eliminan los requisitos de custodia/recuperación para alta real.

## Entregas y dependencias

| ID | Entrega y estado en el corte base | Criterio de cierre | Depende de |
| --- | --- | --- | --- |
| B1 | Plan/contratos y seguimiento: esta documentación | Matriz de alcance, alta obligatoria, decisiones, owners y evidencias registradas | Dirección del dueño |
| B2 | Servicio preparado #120 y parada #156 históricos; preflight #261 falló antes de efectos; inspect #269/41542349197 conservó `effective_preflight_unit_unverified`; corrección #271 en curso | Rootless propio sano; namespace candidato y procedencia de almacenamiento verificados; capacidad/cgroups/permisos de aplicación probados. No reemplazar una DB por inferencia | Corrección revisada/checks, diagnóstico y preflight por Actions |
| B3 | Coordinador130, comandos149, loop161, ciclo164 y TLS173 integrados; RCA canónico187 | Comandos iniciar/detener/estado; guardia persistente, idempotencia, pausa ambigua y replay seguro probados | Contrato servido de B7 y panel B4 |
| B4 | Lectura128, formulario148, panel163, preflight189, custodia208, origen HTTP224/226 y owner-enroll229 integrados; sin inscripción física ni forwarding probado | Acceso privado tablet; Socios > Agregar socio cifrado/atómico; errores, duplicados, denegación y estado posterior visibles | B3 contrato; servicio de alta/clave/DB |
| B5 | Dispatcher134, Telegram162, `/avisos`163, worker188, custodia199/203 y prueba única204 integrados; recorrido host/recepción pendientes | Proyección fiel de estados persistidos, límites/restart/dedup; razón ambigua durable sin llamar entrega real a aceptación de API | Resultados persistidos de B3; UI B4 y provisión #168 |
| B6 | Chromium IPC #237, seguridad242, Compose243 e instalador246/247 integrados; sin ejecución host; observación real 41537796470 UNKNOWN y metadata #270 integrada sin nueva captura | Una sesión aislada con recursos, parada y errores medidos en entorno candidato; alcance de egress explícito | Presupuesto separado; observación real no inferida de test offline |
| B7 | HTTP224, Compose243, `beta-browser-install`246 y ciclo completo/recovery PR #253 integrados, sin aceptación host | Programa arrancado conecta B3/B4/B5; health funcional, acceso privado y manifiesto por componente; instalación desechable probada | B2–B6 según componentes del candidato |
| B8 | HTTP loopback170, probe TLS190 y smoke de contenedor limitado200; E2E host pendiente | Suite E2E, lint/types, RCA, seguridad e imágenes sobre mismo SHA; rapidez/recursos y revisión exacta | B7 consolidado |
| B9 | Publicación dual239 y workflow246 integrados; sin release dual del candidato final ni instalación verificadas | SHA→dos digests/manifiestos del mismo release→procesos instalados trazables; nueva release para HEAD final y capacidad revalidada; sólo workflow y mutex Boca | B2 apto, B8 verde, decisión final del candidato |
| B10 | Aceptación/parada protegida200 integrada, sin dispatch | Recorrido desde interfaz real/tablet, persistencia/reinicio, límites, denegación y avisos; acta de versión/pendientes | B9 y matriz de aceptación |

Estos IDs no son estados de la aplicación. Cada cambio de estado de una entrega
se acompaña de issue/PR, SHA base/candidato/integrado, runs, resultado, límites,
siguiente dependencia y owner. Un merge de módulo no cierra B7/B10 por sí solo.
No es necesario fusionar todos los PR históricos; conservar su reconciliación
en [ROADMAP](ROADMAP.md) y rescatar únicamente aportes todavía pertinentes.

## Matriz completa de alcance UI: panel propio y Site complementario

El diseño y seguimiento deben contemplar desde el principio las funciones
conversadas, sin confundir cobertura del plan con funciones operativas. Esta
matriz conserva el alcance de [#113](https://github.com/mbalbo2023/boca-socios-assistant/issues/113),
[#9](https://github.com/mbalbo2023/boca-socios-assistant/issues/9) y
[#16](https://github.com/mbalbo2023/boca-socios-assistant/issues/16). No inventa
modalidades, permisos o productos que no se hayan definido.

**Panel propio** es la superficie operativa prevista de la BETA privada. El
**Site #113** sigue siendo demo privada sintética/complementaria: su proxy
read-only falla cerrado sin backend y la cola D1 está desactivada; no está
conectado a DB, comandos,
mensajería ni Actions. La intención de contemplar una
función en ambos diseños no decide duplicar todos sus controles ni demuestra
que el Site pueda ejecutarla. La navegación/estado planificado puede mostrar
«pendiente», «diferido» o «no habilitado» con motivo, sin botones que simulen
efectos reales. No afirmar «gestiona todo» ni «todo operativo desde el inicio».

Estados: **visible/planificado** significa incluido en el diseño o seguimiento,
no una pantalla ya publicada; **integrado** describe código; **operativo** exige
interfaz real, identidad/permiso, contrato conectado y prueba del candidato en
el entorno. Hoy ningún control del Site cumple esa última condición. La
aceptación BETA de simulación y la operación real contra Boca son hitos distintos.

| Función conversada | Cobertura UI prevista | Código/evidencia disponible | Estado de entrega y gate pendiente |
| --- | --- | --- | --- |
| Alta y consulta de socios | Socios > Agregar socio; lista/consulta con resultado explícito | Servicio cifrado31, formulario148, lectura128, panel163, TLS173 y preflight189 integrados | Alta sintética obligatoria; credencial física de dueño, instalación y recorrido tablet aún por probar |
| Baja/revocación y cambio de credencial | Acciones de ciclo de vida con confirmación y resultado | Servicio interno y UI owner #163 integrados | E2E servido/host pendiente; no borrar cuotas ni tratar revocación como borrado total de persona |
| Rotación de clave y eliminación completa | Mostrar alcance/estado y requisitos de custodia | Recifrador40 y migración0004 opt-in; no rotación real demostrada | Pendiente explícito: coordinación de escritores, DELETE/retención/recuperación; no se añade a la BETA por una pantalla |
| Eventos, categorías, horarios y fuentes | Selección/configuración definida, horarios ART, origen y fecha de avisos | Modelos/simulador y cuota local; backlog de categorías/ingesta/procedencia conservado | Gestión UI y datos oficiales no operativos; definir contratos concretos sin inventar categorías/modalidades |
| Simulación, iniciar/detener/estado y reinicio | Controles y resultado local, pausa visible en ambigüedad | Coordinador130, comandos149, loop161, ciclo164, controles163, TLS173 y RCA de UUID187 integrados | Objetivo obligatorio BETA; faltan instalación, sesión del dueño/acceso privado y E2E host; no es reserva Boca |
| Sesiones múltiples y límites | Configuración/estado de sesiones autorizadas y consumo | Simulador agrupa aliases por socio/evento; guardia una intención/cantidad1 | UI/BrowserContext/medición pendientes. Varias sesiones no prueban posiciones o tokens Queue-it independientes |
| Avisos locales y Telegram | Bandeja/estado de avisos, canal y fallos explícitos | Outbox durable, dispatcher134, adaptador162, UI163, worker188, parada194, helper cifrado199, custodia203 y prueba única204 | Formulario privado255 integrado; bot/destino reales, custodia/prueba antes de simulación y recepción #168 pendientes, sin afirmar entrega por código integrado |
| Diagnóstico, fuente pública y recursos | Semáforo con procedencia/hora, salud y límites | Workflows fuente/host, inventario98, preparación120 y medición Chromium offline | Proyección UI real pendiente; un semáforo externo no habilita login ni prueba capacidad de host |
| RCA, calidad y trazabilidad | Versiones, SHA/digests, runs, decisiones y errores redactados | CI, reviews, ledger RCA y continuidad45; no editor automático de código | Integración UI/recibos por acción pendiente; nunca sustituir pruebas exactas por una insignia sintética |
| Release/deploy y operación host | Mostrar estado/recibos y alcance permitido | Workflow protegido; rootless #120, preflight #124, parada 41282301501, imagen release 41301618285 para corte #208, custodia owner208 y Site181/196, `beta-install`191 y aceptación/parada200 integrados. #219/PR #220 integró limpieza inmediata y acotada tras un fallo BETA; no ejecutada en host | Revalidar release coincidente con HEAD; faltan BETA marker, identidad privada, dispatch de install y control Site→Actions; en fallos, retener volúmenes y requerir inventario ante estado incierto; nada de SSH/Docker/secreto en Site |
| Backup/restore | Estado diferido y motivo visible/planificado | Biblioteca offline47; ningún ensayo operativo acredita recuperación | Diferido por el dueño hasta versión productiva fiable; sin botón operativo ni backup ahora |
| Login, cola, elegibilidad, reserva/compra real | Identificar hito separado y no habilitado | Modelos y observación pública histórica; sin flujo autenticado validado | No habilitado en esta BETA; requiere consentimiento/custodia, flujo legítimo y conciliación de resultados ambiguos |
| Administración multiusuario y modalidades no descritas | No inventar controles, roles o planes | El formulario de socios no crea administradores; no hay definición aprobada de otras modalidades | Sin definición: registrar la necesidad antes de diseñar/activar, sin presentar una suposición como función acordada |

El simulador sí documenta FIFO/lotería de precola y aliases locales; son
políticas sintéticas, no modalidades comerciales ni una descripción comprobada
de la fila de Boca. Su existencia en código no aprueba por sí sola un selector
nuevo de negocio. La interacción humana en una eventual reserva real conserva
su estado de decisión pendiente en ROADMAP.

Accesibilidad atraviesa todas las filas: tablet Samsung/Android e iOS, etiquetas
visibles, objetivos táctiles amplios, teclado/foco, estados comprensibles y
control por voz sin depender de hover. Las pruebas de HTML/handlers no acreditan
compatibilidad real de cada dispositivo. No publicar credenciales, cookies,
tokens de cola, enlaces que concedan acceso ni secretos en UI/logs/notificaciones.

Cada fila sólo se marca operativa al enlazar superficie concreta (panel/Site),
ruta/handler, permiso, pruebas, gate y recibo de ejecución. Un elemento que se
muestra únicamente como plan conserva ese rótulo y su pendiente; no se cierra
por haberlo dibujado ni se elimina por no entrar en el primer hito funcional.

## Recorrido obligatorio: Socios > Agregar socio

La persona autorizada abre el panel privado, entra a **Socios** y usa
**Agregar socio**. El formulario requiere los datos que ya valida el servicio
(email/identidad local, credencial sintética, registro de consentimiento y
nombre visible opcional). Usar labels explícitos, foco/teclado ordenados,
mensajes de error asociados y campos accesibles por voz; comprobar el recorrido
en tablet sin publicar secretos. La interfaz debe identificar el modo de simulación,
no sugerir que confirmó una cuenta Boca. La autenticación de quien administra
el panel es distinta del alta del socio; gestionar usuarios administradores
adicionales no se declara implementado por este formulario.

El backend autentica/autoriza la operación, valida límites y protección de
sesión/CSRF/replay y llama `MemberEnrollmentService.enroll()`. Ese servicio ya
normaliza email, crea UUID, cifra con AES-256-GCM vinculado al socio y persiste
miembro/credencial/auditoría en una transacción. El caller establece el contexto
de consentimiento; la biblioteca no verifica consentimiento externo ni
pertenencia/eligibilidad ante Boca. La clave no se guarda en DB, HTML, imagen,
repo o logs. La respuesta contiene estado/identificador opaco, jamás contraseña.

Después de éxito se muestra el socio local y puede seleccionarse para la
simulación. Doble envío/reintento no debe crear otro socio ni otra intención
indebida; diseñar el contrato de idempotencia sin sustituir datos existentes.
Validación fallida, email duplicado, clave inválida, DB incompatible o caída
transaccional deben dejar un estado visible y verificable sin filtraciones.
No mostrar de nuevo el secreto ni conservarlo en URL/logs/artefactos de prueba.
Las pruebas usan sólo fixtures sintéticos, incluso en la aceptación final.

## Evidencia de composición ya integrada

[PR152 / issue151](https://github.com/mbalbo2023/boca-socios-assistant/pull/152)
añade cuatro recorridos: alta/repetición/completado/reconstrucción; stop antes
de ejecutar; rechazo sin autenticación; y recuperación de aviso tras fallo de
persistencia sin repetir browser. Usa el WSGI y servicios reales de aplicación
sobre la misma DB temporal sintética, con identidad y browser dobles. Los
comandos se invocan en proceso, no por HTTP. No prueba servidor, passkey,
tablet/voz ni sitio Boca. Ver [aceptación en proceso](quality/BETA_JOURNEY_ACCEPTANCE.md).

## Integración de contratos pendiente antes de servir la aplicación

Los adaptadores #128/#148 por sí solos no constituyen un servidor privado.
El panel owner passkey #163 ya integrado en código unifica alta, estado y
comandos bajo la sesión de dueño. Su identidad no está provisionada ni servida
en el host; un puerto de pruebas no es acceso privado operativo.
[Las opciones concretas de acceso/bootstrap](https://github.com/mbalbo2023/boca-socios-assistant/issues/17#issuecomment-6551922108)
son antecedentes de diseño. Falta un contrato configurado y probando
identidad, origen HTTP localhost sobre SSH y rechazo de terceros. Incluir consulta de estado
después del alta desde la misma sesión autorizada y expiración/denegación
en la aceptación HTTP real.

El outbox persiste sólo pending/claimed/accepted/exhausted. Exhausted no guarda
la causa, y DispatchReport.ambiguous es transitorio; no se puede reconstruir un
motivo ambiguo durable a partir de esos cuatro estados. La proyección de avisos
con razón persistida queda pendiente si se necesita ese detalle tras reinicio;
la UI debe mostrar únicamente lo que la evidencia permite, separándolo de
needs_review del comando. La tabla de aceptación describe un objetivo, no un
motivo durable ya implementado.

El loop persistente #161 y el ciclo local #164 integraron recuperación
exclusiva al arranque en biblioteca; el panel #163 aporta lista, comandos y
avisos bajo un owner WSGI. Un stop de otra instancia no cancela por sí solo la
tarea que vive en un proceso diferente; el servidor debe respetar ese
contrato. Estas pruebas no demuestran listener, TLS, bootstrap, tablet o
navegador real. La composición servida y el despliegue conservan sus criterios
de cierre.

## Matriz de aceptación antes y después de desplegar

| Recorrido | Antes de desplegar | En droplet, después de instalación autorizada |
| --- | --- | --- |
| Acceso privado | Usuario no autorizado/permiso insuficiente/CSRF/replay rechazados; secretos ausentes de respuestas/logs | Acceso desde tablet autorizado y rechazo real de tercero; forward SSH, HTTP localhost y sesión del acceso concreto |
| Alta de socio | E2E formulario→servicio→cifrado/DB/auditoría→lista; error/duplicado/doble clic/reinicio; ninguna fila parcial | Alta sintética desde panel real; estado tras reinicio controlado; clave separada y permisos comprobados |
| Una entrada | Un socio/evento, cantidad1; concurrencia/alias/doble comando/replay sin nueva intención indebida | Repetición sintética desde interfaz sin multiplicar intención; no equivale a ticket Boca |
| Start/stop/status | Comandos idempotentes, parada repetible, reloj/expiración y fallos; UI refleja estado durable | Estado fechado consistente con proceso instalado; parada sin tocar otro proyecto |
| Reinicio/ambigüedad | Caídas antes/después de intención, resultado y aviso; pausa visible, sin éxito inventado ni reejecución ciega | Reinicio autorizado de Boca, datos/clave retenidos y estado coherente |
| Avisos | Estados persistidos y límites/backoff/fencing/replay; causa ambigua durable pendiente, no inferida de exhausted | Aviso local visible y trazable al resultado; no afirmar recepción Telegram |
| Recursos/errores | Clave inválida, DB incompatible, límites CPU/RAM/PID, red/mounts y capacidad post-pull | Pruebas efectivas de cgroups, salud funcional, espacio/inodos y aislamiento Boca |
| Rapidez | Medir tiempos y distribución de recorridos/checks con cantidad de muestras y SHA | Medir mismos recorridos sintéticos y consumo con versión/digests; comparar condiciones |

No aplicar migraciones automáticamente a una DB encontrada. El candidato debe
inventariar las estructuras necesarias de sus módulos y el diff concreto;
0004 de rotación no se transforma en requisito de esta BETA. First-install
no es un procedimiento de upgrade: datos/namespace existentes requieren
compatibilidad, procedencia y un procedimiento revisado antes de escribir.

## Rapidez y eficiencia sin perder integridad

La muestra del corte base [CI 41259139901](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139901)
(SHA `4922e45b5e2e38242263b6ba10969a8190aa939a`) registró calidad16s e
image-build41s: controlador8s, Chromium28s y smoke2s. La suite de 594 pruebas
ocupó 3,53s. Son duraciones de una ejecución de runner, no
capacidad del droplet ni latencia de despliegue; no bastan para atribuir una
mejora causal o prometer un ahorro. El análisis detallado de cola, builds
repetidos, opciones de caché y evidencia se mantiene en issue #143 y
[ADR0060](ADR/0060-measured-ci-budget.md), integrado por #146. No cambió
workflows ni implementó instrumentación nueva o un ahorro demostrado.

Prioridad de trabajo aprobada: consolidar cambios/formatos antes de publicar
cada candidato; ejecutar en paralelo pruebas/scan/build independientes; hacer
una reconciliación final en orden de integración. Conservar mutex único host,
revalidación inmediata de capacidad/identidad y checks exactos. No dividir por
principio una suite de pocos segundos ni anular los builds exigidos por policy
porque el cambio parezca documental. #136 ya separa concurrencia entre PRs.

Registrar cola vs ejecución, build por imagen, scan, suite/E2E, preflight,
release, transferencia/pull, arranque/health y postflight. Para panel/alta/estado
registrar muestras, mediana/p95, errores y CPU/RAM/IO del entorno. Separar
primera ejecución de ejecución con caché y distinguir sobrecarga del runner de
latencia de la app. Aún no hay cifras reales de despliegue ni SLA demostrado;
el candidato debe fijar criterios de aceptación medibles a partir del baseline
antes de presentarse para instalación, sin inventar umbrales cumplidos.

Caché acotada, builds separados o reutilización de imagen se evalúan como
cambios técnicos posteriores con medición y review: preservar lock/digests,
procedencia, aislamiento de confianza y escaneo actual. Nunca promover una
imagen no confiable de PR directamente a release privilegiada ni reutilizar
el resultado de scan de otro candidato como aprobación. Fallos de integridad
se corrigen; no se aceleran debilitando gates.

## Paralelización, documentación y cierre

El [recibo de inicio](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142)
registra los escritores asignados. Ownership operativo puede relevarse allí;
estas responsabilidades evitan editar rutas compartidas simultáneamente:

| Ámbito | Seguimiento | Responsabilidad de escritura/revisión |
| --- | --- | --- |
| Host/rootless | #145 | Helper/workflow y ADR0058; root es único operador del host |
| Coordinación | #127/#130 y #147 | Guardia/coordinador/comandos y ADR0057; contrato de estados primero |
| Panel/alta | #126/#128 y #17 | Adaptadores, formulario/consentimiento y ADR0061; sin docs centrales simultáneas |
| Avisos | #133/#134 | Dispatcher/ADR0051 integrados; ADR0059 sólo reservado para futuro alcance, no existe como contrato aceptado; sin envío real inferido |
| Eficiencia | #143 cerrado con146 | Baseline/análisis y ADR0060 integrados; instrumentación/optimización futura requiere evidencia propia, sin retirar gates |
| Plan/documentación | #144 | Este plan, docs centrales y ADR0056; reconciliar hechos de módulos |
| Integración/continuidad | #45/#113 | Root revisa, serializa merges y actualiza checkpoint/decisiones |

Un escritor por rutas: host/datos, coordinación, panel/alta, avisos, navegador y
calidad/documentación pueden avanzar en paralelo sobre contratos acordados.
Cada PR actualiza su ADR/contrato modular y evidencia en el mismo cambio. El
escritor documental central mantiene este plan y estado; el responsable de #45
actualiza el checkpoint al integrar. Evitar escritores simultáneos sobre docs
centrales y revalidaciones prematuras de todas las ramas tras cada merge.

Regla84 exige consistencia antes de cerrar la entrega; no obliga a duplicar
información idéntica en todos los documentos ni bloquea pruebas paralelas por
esperar un merge ajeno. Si cambia un hecho central, coordinar su actualización
con el mismo candidato o su integración controlada y dejar el pendiente
explícito hasta completar el recibo; no llamar actual a información conocida
como obsoleta. No hay robot ni calendario de mantenimiento separado.

El acta final enlaza versiones, digests, runs, acceso privado, matriz completa,
mediciones, limitaciones y pendientes. Sólo entonces se marca **BETA validada en
simulación**. Permanecen registrados el flujo real, Telegram externo pendiente,
observación pública autorizada, rotación/recuperación real, accesibilidad y
backlog histórico sin evidencia de cierre. Backup/restore diferido y
Porota/PPI Watch fuera de alcance.
