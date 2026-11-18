# Binding instructions for every coding agent

## CHECKPOINT VIGENTE G18 — 2026-11-18 ART / HANDOFF PARA DEPLOY BETA

**Leer primero [handoff G18 completo](docs/HANDOFF_G18_2026-11-18.md) y
[issue canónico #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).**
El producto físicamente instalado y conservado sigue siendo **G17**
(`7f20bf0acf43b2e17812bfc35efc86a552b5a404`); Actions Boca READ_ONLY
[#1252](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44353903240)
y [#1253](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44354524641)
confirmaron controller HEALTHY en `127.0.0.1:8443`, worker CREATED/PID0 y
binding/recursos/inodes intactos. No prueban navegación, login ni tokens.

**G18 está MERGED y publicado, NO desplegado:** [PR #552](https://github.com/mbalbo2023/boca-socios-assistant/pull/552)
y [release #876](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44348462224)
SUCCESS; único [APPLY #1251](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44352430452)
FAILED `ATTEST`, sin commit ni contenedores nuevos. **No reintentar.**
El diagnóstico dejó de ser CODE_ONLY: [PR forense #553](https://github.com/mbalbo2023/boca-socios-assistant/pull/553)
MERGED en `8c3edd972c4be77ebae5be40a54ccff6c3202b30` después de
4GO_FINAL; CI main [44365020955](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44365020955)
3/3 PASS y Security [44365020817](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44365020817)
3/3 PASS. **Una sola** observación forense READ_ONLY [#1255](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44365905614)
SUCCESS halló marcadores genuinos `evidence,intent,terminal`, sin `commit` ni
`technical-postflight-v2`: `NO_GO/ATTEST`, causa exclusiva `UNPROVEN`.
Arquitectura, QA, Operaciones y Root coincidieron en dos rutas indiscernibles:
constructor/factory o `backend.attest`. No inventar cuál; no repetir #1255.
[RCA](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6987374351).

**Código existente: REUTILIZAR.** Navegación URL/HTTP/intentos, evento/cola,
Queue-it/Boca tokens y copia, polling 5 s, Telegram token/Chat ID directo y
dos motores lógicos ya tienen rutas. [Inventario UX](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6987469566).
No confundir `has_auth` con login DOM, worker CREATED con motor activo, ni
configuración de Telegram con sender habilitado. `Ingresar` aún pide passkey
sin sesión; Motor B bajo pliegue y copia profunda requieren QA/corrección
focal. **BETA NO_GO**, `SIMULATION_ONLY`, **sin reservas reales**.

**Ownership y próxima acción:** Root integra/checkpoint; Arquitectura, QA y
Operaciones dictaminan independientemente antes de código, con autor distinto.
Reconciliar el HEAD y PR abiertos antes de trabajar; no repetir PR, builds,
release, APPLY ni observaciones. Toda operación física/Playwright del droplet
**sólo GitHub Actions Boca**; nunca navegar el servicio privado desde browser
interno ni tocar Porota, otros puertos, servicios o Docker. No solicitar de
nuevo autorizaciones ya concedidas. Las secciones inferiores son HISTÓRICAS.

## Histórico: checkpoint G17 — 2026-11-18 ART (corte previo / CODE_ONLY)

Fuente físicamente aceptada y **no repetir**: G16
`main@75b00d8e1cd903d3d727a2628134a27fd740fc42`, release874,
upgrade protegido #1228 ACCEPTED y postflight #1230 SUCCESS. La nueva
observación READ_ONLY [Action #1237](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44300816017)
mostró controller HEALTHY, worker CREATED/PID0, motor físico STOPPED y
STOP/APPLIED/cause NONE. Ese estado posterior **no explica** por sí mismo el
FAILED de Motor A capturado por el titular a las 08:55 ART.

En [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
constan la captura QA, el RCA de código y el consenso 4/4 PRE_CODE para G17.
El coordinador puede cerrar con `WORKER_RECEIPT_UNVERIFIED` tras esperar
30 segundos un acuse de inicio y salir ANTES de abrir sesiones; 25 contextos
solicitados / 0 creados no acreditan URL navegada, evento, cola ni tokens.
La causa física concreta de ese acuse faltante permanece UNKNOWN. Registros
del ejecutor global no prueban navegación particular del motor.

Rama local aislada `feature/417-g17-motor-evidence-ux`: único autor distinto
de Root modifica `engine_view.py` y `test_engine_live_status_ui.py` para
mostrar evidencia de navegación disponible, prioridad del error, estado
lógico versus actividad física no comprobada, y plegar registros globales.
Arquitectura detectó y el autor subsanó el sondeo HOME con los helpers JS
existentes; prueba Node cubre ambos motores y URL/HTTP/fecha saneados.
Un 4/4 PRE_CODE **adicional y limitado a pruebas** quedó en
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6979033163):
`tests/test_automatic_observer_ipc.py` importaba `engine_sessions` por primera
vez **durante** un monkeypatch temporal de `AutomaticQueueObserver`, y su
alias persistente contaminaba la prueba posterior de 50 contextos (50 NO_GO).
El commit local `a242e12` preimporta antes del patch, lo acota y verifica
restauración; pareja RED reproducible antes, GREEN en ambos órdenes después.
No se modificó código productivo del pool, worker o IPC; no era una prueba
del fallo operativo del droplet. La suite serial completa sobre SHA final
queda pendiente de certificación independiente por QA.
El [diseño](docs/superpowers/specs/2026-11-18-g17-motor-evidence-ux-design.md)
y [plan](docs/superpowers/plans/2026-11-18-g17-motor-evidence-ux.md)
mantienen CODE_ONLY: sin PR/build/release/host hasta revisión independiente,
suite exigida y nuevo consenso 4/4 GO_FINAL. No extender a worker, IPC,
Telegram, autenticación ni eliminación de passkey sin RCA y consenso nuevos.

Higiene PR0: Arquitectura, QA, Operaciones y Root revisaron individualmente
los 6 Dependabot #544–#549; fueron comentados y cerrados **sin merge**, ramas
e historial conservados, con ledger en [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
y #417. Cinco tenían CI FAIL, Ruff #549 estaba GREEN pero era mantenimiento
diferible. Reconciliar cualquier PR nuevo antes del futuro release.
SIMULATION_ONLY, sin reservas reales, Porota intocable y operaciones físicas
exclusivamente por GitHub Actions de Boca. Telegram, `/ingresar`, QA Samsung
y certificación BETA todavía no se consideran concluidos.

## G6 — excepción de publisher, no desplegada (2026-11-16 ART)

La release869/run43922790822 falló en el primer push del browser con
`unknown blob`; causa de registry/cliente no acreditada. No reintentar ese run
ni volver a despachar su SHA. La excepción única y 4/4 PRE_CODE están en
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6925043732).
Este cambio es CODE_ONLY hasta revisión independiente, CI, integración y
autorización operativa: un único retry global dentro del mismo run, sin rebuild.
No equivale a release ni deploy exitoso; BETA NO_GO, Telegram sender OFF y
SIMULATION_ONLY. Root conserva ownership de GitHub, gates y operaciones Boca.

## Histórico G2 — candidato CODE_ONLY (2026-11-16 ART)

La continuidad vigente está en [#417, checkpoint canónico](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6922744921)
y [reconciliación de raíz](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6923058844).
G0/G1 están cerrados; no repetirlos. Fuente W/main verificada por raíz:
`55da98df6713d40ebf1455fb328005544043d091`. El único candidato local es
`feature/417-g2-samsung-ux-consolidated`, base de cierre
`0296876539b20e9a00eea0daedcc809e538e4765` más el ajuste focal del mensaje
de socio en polling de Actividad y estos encabezados. Sigue CODE_ONLY:
sin push, PR, CI nuevo, imagen, Action ni instalación por este cierre.

P1 y G3b A1c se recuperaron exactos, sin reimplementación: SHA256 de diff
`f0607e6dcd2a37b4c5e024df1dfaf2e84f0e7a9f481ff40efd1b1047bc1613b6`
(2 archivos) y `39e2a100d12f0000a61ceb26c1a71f5cdde5f802ecb61b922b8480473a487300`
(7 archivos). No repetir sus suites históricas ni la UX ya acreditada.
El [diseño congelado](docs/superpowers/specs/2026-11-16-boca-three-page-qa-design.md)
y [plan](docs/superpowers/plans/2026-11-16-boca-three-page-qa-candidate.md)
gobiernan tres destinos principales: Control, Actividad y Configuración;
dos motores lógicos comparten un worker físico. Preservar ACL de lectores,
POST/CSRF/Origin/one-use, CSP, revelación privada y veracidad de observaciones.

[4GO_PRE_CODE](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6921095928)
y enmiendas [6921748130](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6921748130)/
[6921916858](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6921916858)
están aprobados. 4GO_FINAL, 4GO_INTEGRATION y 4GO_OPERATION siguen pendientes:
autores no son revisores. Root posee la reconciliación final y G3–G7: PR único,
CI/security exactos; G3b metadata-only sobre W antes de reemplazarlo bajo GO
operativo nuevo, siempre engine UNVERIFIED; custodia READ_ONLY sin provisionar
admin; release dual, pair observe → retained observe → un APPLY/postflight;
y prueba integral privada Samsung SIMULATION_ONLY. Ningún GO de código
autoriza operar el host ni certifica actividad de motores o navegación.

La evidencia física heredada es release868/run43811532109,
APPLY1186/run43813151261 y observe1187/run43814281299 SUCCESS; controller
HEALTHY y worker Created/PID0 en aquel recibo, sender OFF. No es medición
actual ni instalación de G2. QA mostró WORKER_RECEIPT_UNVERIFIED, sin causa
acreditada: no equivale a ausencia de evento, cola o tokens. Detalle y
ownership en la [matriz vigente](docs/BETA_INTEGRATION_STATUS.md).
SIMULATION_ONLY, BLACKBOX/datos/passkeys, Porota/PPI y otros recursos intactos;
sin reservas, navegación del agente, credenciales ni Telegram sender.

## Histórico — cierre técnico antes de QA integral

El titular pidió terminar los pendientes y luego realizar su prueba integral.
Root mantiene integración, documentación y cualquier Action como único
operador; autores separados y cuatro votos previos/finales para cada delta.
La [matriz vigente](docs/BETA_INTEGRATION_STATUS.md) concentra evidencia y
ownership. Base `1ab24a6` integra PR528; CI1280/Security1093 SUCCESS.
La observación1170 ya terminó; no repetirla ni recovery1166/APPLY1153.
R308/issue529 y R309/PR530 tienen cuatro revisiones finales GO. La cuenta
regresiva no está instalada; su fixture offline mide165160, cota170000.
R309 corrigió lectoresR, intérprete absoluto y transporte incierto antes
de aprobarse en25ed05e. Su ZIP47/490980B fuente/135443B comprimidos conserva
la adenda installed500000, individual/default450000 y ZIP300000. Root integra
un único candidato y exige CI exacta/main antes de una Action diagnóstica.
Telegram requiere evidencia real de clave/recibos y decisión de adopción
antes de preparar sobre otro producto. DOM autenticado y resultado real carecen aún
de contrato acreditado; no inventar éxito ni atribuir procedencia al simulador.
SIMULATION_ONLY, senderOFF y BLACKBOX intactos; conservar datos/passkeys y
aislamiento de otros proyectos. No pedir permisos rutinarios ya delegados.

## Histórico R307 — continuar observación1167, issue528

El titular transfirió la continuidad del chat interrumpido. Diseño/plan R307
y cuatro GO previos en issue528 limitan el delta al observador existente y
dos tests: CLI actual1167, APIs/defaults1156 preservados para R305. Sin otro
observador ni cambios workflow/builder/bootstrap/backend/cotas. Autor separado
posee sólo esas tres rutas; root docs/RCA/GitHub/única Action. R/release867/
APPLY1153 y recovery1166 ACCEPTED no se repiten. Prepare1167 falló con
restauración saludable/motorOFF; causa desconocida. Cuatro revisiones finales
y CI/main exactas preceden una observación READ_ONLY. Ausencia del helper no
prueba causa ni autoriza retry. SIMULATION_ONLY, senderOFF, BLACKBOX/datos y
Porota/PPI protegidos; no volver a pedir permisos rutinarios ya delegados.

## Histórico R306 — ordenar testigos, issue527

W1 b96db3a13ad50e663ae3eb8cde82345a72792aaf está GREEN.1164 es el único
intento R305: NO_GO/PREFLIGHT, init/retire NOT_ATTEMPTED. No repetirlo ni
atribuir su causa histórica. R/release867/APPLY1153 permanece instalado.

Diseño/plan R306 gobiernan ordenar una copia de raw por Destination después
del contrato _mounts exacto y recorrer esa misma lista para identities.
Conservar todos los campos, Source/RW/duplicados/alias/dev-inode y demás
validaciones. Autor separado sólo módulo recuperador y test R306 nuevo;
raíz docs/RCA/GitHub/host. Cuatro opiniones previas/finales y CI exacta.
No modificar otros tests, codec, workflow, builder, bootstrap ni cotas.

Un único despacho nuevo corregido puede continuar después de RED/GREEN,
cuatro GO, main GREEN y reconciliación: vuelve a probar todas las guardas
antes de START. Otro NO_GO desconocido exige diagnóstico sin efectos;
no encadenar retries. Prepare separado sólo tras init+retiro ACCEPTED.
SIMULATION_ONLY, BLACKBOX unread/unmodified, datos/passkeys/volúmenes
preservados, sender sin activar y Porota/PPI fuera de alcance. El encargo
vigente autoriza esta continuidad sin reiterar permisos rutinarios.

## Histórico R305 — recuperación del inicializador exacto, issue526

Base W0 be788a7dc602f4fce63da1d2a4ce859da73c5b08 integra PR525; CI1273 y
Security1090 SUCCESS. R845f31abfb1762dff27e6fc3274fcc40507f3f18 ya instalada
por release867/APPLY1153. Único diagnóstico1161 COMPLETE/OBSERVED_NO_GO:
par exacto healthy/created; helper1156 initialize-volume created/PID0,
CAP_CHOWN observado contra CHOWN esperado. No repetir R304 ni release/APPLY.

Issue526/comment6896582424 registra cuatro GO previos sobre spec/plan R305.
La recuperación se limita a ese único CID,
con nueva lease/doble lectura/perfil y mount exclusivo. Inicializador R
comprueba vacío/UID0 antes de efectos; start único y retiro sin force/-v sólo
tras respuesta íntegra. Parciales se conservan; ningún retry ante incertidumbre.
No fake _created_volume, nuevo helper, modificación R304/imagen, SQL, borrado
volumen o stop/start del par. Autor separado posee ocho archivos del plan;
raíz docs/RCA/GitHub/host. Cuatro votos previos y finales, CI/main exactos
antes de un despacho. Prepare canónico sólo tras init+retiro aceptados.

Hasta el recibo físico no afirmar recuperación, PREPARED ni motor OFF.
SIMULATION_ONLY, BLACKBOX unread/unmodified, sender sin activar, datos/passkeys
preservados y aislamiento Porota/PPI. El encargo del titular autoriza continuar
sin reiterar permisos rutinarios; no omite guardas ni permite retry ciego.

## Histórico R304 — diagnóstico readonly de Telegram, issue525

R `845f31abfb1762dff27e6fc3274fcc40507f3f18` está instalado por release867 /
APPLY1153 ACCEPTED y cleanup ACCEPT. ADMIN1154 PROVISIONED y STATUS1155
HEALTHY/STOPPED preceden al incidente; no certifican el estado posterior.
PREPARE1156 devolvió FAILED_STATE_PRESERVED/restoration INDETERMINATE/sender OFF.
PAIR1157 no obtuvo inventario. Origin1158 sólo confirmó HTTP200 de loopback:
ni identidad de proceso ni causa; UID distinto no prueba fallo de permisos.

Issue525 y el plan R304 registran antes del código un observador propio,
sin efectos, con coordenadas fijas R/APPLY1153/incidente1156, doble lectura
acotada y razones finitas. Cuatro votos de diseño sobre su hash preceden al
autor separado. Éste sólo edita sus siete archivos; raíz posee docs/RCA/host.
No cambiar censo, healthy, backend, atestadores, caps ni paquetes históricos.
No lease, SQL, custodia, HTTP, exec ni mutaciones Docker. Preservar todos los
datos y helpers inciertos; no atribuir causa histórica sin evidencia.

Cuatro revisiones finales, CI del candidato/main y reconciliación preceden
un único despacho del observador por la Action protegida. W del diagnóstico
puede diferir de R instalado. No requiere release ni APPLY; no repetir prepare,
recuperar o limpiar antes del diagnóstico y decisión específica posterior.
SIMULATION_ONLY, BLACKBOX unread/unmodified, Telegram sender OFF y aislamiento
Porota/PPI siguen vigentes. La aceptación funcional y privada sigue abierta.

## Histórico R303 — ACK de STOP Telegram, issue524

PR521 está merged en Q `7112a4878097bc1696a60a7b1056cd1e7b559ce5`,
árbol `3e328752468895f7c712a9ec9f7630e47e585b91`, CI1268/Security1088 GREEN.
El instalado sigue en M; observe1148 acredita baseline sin0007 y senderOFF,
sin parada/restauración. La causa física de migrate1144 sigue sin demostrar.
El contrato #524 y cuatro GO de diseño en #417/comment6892566944 autorizan
sólo reutilizar `-t` en tres llamadas STOP de las dos fuentes Telegram
instaladas. ACK estricto, tiempos10/5, identidad y writer fence intactos.
Regresión real de frontera antes de producto; plan R303 gobierna el delta.
Autor separado, cinco archivos permitidos; raíz posee docs/RCA/GitHub/host.
No SQL nuevo, parser permisivo, builders/caps/allowlists o pin full-cutover.
Ningún host durante código. Cuatro GO finales y gates del nuevo main preceden
evaluar una migración corregida sobre M/release866; fallo vuelve a RCA.
Sólo éxito físico habilita release final/promoción consolidada; prepare sobre
el nuevo par, nunca M antes de actualizar. SIMULATION_ONLY/BLACKBOX/datos y
Porota/PPI intactos. No navegación, mensajes o certificación50 supuesta.

## Histórico R301/R302 — monitor y observación de esquema, candidato521

R301 conserva sus tres tareas congeladas/revisadas. R302/#522 está registrado
antes del código con cuatro GO de diseño en #417/comment6891704268. Reutilizar
únicamente verify-schema readonly, lease y backend instalados, con selector
telegram-schema-observe; no repetir migrate1144 ni pasar a prepare sin
SCHEMA_READY físico. Plan R302 gobierna el delta de mantenimiento. MainP
c14f98d6adf4c4042f29e11f23f8a76545a1b0f9 está GREEN; instaladoM permanece
5281efae7dafe89be047073796b3e0a7e19785ed. 1144 restauró HEALTHY/engineOFF;
esquema0007UNKNOWN. No afirmar causa ni rollback. ZIP47 entradas/caps450000
fuente300000ZIP: cierre R302449973B,27B de margen; revisar si no cabe. El autor
sólo edita sus ocho archivos asignados; raíz controla docs/RCA/GitHub/host.
SIMULATION_ONLY, BLACKBOX, datos, passkey y Porota/PPI protegidos. Sólo Actions
serializadas por raíz. R301 no autoriza reserva, ganador, foto o mensajes.

## Histórico — instrucciones del delta de monitor R301

## Estado vigente R301 — monitor observado, con contrato registrado

El delta autorizado está registrado en #521 antes del código y descrito en
`docs/superpowers/plans/2026-11-15-r301-observed-monitor.md`, con cuatro GO
de diseño. Reutilizar filas/polling/reveal ya instalados; sólo completar
evento/motivo, configuración/último goto/última URL final y texto del enlace.
Task1: engine_protocol/automatic_observer; Task2: engine_sessions; Task3:
engine_view/private_ui. No ampliar caps, permisos, navegación ni sesiones.
SIMULATION_ONLY, BLACKBOX, datos y Porota/PPI protegidos. No proveedor/host
por autores, no envíos, reservas o capturas de entrada supuestas.
R300/PR520 sigue sus gates y mantenimiento físico por raíz; su árbol es la
base candidata de este worktree. Reconciliar main antes de publicar.
Plan, RCA y documentación son de raíz; revisores separados de autores.
Los cortes siguientes se conservan como historia y no amplían este delta.

## Histórico — Estado vigente R300 — migración Telegram instalada, sin repetir promoción

Main base O `f16db1008418889ffdd9b35a57bf77f1238ec659` integra PR519;
CI1262/Security1086 SUCCESS. El producto M sigue instalado desde
`5281efae7dafe89be047073796b3e0a7e19785ed`, release866/APPLY1134 ACCEPTED,
cleanup ACCEPT, ADMIN1135 PROVISIONED y STATUS1138 HEALTHY/STOPPED.
No repetir release, APPLY, admin ni STATUS ya aceptados.

[TG1142](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43688683723)
superó el import y devolvió SCHEMA_0007_REQUIRED/NOT_NEEDED/sender OFF:
baseline SQLite válido, falta0007, sin detener controller ni provisionar.
El [contrato R300 y cuatro votos previos](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6891021673)
gobierna [RCA520](https://github.com/mbalbo2023/boca-socios-assistant/issues/520)
y el [plan](docs/superpowers/plans/2026-11-15-r300-installed-telegram-schema.md).

Reutilizar telegram_storage_gate migrate ya presente en M mediante backend
instalado/lease única, W y M independientes y perfil fijo. La ruta legacy es
incompatible: no despacharla ni falsificar source. No cambiar SQL, MOUNTS,
imagen o caps. Sólo restaurar controller después de acreditar retirada del
helper escritor exacto; incertidumbre conserva NO_GO sin retry. Prepare no
migra implícitamente. Sin custodia, activación, envío ni backup supuesto.

Pruebas focales y revisión independiente del código preceden CI/main y una
migración protegida; prepare sólo después de SCHEMA_READY físico aceptado.
SIMULATION_ONLY, datos, BLACKBOX y Porota/PPI permanecen protegidos. DOM
autenticado, resultado/ganador/captura/aviso por socio, countdown, aceptación
privada y capacidad física50 siguen diferenciados de esta corrección.
Los cortes siguientes se conservan como historia.

## Histórico — Estado vigente R299 — estado físico aceptado; guard del runner Telegram

R297/PR517 permanece instalado desde `5281efae7dafe89be047073796b3e0a7e19785ed`,
release866/APPLY1134 ACCEPTED y cleanup ACCEPT; ADMIN1135 PROVISIONED.
R298/PR518 se fusionó en `2581e23bbbb8b4a05fb2470a23b3c71866378151`.
[STATUS1138](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43684726506)
aceptó el par exacto, panel HEALTHY y motores STOPPED. No repetir esa lectura.

TG1139 falló antes de SSH por ENV_READY ausente; el marcador se configuró
tras revisión y readback del entorno main-only, sin cambiar secretos/protecciones.
[TG1140](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43685974310)
pasó ese gate y falló antes de SSH en el import del checker de main.
[RCA519 y cuatro votos](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6890476164)
limitan el arreglo a `PYTHONPATH: src` del paso Telegram y su regresión real
en un proceso limpio. No cambiar checker, cuerpo del paso ni entorno global.

Conservar W del workflow separado de M instalado, ZIP aislado, gates y datos.
Revisión/CI/merge exactos preceden un nuevo prepare con M/release866/digests.
Sin otra release/APPLY/admin/STATUS, activate o mensajes. Telegram PREPARED,
aceptación privada y capacidad física de 50 siguen pendientes. SIMULATION_ONLY,
BLACKBOX y aislamiento Porota/PPI intactos. Los cortes siguientes son históricos.

## Histórico — Estado vigente R298 — postflight de R297, sin segundo despliegue

PR #517 ya está fusionado y su producto R297 está instalado desde
`5281efae7dafe89be047073796b3e0a7e19785ed`, release 866/APPLY 1134
ACCEPTED con cleanup ACCEPT. ADMIN 1135 terminó PROVISIONED. STATUS 1136
permanece NO_GO de sólo lectura; Telegram no fue despachado.

El [RCA y cuatro votos previos](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889977546) delimitan el mantenimiento #518:
corregir exclusivamente la ruta del lector portátil de estado dentro del
controller y su regresión de frontera. La ruta host del binding/fingerprint
se conserva; el programa interno usa `/data/boca.sqlite3` y sólo recibe el
fingerprint. Mantener lease, atestación, readonly, doble lectura y recibo.
La corrección viaja con el observador; no repetir release, APPLY ni admin.
Revisión del delta y CI exactos preceden una única lectura corregida.
Después, preparar Telegram sobre las imágenes instaladas sólo con estado
verificable y sin mensajes. SIMULATION_ONLY, caps, datos, BLACKBOX y
separación Porota/PPI siguen vigentes. Aceptación privada/capacidad de 50 pendientes.
Los encabezados siguientes describen sus respectivos cortes históricos.

## Histórico — Estado vigente R297 — correcciones QA y dos motores independientes

El titular ya aportó QA/capturas y autorizó desarrollar dos motores funcionales:
colas/tokens y navegadores/socios, independientes y bajo demanda. El
[contrato DUAL-01..12 y consenso previo](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886406162)
y [ADR0302](docs/ADR/0302-independent-owner-engines.md) gobiernan este delta.
Continúa el mismo PR517 / `feature/417-r295-beta-followups`, sobre b23dc20.
No repetir R294 instalada ni pruebas certificadas del árbol base.

Se amplía expresamente el alcance anterior de sesión única a un presupuesto
lógico global de 50 contextos entre ambos motores, con Chromium/Firefox/WebKit.
No son 50 por motor ni evidencia de capacidad física/posiciones de cola.
Reutilizar observer, parser, vault, monitores y supervisor; un worker físico,
dos activaciones lógicas, STOP aislado y holds/releases durables en audit_events.
El worker sólo puede detenerse al liberar todos los trabajos o por recuperación
explícita de una activación perdida; un contador RAM no autoriza Docker.

SIMULATION_ONLY, BLACKBOX unread/unmodified, cantidad 1 y el guard socio/evento
siguen vigentes. No inventar DOM autenticado o entrada a partir de tokens;
conservar la sesión y declarar evidencia faltante. La revisión previa unánime
autoriza desarrollo; la revisión final requiere votos nuevos sobre el código.
No elevar caps/reservas ni añadir listeners, otro vault, DB o despliegue.

Mientras se consolida este QA: desarrollo, pruebas focales, revisión y CI del
SHA exacto en PR517. Sin merge/release/host/proveedor/mensajes del agente.
La promoción final y aceptación física siguen pendientes; únicamente Actions
protegidas serializadas, postflight y limpieza selectiva Boca, sin Porota/PPI.
El pedido posterior de prueba visual por Actions queda registrado en
[este checkpoint](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886936337).
Reutilizar CI para navegador real con fixtures y artifacts ficticios. El
observador instalado actual sólo prueba salud/identidades; no fabricar una
sesión WebAuthn ni afirmar que una captura offline prueba el panel instalado.
Los encabezados anteriores se conservan como historia, no como prohibición
de la ampliación de sesiones autorizada por el titular.

## Corte histórico R296 — un candidato, pendiente del QA del titular

El titular todavía no realizó su QA y pidió dejar un único candidato preparado
para incorporar sus correcciones antes de promover. Se conserva PR #517 y la
rama `feature/417-r295-beta-followups`; no crear otro PR para duplicar estas
integraciones. [Decisión R296](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6881603931),
[cierre de fases](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6882197549)
y [ADR0301](docs/ADR/0301-r296-consolidated-auth-and-telegram.md) son la continuidad.

R294 sigue siendo la última instalación certificada: main/instalada
`c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`, release #865 / APPLY #1117.
No hay nueva observación física en R296. Sin merge, release, host, START/STOP,
navegación del agente a proveedores ni mensajes mientras se consolidan el QA
y este candidato. Sólo Actions protegidas y serializadas para operaciones futuras.

R296 conecta la selección visible de socio en START, la sesión Chromium única,
readiness/nonce/IPC privados, el transporte R295 y la publicación cercada por
STOP/revocación en el monitor existente. El monitor distingue autenticación
activa de evidencia de cola UNKNOWN. No alterar `synthetic.py`/`ipc_worker.py`,
SIMULATION_ONLY, sin reservas/compras, bypass ni sesiones adicionales.

Telegram reutiliza stage/passkey/custodia/outbox/sender y añade backend instalado,
perfil de mantenimiento exacto, adopción recuperable del binding y proyección
pública real. Guardar el stage precede a mostrar/copiar `/start`. Renovación
explícita archiva sin borrar historia/nonce; continuación conserva el UUID de
aceptación ORIGINAL y rechaza ambigüedad. Recuperación no envía. Ninguna de estas
rutas está certificada físicamente por pruebas offline o por CI.

Reutilizar las pruebas focales y revisiones registradas, no repetir la suite
local del árbol base. Los checks requeridos pertenecen al SHA publicado exacto.
Mantener caps, reservas, reglas de main, aislamiento Boca y datos. Cambios a una
fuente del full ZIP requieren revisar su pin ACTUAL en test_r82_recovery_bundle,
conservar los históricos y medir el cierre de todos los paquetes afectados.
Los encabezados siguientes son históricos y no reinician trabajo pendiente.

## Corte histórico R295 — desarrollo paralelo durante aceptación Samsung

La instalación R294 está completada: main/instalada
`c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`, PR #516, release #865,
APPLY #1117 ACCEPTED, administración #1118 PROVISIONED y par #1120 OBSERVED.
El controller quedó RUNNING/HEALTHY y el worker CREATED/PID0; esto no certifica
un START/STOP posterior del titular. [Handoff físico](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6871954660).
No repetir ese deploy. STATUS #1119 sigue registrado como NO_GO del observador.

El titular autorizó desarrollar pendientes mientras prueba desde Samsung.
[Decisión y responsables R295](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878044872)
y [ADR0300](docs/ADR/0300-r295-postdeploy-status-auth-and-telegram.md)
separan implementación, verificación offline, instalación y aceptación.
R295 corrige el diagnóstico de ledger preservado y la topología Telegram,
y desarrolla el transporte de login Boca a partir de fuentes pinneadas de #12.
Ese transporte todavía no es un productor conectado: falta el wiring de sesión,
IPC, START/STOP y monitor. Telegram tampoco está activado por esta rama.

Durante la prueba del titular: sin releases, APPLY, operaciones de host,
START/STOP ni mensajes Telegram. Trabajo exclusivo en rama, pruebas focales,
revisión independiente y checks requeridos del SHA exacto. No repetir la suite
local certificada del árbol base. No ampliar caps/reservas, duplicar módulos ni
modificar `synthetic.py`/`ipc_worker.py`. Sólo Actions protegidas y serializadas
cuando vuelva a corresponder una operación física. Los cortes siguientes son
históricos y no reemplazan este estado.

## Corte histórico R294 — diseño previo a la promoción (14-NOV-2026 UTC)

R293 terminó por PR #515 en `959a0be9e776329f99a29e65c2c75195700d5596`;
CI #1242 e Image Security #1080 SUCCESS, sin release ni host por CI/CD.
El titular exige continuar hasta deploy y validación y aclaró expresamente
que el worker debe conectarse automáticamente, detectar evento/cola y observar
los tokens recibidos. La carga manual fue descartada. Véase
[ADR0299](docs/ADR/0299-r294-automatic-worker-and-consolidated-beta.md) y
[decisión canónica](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6870816882).

R294 es candidato funcional, todavía sin certificación física. Preservar el
par instalado de #864/#1102 hasta completar checks/revisión exactos y una única
promoción protegida. START del titular activa una sola sesión ordinaria; el
agente no navega Boca/Queue-it durante desarrollo/pruebas. SIMULATION_ONLY
para tickets; sin reservas/compras, bypass, multisesión ni cambios a los
algoritmos de `synthetic.py`/`ipc_worker.py`. Error de conexión nunca equivale
a ausencia. Token de cola no equivale a token/refreshToken de login Boca.

La provisión lateral de sectores y recibo Telegram es una operación explícita
posterior a APPLY, con resultado separado y requerida para aceptación funcional;
fallar allí no autoriza otro deploy. Sólo Actions protegidas, una operación de
host a la vez. No bajar checks, caps, reserva del bundle ni guardas para pasar.
Las secciones siguientes conservan cortes históricos, no reinician trabajo.

## Estado vigente R291–R293 — CI/CD antes de nuevas funciones (13-NOV-2026 ART)

Este encabezado actualiza los cortes operativos históricos que siguen. Leer
[R291](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6868819579),
[R292](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869176533)
y la [decisión R293](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869386141).
El par de `0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe` ya fue instalado:
release #864, APPLY #1102 `SUCCESS/ACCEPTED`, controller `RUNNING/HEALTHY`,
worker `CREATED/PID0`, SQLite estable y 8443 HTTP 200. El fallo #1108 compara
CIDs históricos R186; no invalida ese despliegue. No repetir instalación,
R186, APPLY #1085 ni recuperaciones cerradas.

El titular prioriza optimizar y medir CI/CD: reutilizar R282, revisión y PR
independiente, checks del SHA exacto al día con main y protecciones intactas.
No publicar ni desplegar por cambios de pipeline/documentación. ADR 0297
concentra diseño, métricas y límites; #417 conserva resultados por candidato.
La ventana de 272 runs contiene **5 publicaciones**, además de 11 validaciones
PR de release exitosas; no fueron 16 publicaciones. CI GREEN no es aceptación
física ni funcional. Mantener estados implementado/verificado, sin prueba
física, en rama, pendiente, bloqueado y reemplazado por separado.

Después de CI/CD: reconciliar #12 y código existente, diseño funcional único,
PRs focalizados y una promoción consolidada. Productores Queue-it/Boca,
recibos posteriores START/STOP, actividad completa, eventos/cola/auto-stop,
Telegram y formato 24 h siguen pendientes según R292. `SITE_URL` consistente
no prueba navegación. SIMULATION_ONLY; sin navegación real Boca/Queue-it,
reservas, compras ni recursos ajenos. Sólo Actions protegidas para el droplet,
una operación a la vez; ninguna operación de host forma parte de R293.

## RCA R275 — una sola cronología de los recibos físicos (13-NOV-2026)

El APPLY protegido [#1081](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473805164)
falló con `exit 3` **antes de SSH**: las observaciones READ_ONLY
[#1079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43472874879)
(par instalado, `b61ca3e`, controlador healthy, worker Created, puerto 8443
loopback) y [#1080](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473379911)
(recursos retenidos, `observer_writes=0`) eran genuinas. **No** se instaló
`85e66546` en ese pase. El guard inicial de
`scripts/attest_current_pair_v2.py` todavía exigía
`retained < pair < apply`, en conflicto con el bridge R274 que exige
`pair < retained < apply`. El replay offline con los ZIP reales de GitHub
reprodujo el defecto y pasó luego de corregir esa única comparación.

**Obligatorio antes de cualquier siguiente upgrade:** probar la cronología
`original_attempt < pair_observe < retained_observe < apply` en **todos** los
módulos y en el test integrado del runner usando recibos inmutables;
comparar `MAIN_SHA`, `RELEASE_SHA` e `INSTALLED_SHA`. No reejecutar R186,
no recrear perfiles, no duplicar imágenes de una misma fuente, no permitir
reservas reales, no afectar Porota ni PPI Watch. Si el runner falla antes
de SSH: RCA antes de otro intento. Si alcanza el host: recuperar journal y
observación física, jamás retry ciego. Véase ADR 0294 e issue #417.

## RCA R274 — primero probar la procedencia histórica, después publicar (13-NOV-2026)

Los pases protegidos 43466413414 (#1074) y 43467640849 (#1076) fallaron
en el guard local del runner con `exit 3`, **antes de SSH y de cualquier
modificación de host**. La primera secuencia usó la observación retenida
43464488963 anterior a la observación del par 43464710404; el verificador
exige **par observado → recursos retenidos observados → APPLY**. La segunda
secuencia corrigió el orden con la lectura 43467281965, pero descubrió un
supuesto incompatible con la release histórica 43215180354 (#851): ese
workflow legítimo conserva un `publish-reviewed-image` exitoso **y** un
`release-image-pr-validation` omitido. La autorización histórica debe
aceptar ambos formatos exactos (1 publish o 1 publish + 1 PR skipped), jamás
jobs extra activos o distintos. Véase ADR 0293 e issue #417.

**Regla no negociable para cada nuevo sucesor:** antes de generar una
release costosa, auditar el grafo cronológico de los run IDs y el formato
real de la release anterior con un fixture de regresión; verificar la
compatibilidad del autenticador del runner. CI/release GREEN no prueban
despliegue. No reintentar un fallo que haya alcanzado el host; ante un fallo
de pre-SSH, probarlo con logs y RCA antes de un nuevo intento. Nunca ejecutar
otra vez R186 ni borrar los recibos históricos, recursos Boca o ajenos.

## Estado vigente R273 — no repetir instalación ni R186 (13-NOV-2026 ART)

La recuperación R186 descrita más abajo **ya se ejecutó** y terminó
`ACCEPTED/ARCHIVED_BINDING_ONLY` en la Action 43237528968. Su APPLY original
43217075287 permanece NO_GO histórico, no modificable. Prohibido volver a
ejecutar tanto el APPLY como el finalizador R186. El par físico existente
estaba en `b61ca3e` según Action 43455761226; el código posterior de `main`
`e1b35fc` no estaba desplegado al corte. No afirmar una nueva instalación
por una prueba READ_ONLY ni por CI/release GREEN; registrar por separado
INSTALLED_SHA, MAIN_SHA y BETA_OWNER_ACCEPTED. Las actualizaciones futuras
usan solamente `boca-pair-upgrade-apply` protegido, una vez que su selector
CODE_ONLY, tests, release exacta, permisos y terminal son verificables.
Un error después de iniciar el sucesor es INDETERMINATE, no un NO_GO
falsamente atribuido al preflight. Véase ADR 0292 e issue #417.

Read this file, README.md, docs/DEVELOPMENT_POLICY.md and relevant ADRs **in
full** before touching source. This public repository is independent from
every unrelated service, host configuration and application repository.

## Owner-approved mobile form compatibility — 2026-11-12, #417

The owner reported `Origen no autorizado` on the private `SITE_URL` form
and explicitly authorized relaxing the **response referrer policy** to make
ordinary browser forms work. The private panel may send
`Referrer-Policy: same-origin` for native owner POST forms; this still sends
no referrer to a different origin and avoids inducing `Origin: null` under
`no-referrer`. Telegram setup/pairing pages without native forms retain
`no-referrer`. **Do not remove the exact Origin comparison**, host/scheme,
passkey, CSRF, one-use operation, or protected workflow checks. A passing
offline test is not physical Chrome/Samsung acceptance; do not claim that
the actual browser's header has been captured. See ADR 0237.

## Owner amendment — 2026-11-12: consolidated BETA delivery, #12 + #417

**R186 postcommit clarification (12/11):** the already-authorized first
dual-pair APPLY [#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287)
crossed the irreversible marker and installed the two new containers.
Its terminal result is `NO_GO/RETIRE_OLD/INDETERMINATE`. **Do not dispatch
another pair upgrade or rollback.** After R185 and three independent
READ_ONLY host attestations, complete only the historical Boca binding
retirement through the added `boca-postcommit-finalize` option on the
**existing** one protected manual Action, under a fresh lease and durable
one-shot claim. Validate postflight before installation acceptance. The
old APPLY's NO_GO journal must never be rewritten to ACCEPTED. This R186
fix is about files in the dedicated Boca user namespace only, not external
token URLs, Docker, systemd changes, legacy navigation or Porota.

The owner explicitly transferred active integration/deployment coordination
from the stalled prior #417 chat to the agent continuing this work. The
previous separate-chat ownership restriction is superseded for this delivery.
There is **one** owner of overlapping panel/integration files, one reviewed
release candidate and **one** protected Boca deployment transaction; do not
create parallel installs or presume the old chat has a host lease. Reconcile
GitHub Actions and the live lease immediately before effects.

The owner's subsequent clarification on 2026-11-12 **also removes any
external-provider availability, live-response or separate activation-approval
gate for the real token-source code**. If syntax, imports, offline unit
contracts, repository policy and ordinary CI are correct, the Queue-it
observer and Boca authentication transport contracts must be admitted in
this delivery as implemented. Do not turn an unavailable endpoint or token
into a failed release gate or forcibly disable the interface merely to pass
CI. Runtime must still truthfully report an absent producer/transport and
never fabricate credentials, URLs, tokens or a successful network response.
This amendment does not order live network tests while services are down.

The owner authorizes inclusion of the tested
[issue #12 candidate PR #484](https://github.com/mbalbo2023/boca-socios-assistant/pull/484)
in the single
consolidated BETA (ticket operations remain **SIMULATION_ONLY**). Its
Queue-it and Boca token-monitor contracts are **included, not feature-gated**;
their network-dependent functions naturally require an actual observed URL
or an injected real transport at invocation time. The owner
specifically prohibits validating token-bearing URLs while the external
service is unavailable. Missing real tokens, unavailable Boca/Queue-it,
and a monitor displaying "Sin observaciones" are **not vetoes** on safe
deployment or inclusion of these contracts; never invent observations or
claim live login without a received response.

The member-sector sidecar has an explicit migration. Its absence may keep
sector editing unavailable and must be shown honestly, but **does not block
deploying the existing private panel, members, synthetic bot and controls**.
No implicit migration of legacy SQLite is authorized. Provision the Boca-only
sidecar later through the reviewed protected path before asserting sector
persistence on the host.

The sole outstanding #12 PR should be reviewed and integrated normally; its
existence is not grounds to postpone its own merge or demand a redundant PR.
The final release still uses a reviewed, merged, exact-SHA `main`, applicable
CI, dual manifests/digests, fresh Boca-only host observations and one
protected `boca-pair-upgrade-apply` with postflight and selective cleanup.
**Do not waive** branch protection, anti-replay, origin/passkey, storage
integrity, rootless isolation, one-ticket policy, or protection of unrelated
Docker projects. External-source outage is advisory for the code and the
unavailable live runtime, not a reason to weaken those technical boundaries.

## Absolute scope boundary

- ONLY modify files under this GitHub repository and its feature branch.
- Never read, alter, restart, deploy, back up, clean up or delete **any other
  workload**, host-level timer, dashboard, data volume, port, container,
  secret, workflow or system service.
- Never run Docker commands against a production host from your own shell.
  In later authorized deployments, use ONLY the dedicated Boca Actions workflow.
- Never change existing host Docker Compose stacks; use project
  name boca-socios and its own image, secrets, volume, bridge and service only.
- Ticket/reservation mode is SIMULATION_ONLY: no actual ticket buying or queue
  bypass. Real token-observation/authentication *code paths* are included and
  may be configured without a separate provider-availability gate; never
  claim a successful real exchange or perform a live validation while the
  external system is unavailable.
- One ticket per member per event is **nonnegotiable**; enforce at domain,
  DB and transaction boundaries. Multiple sessions must never multiply
  authorized ticket quantity.
- Store credentials encrypted in the database. The key MUST be held outside
  it; never paste credentials, queue passes, session cookies or HAR into GitHub,
  code, issues, PRs, logs, test fixtures or screenshots.
- Do not assume multi-session support means independent Queue-it positions.
  No bypasses of Queue-it, WAF, CAPTCHA or rate limits.

## Owner-only browser modules and site navigation — 2026-11-03

The owner has reserved **exclusive programming authority** over
`src/boca_socios/browser/synthetic.py` and
`src/boca_socios/browser/ipc_worker.py`. Except for the narrow 2026-11-10
authorization below, agents MUST NOT open their contents, interpret their
behavior, refactor, regenerate, edit or replace their bytes, or use their
internal logic to propose navigation behavior without a new, explicit,
file-specific authorization. The two files supplied
on 2026-11-03 may be copied **byte-for-byte**, identified by SHA-256, and staged
under [issue #288](https://github.com/mbalbo2023/boca-socios-assistant/issues/288).
The owner subsequently declared both modules an **externally validated
blackbox**, expressly waived agent functional review of their implementation,
and authorized merge/deploy with narrowly scoped lint/type/test exclusions.
This does not waive exact-byte integrity, RCA and controller isolation guards,
other CI/security gates or physical host readiness. The owner retains exclusive
responsibility for navigation behavior and any later revisions. See
`docs/ADR/0121-owner-controlled-browser-navigation.md`.

### Narrow owner-approved integration exception — 2026-11-10

The owner **expressly authorizes** agents to open **both named modules** and
modify **only their deployment/integration wiring** (imports, paths,
environment/configuration, IPC connection and bounded, fixed-category
observability) to connect the V3 worker with the existing controller and
private `8443` dashboard. Preserve the existing Python navigation/business
algorithms and behavior: do not rewrite the browser engine or the ticket
flow. This exception supersedes the earlier *absolute no-read/no-edit* rule
only to that extent; it does not authorize live Boca/Queue-it traffic,
credential disclosure, concurrent real sessions or ticket actions.

**Blackbox CI policy remains in force:** keep `synthetic.py` and
`ipc_worker.py` excluded from automated lint, mypy, synthetic execution and
code-level behavioral analysis. Review only the small external integration
boundary and use safe, offline contract tests. Do not loosen any other
quality or security gate. Record exact changed lines/digests and the owner
authorization in the issue and PR.

**Sandbox destination setting, 2026-11-10:** both protected entrypoints now
read the target exclusively from the `SITE_URL` environment variable and
exit without starting Chromium if it is absent. No provider URL may be
hard-coded as a fallback. A configured string alone does **not** prove that
the domain resolves to an internal sandbox or that network access is safe:
the production worker remains `network_mode: none` pending an exact, Boca-only
DNS/IP and egress review. Never silently reinterpret `SITE_URL` as permission
for public-site traffic, Queue-it bypass or real ticket actions.

**Owner-requested URL editor, 2026-11-11:** the `8443` Configuración
page may display/edit exactly `SITE_URL` under passkey + `simulation:write`,
same-origin CSRF and one-use operations. Persist it in the private, Boca-only
data volume. **Owner amendment:** do **not** reject a URL merely because
its hostname or routable address is public. Keep URL syntax checks and reject
embedded credentials, query strings, fragments and link-local metadata IPs.
The browser may consume this setting
*only after* its transport has been approved and proven within the dedicated
Boca rootless boundary. Docker `start` does not refresh a container's Env;
never label a saved setting "applied" merely because the bot was toggled.
Do not expose Telegram token-bearing API URLs as editable browser destinations.

**Owner networking amendment, 2026-11-11:** Chromium must have outbound
Internet access when activated. Replace the current `network_mode:none` only
in a coordinated, verified cutover to a *Boca-only rootless network* with
outbound connectivity, no published worker ports, no shared networks with
other apps, no host networking and no privileged Docker socket. Update every
exact topology/inventory attestor, deployment contract, cleanup boundary and
tests before installing. No change to the daemon or other Docker projects.
Allowing a public URL in Configuración is not, by itself, permission to run
unreviewed live Boca ticket workflows; business/credential protections remain.

**R171 source candidate:** the revised optional Compose overlay names exactly
`boca-socios_boca_browser_egress` as the browser's single outbound bridge,
distinct from `boca_private` and Telegram. Its host/CI checks prohibit extra
peers, host/foreign networks and published worker ports. This source change
does **not** mean the installed worker has Internet: only a separate positive
rootless droplet probe and fully reviewed Cutover may mark that ready.
Cutover A creates only the identified Boca egress bridge, and its compensator
removes only that verified empty attempt bridge. The `beta-browser-install`
legacy workflow is explicitly NO_GO before host effects and its older
`--browser-ipc-v2` cleanup is **not** a substitute for Cutover A compensation.
Keep short-lived `network none` Docker inspection probes separate from the
actual Internet-enabled Chromium worker.

**Uploaded V3 ZIP custody:** the 2026-11-10 supplied ZIP contains a plaintext
Telegram token, a hard-coded public Boca destination, a separate plaintext
password SQLite class, and base images differing from pinned release images.
Never commit/expose the token or overwrite the reviewed Dockerfiles, database,
or Telegram integration with that unreviewed archive. Treat the token as
compromised and require secret rotation by its owner. Any compatible browser
destination patch must use `SITE_URL` while preserving business logic and
must prove it cannot reach real Boca.

**Integration fail-closed gate:** the current `ipc_worker.py` entrypoint
is not a Unix IPC server: it invokes `SyntheticBrowserEngine` using the
`SITE_URL` configured at runtime and multiple sessions, and prints result
payloads. It is
**not safe to enable it unchanged** as the V3 worker simply by fixing an
import or `PYTHONPATH`. This observed mismatch must be resolved as an
explicit, simulation-only IPC adapter without executing the real-site
orchestrator; if achieving that requires a change to the protected navigation
logic, stop and obtain a separate exact-scope owner decision. A healthy
controller alone never certifies the browser worker or Chromium.

**R172 owner amendment (2026-11-11, supersedes only the earlier code-change
prohibition):** the owner explicitly authorizes reading, adapting, correcting,
testing and wiring `synthetic.py` and `ipc_worker.py` when needed to resolve
their actual startup/IPC contract; they are no longer categorically exempt
from relevant quality checks. Prefer a separate bounded adapter when it
preserves working code; never assert the blackbox's token observation equals
`RESERVED_IN_SIMULATOR` or imply a confirmed booking. Runtime `SITE_URL` is
controlled from the passkey-protected 8443 configuration page and transported
through a dedicated, URL-only read-only worker volume (no keys/DB), applied
on next worker start. Public/private URL *class* is not a rejection criterion;
credentialed URLs, metadata destinations, malformed URLs and unauthorized
navigation remain rejected. The worker may have outbound Internet only on
its independently attested Boca rootless bridge; no extra published ports or
foreign Docker effects. This authorization does not turn on real tickets,
payments or reservations; no physical claim until tested on the exact droplet.

Site navigation is **entirely owner-operated**. Agents must not launch or
automate real Boca/Queue-it navigation in any browser on the droplet or on
another surface, or dispatch diagnostics that navigate the site. The Boca
controller-only simulation BETA may continue to be prepared and deployed
under its preexisting exact-SHA safety gates with its browser backend `off`;
no browser-worker/CDP activation is implied by this instruction.

## Operación del bot a demanda — 2026-11-09

El titular autorizó a su sesión privada con passkey a iniciar y detener el bot Boca de simulación. La instalación y actualización siguen en la Action protegida. El ejecutor local, activado por socket, sólo puede consumir la operación durable de la instalación Boca verificada. El worker queda detenido en reposo, con la captura preparada antes de cada inicio. Se aplican las reglas anteriores sobre los dos módulos protegidos y la navegación del titular. Véase [ADR 0223](docs/ADR/0223-bot-bajo-demanda.md) y [la decisión en #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6756261211).

## Development protocol

1. Recover exact main HEAD, open PRs, open work items, CI status and current
   project release state **before** starting. Do not duplicate completed work.
2. Claim exactly one narrow issue with one scoped writer. State files/paths
   being modified. Parallelize independent audits and nonoverlapping issues
   whenever possible; never use concurrent writers on the same scope. If
   another agent owns the same scope, stop and coordinate.
3. Create branch feature/<issue>-<slug> from current main HEAD, and open a
   small, reviewable draft PR; no direct push to protected main.
4. Edit only task-relevant files, keep unrelated work intact. Add regression
   tests and ADR updates for architecture, schema or security changes.
5. Run frozen dependency graph, formatting, lint, strict type check, full
   in-scope unit tests and isolation policy gate. Any FAIL, ERROR, SKIP or XFAIL
   affecting required gates is NO_GO. The **owner-approved** 2026-11-03
   blackbox exclusion of exactly two browser modules and their direct tests
   is a documented scope boundary, verified by fixed SHA-256 and RCA guards;
   never silently weaken unrelated checks to make CI green.
6. Provide exact candidate SHA, base SHA, changed paths, test evidence,
   known limitations and explicit go/no-go in PR description.
7. The agent performs and records technical review; exact-SHA green required
   checks precede merge. GitHub does not require a second human approving
   review; that is distinct from the owner approving the task scope. No
   deployment side effects from push or documentation-only changes.
8. Do not choose infrastructure or business-logic changes unilaterally.
   Present the concrete options, recommendation, effects and evidence to the
   owner, then obtain approval for that scope before changing it. Previously
   broad autonomous-operation wording is superseded by this instruction.
   Approval for a diagnosis or code fix is not approval to install, release,
   migrate a real database or enable another feature. Once a scope is approved,
   complete its routine implementation and checks without asking repeatedly.
   All authorized host actions still use only the dedicated manual workflow
   with exact commit/image/service, isolation, capacity and environment gates.
   Serialize host operations; no automatic retry after a failed gate.
9. On a failed staged `first-install` or `beta-install`, the **same protected
   Boca Actions run must immediately attempt** a bounded stop and cleanup of
   positively identified, unused Boca-only Docker/Compose remnants, with
   before/after disk/inode inventory, redacted receipt and RCA. Preserve the
   original failed result, all owner/key/data volumes and uncertain artifacts;
   never prune host-wide resources or touch another workload. If cancellation,
   runner loss, SSH or rootless failure prevents cleanup, record/retain NO_GO
   and require fresh Boca-only inventory; no blind retry. Fix code defects in
   a new PR; do not redeploy merely because an external source failed.
   **Permanent owner extension (2026-11-04): every Boca install/deploy/update,
   successful OR failed, must execute a final bounded, Boca-only cleanup in
   that same protected Actions run.** Record before/after disk and inode counts,
   exact attempted resource identities and a redacted cleanup receipt. After
   SUCCESS, positively identify and remove obsolete Boca images unused by ANY
   container, disposable staging, abandoned attempt containers and unused
   dedicated networks; retain the active image/container and all owner, key,
   database and uncertain resources. After FAILURE, preserve the original red
   result and apply existing compensation first. Verify removal by exact ID,
   never by broad name/glob, and never use host-wide Docker prune, force image
   removal or unscoped Compose down. Unverifiable residue, runner loss or
   cleanup failure is NO_GO/INDETERMINATE with fresh Boca-only inventory and
   no blind retry. A green deployment without this final receipt is NOT fully
   accepted; this code-only instruction does not authorize a host operation.

   **Cutover V3 forensic exception, 2026-11-07 (R108, #417/#45):** only the
   historical, unused Boca controller image with immutable ID
   `sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`
   may remain after a successful V3 Cutover. Release #41559973013 and manifest
   artifact #13196392925, SHA/revision/digest, zero references and aliases
   must match fresh rootless inventory under the same lease at precommit and
   at **every** finalizer probe; the failure of retirement run #746
   (`42261978336`) is the documented reason to preserve forensic evidence.
   A canonical V2 cleanup receipt MUST explicitly report
   `KNOWN_HISTORICAL_QUARANTINE`, never claim that the image was removed.
   This is an intentional **one-image exception** to the general obsolete
   Boca-image removal rule above, not a general relaxation: any other unknown,
   identity drift, shared reference, missing proof, foreign workload or
   incomplete cleanup remains NO_GO/INDETERMINATE. No image removal retry is
   authorized by this clause. See ADR0209 and issue #417.
10. Use YYYY-MM-DD in America/Argentina/Buenos_Aires for user-facing times.

### Owner release hygiene clarification — 2026-11-06

**Superseding owner instruction — 2026-11-07, Cutover V3 only:**
`cutover-a-apply` is one explicit owner `workflow_dispatch` from exact current
main. No separate PREPARE/APPLY dispatch, copied GO_B hash, email or code is
required or accepted for this route. All source/release/image/legacy pins and
`protected_action_context` stay blank in the form and are derived/verified by
the protected workflow. The V3 dispatch itself authorizes the transaction;
its generated digest is integrity binding, never a second approval. Preserve
the Environment's main-only secret boundary, owner and triggering-owner checks,
attempt=1/anti-replay, PR0, exact source/dual release, rootless same lease,
passkey/loopback8443, terminal ACK and detailed cleanup. Other operations,
including official-import/lifecycle, retain their separate existing contracts.
Historical GO_B/Cutover instructions below are superseded only for this route.
See `docs/ADR/0206-single-dispatch-cutover-v3.md`.

The owner has authorized completion of the Boca simulation BETA through a
physically verified deployment. Do not request another project GO for that
already authorized scope. This does **not** replace exact-SHA release,
protected environment binding, single-owner lease, fail-closed Cutover A,
Boca-only cleanup, or terminal host receipt requirements. Never equate an
Actions green check with a successful physical deployment.

**Zero open pull requests before the final release/deploy, including physical
Cutover A**, is a release invariant. Before preparing the final image,
enumerate *every* open PR, its head/base,
changed paths, CI, linked issues and branch dependents. Decide each one
individually with scope-owner architectural, infrastructure/DevOps and QA
cross-review. Record one evidence-based consensus in issue #45, with an
explicitly attributable opinion for each relevant discipline. Do not assert
unanimity when it was not obtained: investigate any disagreement and repeat
the review before taking the disputed action.

- Merge only an actual missing, tested capability into the single release
  candidate. Check current `main` and in-progress branches first: no code
  duplication, no resurrection of an outdated implementation.
- When code is already present or superseded, close that PR with a concrete
  comparison and a reference to the successor implementation. Retain its
  branch, commits and review history.
- For unique work, determine whether the current BETA *requires* it. If yes,
  implement and test the requirement before claiming BETA complete, using a
  short-lived PR that is merged or otherwise resolved before Cutover. If no,
  record why it is an experiment, incompatible proposal or separate owner-only
  product scope; preserve its branch and source evidence, without describing
  the unneeded proposal as an unresolved BETA blocker.
- Keep issues requiring genuine host, Chrome or Telegram acceptance open until
  physical evidence satisfies their acceptance criteria. PR closure never
  auto-closes such issues. Fix-forward after an actual NO_GO; never blindly
  retry a failed host operation.

The issue #45 checkpoint is the durable per-PR ledger. Do not leave stacks of
obsolete draft PRs indefinitely or use a generic bulk-close operation. If a
new PR appears while the release is prepared, reconcile it before Cutover.

For fast feedback, use narrowly selected tests during intermediate local
development when the change scope allows it. **Every mergeable exact SHA**
still needs the full applicable gates in step 5 above, and the **final
exact-SHA release candidate** needs complete relevant regression and
isolation evidence, including blackbox exclusions and host-contract tests.
Speed improvements must not silently weaken Cutover acceptance.

## Approved BETA preparation scope

### Owner correction: capacity is observed after BETA deployment

The owner expressly rejected unbenchmarked preventive RAM/CPU/PID headroom
as an admission requirement; use the [ADR0112](docs/ADR/0112-postdeploy-resource-observation.md)
candidate and [issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
for implementation/review. Maintain hard container cgroup caps, rootless
identity, SHA/digest provenance, port 8443 isolation, real storage safety
and positive-identity cleanup. Do not claim the PR is merged or the BETA
installed. Measure actual synthetic runtime after deployment and document it.
Existing authorization covers continuing this scope without reconfirmation;
request the owner's assistance only for an actual manual action or physical
Chrome/Telegram test.

### Owner continuity instruction — 2026-11-02

The owner explicitly reiterated: “Ya te dije explícitamente no tenés que
pedirme autorización, esto que quede grabado”. The durable decision is in
[issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6591142632).
Continue the agreed work without asking the owner to reconfirm the same
scope. Carry existing authorization across turns, agents and handoffs;
record each material action and its evidence in GitHub immediately, not only
in chat. This clarification controls any older wording that would prompt
again for a routine step already authorized.

The reiterated instruction followed notice of the platform's rejected public
observation dispatch. Root interpreted it as continuation of that specific
single `chromium-capture-25` diagnostic with the existing 25-path map, origin,
budgets and STOP behavior; the platform nevertheless rejected the dispatch
again, so that operation remains blocked. Record any actual source SHA/run/result separately
from the earlier rejected attempt, which created no run. It does not widen
destinations, enable real login/tickets, change resource/security gates or
authorize bypassing platform controls. If a control blocks an action, record
the concrete blocker and continue independent work; do not seek a workaround
or ask the same authorization question repeatedly.

### Existing delivery boundaries

[ADR 0056](docs/ADR/0056-approved-simulation-beta-delivery.md) and the
[delivery plan](docs/BETA_DELIVERY_PLAN.md) record the owner-approved stage:
private simulation BETA including mandatory **Socios > Agregar socio**,
coordinator/state/stop, durable local notices, restart/idempotency checks and
measured efficiency. The delegated logical destination is `/data/boca.sqlite3`
in `boca-socios_boca_data`, with a separate key; current global existence
remains UNVERIFIED. Preserve and identify any discovered storage. The dedicated
rootless service was prepared by run #120; no application/database was installed
by that operation. Do not rerun first-time preparation over its existing config.

Build on the prepared dedicated rootless service and proceed with approved
implementation/review/tests of an application-served private panel without repeating the
same permission request. Concrete identity/bootstrap/private-access options
still require their documented decision before activation. Final release and
installation use a reviewed concrete candidate under the plan, not this
planning approval alone. No real credentials/login/queue/reservations, existing
real-DB migration, backup or unrelated workload changes are implied.

## Code design principles

- Thin adapters around any external system; Queue-it and Boca are third-party
  contracts, and unverified behavior belongs behind interfaces and feature flags.
- One deterministic state machine per member/event/session; idempotency and
  transaction boundaries on any eventual reservation.
- Small files/modules with type hints and explicit errors. No hidden fallback
  from simulation to live.
- Never store unencrypted third-party secrets; avoid logging personally
  identifiable data. Use stable opaque internal member IDs.
- External I/O must be bounded with explicit timeouts, backoff and stop-on-block;
  simulated tests must not issue public website traffic.
- Check any external-source incident through a dedicated read-only Actions
  diagnostic before proposing a new deploy. Show timestamped green/yellow/red/
  unknown source health in the operation summary. Source outages are alerts,
  not blockers for a safe simulation-only deploy. Code defects and security,
  image or host-resource gates remain blockers. No live behavior is enabled by
  a source-health result.
- Live automation is a separate technical review and controlled milestone;
  the current runtime remains simulation-only with its engine off.

## Rule 84 — documentation must remain factual and current

[ADR 0055](docs/ADR/0055-factual-documentation-and-scoped-approval.md) records the owner instruction and the historical
autonomy clauses it supersedes.

Update affected documentation in the same PR as the change. Separate observed
behavior from configuration, unmerged proposals and future work; never present
a passing candidate or a configured path as a deployed capability. Cite exact
source SHA, PR and run evidence, its scope and its limitations. Preserve prior
cuts only under explicit historical labels.

Before closing a task, reconcile the affected README, operations/status/backlog
documents and the continuity checkpoint with the reviewed result, remaining
work and current authorization. Verify main and relevant checks again; do not
copy an old SHA or test count into a current claim. One assigned writer owns
each document/issue to avoid conflicting updates. If documentation or evidence
is still pending, keep that fact explicit and the task open.

This is a delivery obligation for each authorized task, not a claim that an
automatic robot checks or rewrites all GitHub content. Do not invent schedules
or a freshness date unsupported by a real verification.

## Handoff checklist

- GitHub branch/PR/issue and exact HEAD
- Ownership released/maintained
- Changed files and behavior
- Local and Actions tests (results, not assertions of success)
- Security and resource impact
- Why unrelated resources remain untouched
- Next steps and blockers


