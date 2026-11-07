# Safe operations — verified evidence and gated procedures

**Estado actual (06/11/2026 ART):** leer primero
[R76 — Investigación previa al Cutover](#r76--investigación-previa-al-cutover-06112026-art).
Los apartados R50/R40 y las guías antiguas describen cortes históricos.

## R50 — Cutover A: contrato de dos pulls, candidato NO INSTALADO

Después del [Stage recover #743](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254252830)
y [READ_ONLY #744](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42254498237)
el controller legacy sigue sano en `127.0.0.1:8443` y Stage está ausente.
El incidente APPLY #740 permanece NO_GO. El código de R50 elimina la doble
exigencia de 4 GiB entre las dos imágenes: 4 GiB antes de comenzar el par,
1 GiB/50.000 inodos después de la primera y **antes del segundo pull**, y
otra vez después del segundo. Se mantienen identidad rootless, digests,
50.000 inodos, ausencia de cambios de filesystem, aislamiento, GO independiente,
recibo ACK y limpieza exacta Boca-only. Sin release/PR revisado ni PREPARE
nuevo, **no disparar APPLY**. Ver [ADR0183](ADR/0183-postpull-boca-beta-emergency-residual.md).

## Histórico — R40, regla de admisión dual sustituida por R50

Sobre `main=d4d2b2a6769d867097d31c08364ac33829354da7` se prepara un PR
para conservar **4 GiB + 50.000 inodos antes de cada pull** del par
controller/browser y permitir **1 GiB residual + 50.000 inodos** solamente
después de cada pull y en la BETA ya instalada. El umbral residual es una
red de emergencia, no una medición de consumo ni permiso para omitir identidad
de UID/socket/DockerRootDir, `st_dev`/`st_ino`, SHA/digests, aislamiento o
compensación Boca-only en la **misma** Action protegida. Si falta recibo
físico o cleanup exact-ID, NO_GO/INDETERMINATE sin retry ciego. No hay nuevo
release, GO B o instalación producto acreditados por este PR. Contrato y
evidencia: [ADR0183](ADR/0183-postpull-boca-beta-emergency-residual.md) / [#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).

## Guía móvil GO B en Samsung Chrome — 05/11/2026 ART (R21.21; NO EJECUTAR SIN GO)

**Lo que hay:** código DRAFT [#319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319) HEAD `3cbe31703d74413f8de66ac8783ec68b1b7f8a87`, TREE `208a75e0c7310ea25db55ca509563f0b57972f42`, fuentes #372/#375/#374/#376 verificadas; **7/7 GitHub Actions COMPLETED SUCCESS exact SHA R21.21**: [CI 42064964129](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964129) **3718 pytest PASS +34 subtests**, Ruff/format547/MyPy128/image-build PASS; [FirstDeploy 42064964223](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964223) PR-validation + runtime-smoke SUCCESS, **host SKIPPED**; [Release 42064964145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964145) validación SUCCESS, **publish SKIPPED**; [Panel 42064964232](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964232), [News 42064964239](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964239), [Telegram 42064964156](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964156), [Security 42064964402](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42064964402) SUCCESS. Artifacts de CI/FirstDeploy/Release consultados: **0**; no recibo físico ni imagen publicada. **Lo instalado es legacy `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`**, comprobado en Samsung Chrome/Termius/passkey el 04/11, NO BETA integral. **GO de merge/release/Cutover/Telegram no consta y no se ha ejecutado SSH de efecto.** Esta guía es para el momento posterior a merge, release con digest y GO específico, sin comandos de terminal ni pedir PIN.

**Dos pasos en GitHub para Cutover A — mismo workflow, misma operación, dos ejecuciones distintas:**

1. Desde **Samsung Chrome** abrir [Actions → Boca first deploy](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml), seleccionar **Run workflow** en rama `main` **solo cuando** #319 esté fusionado y tenga release controller/browser revisado. El dueño no debe volver a instalar el controller legacy ni reenrolar passkey.
2. **PREPARE sin efecto:** elegir `operation=cutover-a-apply`, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`, dejar `protected_action_context` **vacío**. Para este GO_B nuevo, `source_sha`, `image_ref`, `browser_image_ref`, `release_run_id`, `legacy_source_sha`, `legacy_image_ref`, `legacy_release_run_id`, `legacy_controller_id` y demás campos de hashes/IDs deben quedar **vacíos**: el runner revisa manifests/release y una observación exacta **READ_ONLY** de Boca para inferirlos. No escribir JSON/base64, CID de 64 caracteres, token, PIN ni contraseña. Pulsar Run workflow **solo con autorización de la etapa PREPARE**. Esto usa **un SSH solo de lectura al host Boca** bajo lease, con 0 mutaciones de aplicación/Docker; no hace Cutover ni limpieza.
3. Abrir el run PREPARE, comprobar `completed/success`, el Summary y artifact **`boca-protected-legacy-go-prepare`** con coordenadas/recibo inmutable (retención 2 días; vigencia de GO 24 h). Guardar el **número corto real de run PREPARE**. El GO `BOCA_CUTOVER_A_GO_BINDING_SHA256` debe ser un valor exacto derivado del recibo y configurado independientemente en Environment protegido `boca-first-deploy`; **no** se obtiene de un booleano/input del formulario. Sin esa evidencia/GO independiente, detenerse.
4. **APPLY con GO vigente:** volver a la misma [Action](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml), rama `main`, misma operación `cutover-a-apply`, servicio/presupuesto iguales, escribir **solo los dígitos del run PREPARE** en `protected_action_context`; los demás campos técnicos GO_B se restauran del artifact que el runner autentica. Verificar actor/main/SHA/attempt1/manifest/ZIP y GO Environment antes de que el único SSH effectful llegue al host. Esperar recibo Cutover A exacto y segunda línea `BOCA_CUTOVER_A_POSTFLIGHT` con bytes/inodos e IDs Boca: si falta, `NO_GO` sin reintento ciego ni cleanup global.
5. **Import oficial posterior al Cutover:** misma secuencia pero `operation=official-notice-import`. En PREPARE también se requiere **solo** `official_news_run_id` público, tomado de un run auténtico de noticias PR-only revisado; todos los otros SHA/ID/artifact/digests deben quedar vacíos y son verificados automáticamente. En APPLY únicamente `protected_action_context=PREPARE_ID` (más service/budget fijos). Variable GO independiente `BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256`, recibo de import `actionable=false`, sin compras ni reservas. No usar esta ruta hasta que el Cutover haya instalado la imagen con CLI revisado y el source report sea válido.
6. **START/STOP bot y Chromium:** el botón del panel deja solicitud `REQUESTED`, **no** detiene/inicia físicamente. Luego el flujo distinto `protected-go-prepare` (1 lectura SSH Boca con `protected_action_context` vacío), GO independiente `BOCA_LIFECYCLE_GO_BINDING_SHA256`, `lifecycle-apply` con ID corto PREPARE, y **ACK UUID exacto**. STATUS se observa vía panel/Actions, nunca inferir de la intención. Falta evidencia física: sigue NO_GO hasta validación.
7. **Aceptación Samsung y limpieza:** confirmar en interfaz de **Termius** el túnel ya existente local 8443 → remoto 127.0.0.1:8443; abrir en **Chrome Android** `http://localhost:8443/ingresar`, verificar persistencia tras cerrar/reabrir/reiniciar controller, alta simulada **Socios > Agregar socio**, ACK físicos y recursos. Verificar recibo de **cleanup selectivo Cutover A** con IDs Boca exactos; conservar imagen activa, datos/owner/clave y todos los otros Docker/Porota. La política tras cualquier deploy PASS/FAIL es general, pero el **código #372 cubre solo Cutover A** y otras seis instalaciones legacy permanecen bloqueadas.
8. **Telegram:** #374 exige passkey WebAuthn UV nueva en el stage cifrado, pero **sender OFF** y `telegram-activate` sin caller host same-lease/UID/PID+egress/ACK validado; **NO_GO**, sin ingresar token real ni pedir PIN, hasta GO distinto y backend físico genuino. Seguridad adicional P2.

**Regla de parada:** cualquier FAIL, artifact/release/GO ausente, TTL vencido, host CID incierto, ACK no exacto o cleanup incompleto ⇒ **NO_GO**, conservar legacy, sin retry ciego ni tocar otros sistemas. No se ejecuta nada ahora. [Matriz de handoff](BETA_INTEGRATION_STATUS.md) y [plan](BETA_DELIVERY_PLAN.md); sin backups, migración legacy SQLite 0008, BLACKBOX, compra/reserva real, nuevos puertos o HTTPS.

## Histórico — Preparación operativa Samsung Chrome / Termius — 05/11/2026 ART (A45-R21.17, NO EJECUTAR AÚN)

**Estado:** `main=cabce9f1e452e63ded115f447559a358dc0f4d1b` legacy instalado 04/11 y autenticación Samsung Chrome+Termius+passkey comprobada. La BETA integral **no** está instalada. [DRAFT #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319) HEAD `82c7c3edf75911805218149d4907ecb37b374a66`, TREE `d6ca906f517571c0025cce7780b674cdc3956fc3`, tiene [CI 42056912053](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056912053) 3645 tests+34 y 7/7 Actions SUCCESS; FirstDeploy [42056911736](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911736) host SKIPPED y Release [42056911857](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42056911857) publish SKIPPED. **Ningún GO nuevo de merge/release/host/Cutover/Telegram consta.** No se te pide ejecutar terminal, PIN, token ni credenciales.

**Plan visual/manual de dos despachos, SOLO después de integrar #371 y superar GO/QA/release exactos:**

1. Desde **Samsung Chrome** abrir [GitHub Actions → Boca first deploy](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml). Pulsar **Run workflow**, elegir rama `main` y operación según el frente **revisado**. No hacerlo mientras `main` siga legacy o #371 no cierre el GO B.
2. **PREPARE revisado:** para controles bot/Chromium, primero solicitar la acción en panel privado (solo crea estado `REQUESTED`), luego seleccionar `protected-go-prepare`; completar `source_sha`, digests de imágenes y `release_run_id` **que se entreguen ya verificados**, servicio `controller`, presupuesto `1.5cpu-1024m-192pids` y dejar `protected_action_context` **VACÍO**. La implementación [ADR0166](ADR/0166-lifecycle-go-mobile-one-read.md) realiza **un SSH host READ_ONLY** bajo lease, **cero mutaciones de aplicación**, y publica artifact `boca-protected-go-prepare`; **no** ejecuta START/STOP. Para **Cutover A/import oficial**, usar únicamente la secuencia y nombres exactos que publique el futuro PR #371 tras revisión: los gates heredados todavía no sirven para un GO B real.
3. Abrir el **run PREPARE completado SUCCESS** y comprobar su **Summary**, artifact y **ID numérico corto**. El digest de autorización GO corresponde a ese recibo, operación y SHA; la variable se deposita **independientemente** en Environment protegido `boca-first-deploy` (`BOCA_LIFECYCLE_GO_BINDING_SHA256` para lifecycle; `BOCA_CUTOVER_A_GO_BINDING_SHA256` o `BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256` para Cutover/import cuando #371 lo implemente). El SHA mostrado en Summary **no es autorización automática**. No copiar PIN, token Telegram ni claves.
4. **APPLY revisado:** volver al mismo Actions → **Run workflow**, rama `main`. Para lifecycle elegir `lifecycle-apply`, conservar coordenadas exactas de release e ingresar **únicamente el número del PREPARE anterior** en `protected_action_context`. Para Cutover A/import seguir los nombres definitivos de #371, sin inferirlos de contratos antiguos. El runner exige mismo actor/main/fuente/artefacto, GO Environment independiente, TTL24h, control de replay y recheck antes del único SSH de efecto.
5. Antes de continuar, comprobar **run completed/success y recibo físico APPLIED/ACK exacto**; ausencia, ambigüedad o SSH perdido implican `NO_GO`, sin reintento ni limpieza a ciegas. El START/STOP real se acepta solo con el UUID de la solicitud original, identidad del proceso y estado final observados; la acción de botón por sí sola no es ACK.
6. Después del Cutover autorizado, en **Termius (interfaz del túnel ya configurado)** confirmar forward local `8443` hacia remoto `127.0.0.1:8443`, abrir **Chrome Samsung** `http://localhost:8443/ingresar`; verificar sesión del mismo Chrome al cerrar/reabrir y tras reiniciar controller, alta simulada **Socios > Agregar socio**, controles físicos y posterior import informativo. Telegram queda **OFF/NO_GO** hasta #362 (WebAuthn HMAC/attestor + caller same-lease egress y rearm stage) y nuevo GO independiente. Nada de navegación/compra/reserva real Boca.
7. Dejar en GitHub los recibos de host, Samsung y rendimiento, más inventario **antes/después** y limpieza **selectiva exclusiva Boca** tras cualquier deploy exitoso o fallido: IDs exactos de imágenes en desuso/temporales, sin tocar imagen activa, volúmenes de datos/owner/clave, Porota u otros proyectos. Recibo ausente o incierto => **NO_GO** y READ_ONLY antes de reconsiderar.

**Bloqueos explícitos al corte:** [#371](https://github.com/mbalbo2023/boca-socios-assistant/issues/371) issue P0 aún sin PR GO B final; [#362](https://github.com/mbalbo2023/boca-socios-assistant/issues/362) Telegram físico; sin GO específico de merge/release/deploy ni artifacts físicos del #319. Seguridad adicional P2. Un solo `127.0.0.1:8443`, sin puertos adicionales/HTTPS, backups, SQLite legacy schema 0008 ni BLACKBOX. Detalles cruzados en [matriz de integración](BETA_INTEGRATION_STATUS.md) y [plan de entrega](BETA_DELIVERY_PLAN.md); **Regla84** [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6662182710).

## Histórico — Operación real al 05/11/2026 ART (R21.11 provisional; requiere GO)

- **Producción actual observada:** `main cabce9f1e452e63ded115f447559a358dc0f4d1b` **legacy** aceptado 04/11 con Samsung Chrome, Termius y passkey; **no es BETA integral**.
- **Candidato:** [DRAFT #319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319), HEAD provisional `5903ded0790ab7254bf68572af47fe75c6e08889`, CI [42044959831](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959831) **3.437 PASS +34**, 7/7 Actions GREEN: además [imagen](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959889), [security](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959974), [news](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959895), [panel](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959814), [telegram](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044959805), [first-deploy](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42044960073). **Verde no es ACK físico.** Publicación de imagen y host manual omitidas.
- **Código incorporado, no operación comprobada:** #349 importación oficial Actions y #350 STOP persistente; #353 Telegram y #355 Compose requieren fase física/backend/egress/custodia.
- **Puertas P0 abiertas:** #356 ACK bot/Chromium, #352 workflow protegido, #358, QA/predeploy del HEAD final y GO para merge/release/deploy. No ejecutar SSH, deploy, release ni intervención protegida sin su GO.
- **Host aislado:** único bind `127.0.0.1:8443`, túnel existente; sin HTTPS nuevo ni otros puertos. No tocar Porota, otros contenedores, BLACKBOX `synthetic.py`/`ipc_worker.py`, ni la SQLite legacy con esquema 0008. Sin reservas/compras reales y sin backups. Seguridad adicional P2.
- **Regla permanente de limpieza:** tras cualquier despliegue (sea exitoso o fallido) relevar y limpiar **selectivamente solo imágenes, contenedores y artefactos Docker huérfanos identificados de Boca**, conservando recursos en uso/compartidos de Porota y otros sistemas. Registrar evidencia antes/después.
- **Regla 84:** documentar cada decisión/recibo y la reconciliación posterior al nuevo HEAD en [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6660565397); las instrucciones bajo “Histórico” pueden corresponder a un corte anterior.

## Histórico — Estado operativo vigente — 04/11/2026, 16:33 ART

El controlador **sí está instalado**: `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`,
release [41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078),
install [41896871289](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41896871289)
`PASS`, aceptación sintética [41897278258](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897278258)
`PASS` (24 requests), y último start
[41897569928](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897569928)
`RUNNING` en `127.0.0.1:8443`, `engine=off`, `site=off`, Telegram `off`.
Los volúmenes de datos/clave/owner se preservaron. **No reejecutar** el
primer install, el alta por PIN ni la aceptación ya verde para comprobar
el panel. La comprobación tablet aún es obligatoria: Termius SSH forwarding
local `8443` → remoto `127.0.0.1:8443`, Chrome Android
`http://localhost:8443/ingresar` para sesión nueva (`/` exige cookie). La
passkey de owner se registró previamente; cookie temporal: inactividad 15 min,
límite absoluto 8 h, invalidación tras reinicio. No certificar la
sesión/cookie hasta observarla físicamente.

La imagen browser está publicada pero **no instalada/activada**; no despachar
`beta-browser-install` sobre este controlador sin validar el contrato
new-only, ocupación del puerto y transición conservadora de almacenamiento.
No activar BLACKBOX ni navegar el sitio por agentes. Telegram requiere
custodia y prueba Bot API, luego comprobación humana; ningún mensaje real
acreditado. Para estado y bloqueos futuros, usar el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355).
Sólo Actions Boca para operaciones de host; limpieza exclusivamente selectiva.

### Regla permanente de higiene Docker posterior a deploy (decisión del dueño, 04/11/2026)

**Toda** instalación, actualización o despliegue Boca —tanto PASS como FAIL—
termina con una limpieza selectiva **obligatoria dentro del mismo workflow
protegido**, con inventario previo/posterior de espacio e inodos y recibo
redactado. Después de PASS se eliminan contenedores temporarios, redes/staging
de intento ya sin uso e **imágenes Boca anteriores** solamente cuando el
inventario por ID/digest/labels demuestra que no están referenciadas por ningún
contenedor. El controlador activo, su imagen y los volúmenes owner/clave/DB
persisten. Después de FAIL se ejecuta primero la compensación acotada vigente,
sin convertir el fallo original en éxito. Los recursos de identidad incierta
se retienen con motivo explícito; una limpieza incompleta o no verificada
deja `NO_GO/INDETERMINATE`, sin reintento ciego ni proclamación de instalación
integral GREEN. **Prohibidos** `docker system prune`, `docker image prune -a`,
`docker volume prune`, eliminación forzada, globs y tocar otros proyectos.
Esta decisión está aprobada para **desarrollo en código y pruebas**; los
PR DRAFT correspondientes aún no implementan ni ejecutan la limpieza física.

## Historial previo — RCA del beta-install rechazado antes del fix #307

El último `beta-install` protegido [#41890280818](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41890280818)
pasó el gate `BOCA_BETA_ENV_READY=ready`, SHA/release, arranque existente del
daemon Boca, inventario/staging de owner, Compose y disponibilidad de
`127.0.0.1:8443`. `beta-preflight` registró MemAvailable de 931.808 y
914.340 KiB; nueve segundos después `beta-apply` releyó el inventario y
emitió `BOCA_NO_GO: insufficient available host memory`. No hay dato público
del valor final ni benchmark de consumo. La causa de software identificada
es el umbral **768 MiB** que persiste en `validate_snapshot`, incompatible
con la política de [ADR0112](ADR/0112-postdeploy-resource-observation.md)
de reservar los umbrales preventivos para observación; aceptación aún usa
512 MiB/0,25 CPU. El [issue #307](https://github.com/mbalbo2023/boca-socios-assistant/issues/307)
centraliza el fix-forward.

Las etapas de detención del controlador, limpieza selectiva y parada del
daemon exclusivo finalizaron SUCCESS. No hubo instalación acreditada; no
reintentar sobre el mismo SHA. Una nueva ejecución requiere PR revisado,
CI/security exactos, integración, release por digest y nuevo recibo de
entorno protegido. La observación posinstalación comprobará rendimiento
real; los cgroups (0,5 CPU, 256 MiB, 64 PIDs), aislamiento y resguardo de
volúmenes no se flexibilizan. El navegador interno autenticado de GitHub
ofrece `Run workflow`; intentar usarlo para el próximo despacho sin comandos
de Termius, nunca para saltar el gate protegido.

## Aceleración de checks PR (candidata #306, 04/11/2026)

La concurrencia de `release-image.yml` y `boca-first-deploy.yml` cancela
**únicamente validaciones antiguas de un mismo PR**, al cambiar su SHA.
Los disparos físicos `workflow_dispatch` siguen serializados: no se admiten
dos escritores sobre Docker rootless, volumen de datos ni puerto
`127.0.0.1:8443`. El ajuste no publica imágenes ni inicia el host, no
reduce Trivy, CI o gates de seguridad y exige pruebas y revisión del SHA
final. Hasta recibo físico, la BETA permanece **NO instalada**. ADR0129.

## Ciclo protegido de despliegue BETA — candidato #305, 04/11/2026

[PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) **fusionado** en `main=5398669d5c32ca64ba113cddcc20363502c85c1e`: CI postmerge [#41859364620](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41859364620) y seguridad de imágenes postmerge [#41859364192](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41859364192) **GREEN**. Esto habilita el perfil ICC=true solo en la red temporal privada de owner-enroll, sin módulo br_netfilter ni firewall global; **no instala BETA**.

La nueva candidata [#305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) / [ADR0129](ADR/0129-controller-only-beta-resume.md) corrige dos dependencias antes del release final: `start-existing` de la unidad Boca antes de `beta-install` tras owner-enroll, y operación `beta-start` para reanudar **solo el controlador instalado**, conservando identidad/digest, tres volúmenes y el volumen Telegram adicional únicamente si se verifica. La aceptación detiene el servicio; `beta-start` debe devolverlo a RUNNING sin `compose up`, reinstalación ni reinicialización de DB/clave. Todas las operaciones por Actions protegidas, `source_sha=main`, servicio controller, imagen por digest, recibos acotados y limpieza selectiva tras fallos. No usar `beta-browser-start` para reanudar el panel; blackboxes intocables.

**Estado del nuevo desarrollo:** rama `feature/305-boca-beta-lifecycle` en validación, aún **NO fusionada ni desplegada**. Después de integración y postmerge GREEN: release dual, pruebas físicas de owner-enroll/Chrome, instalación, aceptación, reanudación, Telegram y recursos reales. No reutilizar SHA antiguo para instalar.

## Contrato vigente para corrección del bloqueo rootless — 04/11/2026

**Actualización 04/11/2026 (Regla 84, RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)):** El [run protegido #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848) verificó `module=absent`, `nf_call_iptables=unavailable`, `index=listed`, `modules_disabled=0`, `write_ops=none` en `main=41fc15e261d002dc614124ac0f2d2e1bea81f896`; fue una **lectura exitosa**, no un deploy.

El propietario ordenó flexibilizar el obstáculo y llegar a BETA. [PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) / [ADR0128](ADR/0128-boca-only-owner-enroll-icc-compat.md) implementan el cambio **solo en la red temporal de `owner-enroll`**: `ICC=true`, UID rootless Boca, cero masquerade, exactamente un peer autorizado, host loopback `127.0.0.1:8443`; limpieza positiva con opciones concordantes. El `network-probe` histórico ICC=false y la variante diferencial ICC=true siguen separados; **no** se cargan módulos ni se modifica kernel/firewall global, Porota u otros servicios. Riesgo residual: menor aislamiento entre potenciales contenedores de esa única red; ningún segundo contenedor está autorizado.

**Estado físico vigente: BETA NO instalada.** PR/CI, release dual exacto, alta Chrome real, `beta-install`, aceptación, recursos y Telegram todavía requieren evidencia. Además [issue #305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) rastrea arranque del daemon antes de instalación y reanudación controller-only después de aceptación. Nunca reutilizar `beta-install` para reanudar, ni activar el navegador BLACKBOX desde agente. Los apartados anteriores del 03/11 abajo son **cortes históricos**, no la instrucción operativa actual.


## Inspección del kernel por workflow protegido — evidencia 2026-11-03

PR #298/[ADR0125](ADR/0125-readonly-kernel-bridge-hints.md) está fusionado.
El [run #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589)
de `infrastructure-inspect` sobre
`main=a83e105d4ccec2cc59dfabce77142750de733630` devolvió
`BOCA_KERNEL_BRIDGE state=OBSERVED ... module=absent nf_call_iptables=unavailable write_ops=none`.
Fue lectura sin módulo cargado, puerto ni servicio iniciado. El green de
workflow **no autoriza `owner-enroll` ni BETA**: la red real `ICC=false`
continúa NO_GO. [ADR0126](ADR/0126-readonly-kernel-module-availability.md)
describe la ampliación propuesta para verificar índices del módulo del kernel
y política `modules_disabled`, no ejecutada todavía en el host. Una vez
integrada con todos los gates, usar el mismo workflow manual, `--ref main`,
SHA exacto, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`,
imágenes/release/envelopes vacíos. Ninguna fase corre `modprobe`, `sudo`,
escrituras `sysctl`, Docker ni operaciones sobre otros servicios. Logs
únicamente con recibos allowlisted; consola Termius devuelve resultado breve
y copia OSC52, sin fotografías de pantalla.

## Piloto conectado: Chrome físico encontrado; nueva prueba pública acotada (03/11/2026)

La operación `chrome-host-inspect` de [issue #281](https://github.com/mbalbo2023/boca-socios-assistant/issues/281) ya dio recibo físico [#347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167) `PRESENT google-chrome-stable uid=10001`. Ahora [issue #283](https://github.com/mbalbo2023/boca-socios-assistant/issues/283) agrega **`chrome-host-public-smoke`**, con URL única fija de login de Boca, navegador headless existente, sandbox activo, perfil privado efímero y grupo de procesos terminado aun ante timeout. No se transmiten credenciales ni se opera cola/reserva. Requiere `source_sha` idéntico a `main`, `service=controller`, presupuesto `0.5cpu-256m-64pids`, entorno de lectura habilitado, entradas privadas/image/release vacías; sólo disparar tras CI y seguridad de PR y main GREEN. El recibo es sólo `FORM_VISIBLE|OTHER_PAGE|CHALLENGE|NO_GO` y cleanup; un challenge o un login no completado no justifican bypass. Ver [ADR0118](ADR/0118-one-shot-public-login-chrome-smoke.md). No alterar otros workloads.

## RCA #275 — diagnóstico rootless #342 y experimento ICC=true (2026-11-03 ART)

[Run #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050) sobre `main=d9ad6d492592c403eed70ae85af63f8b1821a67d`: **`BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`**; la red temporal quedó ausente y el daemon exclusivo detenido. El host no recibió imagen, contenedor, puerto ni BETA. #317/#329/#337 se conservan como diagnósticos históricos menos precisos; CI/seguridad postmerge de #279 GREEN.

[Moby #50635](https://github.com/moby/moby/issues/50635) documenta una coincidencia con `enable_icc=false` del owner-enroll y falta de `bridge-nf-call-iptables`. Para comprobarla sin cambiar el kernel, el dueño autorizó sólo una red de **prueba** con `icc=true` y cero peers, misma identidad SSH/UID 10001, rootless, SHA, inventario y limpieza. Nueva operación propuesta `network-probe-icc-true` en el mismo workflow protegido, nunca `owner-enroll` ni `beta-install`. Si falla o la identidad de la red no puede verificarse, conservar `NO_GO`, ejecutar limpieza independiente y stop, sin reintento. El estado de módulo kernel y la reparación siguen no verificados. Ver [ADR0116](ADR/0116-rootless-icc-true-differential-probe.md) y [issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275). No publicar imágenes ni habilitar otros servicios mientras la red real sea NO_GO.

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

## Documented state and current checkpoint

Historical baseline `032de0` already integrated #224/#226/#229 and browser
release/install/cleanup #237/#239/#242–#249. PR #254 merged at
`b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8`; PR #255 merged at
`dada569a2d71ad4411a73ebdaca1186ed3be6936`. Its private Telegram form passed
[CI 41481913145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913145)
(1663 tests plus 31 subtests and real offline Chromium UI proof) and
[security 41481913075](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913075)
before merge. PR #253 integrated lifecycle/recovery and durable Telegram in
`5ddfba568d0b53168f51c0e5b33c363ba24c505e`. The historical main cut
`6f7fa0939d28df7c315440bba15237b0c1bfbe77` includes PR #263, with CI 41511631024
and security 41511631004 PASS. PR #261 was unmerged at that cut. Its historical
`42eb497e8b597cd86035d08370dc935cba9b0f17` checks precede the reviewed CPU
correction and cannot validate the final candidate; see the
[evidence and pending checks](BETA_INTEGRATION_STATUS.md).
Later smoke [41514375981](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41514375981)
on `7cfc9b6…` exited 2 despite CI passing 2081 tests.
[RCA #265 / ADR0107](ADR/0107-opaque-owner-cli-operands.md) records the
independently reviewed argument-terminator correction integrated by #261; it
reproduces a compatible defect without proving the unrecorded random value from that
run. These earlier cuts remain historical. Main
`fe70271f940dbc6fc1f422907f5e7254eb2ae508` includes #261/#266/#269/#270:
[postmerge CI 41544296010](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544296010)
and [security 41544295980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544295980)
passed. The five #270 candidate checks also passed, including 2283 tests plus
31 subtests and 35 RCA lessons/119 selectors. New candidates require their
own checks. Operational state is maintained in
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836).
No matching current dual release, BETA installation, real activation URL,
physical Chrome/GPM persistence or Telegram delivery is established here.

[Authorized public capture 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470/job/125593993374)
completed 25 permitted GETs, all HTTP 200, and 25 proxy connections. Chromium
under `network=none` remained UNKNOWN: a denied script GET had
`same_origin=false`, `query_redacted=true`, `path=null`, `path_class=external`.
Its host and function are unknown; do not infer analytics, challenge or another
provider from those flags. The renderer evaluated 25 requests and cancelled
five after STOP; those cancellations are not new dependencies or public GETs.
Startup, network-none, pre/post isolation and selective cleanup passed.
#266/[ADR0106](ADR/0106-sanitized-public-render-denials.md) supplied the bounded
diagnostic without expanding the capture map. The owner authorized this capture
and the infrastructure test; both ran. Following a later blocked dispatch, the
owner reaffirmed continuation of the same 25-GET diagnostic without another
confirmation. This does not expand the map or enable blind retry. Full-site
acceptance remains open, without evidence of an outage or
block by Boca. The [report](quality/public-source-validation-2026-11-02.md)
preserves the earlier UNKNOWN captures 41481095746 and 41512196530; the latter's
unrecorded URL cannot be recovered from this new receipt.

PR #270 integrated [ADR0110](ADR/0110-public-denied-authority-metadata.md),
adding `scheme`, a validated `authority` or null, and `host_kind` to the first
causal denial. `dns_syntax` proves syntax only; it does not establish public
DNS answers, ownership or the script's role. No lookup or connection occurs.
Userinfo/query/fragment and arbitrary paths remain omitted; hostname labels
are intentionally visible when accepted. Its five candidate checks and postmerge
CI/security passed. The 25-GET map, STOP and network barriers are unchanged. This
metadata cannot reconstruct the authority of 41537796470; no new public
observation is authorized by this integration alone. The owner subsequently
reaffirmed the same-scope diagnostic; no new capture result is established in
this cut. The earlier blocked dispatch created no run or public traffic.

[Infrastructure preflight 41537794166](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166/job/125593988779)
failed at step 28, the initial read-only `infrastructure-check`. The attempt
marker, daemon start, observation and restoration steps were SKIPPED: no
installation or residue-producing effect occurred. RCA #268 records that the
workflow lost the diagnostic reason; it cannot be recovered retrospectively.
This does not establish which host condition failed. PR #269 integrated
`infrastructure-inspect` below and its authorized run already occurred:
[41542349197/job125609403017](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017),
on main `4b0c65becea753151d39acaf12f9bbacc6199407`, 20:03:38–20:03:40 ART.
It returned `NO_GO`, `rc=1`, `transport=confirmed`,
`reason=effective_preflight_unit_unverified`, `start_attempted=no`.
No Docker operation or capacity evaluation occurred. [RCA #271](https://github.com/mbalbo2023/boca-socios-assistant/issues/271#issuecomment-6590959214)
reproduces the parser rejecting empty Exec arrays omitted by the official
systemd v255 renderer even with `--all`. The exact host output was not captured; neither its
omitted fields nor the full host cause are proven. The read correction requires
review and exact checks; activation remains blocked until state and policy
are established, without rerunning the failed preflight blindly.

[Later read-only inspection 41538696464](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41538696464/job/125597016052)
at 2026-11-02 19:36:40 ART reached SSH as UID10001, with private runtime and
owned user bus. The rootless socket was absent, rootful socket not writable,
and the dedicated daemon inactive/dead/result=success. It observed
MemAvailable=1015044 KiB, legacy `cpu_headroom=1.80` and PIDs UNKNOWN;
capacity remained NOT_EVALUATED. The legacy estimate is not a decision under
the reviewed CPU policy. `dockerd 29.7.2` is the binary version, not an active
Engine verification. The three fixed DB candidates were absent; global
location remains UNVERIFIED. This snapshot neither identifies the earlier
failed condition nor proves readiness to activate.

[Earlier read-only inspection 41495516709](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495516709/job/125449321031)
at 2026-11-02 14:54:42 ART found the dedicated Boca unit inactive/dead and its
private socket absent, so prerequisites remained NO_GO. It observed
MemAvailable=1020020 KiB, CPU estimate=0.27 and free PIDs=UNKNOWN;
the capacity gate was NOT_EVALUATED. These aggregate readings do not measure
free CPU or validate application capacity.
No Docker operation, install, cleanup or residue-producing attempt occurred.
DB candidates were absent only at the three fixed metadata paths; global DB
location remains UNVERIFIED. [Port check 41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298/job/125454798607)
at 2026-11-02 15:04:45 ART observed `FREE address=127.0.0.1 port=8443 reserved=no`.
This does not reserve the port or verify Engine version, capacity, listener,
tablet forwarding, rootless health or application readiness.

The baseline audit reproduced lifecycle gaps between owner shutdown, browser
startup, stop/acceptance, Telegram and restart. PR #253 integrated the
correction described below. Source tests and review do not establish host
execution. Do not rerun first-time `prepare-rootless` or use another service
to start Boca; only the guarded existing-daemon transition is permitted.

GitHub environments were inspected on 2026-11-02: both are main-only, required
reviewers are off and administrative bypass is available. Release READY is set;
deploy/read-only READY are set. Only SSH key/known-hosts secrets and the host
variable are present in deploy; BETA/BROWSER/Telegram readiness and owner
origin/subject are absent. See [settings evidence](GITHUB_SETUP.md). No bypass
or setting change is implied by this observation.

**SSH-local owner enrollment #225 / PR #229 / ADR0092 (integrated code only):**
PR #224 integrated `http://localhost:8443` at
`main=93c14ee5d939fd7d6abf56a57843c23c32b281c3`, with no certificate
requirement and no droplet effect. The proposed first-owner URL
`http://localhost:8443/activar#key=…` is **not live** and the placeholder
is not a usable credential. The #225 source can verify WebAuthn create→get
and stage only encrypted v2 ciphertext. The HTTP container is forbidden to
mount the owner volume, which holds an X25519 private recipient key.
Protected host orchestration, same-job selective deletion after success/failure
and offline `owner_bootstrap.install-staged`/`verify` are integrated.
Their host execution, private handoff of a real one-use link, an exact release
and physical Chrome/Termius testing remain separate gates. Until then,
**NO-GO** for owner activation or BETA. No web server/proxy/firewall, other
app, other port or existing droplet service may be changed; `8443` BUSY
means stop. See [ADR0092](ADR/0092-one-use-ssh-chrome-owner-enrollment.md).

The default runtime remains dormant and CI never deploys. The dedicated rootless service
was prepared in #120 and stopped in #156/41272785626; the BETA application
remains not installed/NO_GO. The protected [image release 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820)
published `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
with manifest 13086161844 for the pre-change #214 main
`8fdbec97262a525821eb87f3fbc27f1841a5d2ec`. This was registry-only,
with no droplet pull/install. Earlier releases 41301618285/#208 and
41302342233/`3ef7aff8...` are historical. The HEAD after this code change
requires a matching new release, tracked in [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
The [stop-test #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) observed `ALREADY_STOPPED
containers=not_queried data=preserved` at 03:48 ART; it did not inventory
stopped containers and future daemon state must be rechecked.
[Read-only preflight #124](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41268626135)
on `main` `213be4903669c6e88122a536ad8fee6785c997ac`, attempt 1, passed
at 2026-11-01 00:18 ART: UID10001, rootless boundary, empty namespace,
853288 KiB available memory, 8009560064 free bytes, 2902623 free inodes
and 1.60 CPU headroom. It tested the existing 0.5 CPU/256 MiB controller
contract and performed no install. It does not establish capacity for a
functional BETA with Chromium, public HTTPS access or Telegram.
[Run #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418)
(attempt1, job124718888659, source `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`)
executed prepare-rootless successfully after exact-source CI41262581358 and
scan41262581422. The apply receipt at 2026-10-31 22:49:24 ART reported
SERVICE_READY, application_database=not_accessed and application=not_installed.
The reviewed helper verified rootless/cgroup-v2-systemd/overlay2/private data
root, zero containers and an empty Boca namespace before enabling its user unit.
See the [operational receipt](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).

Only dedicated daemon configuration, unit, enablement and private Docker
bookkeeping were created. No image was released/pulled, no container, SQLite,
application/key volume or key was created, and no backup ran. Informative
capacity was 8010493952 bytes/2902936 inodes at check, then 8010489856/2902936
before apply effects and 8010072064/2902879 after; application_budget=not_checked.
These readings do not validate BETA resource capacity or causal disk usage.
Global location of any older database remains UNVERIFIED.

The earlier inspection #98 on source5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e
found the service/socket absent and DB/WAL/SHM candidate-absent only at the three
fixed paths of ADR0054. It remains historical evidence; #120 supersedes the
service state, not the limited meaning of that database inventory. No SQLite
content was opened by either operation. Do not rerun #98 or prepare-rootless:
first-time preparation must now preserve the configuration it created.

The earlier scoped diagnosis/fix work is complete. The
[current BETA authorization](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
extends the previously approved preparation to a connected private Site,
Telegram and a validated simulation BETA through the protected workflow.
Concrete identity, release and installation still require reviewed exact
candidate evidence and security gates, but the owner has already authorized
this scoped delivery. No reservation, purchase, Boca account mutation,
unreviewed migration of existing data, backup or unrelated infrastructure
operation is implied. Neither prior inspection nor first-time preparation is
a retry recipe.
See issue #45 for the current scoped decision and BETA_INTEGRATION_STATUS.md
for the source/integration cut. PR #141 separately fixed the migration function
through synthetic fixtures; merging it did not run Database.migrate on the
droplet or create a service database. ADR0053 states the WAL/concurrency limits.

## Pre-release infrastructure observation

#261 / [ADR0103](ADR/0103-pre-release-infrastructure-observation.md) integrated
`infrastructure-preflight` in the existing protected workflow. Its authorized
host execution 41537794166 failed before the attempt marker, as recorded above.
The operation's inputs remain `service=controller`,
the exact `source_sha`, and budget `1.5cpu-1024m-192pids` or
`1.75cpu-1152m-224pids`; image and release fields stay blank. It requires both
`BOCA_HOST_READONLY_ENV_READY=ready` and `BOCA_DEPLOY_ENV_READY=ready`, because
it may temporarily start the already prepared dedicated daemon.

The operation verifies the loaded unit/configuration and empty private
container metadata before starting only that daemon. It observes Engine,
cgroup delegation, empty inventory, Boca storage and the permitted loopback
port, then attempts verified restoration to stopped after the attempt marker.
An initial read-only rejection does not enter that effect/restore phase. It creates no
image, application container, volume, key or owner, and performs no Docker
deletion. A failed earlier check stays NO_GO even if restoration succeeds;
an unverified stop or lost SSH is INDETERMINADO and blocks activation/retry.
Do not use first-time `prepare-rootless` to substitute for this transition.

`BOCA_INFRA_OBSERVATION` registra únicamente metadata agregada y
validada, no consumo medido de la BETA. La política anterior exigía
1536/1792 MiB, 1.75/2 CPU y 256/288 PIDs libres más almacenamiento;
esa reserva preventiva fue introducida sin benchmark de la BETA.
**Decisión nueva del dueño [ADR0112](ADR/0112-postdeploy-resource-observation.md):**
estos valores ahora sólo son referencias de dimensionamiento;
`BOCA_INFRA_POLICY` produce `result=OBSERVED
meaning=postdeploy_measurement_required` y flags `PASS/BELOW` informativos,
sin veto por ese margen. El workflow mantiene la comprobación estricta
del recibo, SHA, inventario/puerto, transporte y parada del daemon.
Persisten los caps internos de CPU/RAM/PIDs y la protección de almacenamiento
previa/tras pulls, además de limpieza selectiva. El CPU ceiling estructural
no implica CPU libre medida; loadavg no es un gate. Medir consumo auténtico,
salud y latencia de controller/Chromium/Telegram tras instalar la BETA.

**Recibo anterior histórico:** el run #290 falló en el paso de observación
previo sin publicar valores verificables en logs comunes; la parada del daemon
SUCCESS no transforma el NO_GO en deploy. PR #273 corrige el contrato sin
reintentar #290.
### Read-only infrastructure diagnostic — RCA #268, integrated by #269

[ADR0109](ADR/0109-readonly-infrastructure-diagnostics.md) integrated
`operation=infrastructure-inspect` in the same workflow. Use the exact current
`source_sha`, `service=controller` and either
`1.5cpu-1024m-192pids` or `1.75cpu-1152m-224pids`. Image/release fields,
envelopes, capability hash and recovery run ID must be empty. Only
`BOCA_HOST_READONLY_ENV_READY=ready` is required; the operation does not use
deploy readiness to authorize effects. The selected budget validates inputs,
not capacity.

One bounded SSH call runs the existing `infrastructure-check`. There is no
attempt marker, start, stop, Docker operation, image pull, observation/policy
phase or cleanup: this path has no effect to undo. It captures bounded stdout,
stderr and exit status; the parser accepts only exact receipts or allowlisted
fixed reasons and never prints raw stderr. An exact successful check can report
stopped/prepared with capacity NOT_EVALUATED. A known rejected condition remains
NO_GO; unknown output or transport failure is INDETERMINATE and remains failed.
It neither recovers the old reason nor substitutes for a successful preflight.
The first execution, 41542349197, returned the fixed unit-verification rejection
above; it did not issue the PASS receipt. Candidate
[ADR0111](ADR/0111-typed-effective-unit-properties.md) separates six scalar
properties from typed Exec arrays read over the user bus. Empty arrays must be
explicit and `ExecStart` remains an exact single command; absence cannot stand
in for emptiness. This read correction changes no effects or capacity policy
and is not a host validation result.

[ADR0104](ADR/0104-existing-smoke-resource-observations.md) adds bounded cgroup
observations around the existing CI HTTP/SQLite, IPC/restart and offline sender
workloads. The candidate smoke ran on a disposable runner; it is not droplet
evidence. Missing counters remain `UNKNOWN`; peaks include observation overhead
and apply to the current cgroup lifetime. The sender runs after the pair stops,
so three-service concurrency is unmeasured and individual peaks must not be
summed as a simultaneous peak. See the [resource report](quality/resource-observation-2026-11-02.md).

## Protected browser lifecycle contract

This is the code contract integrated by PR #253 in `5ddfba5`, not a record of
completed host operations. Before use, verify the final frozen SHA and its
successful checks in checkpoint #45.
Use only [boca-first-deploy.yml](https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml).
`source_sha`, both image digests, release run and staged hashes must identify
the same frozen main/release; `service=controller`. No terminal work is required
from the tablet owner.

| Operation | Purpose and required state |
| --- | --- |
| `beta-browser-install` | New-only pair after owner custody; guarded start of the already prepared daemon, then capacity/identity checks and atomic staging |
| `beta-browser-status` | Read-only inspection of the existing pair/optional sender; does not start stopped resources |
| `beta-browser-start` | Resume the verified stopped daemon and same installed service IDs; no initialization, pull or recreation |
| `beta-browser-restart` | Bounded stop/start of the verified running topology; preserve data, key and owner |
| `beta-browser-acceptance` | Synthetic IPC and local HTTP acceptance, then mandatory Boca-only stop; use explicit start afterward |
| `beta-browser-telegram-start` | Create the sender only after custody and same-source one-shot proof; no implicit activation by the form |
| `beta-browser-telegram-recover` | After connectivity returns, remove only the proven failed run's sender and empty egress, then stop; never start applications or repeat a send |

The install/pair budget is `1.5cpu-1024m-192pids`. Once
`BOCA_TELEGRAM_OWNER_READY=ready`, existing browser lifecycle and dual-topology
Telegram phases declare `1.75cpu-1152m-224pids`; sender-start/recovery require
the full budget. Owner custody, inspection and standalone stop retain their
`0.5cpu-256m-64pids` input. These are declared caps, not a capacity receipt.
The pair preflight separately requires at least 1.5 GiB memory, 1.75 CPU and 256
free PIDs; a complete three-service start uses its larger reserve checks.

Before a sender attempt, prove sender/egress absent and record the current run
marker. Immediate selective cleanup runs after failure/cancellation. With SSH
loss or unverifiable cleanup, mark INDETERMINADO and stop activation. Recovery
requires `failed_telegram_run_id` from the exact completed failed/cancelled/
timed-out first attempt, with a successful attempt marker verified by GitHub.
It checks the original SHA/digests/owner and old runtime label; an inactive
daemon may be started solely to inspect/clean, never to start applications.
Unknown provenance prevents removal. Preserve all owner/key/data/Telegram
volumes and every foreign resource. A new run must not adopt old leftovers.

**Freeze main before publication and keep it frozen through all owner, install,
Telegram and recovery phases.** Merge this documentation before release. Use
checkpoint #45 for subsequent SHA/check/run receipts without further commits.
If main advances after an uncertain failure, the current-main gate blocks
recovery; a separate reviewed recovery change is required, not a substituted
SHA, bypass or blind retry. Upgrading an installed source is outside this
same-SHA lifecycle contract.

## Telegram setup before the first persistent simulation

Complete `telegram-migrate` and `telegram-prepare` with the controller/browser
stopped. These custody operations start only the dedicated daemon and end in
Boca-only stop. Verify the public receipt, then use `beta-browser-start` to
serve the panel without a sender. After passkey login, open the approved
`http://localhost:8443/telegram/configurar#recipient=…` receipt link.
This is a public-recipient template, not an issued activation URL.

The owner fills the bot token and positive private-chat ID in that private
page. Chrome encrypts locally and derives the bot ID/chat HMAC. Copy only the
three displayed outputs to their indicated destinations: encrypted envelope
into `telegram_envelope`; the two pins into environment Secrets
`BOCA_TELEGRAM_EXPECTED_BOT_ID` and `BOCA_TELEGRAM_EXPECTED_CHAT_HMAC`.
Never request token/chat plaintext in chat, Actions inputs or a terminal.
The form's success is not installation, identity verification or delivery.

**Corrección candidata P0 #315 — no desplegada:** el transporte previo
exponía el sobre cifrado/HMAC de Telegram en los argumentos SSH. El DRAFT
propone un único SSH por fase con helper+operandos en frame de stdin,
bootstrap remoto estático y secretos retirados del entorno del proceso SSH.
Sus regresiones son sintéticas y no prueban instalación, identidad real ni
recepción humana. Hasta exact-SHA CI/merge/cutover protegido, Telegram sigue
OFF. Véase [ADR0134](ADR/0134-private-telegram-pairing-discovery.md).

Stop Boca with `stop-test` before `telegram-install`; perform protected
install/verify/test with the reviewed coordinates. `telegram-test` must run
before the first persistent simulation, while the outbox is empty. Its API
receipt needs separate human delivery confirmation. The BETA acceptance probe
uses temporary SQLite in `/tmp` and does not contaminate that outbox.
The custody/test phases finish with the daemon and pair stopped. After the
approved owner-readiness setting, run `beta-browser-start` with the full
`1.75cpu-1152m-224pids` budget to resume the verified pair; only then run
`beta-browser-telegram-start`, which requires that pair already active and
does not start its daemon.
Readiness binds token, destination and source SHA: restart at the same SHA
preserves it; a future source upgrade needs a separate reviewed procedure.

## Historical preparation evidence

The previous receipts and implementation lineage below remain historical.
Their TLS or unmerged-candidate statements do not replace the current SSH-only
contract or supply missing host/tablet/Telegram evidence.

## Functional BETA preparation and final operation

Follow [BETA_DELIVERY_PLAN](BETA_DELIVERY_PLAN.md). The chosen future database
mount is `/data/boca.sqlite3` on `boca-socios_boca_data`, with a separate key.
The choice does not mean the file exists or authorize replacing storage found
later. First-install's empty-namespace assumption must be checked; an existing
installation needs a compatible reviewed procedure, not deletion by default.

For subsequent approved host work through the sole workflow, verify
service/socket/cgroups/storage capacity and separate the browser budget. Do
not reinstall Docker merely because the user unit was absent. The existing
install/diagnostic code expects the dormant controller with no exposed ports;
it must be reviewed against the functional runtime/private-access candidate.
Completing code here does not itself configure the host or deploy the BETA.

Before final publication/installation, record the concrete reviewed candidate
with exact SHA, immutable images/manifests, access, schema/data handling,
capacity, stop plan and synthetic acceptance results. All recorded gates
precede the serial Actions operation under the current authorization. Then run the real
interface acceptance with synthetic enrollment, start/stop/status, local notices
and authorized restart. Preserve data/key on failure; no backup or other project.

## Implemented prepare-rootless contract — executed once in #120

PR #150 adds prepare-rootless to the same protected workflow. It uses the
existing BOCA_DEPLOY_ENV_READY mutation gate, blank image/release inputs and
fixed controller/budget coordinates. Those coordinates do not establish an
application budget for the daemon. The helper check is read-only; Actions
rechecks current main immediately before apply, which repeats prerequisites.
Apply runs an ephemeral isolated namespace smoke before persistent writes,
creates daemon configuration/user unit exclusively, validates configuration
and effective unit provenance, starts only the dedicated user docker.service,
verifies the private rootless daemon, then enables only that unit. No package
installation, shared-daemon access or application/DB/key creation is included.

The procedure refuses existing configuration, enablement, unsafe paths or a
nonempty/inaccessible dedicated data root; it is not repair/upgrade. Capacity
receipts are informative, leaving application preflight separate. Failures
preserve files/data; after an attempted start, only that new service is stopped.
An enablement link may remain after a late failure even if stop succeeds:
report UNVERIFIED and inspect the exact Boca state before retry. Diagnostics
expose only fixed phase/exit/timeout and allowlisted unit Result/ExecMainStatus,
never stderr or journal. See ADR0058 for prerequisites and limits.

## Integrated stop-test for mandatory shutdown — issue #157

PR #165 integrated `stop-test` in
`1441d55a632d4a545b21ee7f6f2b0a4140ab2320` into the existing protected manual
workflow. It uses the same owner/main/environment/SSH/mutex gates, blank
image/release inputs and an immediate main recheck. Its reviewed helper checks
the dedicated unit/config and inventories all containers of the private
rootless daemon. Unknown containers prevent any stop; recognized Boca test
containers are stopped by exact ID, then the dedicated user unit is stopped.
Success requires no running Boca container, inactive unit, PID zero and absent
private Docker socket. The operation is idempotent when already stopped. It
preserves data/key volumes and enablement; a later reboot may start the daemon
again. CI 41269572935, scan 41269572802 and review 5726252792
cover its exact candidate. The protected manual
[run #156 / 41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626)
on main `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163` emitted
`BOCA_STOP_TEST state=STOPPED ... containers=0 data=preserved` after the
immediate main check. It stopped the dedicated daemon after preparation tests;
no BETA application had been installed. Reinspect after any reboot because
enablement was preserved.
See ADR0067.

## Protected Site custody phases — integrated, not dispatched

[PR #181](https://github.com/mbalbo2023/boca-socios-assistant/pull/181)
integrated `site-prepare`, `site-install` and `site-verify` into the same
protected manual workflow at
`9e923af56e76a04069bfad6f8ca9c68db0edd890`. Candidate
`4c8158d79a49924738b2a52573dc37cc91eccc1a` passed CI 41273068810,
scan 41273068858, disposable sealed owner-volume smoke/deploy validation
41273068811, release PR validation 41273068906 and review 5726437610. The
host job was skipped. These operations accept a reviewed release digest for
the exact main SHA; install accepts only a bounded, canonical sealed envelope
as ciphertext. They do not create the application DB/key, stage BETA Compose,
start a service or enable the Site bridge. See ADR0074.

The prior environment inspection found `BOCA_RELEASE_ENV_READY` absent.
It was subsequently set to `ready` only in `boca-image-release` without
changing its main-only branch rule. [Release #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638) succeeded and
published the digest above for the then-current main SHA; verify a matching
release for any later HEAD. No Site custody phase was dispatched. Its real
recipient key and the Site bypass/HMAC material have not been installed on
the host. The dedicated daemon was observed ALREADY_STOPPED in protected
stop-test 41282301501; recheck its state before any future use.
A successful runner smoke cannot satisfy these host gates.

PR #196 integrated the Site custody global-inventory RCA in
`2768d23dd2e9e58563a13aa80d8b76885448d020`. Candidate
`2676bd9f0cb91e4da0785b0cd149e2d33fd5810a` passed CI 41276268828,
scan 41276268931, release/deploy validation 41276268935/41276268997 and
review 5726595915. It checks the entire dedicated rootless daemon before
and after each Site effect; the test injected a foreign container at five
boundaries. No Site host phase was dispatched. See ADR0082.

## Protected served BETA and acceptance — code only

**Integrated #224 / ADR0091:** the selected droplet/tunnel origin is
`http://localhost:8443`, without a device TLS certificate or CA. The
`beta-install` package still publishes **only** host `127.0.0.1:8443` from
the dedicated Boca rootless container. It must not configure, restart, proxy,
or modify any host web server, other application or port. An occupied or
unavailable 8443 is a fail-closed **STOP**, not a reason to stop the occupant.
The historical TLS code/release receipts below document earlier candidates;
neither they nor synthetic acceptance mean an installed panel. The one-use
Chrome registration link is implemented by #229 but has not been activated.

PR #189 integrated image-side `check-beta-owner/config` without listener in
`63965b087fbd6d7a68308302bb8baf2e08975674` (candidate `b2b34a17`, CI
41274671069, scan 41274671077, release/deploy 41274671053/41274671118,
review 5726527799). These are file/identity/TLS preflights, not owner
enrollment or host configuration. See ADR0079.

PR #191 integrated a separate protected `beta-install` in
`161043f15befd5b612b71e036c9c1dead21581ce` (candidate `5265546`, CI
41275510437, scan 41275510471, release/deploy 41275510497/41275510438,
review 5726574754). It gates exact current main and successful protected
image digest, `BOCA_BETA_ENV_READY`, owner subject/origin, empty dedicated
daemon, owner-only files, key, new-only data volume, host-loopback TLS and
positive-identity rollback. Disposable runner smoke exercised both no-listener
preflights before data init. The host/publish jobs were skipped. See ADR0075.

PR #190 integrated the synthetic container TLS probe in
`64746289363741c4d85df79fa4e133b07f261efa`; PR #200 integrated protected
`beta-acceptance` in `f21b55f8cc79f9906b8ce1eff3fa1e6c152e896e`.
The latter candidate `8d629841` passed CI 41277081359, scan 41277081440,
release/deploy 41277081383/41277081431 and review 5726623269. Its PR
smoke ran the probe inside a capped disposable controller. A manual host run
would validate installed identity before/after the probe, then attempt
`stop-test` in the same job even on probe failure or main drift; success
requires a positive STOPPED receipt. No host BETA install/acceptance run has
occurred. Container-loopback tests do not prove owner tablet, Site or Telegram.
See ADR0076 and ADR0081.

PR #208 integrated `owner-prepare/install/verify` for the dedicated owner
volume, with purpose-bound ciphertext holding the physical passkey's **public**
credential and matching TLS/health material. ADR0086 defines the isolated
runner/host contract and the nonsecret receipt. Each owner phase temporarily
starts only the previously prepared, stopped Boca rootless daemon after its
unit/config/inventory proof, then requires `stop-test` in the same job even
after a failed phase; an uncertain stop remains NO-GO. This is code only:
no real owner passkey, origin, certificate, private tablet route or host
custody operation has been verified. The 41301618285 protected release is
SUCCESS for the historical #208 integration main `58f57822e95da9574c0a9d5122607616da4a024a`;
the later #214 release and the requirement for a new exact HEAD are recorded
above. Issue #209 holds
the private tablet route and first-owner ceremony. Do not set the BETA marker
or run `beta-install` from a synthetic fixture.

**Chrome passkey enrollment, issue #225 / PR #229 — integrated, not activated:** The
owner chose `http://localhost:8443` through Termius SSH forwarding (PRs
#224/#226, ADR0091), with **no HTTPS, certificates or Termux**. The PR integrated
`owner-enroll` to the same `boca-first-deploy.yml`; it cannot be executed
from a pull request. Inputs remain exact-main SHA, reviewed release run/digest,
fixed `controller`/budget and a SHA-256 **hash** of the one-use private
Chrome key (never the key/URL). The existing owner-prepare X25519 recipient
must already be prepared. A dedicated helper verifies owner volume identity,
empty Boca rootless container/network inventory, storage topology and an
unoccupied `127.0.0.1:8443` and Docker Engine version **28+** before
creating a disposable labelled Boca bridge without IP masquerading or
intercontainer traffic (not `--internal`, which blocked the published port
in the disposable runner),
named volume `boca-socios_owner_enroll_staging` and listener on **that port
only**. The web container has no owner/key/data/socket mount. After one
successful WebAuthn proof or a 900s timeout, offline `install-staged` reads
only ciphertext from the staging volume, with `--network none`; verify uses
owner read-only. The same protected job always attempts `host_cleanup.py
--enroll` after starting the stage, verifying removal of only the known
temporary container, bounded Boca bridge, volume, marker and optional newly
pulled unshared image. The persistent owner/key/data and all other resources
survive; an uncertain cleanup is NO-GO with no automatic retry. Never use
`docker prune`. The PR's disposable runner smoke is **not** a host run.
The helper only *inspects* a previously prepared owner recipient with
owner mounted read-only; it never generates an X25519 private key during
the temporary attempt. Actions rechecks current `main` **after** Chrome
proof and **before** owner decryption/import.
Disabling masquerading reduces external connectivity, but is not absolute
egress denial on every routed host; the temporary HTTP application contains
no outbound request path. The workflow validates exact network options,
the published Docker port and the local HTTP response. Do not loosen the
loopback-only host binding or perform external network probes.
No real link, private key, tablet proof, new port publication or droplet
side effect exists from this change. The [ADR0092](ADR/0092-one-use-ssh-chrome-owner-enrollment.md)
tracks the code/physical gates separately.

The historical 2026-11-01 GitHub environment inspection found no
`BOCA_RELEASE_ENV_READY`; this release marker was then enabled and release
#198 succeeded for the source SHA above. The deploy environment still lacks
`BOCA_BETA_ENV_READY`, both Telegram readiness markers, protected bot/chat
assertions, owner origin/subject and real passkey/TLS files. There is a
protected image release/digest for the source SHA above, but no host install
or private tablet route. The dedicated Boca daemon was observed ALREADY_STOPPED
in stop-test 41282301501, without a stopped-container inventory; recheck
before another operation. Do not
dispatch `beta-install`, Site phases or `beta-acceptance` until their exact
gates are satisfied. No `prepare-rootless` retry over the existing unit.

## Telegram opt-in package — no host provisioning

PR #188 integrated a separate default-off worker in
`1bdc80b7f50021227cd798e655844b157198ea93`; #194 integrated exact
Telegram container recognition for `stop-test` in
`451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`; #199 integrated sealed
bot/destination custody helper in
`a808a6455e624eea7e1eeb7bedd10f3ab63f9a7c`. #203 integrated protected
post-install schema0007 and sealed custody phases in
`487995ca57282e2947d977333e72bd10775fbb98`. #204 integrated a protected
one-shot Bot API identity/send test in `5cb8ce17715f571979a2ea3bb092da9b470f362d`.
Exact local/hosted evidence and reviews are in
[the integration status](BETA_INTEGRATION_STATUS.md).
No bot,
destination, schema0007 migration, private volume, worker or send has been
provisioned on the droplet. The new stop-test code itself has not run on the
host. See ADR0078/0080/0083/0084/0085 and issue #168.

## Implemented first-install contract — not executed

The integrated `boca-first-deploy.yml` provides a manual, environment-gated
installation path. Its read-only inspection has run; first-install has not.
`pull_request` only runs tests and the isolation policy, with no host credentials. A manual dispatch is allowed only from
the exact current `main` commit by the repository owner after agent technical
review, green exact-SHA checks and a recorded gate receipt for the commit,
complete GHCR digest, successful release run, `controller` and resource
budget. The protected `boca-first-deploy` GitHub environment must restrict
deployment to `main` and contain only Boca-specific credentials/variables.
The current owner authorization in #45 includes this simulation BETA delivery;
the ruleset still requires the candidate review and exact checks. Readiness
alone does not prove environment protection or operational success.
The manual job uses separate fail-closed environment variables: only
`BOCA_HOST_READONLY_ENV_READY=ready` can enable `inspect-prerequisites`,
`port-check` or `preflight`, while `BOCA_DEPLOY_ENV_READY=ready` is required for prepare-rootless,
first-install, diagnostic or `stop-test`. READONLY was set before #66; DEPLOY was added only
to the protected environment for #120, without changing secrets/protections.
RELEASE was not enabled by that preparation. Revalidate scope/values before
another operation; a readiness marker does not itself authorize it. Read-only
choices and prepare-rootless require blank image/release inputs; first-install
and diagnostic require both. See ADR0046 and ADR0058.

`port-check` probes only the Boca host's fixed IPv4 `127.0.0.1:8443` with a
dedicated-UID bind and immediate close. It returns an allowlisted FREE/BUSY/
ERROR receipt, does not enumerate or connect to a process, and runs without
the rootless daemon. The BETA install workflow repeats this check just before
app/key effects. A FREE result is instantaneous and does not reserve the port;
the later Docker binding/local-HTTP probe and real tablet access have separate gates.
See ADR0087 and issue #211.

The later protected [run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on exact `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`, attempt 1,
passed `BOCA_PORT_CHECK state=FREE address=127.0.0.1 port=8443 reserved=no`.
This supersedes only the preceding absence of a host port observation; it did
not start Boca. The owner selected a private local tablet forward and kept
Site decommission pending. ADR0088's old candidate origin
`https://localhost:8443` is superseded for the SSH-only BETA by
`http://localhost:8443` in ADR0091, without device certificates or CA.
Owner preparation requires its specific protected scope and exact release;
owner enrollment then proves the passkey through the physical tablet route.
Do not install the BETA before that proof and offline custody verification. The single owner
credential needs separate Android/iOS interoperability proof. No terminal
operation by the owner replaces the gated Actions host workflow.

## First-owner registration on Chrome — implemented, activation pending

The old #215/ADR0089 one-use **device-local** Python/TLS emitter is retained
for historical audit only; **do not ask the owner to run it**. Per #223/ADR0091,
the planned Chrome flow must be served by a temporary Boca-only registration
service on the *same* droplet host loopback 8443 through Termius SSH. The
owner wants one private URL with a short-lived 256-bit one-use key. The endpoint
is integrated but not served on the host. Its contract prevents token exposure in publicly
accessible GitHub Actions logs, workflow dispatch history, PRs or screenshots;
authorization must be consumed atomically before creating a discoverable
WebAuthn passkey, and the physical create→get ceremony must verify the user.
Only the public credential ID/ES256 key may persist in Boca owner custody.
The private passkey stays in the chosen Android credential manager; it is not
a permanent browser cookie. **Este párrafo conserva la ceremonia histórica**:
Tincho confirmó el 04/11/2026 que Samsung Chrome + Termius + passkey ya permite
ingresar al controller-only. Su cookie aún tiene expiración legacy de 15
minutos de inactividad/8 horas y se revoca con restart. En el **candidato DRAFT
#319 / Opción B #321/#322** la cookie será HttpOnly/Secure/SameSite=Strict,
renovable hasta el máximo de Chrome de 400 días, con autorización singleton
persistente en SQLite lateral; esto **no** se ha instalado físicamente.
Persistencia tras reinicio, Google Password Manager e iOS son gates físicos.
SSH encrypts the remote path, **not** an app-to-localhost connection
inside Android; do not claim general HTTPS-equivalent protection.

The activation sequence is: finish RCA #271 review/integration and exact checks;
verify the unit with read-only inspection, then complete the image-free
infrastructure preflight and evaluate its observations; approve/publish the exact dual release;
verify image-specific capacity/isolation and the private token handoff; run `owner-prepare`,
then `owner-enroll` with real Chrome create→get; verify offline custody and
selective cleanup; then install the BETA and prove login/restart/resume.
Owner enrollment precedes installation because the BETA requires its credential.
Only the URL-key SHA-256 enters Actions, never the bearer. Prepare the tablet
forward before the 900-second enrollment window. Do not touch a shared web server,
create a public listener, add a new host port, or run another workload's Docker
command. Failed Boca BETA staging still invokes the immediate selective cleanup
of ADR0090, preserving all persistent and uncertain volumes.

The host prerequisite is a dedicated `boca-deploy` identity with UID
10001, dedicated rootless Docker, Python 3.10+, and an already provisioned empty
`/srv/boca-socios` directory owned by that UID with mode 0700. The SSH host
identity must be independently verified and pinned in the environment's
known-hosts secret; the workflow has no `ssh-keyscan` fallback. First-install
does not provision these prerequisites; prepare-rootless is the separate
reviewed operation described above. Confirm the GHCR package is accessible by the host
without placing registry credentials on it. If any prerequisite is absent,
stop before dispatch and record NO-GO; do not improvise a host change.

**Security correction #78:** Docker access must be to a dedicated rootless
socket at `/run/user/10001/docker.sock`; access to the shared rootful daemon
is NO-GO. The helper checks real/effective UID/GID before private paths, pins
that endpoint, strips inherited context/TLS client settings and rejects
missing rootless/cgroup evidence before any first-install or diagnostic phase.
**Correction #80:** The key is generated inside a separate Boca-only volume
under the container UID map and mounted read-only by the UID 10001 controller.
No host file secret or 0444 permission is used. An isolated rootless trial
must still prove key access, delegated CPU/memory/PID limits, host account
privileges and restart/retention. Do not dispatch merely because the runner
smoke passes. See [ADR 0033](ADR/0033-rootless-daemon-boundary.md) and
[ADR 0034](ADR/0034-rootless-key-custody.md).

For first-install/diagnostic, the workflow validates dispatch inputs and the
successful manual image
release run for the same current `main` SHA. It downloads that run's immutable
manifest and requires the selected image digest, SHA and run ID to match
before opening SSH; an absent or expired artifact or any rerun attempt blocks
installation. See [ADR 0036](ADR/0036-release-digest-binding.md). It validates
the resolved Compose contract on the runner, reads aggregate host capacity
and Boca-only resource names, stages and hashes one Compose file, then
validates the host-resolved model before pulling the exact digest. It then
rechecks the Compose hash, rootless Docker backend/path/device and free
bytes/inodes on staging and Docker storage **after the pull**, before creating
an owner-only key once inside a separate rootless volume and starting the
simulation-only controller.
Before reporting success, the helper reuses the read-only diagnostic contract
to check the actual container, image, dormant engine, resource limits, both
mounts, network, capabilities, tmpfs, effective cgroup v2 limits and key
metadata. It measures both capacities again before the PASS receipt. Startup
or postflight failure attempts to stop only the Boca controller and preserves
the key and both volumes for separate diagnosis. A failed stop leaves the
controller state unverified: `BOCA_ROLLBACK_UNVERIFIED`, NO-GO and Boca-only
inventory before retry. An
existing Boca key, container, volume, network or staged file blocks a fresh
installation; this flow is not recovery or upgrade. The CPU snapshot remains
an estimate and capacity cannot be reserved against another actor. See
[ADR 0042](ADR/0042-effective-runtime-and-post-pull-capacity.md). An external
source failure is reported by Actions as an alert, not a deploy blocker for
the simulation-only controller.

After a failed first-install, the same Actions job attempts selective cleanup
only if the read-only preflight, current-main recheck and staging marker passed.
It removes an exact unreferenced image without force if no container uses it,
even when key/data volumes remain. It removes the matching staged Compose file
only when no Boca container, volume or network exists; otherwise it retains
that file and all volumes/networks and reports `PARTIAL` or `RETAINED`. The
bounded receipt records staging and rootless Docker data free space/inodes
before and after, plus whether they share a filesystem. Virtual image size
and observed free-space changes are not proof of causal reclamation. Unknown
storage backends or paths stop before deletion. A failed or unverified cleanup
reports `NO_GO INDETERMINADO`: a partial deletion may have occurred, and a
Boca-only inventory is required before any retry. The original install
failure remains failed. See [ADR 0039](ADR/0039-boca-failed-install-cleanup.md).

**Failed served BETA install — #219/PR #220 integrated in code, no host run:**
the same protected Actions workflow adds a bounded cleanup step immediately
after the existing `beta-rollback` failure step. Only after the BETA staging
marker does it check exact Docker rootless identity, SHA/digest/Compose hash,
entire dedicated-daemon container inventory, controller UID/labels/mounts,
private network attachments and named owner/key/data volumes. It may stop
and discard only that exact failed BETA controller (without removing volumes),
its unused private network, its unshared digest image and its exact staged
`compose.beta.yaml`; it confirms each removal and unchanged volume inventory.
The protected owner/key/data volumes remain deliberately, even when freshly
created, because their contents cannot be assumed disposable. The original
deploy still fails. A changed/unknown artifact, unreachable daemon or
mid-cleanup failure yields `NO_GO INDETERMINADO`, an inventory gate and no
automatic retry. Cancelling/losing the Actions runner can prevent the hook;
no unconditional zero-residue guarantee is claimed. See
[ADR 0090](ADR/0090-immediate-failed-beta-deploy-cleanup.md). No host cleanup
was performed merely by adding this code.

## Read-only diagnostic under demand (issue #68)

The same protected workflow provides a manual `diagnostic` choice for a Boca
controller already installed from the exact current `main` SHA. With the
concrete operation scope approved, its recorded gates and environment restrictions
must match the exact operation, SHA, digest, service and budget. It checks
only Boca Compose, key **metadata**, immutable image identity, resource
limits, effective cgroup values, one Boca-only network, security flags,
tmpfs, both mounts, health and `BOCA_ENGINE_MODE=off`. Fixed in-container
probes check key metadata and cgroup files without printing key bytes. It
never reads the key value or database rows, starts the motor, visits the site
or changes a container.
The run summary contains only bounded status and immutable coordinates. A
mismatch is NO-GO and requires diagnosis; it is not a reason to retry the
first install or alter another workload. The helper checks real/effective
UID/GID before private metadata and pins rootless Docker transport. It must
remain uninvoked until the environment, identity and host prerequisites are
verified under the objective gates. No operation=diagnostic of an installed
controller has run; prerequisite/file inspections have.

## Implemented read-only host preflight — executed in #124

Before an image release or first install, the same protected manual workflow
can check the Boca rootless socket, cgroup delegation, dedicated identity,
empty Boca namespace and aggregate capacity with `operation=preflight`. Its
image and release-run fields must be blank. This operation has no stage,
pull, key, volume, container or site effect and is unavailable on PRs. It
requires the protected environment and pinned SSH identity. Prerequisite
inspection ran before #120. The stricter daemon preflight subsequently passed
in #124/41268626135 with the existing controller budget. Its success does not
validate a different Compose budget or the final functional candidate. See
[ADR 0035](ADR/0035-readonly-host-preflight.md).

## Executed prerequisite inspection and its limits

The same manual workflow provides `operation=inspect-prerequisites`, with blank
image and release-run fields. #140 added fixed-path DB/WAL/SHM metadata receipts
without opening SQLite or file contents; ADR0054 defines their narrow scope. It checks socket and cgroup **metadata as UID
10001**, differentiating `absent` from `unavailable`, without running Docker
or altering the host. A failed job reports unproven prerequisites; a metadata
candidate is not proof that a Docker daemon is rootless or healthy. The legacy
`preflight` needs an active daemon and checks the dormant controller budget.
The #261 implementation adds the separately gated pre-release operation described above;
neither metadata inspection nor that operation replaces the final
image/topology-specific installation preflight.
The environment must first be verified and marked ready as an **environment**
(pinned identity and main-only branch rule), independently
of the daemon's readiness. See [ADR 0037](ADR/0037-host-prerequisite-inspection.md).
That initial verification enabled only `BOCA_HOST_READONLY_ENV_READY` for the first
inspection, scoped to the protected `boca-first-deploy` environment after
checking no repository-level variable of that name exists; the shell cannot
prove variable scope. That read-only authorization did not permit setting
`BOCA_DEPLOY_ENV_READY` or `BOCA_RELEASE_ENV_READY`. Subsequently, the separately
approved preparation scope enabled `BOCA_DEPLOY_ENV_READY=ready` in that
protected environment for run #120. `BOCA_RELEASE_ENV_READY` was enabled later for release #198; the deployment
marker does not itself approve application installation.
A successful metadata inspection
permits considering the stricter read-only `preflight`; it is not host approval.

The manual host workflow rejects reruns and verifies the current `main` ref
through the GitHub API before SSH. First installation repeats that check
before staging Compose and again immediately before applying the reviewed
image; the host helper refuses a real/effective UID or GID mismatch before
private-path or Docker checks. A queued
run whose source SHA is no longer current fails closed. These controls do
not prove the SSH account has no other privileged route on the host.
The read-only capacity gate checks free bytes and inodes separately on the
Boca staging directory and the dedicated rootless daemon's verified
`DockerRootDir` beneath the private Boca home. Unknown storage location,
ownership or available capacity is NO-GO; a healthy staging filesystem alone
cannot establish that image storage has headroom.

## Configured isolated deployment layout — not evidence of host resources

| Item | Boca project | Unrelated workloads |
| --- | --- | --- |
| Repository | mbalbo2023/boca-socios-assistant | Existing repos, untouched |
| Compose project | boca-socios | Unknown existing names, never inspect destructively |
| Directory | Dedicated Boca-owned path after gated Actions preflight | No shared subtree |
| Database | Boca-only named volume | No shared database |
| Network | Boca-only bridge | No shared network |
| Secrets | Boca-only key volume, separate from DB | No copied/reused keys |
| Image | Boca-only tag + digest | No reused images |
| Host ports | None in dormant model; BETA only `127.0.0.1:8443` | None altered |
| CPU/RAM controller | 0.5 vCPU / 256 MiB | Existing capacity protected |
| Deployment lock | Boca-specific | Never invoke another project's deployment lock |

## Gate before any future live Docker deployment

1. Present infrastructure/business options and a recommendation; obtain owner
   approval for the concrete scope. Record the exact current commit SHA,
   immutable image digest for an install, Compose service, CPU/RAM/disk budget
   and operation before dispatch. A merge never deploys by itself.
2. Controlled GitHub Actions environment, main-only branch restriction,
   dedicated SSH identity and pinned host key. Technical checks do not replace
   the scope approval above.
3. Check spare host disk/inodes/CPU/memory and existing service health using
   non-mutating observations. If capacity is insufficient: NO_GO.
4. Confirm Compose project is boca-socios; no host mounts, Docker socket,
   broad privileges or common secrets/volumes/networks. The dormant package
   publishes no port; the approved served BETA binds only reviewed
   `127.0.0.1:8443`, never a wildcard or public interface.
5. Build once in CI, scan and publish image by digest. Deploy exact digest,
   never rebuild on the production host.
6. Serialize deployment with a Boca-only lock, never parallel retry.
7. Record Boca-only pre/post health and disk/inode capacity; never touch or
   stop an existing workload or enumerate unrelated services destructively.
8. After every success **and** failure: inventory the Boca attempt through the
   same protected Actions workflow, run bounded selective cleanup and verify
   before/after disk/inodes and resource IDs. On failure, first compensate/stop
   only the exact Boca attempt, preserving the original failed result. On
   success, remove positively identified obsolete Boca images only if no
   container references them, plus disposable Boca staging/network remnants.
   Retain key/data volumes and uncertain resources. No destructive Docker
   prune, blanket compose down, or volume deletion. An unverified postflight
   cleanup leaves NO_GO/INDETERMINATE even when the app started successfully.
9. Diagnose any external-source failure via bounded read-only Actions before
   proposing a new deploy. Report green/yellow/red/unknown with timestamp;
   source failure is an alert, not a NO_GO for the simulation-only controller.
   A demonstrated code defect may be fixed in a new PR. Security, image,
   capacity and isolation gates remain strict.

## Explicitly prohibited

docker system prune, docker volume prune, mass cleanup, restarting a shared
Docker daemon, reboot, host-wide network changes, shared Compose files, altering
other services' ports or workflows, disabling host timers, publishing new
ports without approval and production SSH outside the owner-approved
Actions workflow.


## R76 — Investigación previa al Cutover (06/11/2026 ART)

**No despachar Cutover A mientras el estado físico esté indeterminado.**
El preflight worker [#42329475083](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329475083)
falló en limpieza; el observador histórico de APPLY
[#42329673385](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42329673385)
no recuperó inventario. El release nuevo existe, pero no fue instalado.

La ruta candidata `cutover-a-worker-inspect` es **solo lectura y acotada
únicamente al intento #42329475083** (no contiene bloqueo técnico de replay;
la operación se despacha puntualmente). Tras fusionar el PR y comprobar
CI, se ejecuta en la misma GitHub Action protegida con `service=controller`,
`resource_budget=1.5cpu-1024m-192pids`, `protected_action_context=42329475083`,
`legacy_controller_id=27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`,
`legacy_source_sha=cabce9f1e452e63ded115f447559a358dc0f4d1b`,
`legacy_image_ref=ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59`.
Todos los demás campos técnicos, incluso `source_sha`, se dejan vacíos.
No requiere comandos de terminal, PIN, credenciales, nueva sesión Chrome ni
autorización de GO de Cutover. Su recibo `READ_ONLY_NO_GO` **no habilita retry**:
sirve exclusivamente para decidir el fix-forward a partir de identidades
concretas; ver [ADR0187](ADR/0187-failed-worker-preflight-readonly-diagnosis.md).

