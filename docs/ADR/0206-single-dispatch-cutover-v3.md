# ADR0206 — Cutover V3: un despacho, sin GO_B manual

Fecha: 2026-11-07 ART. Owner: #417; continuidad #45. Estado: CODE_ONLY.

## Decisión explícita del propietario

Se abandona para Cutover el circuito PREPARE→copiar hash en Environment→APPLY.
`cutover-a-apply` en Boca first deploy pasa a significar una transacción
SIMULATION_ONLY autorizada por un único dispatch autenticado del propietario.
No se solicitan emails, códigos, hashes ni IDs PREPARE manuales. No es un GO
independiente generado automáticamente: se elimina conscientemente esa segunda
aprobación. Una identidad GitHub autenticada no prueba por sí misma clic humano
frente a uso autorizado de API; no afirmamos esa garantía.

La inspección read-only de Settings comunicada por el agente coordinador en
2026-11-07 ART observó Environment `boca-first-deploy` sin required reviewers,
wait timer 0 y rama autorizada `main`. No se modificó esa configuración. El
Environment y sus secretos siguen siendo la frontera del job. Si su protección
cambia, respetar el control real; nunca autoaprobarlo ni deshabilitarlo.

## Alternativas y alcance

Se eligió reutilizar el selector y backend Cutover existente: evita duplicar
las rutas de discovery, inventario, lease y rollback. Un nuevo workflow/alias
duplicado o un nuevo motor Docker no son necesarios. Dejar GO_B vacío o volver
al token v1 no sirve: v1 no exige el receipt detallado de cleanup que V3 necesita.
Official-import/lifecycle/Telegram no cambian. Conservamos parsers históricos
v1/v2 para evidencia y tests, pero el workflow Cutover no puede entrar por ellos.

## Admisión y binding

El formulario requiere `operation=cutover-a-apply`, `service=controller` y
ningún pin/contexto técnico. V3 fija el presupuesto revisado 1.5cpu/1024m/192pids;
admite el default histórico del formulario o esa opción, rechaza otra.
Se verifican evento manual, repo/workflow/ref exactos, actor y triggering_actor
propietarios, run_attempt=1, run actual in_progress y main igual a github.sha.
PR0 y quality-and-tests/image-build SUCCESS del SHA son obligatorios, ligados
por check_suite.id al único run auténtico de ci.yml, push/main, attempt1 y
SUCCESS de esa fuente; otro workflow con los mismos nombres no los sustituye.
El historial paginado completo del workflow para ese SHA debe tener exactamente
un `BOCA-SIMULATION-DEPLOY-V3`, el run actual. Un segundo despacho o rerun falla.

Discovery auténtico existente resuelve una release dual inequívoca y sus
manifests controller/browser del mismo source/run, además de release/Compose
históricos y CID legacy observado. Se verifican todos los manifests, hashes,
ZIP memfd/Option B y owner. El digest V3 es una vinculación de integridad de
esos bytes con el run, con dominio distinto del antiguo GO; no una aprobación.
Main, PR0, checks, run e historial se refrescan inmediatamente antes del efecto.

## Host y aceptación física

Un entrypoint `cutover-a-dispatch-v3` sólo admite tokens v3 y su binding V3.
No acepta tokens v1/v2 ni PREPARE IDs. Una única transacción reutiliza el backend
reviewed con lease Boca, rootless UID10001, intent O_EXCL/fsync antes de efectos,
atestación legacy, guardas stage/storage/cgroups/seccomp, volúmenes protegidos,
passkey y binding exclusivo 127.0.0.1:8443. Nunca toca Porota u otra carga.

V3 exige cleanup detallado aunque `prepare_run_id` sea nulo. El parser recibe
exactamente una observación READY producida por el host y coincidente con el
plan completo, un ACK terminal del run/SHA y una línea POSTFLIGHT validada.
No acepta ruido extra, segunda observación, CID distinto o cleanup incompleto.
Se conserva el resultado durable, la limpieza acotada en mismo lease y la
compensación conservadora antes del retiro irreversible. No se usa prune global.
El stdout acotado se valida en el runner y se conserva el terminal en el host;
no se promete un artifact Actions de Cutover que el workflow no sube.
Runner/SSH perdido, cancelación, no ACK o cleanup incierto = NO_GO/INDETERMINATE;
`if:always` no inventa un cleanup. No hay retry automático ni reutilización del
run. Un nuevo SHA no autoriza saltar un incidente pendiente: exige inventario
fresco y resolución/revisión en #417/#45. No real login, navegación ni tickets.

## Pruebas y límites

TDD: gate dispatch rechazó inicialmente por implementación ausente; matriz
owner/main/attempt/replay/PR0/checks/input deriva binding V3 sin GO_B. Protocolo
v3 se probó RED antes de introducir la versión; tests usan `_cutover_observe`
real con fronteras físicas sintéticas, CLI real y parser runner real para
READY→ACK→POSTFLIGHT. Falta de cleanup o manipulación sigue NO_GO.
La suite conserva tests históricos v1/v2; se actualizan exclusivamente sus
expectativas del wiring Cutover ya sustituido. Ningún test local prueba deploy.
CI exact-SHA, release dual nueva y evidencia física siguen pendientes antes
de aceptación. Esta ADR no afirma que #417/R99 esté resuelto.

## Enmienda R140 — CI reejecutado por el propietario

La exigencia histórica `run_attempt=1` del **CI** se reemplaza por la admisión
estricta de `run_attempt=1` o de un único reintento `2` del mismo run
`ci.yml` `push/main` y SHA con último estado SUCCESS,
suite y checks `filter=latest` autenticados; un reintento exige
`triggering_actor=mbalbo2023`. Consultar [ADR0228](0228-r140-ci-rerun-provenance.md).
El intento **del Cutover** debe continuar siendo exactamente 1, único y
autenticado. Ninguna enmienda supone que la BETA está instalada.
