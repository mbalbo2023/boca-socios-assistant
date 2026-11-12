# ADR 0249 — R246: prueba V2 del par instalado sucesivo

Fecha: 12-NOV-2026. Estado: contrato local **NO_GO / NO WIRED**; pendiente revisión e integración futura. Fuente de continuidad: issue [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417), R245 ADR0248, R188 ADR0238 y contrato de actualización ADR0240.

## RCA concreto

El testigo R188 V1 (`host_boca_retained_resources.py`) contiene como constantes el SHA, `attempt` y los dos CIDs de R186. Es correcto para preservar la **procedencia histórica** del volumen IPC, el volumen SITE y la red egress, pero **es incorrecto reutilizarlo como observador del par instalado actual** después de una actualización. Una secuencia `R186 → B → C` cambia los CIDs, SHA y `attempt` de controller/worker, mientras los recursos persistentes conservan sus etiquetas de **creación original**.

Además, `download_authenticated_release` valida que el SHA liberado sea el `main` **actual**, apropiado para la publicación del objetivo, pero insuficiente para autenticar el **release anterior** cuando `main` ya avanzó. No se debe suprimir la comprobación de `main` para los nuevos releases ni considerar etiquetas OCI suficientes para autenticar un release histórico.

## Decisión y perímetro exacto

Se agrega el módulo independiente `src/boca_socios/host_boca_current_pair_v2.py`, sin reemplazar V1 ni modificar Actions, R245, puertos, rootless, la migración histórica, el worker ni la operación de host. Una invocación pura/injectable `authenticate_current_pair_v2` exige tres pruebas **separadas**:

1. **Par actual y procedencia de su observación**: el receipt V1 dinámico de `host_boca_pair_observe` debe provenir de un nuevo run READ_ONLY autorizado de `.github/workflows/boca-first-deploy.yml`. Se delega a `host_boca_upgrade_observation_bridge.authenticate_runner_observation` (run `main`, actor, workflow, step list, run-attempt 1, ZIP digest/único miembro, doble comprobación, frescura 48 h). Luego se vinculan exactamente los CIDs, image IDs, SHA y `attempt` a `PairCoordinates` del upgrade considerado.
2. **Publicación anterior independiente**: el release del **SHA anterior** se valida contra el run histórico `Boca image release` (`run_attempt=1`, dueño, workflow, job/steps) y sus dos ZIPs autenticados. Se reutilizan `_verify_release_job`, `_release_artifact`, `validate_manifest`, `validate_browser_manifest` y la doble lectura de metadata de `host_boca_upgrade_release_auth`; no se exige que el commit anterior siga siendo `main` hoy. Ambos digest de imágenes deben coincidir con los observados físicamente en el receipt del par. Tras estas descargas se vuelve a verificar el `main` **actual**, para impedir un cambio de HEAD entre la observación y la terminación del comprobante anterior.
3. **Custodia original de recursos**: R188 V1 se sigue autenticando **únicamente** como semilla histórica mediante `verify_custody_seed`. Sus intentos creadores, inodes y network ID se exponen en el envelope V2, sin comparar `historical_installed_source_sha`/`historical_install_attempt` contra el par B o C. Los recursos deben ser recapturados de nuevo bajo lease física antes de cualquier actuación.

El resultado es `BOCA_CURRENT_PAIR_V2` con `schema=2`, campos allowlisted, JSON canónico, detección de claves duplicadas, límites de bytes, coordenadas/huellas hex exactas y checksum de integridad (solo detecta corrupción: **no es firma**). Son constantes las negaciones `read_only=true`, `observer_writes=0`, `foreign_resources_touched=0`, `apply_authorized=false` y `requires_fresh_same_lease_reproof=true`. El parser `verify_current_pair_v2` valida estructura e integridad, **no** autentica por sí mismo origen GitHub. No se introduce CLI, token, red ni fallback que acepte JSON aportado por el usuario.

## Pruebas TDD y casos excluidos

- RED: `pytest` falla por módulo ausente antes de implementar V2.
- GREEN: 17 casos R246 y 125 casos focalizados en releases, observación y custodia.
- A→B: SHA `b…`, attempt `44100000011`, CIDs distintos; origen histórico R186 constante.
- B→C: SHA `c…`, attempt `44300000011`, CIDs distintos del primero; `previous_release_run` equivale al `target_release_run` de A→B; custodia R188 **idéntica**.
- Un receipt del par A presentado como par B es rechazado. Un release A no valida el par B **incluso si la observación vigente de B y los checksums ZIP forjados son internamente consistentes**. Se rechazan metadatos de release con conclusión fallida, rerun, source ajeno, workflow ajeno, step fallido, ZIP expirado, digest alterado, padres cruzados o bytes alterados; también CIDs distintos al plan, R188 no autenticado, JSON V2 incompleto, autorización falsa convertida a verdadera con checksum recalculado, claves adicionales, duplicados y residuos de bytes.
- El test de frontera demuestra expresamente que un atacante puede cambiar un SHA y recalcular el checksum **sin engañar a ningún autenticador**: `verify_current_pair_v2` admite tal JSON como estructura, pero solo `authenticate_current_pair_v2` con API autenticada puede afirmar su procedencia; en todos los casos `apply_authorized=false`.
- La metadata `main` del observer se autentica y debe coincidir con la nueva fuente; que `main` ya no sea la fuente anterior es **esperado**. Se rechaza también una alteración del `main` mientras se descargan los ZIPs de la publicación previa.

## Límites reales; no confundir código verificado con droplet GREEN

- El `EvidenceAuthenticator` para una observación R188 auténtica sigue siendo una frontera externa: el run histórico R189 no posee un ZIP verificable recuperable en el transporte revisado. No se inventa un artefacto a partir del step summary; sin custodio autenticado el resultado siempre es NO_GO.
- No existe aún un runner productivo que escriba/proteja el envelope V2 ni una integración effectful bajo misma lease. Un objecto de prueba fabricado por un fake GitHub *solo prueba el contrato*.
- La procedencia de release anterior **no equivale** a prueba de que ese release fue efectivamente instalado; la vinculación con el systemd binding, journal persistente, SQLite, CIDs y recursos inmutables debe comprobarse con nueva captura física bajo la lease.
- La procedencia se basa en autenticación GitHub API, run protegido y hashes ZIP/manifiesto; **no** afirma que exista una firma criptográfica nueva del par. `now` es exclusivamente un reloj inyectado para pruebas sintéticas; el runner real debe omitirlo, nunca recibirlo como input del workflow o del usuario.
- El puente histórico `host_boca_upgrade_same_lease._custody_matches` compara el `installed_source_sha`/`installation_attempt` del R188 con el par actual; después de la primera actualización esa igualdad es imposible y requiere otra revisión independiente, sin alterar R188. Asimismo el requisito de `requires_persistent_receipt=False` mantiene deshabilitado el actor sucesor.
- El enlace actual de R188, la identidad rootless Boca y la restricción de limpieza exclusiva Boca se mantienen intactos; no ejecutar migración R186 ni comprar o reservar entradas reales. No modificar Porota ni otros Docker.

## Camino de integración futura

1. Revisión ajena del módulo/tests R246 y un único PR separado del R245. Reconciliar el SHA actual y las instrucciones de `AGENTS.md` antes de publicar.
2. Elegir y probar un transporte efectivamente autenticado de R188, o una semilla durable firmada derivada de esa captura sin elevar step summaries a evidencia.
3. Corregir el puente de same-lease para aceptar `historical_creator_pins` como historia y `current_pair` como identidad cambiante; mantener estrictos los CIDs del plan, la procedencia del release anterior y la comprobación doble de recursos.
4. Reconciliar observación del par **fresca** después de cada upgrade sucesivo, release nuevo autenticado con SHA exacto, nuevo journal/binding y cleanup V2. Pasar tests de dos upgrades + política + revisión.
5. Recién entonces invocar el procedimiento protegido existente para lectura física y, si hay GO independiente, una sola promoción; documentar recibos y RCA en issue #417. No afirmar deploy físico a partir de esta prueba de laboratorio.
