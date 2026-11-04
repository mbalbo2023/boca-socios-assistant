# Estado de integración BETA

## Estado físico vigente — 04/11/2026, #307 (NO DEPLOY)

- `main=3c5a0da3df527cfe58a98442ea471be81f9f06ab`, PR #306 fusionado;
  [release #41873165726](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41873165726)
  y [owner-enroll PIN #41887635433](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41887635433) completados.
- [beta-install #41889141825](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41889141825):
  NO_GO antes de SSH por variable `BOCA_BETA_ENV_READY` vacía.
- [beta-install #41890280818](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41890280818):
  gate `ready`, identidad rootless, owner, staging, Compose, SHA/release y
  puerto 8443 FREE pasaron. `beta-apply` falló por veto preventivo de RAM
  `MemAvailable < 768 MiB`; la lectura exacta del instante de fallo no se
  publicó. Últimas observaciones previas: 931.808/914.340 KiB. Detención
  identificada, limpieza selectiva y daemon stop: pasos SUCCESS.
- [RCA #307](https://github.com/mbalbo2023/boca-socios-assistant/issues/307):
  proponer observación numérica sin veto arbitrario, con contadores válidos,
  cgroups estrictos, storage/identity gates y medición sintética posterior.
  **Sólo candidata de código; ninguna BETA instalada, medida ni reiniciada.**

Los siguientes apartados de #306/#305 son **cortes de desarrollo previos** y
no reemplazan este recibo físico.

## Validaciones en paralelo — PR #306 (04/11/2026, NO deploy)

Los checks de CI y seguridad de imágenes ya son independientes. El candidato
#306 sustituye la cola no cancelable de validaciones antiguas de Release PR y
First Deploy PR por cancelación **limitada al evento pull_request**; la
operación protegida `workflow_dispatch` mantiene serialización y todos
sus controles. Esta edición necesita cuatro checks GREEN del SHA final,
revisión técnica, merge y checks postmerge. **BETA física aún no instalada**.
Detalle y regresión: ADR0129.

## Ciclo protegido de despliegue BETA — candidato #305, 04/11/2026

[PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) **fusionado** en `main=5398669d5c32ca64ba113cddcc20363502c85c1e`: CI postmerge [#41859364620](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41859364620) y seguridad de imágenes postmerge [#41859364192](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41859364192) **GREEN**. Esto habilita el perfil ICC=true solo en la red temporal privada de owner-enroll, sin módulo br_netfilter ni firewall global; **no instala BETA**.

La nueva candidata [#305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) / [ADR0129](ADR/0129-controller-only-beta-resume.md) corrige dos dependencias antes del release final: `start-existing` de la unidad Boca antes de `beta-install` tras owner-enroll, y operación `beta-start` para reanudar **solo el controlador instalado**, conservando identidad/digest, tres volúmenes y el volumen Telegram adicional únicamente si se verifica. La aceptación detiene el servicio; `beta-start` debe devolverlo a RUNNING sin `compose up`, reinstalación ni reinicialización de DB/clave. Todas las operaciones por Actions protegidas, `source_sha=main`, servicio controller, imagen por digest, recibos acotados y limpieza selectiva tras fallos. No usar `beta-browser-start` para reanudar el panel; blackboxes intocables.

**Estado del nuevo desarrollo:** rama `feature/305-boca-beta-lifecycle` en validación, aún **NO fusionada ni desplegada**. Después de integración y postmerge GREEN: release dual, pruebas físicas de owner-enroll/Chrome, instalación, aceptación, reanudación, Telegram y recursos reales. No reutilizar SHA antiguo para instalar.

## Contrato vigente para corrección del bloqueo rootless — 04/11/2026

**Actualización 04/11/2026 (Regla 84, RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)):** El [run protegido #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848) verificó `module=absent`, `nf_call_iptables=unavailable`, `index=listed`, `modules_disabled=0`, `write_ops=none` en `main=41fc15e261d002dc614124ac0f2d2e1bea81f896`; fue una **lectura exitosa**, no un deploy.

El propietario ordenó flexibilizar el obstáculo y llegar a BETA. [PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) / [ADR0128](ADR/0128-boca-only-owner-enroll-icc-compat.md) implementan el cambio **solo en la red temporal de `owner-enroll`**: `ICC=true`, UID rootless Boca, cero masquerade, exactamente un peer autorizado, host loopback `127.0.0.1:8443`; limpieza positiva con opciones concordantes. El `network-probe` histórico ICC=false y la variante diferencial ICC=true siguen separados; **no** se cargan módulos ni se modifica kernel/firewall global, Porota u otros servicios. Riesgo residual: menor aislamiento entre potenciales contenedores de esa única red; ningún segundo contenedor está autorizado.

**Estado físico vigente: BETA NO instalada.** PR/CI, release dual exacto, alta Chrome real, `beta-install`, aceptación, recursos y Telegram todavía requieren evidencia. Además [issue #305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) rastrea arranque del daemon antes de instalación y reanudación controller-only después de aceptación. Nunca reutilizar `beta-install` para reanudar, ni activar el navegador BLACKBOX desde agente. Los apartados anteriores del 03/11 abajo son **cortes históricos**, no la instrucción operativa actual.


## Última evidencia rootless — 03/11/2026, NO_GO para ICC=false

Main verificado `a83e105d4ccec2cc59dfabce77142750de733630` tras PR #298.
La comprobación temporal `ICC=true` [#41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622)
dio `PASS cleanup=VERIFIED`; la comprobación `ICC=false` para el alta de
dueño [#41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453)
dio `NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`.
El diagnóstico protegido [#41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589)
pasó con `module=absent nf_call_iptables=unavailable write_ops=none`, sin
arrancar el daemon. **No hay BETA desplegada**. Ese recibo no distingue
módulo ausente frente a módulo disponible no cargado; la nueva candidata
[ADR0126](ADR/0126-readonly-kernel-module-availability.md) solo propone
lecturas adicionales. Los apartados siguientes son cortes históricos, no
el gate vigente de host.

## Prioridad 03/11 antes de 12:00 — verificación del navegador del droplet

El usuario pidió un piloto de login/cola/reserva en el sitio real y propuso Chrome del droplet. El sitio de Boca Socios respondió al navegador de ChatGPT, pero **no se acreditó sesión autenticada** de Fernando; el usuario confirma que sus credenciales son correctas. No se inició cola ni reserva. El código actual sólo simula reservas. El [run protegido #347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167) confirmó **`google-chrome-stable` presente bajo UID 10001**, PR #282 integrado. Siguiente candidata separada [#283](https://github.com/mbalbo2023/boca-socios-assistant/issues/283): prueba pública con Chrome real, URL fija de login, sin credenciales, sin cola y perfil efímero. Ningún resultado de presencia indica autenticación ni BETA instalada. Ver [ADR0118](ADR/0118-one-shot-public-login-chrome-smoke.md).

## RCA #275 — diagnóstico físico #342 y prueba ICC=true autorizada (2026-11-03 ART)

El [run #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050) en `main=d9ad6d492592c403eed70ae85af63f8b1821a67d` dio **`BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`**. El PR #279 y los [checks postmerge](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640180891) de CI y [seguridad](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640181029) ya pasaron. La red temporal quedó ausente y el daemon Boca detenido; no se instaló BETA/Chrome/Telegram ni se abrió un puerto. #317/#329/#337 son evidencias previas menos específicas.

El titular confirmó la **opción A** y se ejecutó una única vez: [run físico #345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41653887958) con `enable_icc=true` resultó **NO_GO reason=unclassified**, `cleanup=VERIFIED`, daemon STOPPED, contenedores Boca=0; `owner-enroll` real continúa `icc=false`. Por tanto ICC=true **no es solución acreditada**. La causa del NO_GO diferencial requiere diagnóstico adicional acotado, sin reintentos ciegos; **BETA sigue NO_GO**. PR #280 y [ADR0116](ADR/0116-rootless-icc-true-differential-probe.md) permanecen como evidencia del experimento.

## Decisión vigente sobre recursos (2026-11-02, PR #273 integrado)

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 fue integrado y verificado en `main=0e830e3eed941de1da70cef8b42bda9f20258b65` con CI y seguridad postmerge GREEN. La decisión sigue vigente.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

La reiteración del dueño está registrada, pero la revisión automática volvió a bloquear el dispatch antes de ejecutarlo; no existe un nuevo run. Véase el [bloqueo actualizado](https://github.com/mbalbo2023/boca-socios-assistant/issues/27#issuecomment-6591174050). La captura sigue pendiente por ese control de plataforma.

## Corte histórico de 2026-11-02 previo a PR #272 — aplicación no instalada

El corte de main `fe70271f940dbc6fc1f422907f5e7254eb2ae508` integra
#261/#263/#266/#269/#270. [CI postmerge 41544296010](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544296010)
y [seguridad 41544295980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544295980)
PASS. El candidato #270 `6604799918060dcbc2b8362638f724fb58f5bf5b`
pasó sus cinco checks: CI 41542179140 (2283 pruebas +31 subtests,
35 RCA/119 selectores), seguridad 41542179044, aislamiento Chromium offline
41542179350, smoke Docker 41542179148 y validación PR del release
41542179079. No hubo publicación ni trabajo host por esos checks.

PR #269 integró RCA #268 en `4b0c65becea753151d39acaf12f9bbacc6199407`;
CI/seguridad postmerge 41541729447/41541729743 PASS (2235 pruebas +31 subtests).
Su [infrastructure-inspect 41542349197/job125609403017](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017),
20:03:38–20:03:40 ART, devolvió `state=NO_GO`, `rc=1`,
`transport=confirmed`, `reason=effective_preflight_unit_unverified`,
`start_attempted=no`. La inspección ya ocurrió y conservó el motivo actual;
no arrancó Docker ni evaluó capacidad. No recupera el motivo perdido del
preflight 41537794166.

[RCA #271 / evidencia independiente](https://github.com/mbalbo2023/boca-socios-assistant/issues/271#issuecomment-6590959214)
reproduce que el renderer oficial de systemd v255 omite arrays Exec vacíos
incluso con `--all` y el parser
rechaza esa salida compatible. El output exacto del host no se capturó, por
lo que no se conocen sus campos omitidos ni se da por probada la causa completa.
Esta era la situación antes de integrar el PR #272. La inspección #289
posterior fue PASS, sin arranque; el preflight #290 falló durante observación
con parada verificada. El candidato #273 trata la holgura preventiva como
advisory sin alterar seguridad, y aún no constituye host BETA instalado. El
[checkpoint vigente #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836)
registra pasos y recibos posteriores para continuar sin duplicar trabajo.

La base histórica `032de0ebb923b4f80154e93cee3dfd1b254687ed` ya integró
#224/#226/#229 y #237/#239/#242–#249. PR #254 se integró como
`b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8`; PR #255 como
`dada569a2d71ad4411a73ebdaca1186ed3be6936`. No rehacer esos componentes.
PR #253 integró ciclo de vida, recuperación y sender durable en `5ddfba5`.
PR #263 también está integrado; el main del corte documental comprobado fue
`6f7fa0939d28df7c315440bba15237b0c1bfbe77`, con
[CI 41511631024](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41511631024)
y [seguridad 41511631004](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41511631004)
PASS. Ese corte precede la integración de #261. Su candidato final, los
checks posteriores y el estado operativo se registran en el
[checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6563012208).
Los resultados anteriores no se trasladan a un SHA nuevo.

Después de ese corte, #261 se integró como main
`32506362be24d350424cfc1911627d038ff8059c`, árbol
`a32cedf8f68ec6977653da65e528efdfac5fe060`, idéntico al candidato revisado
`3e34717735064cdae7dcbcef120f3b381f6cf7e4` y al checkout de prueba
`12ea553d7f86a6cbff06b6f0ed4ba5c30c3d7d95`.
[CI 41518027202](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41518027202)
pasó 2142 pruebas +31 subtests y 32 RCA/106 selectores ejecutados;
[seguridad 41518026922](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41518026922),
[smoke Docker 41518027065](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41518027065)
y validación PR del release 41518026926 PASS. El smoke superó el listener,
24 solicitudes sintéticas, IPC real, arranque/parada/reinicio del mismo par,
sender offline y los pasos de limpieza. Emitió diez recibos OBSERVED; no
midió tres servicios simultáneos ni el droplet. CI/seguridad postmerge
41518842124/41518842093 y los checks posteriores de #266 se
conservan en #45; el corte integrado comprobado figura arriba. No hay publicación
ni despliegue por estos merges.

El candidato intermedio #266 `f54485241617194eee316c7a79dc7e79a89580ba`
pasó seguridad, Chromium offline y lifecycle, pero
[CI 41519743366](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41519743366)
falló una prueba antigua que buscaba `tls` en bytes cifrados aleatorios
(2158 pruebas +31 subtests PASS). [RCA267/ADR0108](ADR/0108-structural-owner-envelope-tests.md)
reproduce ese falso positivo con una sal sintética válida. La corrección de
esta versión verifica esquema y bundle descifrado reales, mantiene negativos
TLS/clave privada y obtuvo revisión independiente con 57 pruebas focales PASS.
Producción y entropía permanecen intactas. La corrección se integró en #266
y sus checks posteriores figuran arriba; el fallo histórico no se transforma
en PASS ni autoriza un reintento protegido.

| Frente | Evidencia comprobada | Pendiente de aceptación |
| --- | --- | --- |
| Host | #269 integrado. [Inspección 41542349197/job125609403017](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017), 20:03 ART: NO_GO, transporte confirmado, `effective_preflight_unit_unverified`, sin arranque. El preflight anterior 41537794166 perdió su motivo antes de efectos | Corregir/revisar/comprobar RCA #271; inspeccionar la unidad con el candidato integrado antes de evaluar preflight/capacidad. No repetir preparación inicial ni el preflight a ciegas |
| Puerto | [41497093298/job125454798607](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298/job/125454798607): `127.0.0.1:8443 FREE reserved=no` a las 15:04:45 ART del 2026-11-02 | Nueva comprobación justo antes del uso; listener y forwarding reales |
| Release | Publicación dual integrada en código | Dos digests/manifiestos reales del mismo release y SHA final aprobado |
| Ciclo operativo | PR #253 integrado en `5ddfba5`: start/restart/status/acceptance y sender-start/recover con identidad y presupuesto explícitos | Comprobación host sobre el SHA final; no hay instalación ni reinicio probado en el droplet |
| Recursos | #261 integrado, ADR0103/0104; smoke y `cpu_ceiling` revisados. Inspección 41538696464: MemAvailable 1015044 KiB, `cpu_headroom=1.80` legacy no decisorio, PIDs UNKNOWN; [informe histórico de recursos](quality/resource-observation-2026-11-02.md) | Política host aún NOT_EVALUATED; resolver lectura de unidad #271. Requisitos/caps sin cambio; no extrapolar runner ni interpretar la estimación legacy como CPU libre |
| Telegram privado | PR #255 integrado; [CI 41481913145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913145): 1663 pruebas + 31 subtests y Chromium UI offline PASS; [seguridad 41481913075](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913075) PASS | Recibo real de prepare, formulario en tablet, custodia de token/destino, one-shot y recepción humana |
| Chrome/passkey | Owner-enroll integrado; localhost HTTP sobre SSH | Enlace de un uso real, create→get, Google Password Manager, segundo acceso y persistencia tras reinicio |
| Sitio oficial | [Captura autorizada 41537796470/job125593993374](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470/job/125593993374): 25 GET/200, Chromium `network=none`, UNKNOWN; script GET con `same_origin=false`, query redactada y `path=null`; aislamiento/cleanup PASS. #270 integra metadata de autoridad para otra observación | Host y función del script desconocidos; sitio completo sin aceptación ni evidencia de caída/bloqueo de Boca. El dueño reafirmó continuar el mismo diagnóstico de 25 GET; no hay recibo nuevo en este corte ni ampliación/reintento automáticos |
| Entornos | Observación inicial 2026-11-02: main-only, reviewers off, bypass disponible; READY release/deploy/read-only y secretos SSH existentes | Verificar configuración de activación exacta y permisos; marcadores solos no acreditan capacidad ni consentimiento |

Como antecedente previo al merge, #263 pasó [CI 41508912214](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912214)
(1902 pruebas + 31 subtests), [seguridad 41508912267](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912267)
y [smoke Docker/Chromium 41508912351](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912351),
con `public_connections=0`. El checkout fue el merge PR
`c470c530c3f93895722fe22c7168a6957ced723e`, árbol
`b3d12d0d09f224e0ba25316024dbd7a78be13cf7`, idéntico al head `9c693cb296e037af397e3ade2634f6264f717782`.
Ese smoke fue offline. La captura pública autorizada posterior ocurrió el
2026-11-02, 16:41:50–16:42:13 ART: 25 GET/200, 25 conexiones TLS y 30
peticiones internas contabilizadas por Chromium, con el resultado UNKNOWN
indicado arriba. No identificó la URL fuera del mapa; el [informe público](quality/public-source-validation-2026-11-02.md)
conserva el alcance y el antecedente de un GET 41481095746. No acredita un
sitio conectado completo, login, fila o reserva.

Inspect/port-check no ejecutaron Docker ni una instalación: no generaron
residuos de instalación y no corresponde inventar su limpieza. La DB se
inspeccionó sólo en tres rutas de metadata; ubicación global UNVERIFIED.

El preflight 41537794166 falló en el paso 28, `infrastructure-check`, antes
del marcador. Arranque, observación y restauración quedaron SKIPPED; no hubo
recursos de instalación que limpiar. El defecto de observabilidad ocultó el
motivo, que no puede recuperarse retrospectivamente. La inspección posterior
41538696464 sí alcanzó SSH como UID10001: runtime privado, bus owned, socket
rootless ausente, rootful no escribible, daemon inactive/dead/result=success.
`dockerd 29.7.2` identifica el binario, no un Engine activo verificado.
No identifica cuál condición falló antes ni evalúa capacidad. Las tres rutas
fijas de DB estaban ausentes; la búsqueda global sigue UNVERIFIED.

La captura posterior autorizada completó 25 conexiones del proxy y 25 GET/200;
el renderer contó 25 solicitudes evaluadas y cinco cancelaciones posteriores
al STOP. Son contadores separados, no cinco dependencias nuevas ni cinco GET
públicos adicionales. El [informe público](quality/public-source-validation-2026-11-02.md)
conserva ambas capturas y sus límites; no divulga ni reconstruye la URL redactada.

PR #270 integró [ADR0110](ADR/0110-public-denied-authority-metadata.md):
`scheme`/`authority`/`host_kind` en el primer rechazo, con validación y
redacción acotadas, sin resolver DNS ni contactar ese destino. Sus cinco checks
y CI/seguridad postmerge pasaron. No cambia STOP, allowlist ni red, y no recupera
la autoridad ausente de 41537796470. El intento posterior de dispatch fue
bloqueado antes de crear un run o generar tráfico; luego el dueño reafirmó
continuar el mismo diagnóstico de 25 GET sin pedir otra confirmación. No hay
recibo nuevo en este corte; autorización y resultado siguen separados.

### PR #261: evidencia histórica e integración comprobada

El corte posterior `7cfc9b60564f8c7bb8a589c86e15153c77bc948d` obtuvo
[CI 41514375866](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41514375866)
PASS (2081 pruebas +31 subtests) y seguridad PASS, pero el
[smoke 41514375981](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41514375981/job/125514028659)
falló antes del ciclo BETA: listener temporal `exited/2`,
`loopback_unreachable`. Sus etapas posteriores quedaron sin ejecutar; no
corresponde GO de integración. Los pasos de limpieza hospedada terminaron,
pero el fallback best-effort no prueba por sí solo un inventario final.
[RCA #265](https://github.com/mbalbo2023/boca-socios-assistant/issues/265)
reprodujo que una clave pública válida comenzando con `-` es interpretada
como opción por argparse. La clave aleatoria del run no quedó registrada:
la relación con ese fallo concreto sigue inferida. La corrección de
[ADR0107](ADR/0107-opaque-owner-cli-operands.md), incluida en esta versión,
cubre el comando de producción, smoke, transporte SSH del owner y
reconocimiento estricto de limpieza. Recibió revisión independiente y 128
pruebas focales PASS; conserva los operandos/opciones y las dos formas
exactas de identidad legacy/nueva. Se exigió comprobar el candidato corregido
en CI, seguridad y smoke antes del merge; sus recibos se conservan en #45.
Sin reintento ciego ni operación en el droplet.

En el corte documental previo al merge de #261, su primer candidato,
anterior a la corrección CPU,
`42eb497e8b597cd86035d08370dc935cba9b0f17`, sobre main `5ddfba5`, se comprobó
mediante checkout del merge PR `07b1b11a73b486142c3528a4896a20d5df59e57c`;
ambos tienen árbol `ebf53c7dfb082d25257acd2ed6f8bebb54e36499`:

| Comprobación del mismo árbol (checkout merge PR) | Resultado |
| --- | --- |
| [CI 41507866223](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507866223) | SUCCESS |
| [Seguridad de imágenes 41507865955](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507865955) | SUCCESS |
| [Smoke Docker/validación de deploy 41507865954](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507865954) | SUCCESS en runner desechable |
| [Validación PR del release 41507865916](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41507865916) | SUCCESS, sin publicación |

Los cuatro son runs `pull_request`, intento 1. Son evidencia histórica del
corte previo a la corrección CPU y esta reconciliación; no validan el candidato
final. Su SHA, revisión y checks exactos se registran en #45 antes del merge.

[ADR0103](ADR/0103-pre-release-infrastructure-observation.md) agrega el
preflight sin imágenes y restauración verificada del daemon detenido;
[ADR0104](ADR/0104-existing-smoke-resource-observations.md) mide las cargas
ya existentes de CI, sin repetirlas. La corrección CPU recibió GO independiente
con 290 pruebas focales: reemplaza afinidad-SSH menos loadavg por `cpu_ceiling`
de la rama `user.slice`, cuotas ancestrales, cpusets y configuración efectiva.
`cpu_scope` distingue `materialized`/`configured`; `daemon_startup_cpu_count`
es sólo otro límite. Load es advisory, no CPU libre. Los requisitos CPU
1.75/2.0, RAM 1536/1792 MiB, PIDs 256/288 y caps permanecen intactos.
Un techo no comprobable sigue UNKNOWN/NO_GO. Los checks finales de #261
pasaron en 41518027202/41518026922/41518027065; #266 también está integrado.
El preflight posterior falló antes de evaluar política; RCA #268 quedó integrado
por #269 y su inspección obtuvo el rechazo actual documentado en RCA #271.
La concurrencia de tres servicios no
está medida y los recibos del runner no acreditan capacidad host.

Secuencia: revisar/integrar la corrección RCA #271 con sus checks exactos →
`infrastructure-inspect` sólo lectura → establecer causa/estado y resolver
el bloqueo con alcance concreto → completar y evaluar `infrastructure-preflight` → aprobación
específica/release dual → preflight de imágenes/topología → owner-prepare y owner-enroll físico → instalación → aceptación
sintética temporal → formulario/custodia y prueba Telegram con outbox vacío
→ sender explícito → simulación persistente, reinicio y acceso físico repetido.
La aceptación termina detenida; la disponibilidad posterior exige start
explícito. El presupuesto del par es `1.5cpu-1024m-192pids`, y del ciclo con
owner Telegram listo `1.75cpu-1152m-224pids`.

Congelar main durante release/alta/install/Telegram/recovery. Registrar en #45
el SHA final, CI, seguridad, digests, runs, limpieza y evidencia física; no
crear un commit documental después de release que invalide el SHA operativo.
La prueba Telegram vincula token/destino/SHA y no se hereda a un upgrade.
Un fallo incierto detiene activación; recovery requiere el run fallido exacto,
misma procedencia y conectividad, sin iniciar apps ni reenviar mensajes.

## Historial: corte #224/#226 y candidato #225 antes de su integración

Los siguientes cortes conservan sus estados y enlaces originales; sus frases
«candidato», «no integrado» o TLS describen esas fechas, no el estado actual.

`main=4b1d219c2ba1739dc20c9c103170beedff8c1607` incluye
[PR #224](https://github.com/mbalbo2023/boca-socios-assistant/pull/224) y
[PR #226](https://github.com/mbalbo2023/boca-socios-assistant/pull/226):
**`http://localhost:8443`** con WebAuthn RP `localhost` por túnel SSH
Termius, sin certificados/CA ni configuración de servidor web compartido.
CI main 41341214858 y seguridad 41341214783 pasaron; no hubo deploy.
Boca conserva solamente el futuro host bind `127.0.0.1:8443` y la limpieza
Docker selectiva de #220, sin tocar puertos/servidores/contenedores ajenos.
El modo HTTP cifra exclusivamente el ID y la clave pública de la credencial
en un sobre v2; el camino TLS anterior de #214/#215 es histórico.

El candidato de código [#225](https://github.com/mbalbo2023/boca-socios-assistant/issues/225)
agrega un servidor temporal HTTP distinto del panel y una URL **plantilla**
`http://localhost:8443/activar#key=…`. Recibe sólo el hash de una llave
aleatoria de 256 bits y una clave pública de destinatario, valida
WebAuthn create→get y guarda únicamente el **sobre cifrado v2** en staging
temporal; el volumen de dueño con clave privada X25519 no se monta en el
servidor web. La rama candidata #225 añade al **mismo workflow protegido**
`owner-enroll` el preflight de puerto ocupado, contenedor temporal, volumen
staging Docker exclusivo, instalación/verify offline y limpieza selectiva
inmediata tras éxito o fallo. Pruebas de código y smoke en runner desechable
son parte del PR; **todavía requieren CI hospedado, revisión y merge**. El
canal de entrega de clave privado y la activación host **no están ejecutados
ni autorizados por ese PR**. Ver [ADR0092](ADR/0092-one-use-ssh-chrome-owner-enrollment.md).
**NO-GO operativo:** no existe aún enlace/token funcional servido en el
host, envío privado de la llave, prueba física Chrome/passkey/Termius ni
instalación BETA. Las pruebas sintéticas no sustituyen esos gates.

### Frentes obligatorios de primera BETA desarrollados en paralelo

- [#225](https://github.com/mbalbo2023/boca-socios-assistant/issues/225):
  enlace de Chrome de un uso por Actions protegido y cleanup Boca-only.
- [#227](https://github.com/mbalbo2023/boca-socios-assistant/issues/227):
  worker Chromium sintético bajo demanda, límites/timeout y contrato de
  integración con el runtime; sin conexión a Boca real.
- [#25](https://github.com/mbalbo2023/boca-socios-assistant/issues/25):
  recorrido Playwright offline reproducible en CI/imagen desechable.
- [#228](https://github.com/mbalbo2023/boca-socios-assistant/issues/228):
  regresiones HTTP de reinicio, comandos ambiguos y avisos sin duplicación.
- [#168](https://github.com/mbalbo2023/boca-socios-assistant/issues/168):
  cierre de seguridad/preflight del transporte Telegram y pruebas; token,
  destino, aceptación Bot API y recepción real mantienen gates privados.

Estas ramas son **candidatos independientes**, no integraciones verificadas
ni evidencia de aplicación instalada. Los componentes ya integrados de panel,
alta sintética, comando durable, estado y avisos se reutilizan; no se
duplican. Login/cola/reserva/compra real en Boca quedan fuera de la BETA de
simulación autorizada.

## Historial: corte verificado y alcance anterior

Corte de evidencia previo a esta actualización documental: `main` era
`6d3007a3ca1dfdba428cb7595486b1166a1d02b6` (PR #205 integrado). La publicación de imagen #198
corresponde exactamente a ese SHA; una posterior actualización de documentación
mueve `main` y requiere otro release para mantener la vinculación exacta.
Revalidar la HEAD, Actions y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
antes de una operación: este SHA no se traslada automáticamente a candidatos
posteriores. Rige la [autorización ampliada](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
para completar BETA de simulación, Site conectado, Telegram y despliegue
validado; se excluyen reservas, compras y mutaciones reales en Boca.

El corte histórico posterior #208 quedó en `58f57822e95da9574c0a9d5122607616da4a024a`.
Su [release protegido 41301618285](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41301618285)
terminó SUCCESS con digest `sha256:6f067e5078081760dec27f81d95792a4423ff9c1d9cb3bef19ef70dbfc8cf889`
y manifest 13082030761. Es sólo publicación, no instalación. #208 integró
custodia cifrada owner en código y ADR0086; no se ha inscrito una
passkey real, definido el origen privado, configurado un certificado ni
ejecutado su operación en el droplet. #209 sigue la decisión de ruta/ceremonia.
Ese corte ya fue superado; la release #214 previa a este cambio se registra
abajo y una HEAD final distinta exige su propia publicación.

**Corte posterior comprobado 2026-11-01:** #212 integró la comprobación
protegida del puerto; `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`
con CI 41310796782 y scan 41310796751 SUCCESS. La operación manual
[41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
en ese SHA, intento 1, reportó `FREE address=127.0.0.1 port=8443
reserved=no`. Sólo comprobó disponibilidad instantánea, sin Docker ni Boca
arrancado. La release 41302342233 para `3ef7aff8...` quedó histórica tras
#212; un install exige publicación de la HEAD final exacta. Por decisión del
dueño, el panel local con forwarding privado es primario; Site #113 queda
privado/offline, su baja diferida y fuera del gate BETA local. El cambio
PR #214/ADR0088 integró el origen HTTPS localhost exacto en
`main=8fdbec97262a525821eb87f3fbc27f1841a5d2ec`; CI 41312228362 y
scan 41312228548 SUCCESS. La [release protegida 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820),
intento 1 SUCCESS, publicó sólo
`ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
con manifest 13086161844. Sin pull ni instalación host. Este cambio
#215/PR #216/ADR0089 incorpora código de emisor WebAuthn local de un solo uso, sin prueba física de
Android, confianza CA, clipboard, entrega cifrada ni iOS (#209). La credencial
única tampoco acredita automáticamente ambos sistemas. La HEAD final de
este cambio exige nueva release exacta antes de cualquier host install. Los
runs históricos siguientes conservan su SHA original.

**BETA operativa en el droplet: NO_VERIFICADA / aplicación no instalada.**
RCA #219/PR #220 ya integra en main, **sin ejecutar en host**, una limpieza
selectiva inmediata en el mismo workflow tras fallar un `beta-install` marcado:
parada/identificación del controlador y descarte seguro de contenedor, red,
imagen y Compose exactos si son descartables, con clave/datos/owner preservados.
Los casos inciertos requieren nuevo inventario Boca y nunca permiten un retry
automático. No hubo operación real de limpieza. Ver ADR0090.
El cambio #217 requiere una passkey descubrible en la ceremonia local, para
evitar aceptar una credencial no sincronizable por Google Password Manager.
El navegador sólo recibe una cookie de sesión temporal; la llave privada
reside en el administrador de credenciales elegido. No hay prueba física de
persistencia, sincronización Android/iOS ni renovación TLS (#209).
Código integrado, Site publicado, CI verde y servicio rootless preparado y
detenido son
evidencias distintas. El controlador de `compose.yaml` todavía espera con
`engine=off`, sin listener ni puerto; `compose.beta.yaml` #171 empaqueta
un entrypoint BETA TLS para pruebas desechables, no instalado. #120/#124 no
crearon DB, clave ni volumen de aplicación en el host; #156 detuvo el
servicio dedicado y 41282301501 confirmó ALREADY_STOPPED. La ubicación global de una DB Boca anterior sigue
UNVERIFIED; el destino lógico futuro es `/data/boca.sqlite3` en el volumen
`boca-socios_boca_data`, sin permiso para reemplazar datos encontrados.

| Frente | Código o ejecución comprobada | Gate restante |
| --- | --- | --- |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164 y entrypoint TLS #173; RCA de UUID canónico #187 y probe sintético #190 | Empaquetar/servir en host con identidad y acceso privado; E2E host. No hay cliente Boca real |
| Panel | Adaptadores #128/#148, owner passkey/controles #163, registro WebAuthn #174, preflight #189, custodia #208 y origen `https://localhost:8443` #214 integrados; este cambio #215 incorpora emisor local sólo en código, sin instalación | #209: confianza CA, UV real, entrega privada del sobre, forward y uso Android/iOS, rechazo real de terceros |
| Avisos/Telegram | #162 fence/migración0007/adapter, #176 estado, worker default-off #188, parada opcional #194, helper cifrado #199, fases protegidas #203 y prueba Bot API de un solo intento #204 | Sin bot/destino privados, provisión en host ni envío/recepción real; `api_accepted` tampoco probaría lectura humana |
| Site #113 | Versión privada v10 D1 desactivada; #178 helper, #179 cliente opt-in, #181 custodia Actions y #196 inventario global | Ya no es gate de la BETA del panel local. Sigue offline y privado; baja diferida tras validar reemplazo. Ver #113 |
| Host | Rootless #120, preflight dormido #124, parada #198/41282301501 ALREADY_STOPPED; `port-check` #211/41310958281 observó 8443 FREE `reserved=no`; custodia owner #208, `beta-install` #191 y `beta-acceptance` #200 sólo en código | Sin marca BETA, identidad/archivos privados, instalación funcional ni aceptación host. Revalidar daemon, capacidad, puerto y SHA antes de operar |
| Chromium | Imagen y smoke offline #43/#44 con límite sintético | Capacidad/egress del droplet y visita real no acreditadas |
| Calidad/release | Corte previo a este cambio: main #214 `8fdbec97262a525821eb87f3fbc27f1841a5d2ec`, CI 41312228362 y scan 41312228548 SUCCESS; release 41312460820 publicó imagen/manifiesto sólo para ese SHA | Nueva release y manifiesto para la HEAD final exacta antes de instalar; CI no demuestra capacidad/postflight ni acceso tablet |
| Aceptación sintética | #170 HTTP loopback desechable, #190 probe TLS en contenedor y #200 operación protegida de aceptación/parada | Sin ejecución host/tablet, Site, Telegram ni recursos medidos del droplet |

## Historial: evidencia exacta de esos cortes

- [PR #161](https://github.com/mbalbo2023/boca-socios-assistant/pull/161)
  integró el loop de comandos en `77bf93c29dc59d5db0b5cf57c2c6ba2a14e8f39e`;
  [CI 41269055409](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269055409)
  y [scan 41269055410](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269055410)
  fueron verdes sobre el candidato revisado. No agregó listener.
- [PR #162](https://github.com/mbalbo2023/boca-socios-assistant/pull/162)
  integró Telegram en `466517d90991d3c9b600502af69424a84b82fabc`.
  HEAD candidato `e93bd190798d0974183935c21965b046b6ff965e`:
  [CI 41269298595](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269298595),
  [scan 41269298533](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269298533)
  y validaciones release/deploy 41269298646/41269298514 SUCCESS; sin envío real.
- [PR #165](https://github.com/mbalbo2023/boca-socios-assistant/pull/165)
  integró `stop-test` en `1441d55a632d4a545b21ee7f6f2b0a4140ab2320`.
  Candidato `4a812a275387bf18ba70b63a6c28ad865fcd34a0`:
  [CI 41269572935](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269572935),
  [scan 41269572802](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269572802)
  y validaciones release/deploy 41269572673/41269572784 SUCCESS.
  [Revisión técnica 5726252792](https://github.com/mbalbo2023/boca-socios-assistant/pull/165#pullrequestreview-5726252792).
  El dispatch posterior #156/41272785626 se registra abajo.
- [PR #164](https://github.com/mbalbo2023/boca-socios-assistant/pull/164)
  integró ciclo de vida local en `df668e066d2967ad7eb82e3c9f96935af282e2e2`.
  Candidato `46f9a48e6e6c2c7a738e5559a536e3de6011170f`,
  [CI 41269722611](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269722611),
  [scan 41269722595](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269722595)
  SUCCESS, [revisión 5726257987](https://github.com/mbalbo2023/boca-socios-assistant/pull/164#pullrequestreview-5726257987).
  Es biblioteca local: no instaló servicio ni abrió socket.
- [PR #163](https://github.com/mbalbo2023/boca-socios-assistant/pull/163)
  integró el panel en `ebb5e95399233eec629c8c52d4176092e97c5f34`.
  Candidato `4b608b1ae8dedd4ad9fe541ecbd5f45fac42958c`,
  [CI 41270060363](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270060363),
  [scan 41270060350](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270060350),
  validaciones release/deploy 41270060360/41270060361 y
  preview 41270060364 SUCCESS;
  [revisión 5726269111](https://github.com/mbalbo2023/boca-socios-assistant/pull/163#pullrequestreview-5726269111).
  Código WSGI sin credencial/origen/servidor de host: no acredita login.
- [PR #170](https://github.com/mbalbo2023/boca-socios-assistant/pull/170)
  integró aceptación HTTP sintética en
  `1ca5c0cf3d83e94e308ed6ef75d410bea31e0d7e`.
  Candidato `a3715286a3f17ce4119ec42eca4a1ff428610ce6`,
  [CI 41270258546](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270258546),
  [scan 41270258580](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270258580)
  y validaciones release/deploy 41270258625/41270258540 SUCCESS;
  revisión 5726279353. En un entorno loopback desechable, 21 requests:
  mediana 0.72 ms y p95 7.18 ms. No extrapolar al host/tablet.
- [PR #173](https://github.com/mbalbo2023/boca-socios-assistant/pull/173)
  integró entrypoint explícito en
  `0161922fb68bad3c36101bf9633ba025faf52f32`.
  Candidato `e86818dd87cbfd6fada494c1fe537aef19ee7834`,
  [CI 41270849469](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270849469),
  [scan 41270849494](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270849494)
  y validaciones release/deploy 41270849425/41270849419 SUCCESS;
  revisión 5726302585. `init-beta` sólo crea DB nueva/evento de prueba;
  `serve-beta` exige archivos passkey/TLS y sirve WSGI con loop local.
  Sin Compose beta integrado, credencial de dueño ni operación host.
- [PR #174](https://github.com/mbalbo2023/boca-socios-assistant/pull/174)
  integró sólo verificación de registro WebAuthn de dos pasos en
  `74edba458efe8cc2ce3b5f6e0deb1a8da9a0529d`.
  Candidato `91c05f6a75499f3643af06834262ae6a1527e468`,
  CI 41271084422, scan 41271084439, preview 41271084425 y
  validaciones release/deploy 41271084417/41271084459 SUCCESS;
  revisión 5726310354. No inscribió una passkey real.
- [PR #176](https://github.com/mbalbo2023/boca-socios-assistant/pull/176)
  integró RCA #175 en `8d37332f1b4674752963b4e8fda1b52da0925287`.
  Candidato `c4404c2fa8b6bcc8ad7b960b3b397bf834b3b6d3`,
  CI 41271432002, scan 41271432001, preview 41271432063 y
  validaciones release/deploy 41271432029/41271432013 SUCCESS;
  revisión 5726325061. `/estado` acepta sólo checksum conocido de 0007;
  sigue rechazando deriva o versión desconocida. No hubo migración host.
- [PR #171](https://github.com/mbalbo2023/boca-socios-assistant/pull/171)
  integró paquete BETA separado en
  `472574ca380e9c14d665b8aab97790b9a05e1f71`.
  Candidato `e498c8d1f4d09202b09fcda19d6accd09850d8f2`,
  [CI 41271723362](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41271723362),
  [scan 41271723366](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41271723366),
  validaciones release/deploy 41271723342/41271723422 SUCCESS;
  revisión 5726348620. Smoke desechable `init-beta→serve-beta` validó
  TLS, health, bind loopback, mounts, límites efectivos y cgroups. No
  publicación/instalación host ni credencial real.
- [PR #178](https://github.com/mbalbo2023/boca-socios-assistant/pull/178)
  integró helper de provisión cifrada en
  `497028ba49ec509f586051feca8876f2250ff5ac`. Candidato
  `ee11d8eb5332913f28eda48d14b1ec5e1749d0c4`,
  CI 41271955784, scan 41271955801, validaciones release/deploy
  41271955795/41271955816 SUCCESS, revisión 5726355216.
  No hubo secreto ni operación host real.
- [PR #179](https://github.com/mbalbo2023/boca-socios-assistant/pull/179)
  integró cliente/worker outbound opt-in en
  `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163`. Candidato
  `7933550bed4e7cfb6955dc4366be20c659b5cc5b`,
  CI 41272179087, scan 41272165010, validaciones release/deploy
  41272164915/41272164965 SUCCESS, revisión 5726364954.
  Site v10 confirmó vector HMAC y protocolo; default off, sin polling real.
- [PR #181](https://github.com/mbalbo2023/boca-socios-assistant/pull/181)
  integró `site-prepare/install/verify` en el workflow protegido en
  `9e923af56e76a04069bfad6f8ca9c68db0edd890`. Candidato
  `4c8158d79a49924738b2a52573dc37cc91eccc1a`: CI 41273068810,
  scan 41273068858, smoke/validación de deploy 41273068811 y validación
  release 41273068906 SUCCESS; revisión 5726437610. El smoke preparó,
  instaló y verificó un sobre sintético en volumen desechable del runner;
  el job host quedó omitido. Ninguna fase Site se despachó al droplet.
- [PR #187](https://github.com/mbalbo2023/boca-socios-assistant/pull/187)
  integró RCA del redirect a UUID canónico en
  `b92e2abacd63d1654dfb6d795f718af2ea283589`; candidato
  `6c0ade927811f19f331c68b2b6b3e7a0bf8b8ed9`, CI 41274391525,
  scan 41274391451, validaciones release/deploy 41274391657/41274391454,
  preview 41274391653 SUCCESS y revisión 5726518608. Prueba roja previa;
  no hubo efecto host.
- [PR #189](https://github.com/mbalbo2023/boca-socios-assistant/pull/189)
  integró `check-beta-owner/config` sin listener en
  `63965b087fbd6d7a68308302bb8baf2e08975674`; candidato
  `b2b34a17f207f7021d09bb63455f7aafa7ba958d`, CI 41274671069,
  scan 41274671077, release/deploy 41274671053/41274671118 SUCCESS,
  revisión 5726527799. No inscribió al dueño ni configuró TLS host.
- [PR #188](https://github.com/mbalbo2023/boca-socios-assistant/pull/188)
  integró worker Telegram explícito y apagado por defecto en
  `1bdc80b7f50021227cd798e655844b157198ea93`; candidato
  `2e1ee9339b6c2ec83ba235deb2a81699c8c928b9`, CI 41274848402,
  scan 41274848345, release/deploy 41274848336/41274848461 SUCCESS,
  revisión 5726534430. Sin bot, destino ni envío.
- [PR #190](https://github.com/mbalbo2023/boca-socios-assistant/pull/190)
  integró probe TLS sintético desechable en
  `64746289363741c4d85df79fa4e133b07f261efa`; candidato
  `04592f882d1492b03fbe93a3c50e7293237a83a2`, CI 41275005313,
  scan 41275005491, release/deploy 41275005329/41275005377 SUCCESS,
  revisión 5726547113. Sin ejecución host.
- [PR #191](https://github.com/mbalbo2023/boca-socios-assistant/pull/191)
  integró `beta-install` protegido en
  `161043f15befd5b612b71e036c9c1dead21581ce`; candidato
  `5265546027fc8f69f03495202fbfd427a5232af2`, CI 41275510437,
  scan 41275510471, release/deploy 41275510497/41275510438 SUCCESS,
  revisión 5726574754. El smoke corrió preflight e imagen desechables;
  host/publish omitidos, sin instalación.
- [PR #194](https://github.com/mbalbo2023/boca-socios-assistant/pull/194)
  integró reconocimiento fail-closed del worker Telegram en `stop-test` en
  `451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`; candidato
  `ba5f8b4cc42c47dc279a95222c6fff3b4d30748b`, CI 41275762284,
  scan 41275762308, release/deploy 41275762296/41275762254 SUCCESS,
  revisión 5726581135. No hubo nuevo dispatch de parada.
- [PR #196](https://github.com/mbalbo2023/boca-socios-assistant/pull/196)
  cerró RCA de inventario global del daemon antes/después de custodia Site en
  `2768d23dd2e9e58563a13aa80d8b76885448d020`; candidato
  `2676bd9f0cb91e4da0785b0cd149e2d33fd5810a`, CI 41276268828,
  scan 41276268931, release/deploy 41276268935/41276268997 SUCCESS,
  revisión 5726595915. No hubo Site host dispatch.
- [PR #200](https://github.com/mbalbo2023/boca-socios-assistant/pull/200)
  integró `beta-acceptance` y parada Boca obligatoria en el mismo job en
  `f21b55f8cc79f9906b8ce1eff3fa1e6c152e896e`; candidato
  `8d629841832cb32d5435521f222359892f498389`, CI 41277081359,
  scan 41277081440, release/deploy 41277081383/41277081431 SUCCESS,
  revisión 5726623269. El runner ejecutó el probe con límites del
  controlador; job host omitido, sin aceptación del droplet.
- [PR #199](https://github.com/mbalbo2023/boca-socios-assistant/pull/199)
  integró helper de custodia cifrada del bot/destino Telegram en
  `a808a6455e624eea7e1eeb7bedd10f3ab63f9a7c`; candidato
  `e73c6a5c7339e47d6e69bf1e26c9d65749b123e3`, CI 41277311559,
  scan 41277311577, release/deploy 41277311519/41277311599 SUCCESS,
  revisión 5726629731. Ningún secreto real ni volumen host.
- [PR #203](https://github.com/mbalbo2023/boca-socios-assistant/pull/203)
  integró las operaciones protegidas de migración 0007 y custodia Telegram
  posterior a BETA en `487995ca57282e2947d977333e72bd10775fbb98`;
  candidato `6c5dd64b1f5c6302ce309de181ff8d49be3ac3fe`, CI
  41278835729, scan 41278835819, release/deploy 41278835721/41278835778
  SUCCESS y revisión 5726684632. El smoke en runner probó prepare/install/verify
  cifrados con datos sintéticos y stdin canónico; el job host y la publicación
  se omitieron. Main push CI 41278970494 y scan 41278970501 SUCCESS. Sin
  migración, volumen, bot ni destino reales en el droplet.
- [PR #204](https://github.com/mbalbo2023/boca-socios-assistant/pull/204)
  integró prueba protegida de identidad privada y un único aviso Telegram
  sintético en `5cb8ce17715f571979a2ea3bb092da9b470f362d`; candidato
  `6e8205c0063c095bd51e36820e7be89ba98079c4`, CI 41281318516,
  scan 41281318527, release/deploy 41281318543/41281318563 SUCCESS y
  revisión 5726822139. El runner validó metadata Docker real y pruebas
  falsas de Bot API/SQLite; publicación y operación host omitidas. No hubo
  token/chat, tráfico Telegram ni envío real. Main push CI 41281517606 y
  scan 41281517611 SUCCESS.

El Site privado v10 (source `d4c7f9094caddc018646b165e5ce42ebbccc93df`,
versión `appgver_1fda8ad8e44881918895842f6b608f77`, deploy
`appgdep_6ae6b9bf1894819199b6c2f7e41bdf91` SUCCEEDED) probó
10/10 casos Node+SQLite. La ruta hosted `/api/bridge/status` devolvió
503 `unconfigured`; no se encolaron comandos ni se instaló secreto/flag.
El feed GitHub v8 queda fail-closed por rate limit del egress, no es un
recibo operativo. #113 conserva configuración y gates.

El [run #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418),
attempt 1, preparó sólo el daemon dedicado sobre
`6be606f83c5a6afe0ba7226abbca6a09276d1ca1`: rootless,
cgroup v2/systemd, overlay2 y namespace vacío, con
`application_database=not_accessed`/`application=not_installed`. No repetir
la preparación. El [preflight #124 / 41268626135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41268626135),
attempt 1, source `213be4903669c6e88122a536ad8fee6785c997ac`,
informó `mem_kib=853288`, `stage_disk_bytes=8009560064`,
`stage_inodes=2902623`, `cpu_headroom=1.60`, `namespace=empty`.
Sólo validó el presupuesto actual 0.5 CPU/256 MiB/64 PIDs, sin instalar.

El [stop-test #156 / 41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626),
attempt 1, operó desde `main` `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163`
con imagen y release vacíos. El job protegido revalidó la HEAD antes del
host y emitió `BOCA_STOP_TEST state=STOPPED ... containers=0 data=preserved`.
Detuvo el daemon dedicado Boca y preservó datos/clave; no instaló la BETA ni
afirma que haya probado el panel, Site o Telegram. `containers=0` cuenta los
contenedores detenidos por esa invocación, no el inventario total: la operación
verificó que ninguno quedara en ejecución y preservó los ya detenidos, si
existían. La unidad conserva su
enablement y podría reiniciar en un reboot posterior; revalidar el estado
antes de otro uso.

La inspección anterior de entornos protegidos en GitHub del 2026-11-01 halló
`boca-image-release` sin variables ni secretos. Después se configuró sólo la
variable de entorno `BOCA_RELEASE_ENV_READY=ready`, preservando la regla de
rama `main`. La [publicación protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638), attempt 1, SUCCESS,
produjo `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:ab0745a840e35a6d713fed14ec0761512fdc90284c133f2c321c9ffe2d3c9284` para `6d3007a3ca1dfdba428cb7595486b1166a1d02b6` y el artefacto
`boca-release-manifest` ID 13079654802. El push CI 41282070869 y scan
41282070707 del SHA base fueron SUCCESS. La imagen no se descargó ni instaló
en el droplet; un nuevo commit exige release propio antes de cualquier install.
`boca-first-deploy` conserva sólo las dos credenciales SSH y tres variables
de despliegue/lectura; carece de `BOCA_BETA_ENV_READY`,
`BOCA_TELEGRAM_ENV_READY`, `BOCA_TELEGRAM_OWNER_READY`, origen/sujeto owner,
HMAC/bot ID protegidos y material Site. No se ha provisionado la
credencial/passkey/TLS real. Las
fases Site #181/#196, instalación #191, aceptación #200 y Telegram #203/#204
exigen su release y
gates correspondientes. La [parada protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) sobre `6d3007a3ca1dfdba428cb7595486b1166a1d02b6`
fue SUCCESS y emitió `ALREADY_STOPPED containers=not_queried data=preserved`;
no inventariaba contenedores. El daemon puede reiniciar tras un reboot, por lo
que se revalida antes de operar. El puente sigue desactivado.

La [inspección #98](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258754195)
es histórica: servicio ausente antes de #120; DB/WAL/SHM candidate-absent
únicamente en tres rutas fijas. No es censo global ni migración. Las DB de CI
son temporales. No se abrió, movió ni migró una DB del host.

## Secuencia de aceptación pendiente

El [plan BETA](BETA_DELIVERY_PLAN.md) exige alta sintética desde
**Socios > Agregar socio**, lista y ciclo de credenciales, iniciar/detener/
estado durable, avisos locales, reinicio, denegación y accesibilidad. Las
funciones diferidas o sin definición en su matriz se muestran con motivo,
sin fingir efectos. Conectar Site y Telegram requiere sus gates de identidad,
transporte y pruebas propias. [Issue #168](https://github.com/mbalbo2023/boca-socios-assistant/issues/168)
registra la provisión/recepción Telegram pendiente; [issue #113](https://github.com/mbalbo2023/boca-socios-assistant/issues/113)
registra el puente Site no resuelto.

La cadena pendiente es: revisar/integrar/verificar la corrección RCA #271 → inspección diagnóstica
de sólo lectura → resolver el bloqueo y completar/evaluar el preflight
→ congelar main
→ autorizar/publicar release dual exacta → preflight de imágenes/aislamiento → owner-prepare
y owner-enroll real → instalación/aceptación temporal → Telegram antes de la
primera simulación persistente → E2E desde interfaz real y reinicio/reanudación.
Las capturas públicas autorizadas 41512196530 y 41537796470 quedaron UNKNOWN.
#266/ADR0106 está integrado y el segundo run emitió la metadata saneada del
script denegado, sin revelar su host o función. #270/ADR0110 también está
integrado, pero no hay recibo nuevo que use su metadata de autoridad. El dueño
reafirmó la continuación del mismo diagnóstico de 25 GET; no amplía el mapa ni
identifica retrospectivamente URLs. El sitio completo sigue sin aceptación. La
parada de 41272785626 cerró las pruebas de preparación, no una instalación
BETA. El workflow `first-install` instala sólo un controlador dormido; #191
agrega `beta-install` y #200 `beta-acceptance` con parada, ambos sin dispatch
host. Su código no autoriza presentarlo como BETA operativa. El Site privado
v10 y el código Telegram no
suplen esos pasos. No hacer backup/restore ahora; sigue diferido.

El historial detallado del candidato offline #24 y de cortes previos permanece
en [la versión anterior de este documento](https://github.com/mbalbo2023/boca-socios-assistant/blob/1441d55a632d4a545b21ee7f6f2b0a4140ab2320/docs/BETA_INTEGRATION_STATUS.md);
sus tablas no describen el estado vigente. Regla 84 exige reconciliar este
archivo, README, ROADMAP y plan antes de release; durante activación, registrar
los resultados reales en #45 sin cambiar el SHA congelado.
