# ADR0278 — R258: lectura PREDEPLOY de titularidad rootless desde Boca Actions

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** CODE_ONLY;
**no integrado, no ejecutado; DEPLOY NO_GO**.

## Contexto y RCA

La observación SQLite del intento protegido
[#43350432873](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350432873)
probó continuidad del inode, no titularidad real de `subuid/subgid`. El
atestador de [ADR0275](0275-r255-rootless-mapped-boca-inode-custody.md)
compara mapas de `/proc/<PID>/{uid,gid}_map` con tres inodes Boca, pero su
función de postflight necesita `PostflightExpected`, una expectativa construida
con cleanup V2 `SUCCESS` verdadero del intento. La instalación histórica
R186 carece de ese éxito; **no se puede reconstruirlo o fingirlo para obtener
`VERIFIED_MAPPED` final**.

El recurso preflight usado en la primera lectura R258 se seleccionó como
`0.5cpu-256m-64pids`; esa selección disparó un rechazo antes de SSH. Este
workflow fija exclusivamente para la nueva opción el presupuesto
`1.5cpu-1024m-192pids`, evitando que el valor predeterminado del formulario
introduzca ese mismo rechazo. Es un arreglo de admisión en código, no una
observación física posterior.

## Decisión técnica: evidencia preliminar sin capacidad de instalar

Se añade una elección explícita `boca-rootless-mapping-observe` en el **único**
workflow manual protegido `boca-first-deploy.yml`, nunca otro workflow,
despacho automático, script remoto genérico ni canal SSH adicional.

- Sólo `workflow_dispatch` del repositorio, rama `main`, titular y Environment
  `boca-first-deploy`. Conserva la exclusión de concurrencia global del host.
- `GITHUB_SHA` del `main` exacto, sin SHA, digest, ID de contenedor, PID, ruta,
  URL, autorización passkey, credencial ni parámetro histórico suministrado.
  Revalida el ref remoto `main` antes de SSH.
- Requiere la entrada de host autenticada `host_boca_rootless_mapping_cli.py`
  y el ZIP determinista `--rootless-mapped-observe`; si falta cualquiera, el
  runner aborta **antes** del SSH. El bootstrap acepta sólo
  `boca-rootless-mapping-observe <GITHUB_RUN_ID>`, digest SHA-256 autenticado,
  argumentos fijos y un solo stream de código empaquetado. No se permite
  `sudo`, comandos Docker mutantes, sidecars, backups ni otras aplicaciones.
- El productor R259 separado debe obtener el par y binding instalados de
  observadores auténticos, abrir el **lease Boca preexistente sin `O_CREAT`**,
  comprobar su exclusividad hasta finalizar, verificar volúmenes y mapas
  reales e imprimir **sólo metadatos**. Si el lease no existe o cualquier
  identidad cambia, devuelve `NO_GO`. Adquirir o verificar un lease no
  autoriza un APPLY.
- El runner acepta como evidencia preliminar únicamente una línea canónica
  `BOCA_ROOTLESS_MAPPING ` con `schema=1`, `attempt_id` exacto del run,
  `stage=PREDEPLOY`, `state=PRELIMINARY_PREDEPLOY`, `lease_verified=true`,
  `observer_writes=0`, `foreign_resources_touched=0` y
  `cutover_authorized=false`. El verificador local R259 debe rechazar
  formatos, campos o valores desconocidos, varias líneas, IDs privados y
  estados finales. El resumen incluye el SHA-256 de la línea canónica
  verificada, ligado al `attempt_id`, y no expone el contenido remoto bruto.
  La salida `NO_GO` o una conexión SSH incompleta deja el job rojo.

Una Action verde de esta operación probaría **sólo la lectura física
PREDEPLOY acotada a Boca**, no cleanup, cambio de imágenes, instalación,
postflight, aceptación passkey ni el mapeo **posterior** al deploy. El resumen
de Actions mantiene `cutover=NO_GO postflight=UNVERIFIED` incluso si la
observación preliminar es válida.

## Dependencias de integración e integridad

Esta rama contiene exclusivamente el selector/admisión/SSH del workflow,
`tests/test_r258_rootless_mapping_workflow.py` y este ADR. No implementa ni
afirma que el módulo CLI R259 o el ZIP R258 estén disponibles. Los owners
separados deben entregar y verificar ambos antes de incorporar el selector
a `main`, incluyendo límites del bundle, procedimiento no-mutante de lease,
recibo canónico, `NO_GO` negativo y pruebas bajo contrato cruzado. No
despachar esta elección desde código aislado.

**Actualización R260, integración CODE_ONLY:** ADR0279 entregó el CLI
READ_ONLY y ADR0277 incorporó su ZIP dedicado con límites/allowlist; ambos
están en la rama candidata consolidada. Esto sustituye el pendiente de
código de la frase anterior, **no** autoriza dispatch hasta CI de `main`
y validación física bajo lease preexistente.

Convergen tres pruebas independientes: 1) Action PREDEPLOY anterior;
2) cleanup y postflight V2 **del mismo intento de instalación**;
3) validación real del panel `127.0.0.1:8443`, passkey, SITE_URL persistente,
worker bajo demanda, monitor y SQLite. Sólo la combinación y la evidencia
física de release/instalación permiten considerar otro dictamen. Porota,
recursos externos, navegación Boca/Queue-it y reservas reales permanecen
fuera de alcance.

## Evidencia de desarrollo

Prueba TDD inicial del nuevo contrato: **4 FAIL** por falta del selector,
admisión, paso SSH y ejecución QA, antes del cambio de workflow. Dos ciclos
TDD adicionales confirmaron que no se exponía el hash del recibo y que se
publicaba un recibo positivo antes de confirmar `remote_rc=0`; ambos quedaron
corregidos. Verificación local: 27 pruebas focalizadas, 46 de contratos de
workflow vecinos y la suite general **8035 PASS + 34 subtests PASS;
1 SKIP** por falta de creación AF_UNIX en este sandbox (`EPERM`, fixture
`test_r177_fixture_probe_transport.py:72`). Ruff total, formato, mypy para
198 fuentes, política del repositorio y sintaxis Bash del paso: PASS.
El selector y las dos últimas modificaciones de hardening se revalidaron
mediante la suite focalizada tras concluir la suite completa. Este SKIP
ambiental no se acredita como prueba del droplet ni del runner Actions.
Ninguna ejecución
de GitHub Actions, publicación de PR, contacto SSH o acceso al droplet se
atribuye a este desarrollo CODE_ONLY.
