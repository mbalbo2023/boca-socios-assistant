# ADR 0240 — Upgrade repetible del par, sin segunda migración

Fecha: 2026-11-12 (ART). Issue #417. Estado: **CODE_ONLY / UNWIRED / NO_GO**.
Base exacta: `b05da1d9ab8dae4a41b337baa1cebf0589b365fc`.

**Reconciliación CODE_ONLY posterior:** actor y adaptadores se combinaron en
una worktree nueva desde `1089de83492d517ca67979dba9c7a34436ffc376`, sin
modificar sus dos módulos productivos, workflow, bundle ni interlock FALSE.
La base anterior identifica el desarrollo histórico, no el main integrado.
Los tests combinados prueban rechazo de defaults no autenticados, conversión
no implícita de pins, ausencia de GO incluso con receipt de imágenes ACCEPT,
y exclusión de ambos módulos del ZIP effectful real. No se agregó bridge
productivo ni se acreditó una transacción física.

## Decisión

Conservar una sola transacción de reemplazo dual y una sola Action protegida.
No agregar un hotfix de controlador por separado: la observación, la release,
el binding y el lifecycle actuales exigen un SHA común para ambos servicios.
Un controlador nuevo con worker viejo obligaría a modificar esas cuatro
fronteras y a mantener una segunda familia de rollback. No se justifica por
un cambio pequeño de panel. Las optimizaciones de build/CI son independientes.

El backend histórico es una migración inicial, no una API de mantenimiento.
Fija `03df9a14...` / intento `42806447101`, exige worker EXIT1/red none y
ausencia del volumen SITE y bridge egress. Repetirlo no actualiza el par actual.
Sus pruebas, entrypoint, CLI, bundle y recuperación R186 permanecen intactos.

Se agrega **solamente** `ReusablePairUpgradeBackend`, reutilizando el orden,
park/create/bind/retire y compensación existentes. No se crea otra máquina
transaccional. La clase tiene `requires_persistent_receipt=False`; el gate
existente consulta el tipo concreto y la rechaza antes de lease/journal/efectos.
No hay CLI, selección automática, importación desde el dispatcher ni inclusión
en ZIP. Los adaptadores protegidos aún no existen; no hay un default permisivo.

## Tres procedencias distintas

| Identidad | Fuente de autoridad requerida | Duración |
|---|---|---|
| Par actualmente instalado | Binding, release histórica autenticada y par físico bajo lease | Hasta el próximo reemplazo |
| Release destino | Main exacto, CI, seguridad y manifests duales autenticados en GitHub | El candidato exacto |
| Recursos retenidos | R188 auténtico más relectura positiva bajo la lease actual | Sobrevive a varios reemplazos |

Un label OCI o Docker es una coordenada comprobable, no autenticación de una
release. El recibo R188 no autoriza ningún deploy. `CandidateRelease.validate`
comprueba sintaxis, no autenticidad. No convertir ninguna de estas fuentes en
la otra ni aceptar booleanos suministrados por el usuario como evidencia.

La coordenada `RetainedResourcePins` contiene exactamente:
`ipc_creator_attempt`, `ipc_inode_sha256`, `site_creator_attempt`,
`site_inode_sha256`, `egress_creator_attempt`, `egress_id`. Los tres attempts
son los **creadores** originales. No deben igualarse al attempt del nuevo par.
En el estado informado, IPC nació en `42806447101` y SITE/egress en
`43217075287`. Nunca recrear, relabelar ni eliminar esos recursos durante un
upgrade o su compensación. Tampoco borrar datos, key, owner ni SQLite.

## Contrato de recepción R188 V1 para el adaptador pendiente

Se verificará el parser canónico del otro frente, no un parser JSON laxo:
prefijo `BOCA_RETAINED_RESOURCES `, `schema=1`, `state=READ_ONLY`,
`observation_run_id`, `installation_attempt`, `source_sha`, `volumes`,
`egress`, `images`, `unclassified_image_count`,
`control_socket_directory_inode_sha256`, `bind_mounts`,
`expected_resource_provenance`, `observer_writes=0`,
`successor_apply_authorized=false`. La versión inicial R188 observa el par
`43217075287` / `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`; no demuestra
por sí sola un sucesor ni debe parchearse con nuevos literales en cada release.

El runner verificará run real, repository/workflow, fuente exacta revisada,
conclusión, artifact/digest, frescura y coincidencia con el par esperado.
Dentro de la operación se volverán a capturar las identidades bajo la lease
Boca UID/GID10001. La relectura de recursos no reutilizará el observer de
exactamente dos CIDs durante la coexistencia transitoria de cuatro CIDs:
deberá permitir **sólo** esos cuatro IDs del journal y sus referencias válidas.
Egress permanece sin peers activos mientras ambos workers están CREATED.

El inode del directorio control antiguo se prueba **antes de park**. No se
puede exigir su igualdad durante toda la transacción: `park_binding` renombra
la raíz y `prepare_control_directory` crea la raíz nueva. Antes de commit se
verifica el nuevo bind mount contra el directorio nuevo; antes de retiro, la
custodia del directorio antiguo permanece en el respaldo aparcado verificado.
Un diagnóstico de inode viejo no autoriza borrar el respaldo ni reconstruirlo.

## Actor actual y límites

`attest` requiere integrations explícitas antes de lecturas host, release
autenticada, par/binding concordantes, controller healthy, engine STOPPED,
worker **CREATED/PID0/Exit0**, hashes Compose del binding, rootless y SQLite
estable. No admite por defecto el perfil histórico EXIT1 ni un worker activo.
Un futuro soporte a worker EXITED tras STOP normal necesita su contrato
específico; no se infiere que EXIT1 sea aceptable.

`stage` vuelve a verificar release/recursos, prepara bytes objetivo y tira
ambas imágenes exactas; no crea redes/volúmenes. El hash del Compose histórico
del filesystem es custodia del archivo histórico, no un requisito de que los
bytes objetivo de Compose sean iguales: el futuro lector de sources debe
quitar sólo esa igualdad indebida, preservando el pin/inode antiguo.

La nueva clase conserva el rollback sólo precommit. Después del intento de
marcador irreversible jamás reactiva los viejos. R186 continúa exclusivamente
para su incidente histórico; no se generaliza ni se repite como instalador.

`finalize` exige un adaptador de cleanup que produzca evidencia duradera de
disco/inodos antes/después y cada ID intentado/removido, compruebe ausencia y
referencias globales de imágenes y preserve la excepción histórica R108.
No basta un ACK del par ni borrar dos CIDs. El adaptador debe conservar el
stage que todavía respalda el seccomp/config del par activo. Recursos inciertos
se retienen y producen NO_GO/INDETERMINATE, nunca prune ni force-rm. Tras cleanup
se revalidan recursos, SQLite, par y binding otra vez.

El retorno string del callback `final_cleanup` es sólo una interfaz interna,
**no un recibo confiable ni evidencia duradera**. La clase continúa bloqueada.
Antes de habilitarla, el adaptador real debe escribir y verificar el recibo
detallado canónico, correlacionado al mismo intento/lease, con todos los IDs y
medidas anteriores, y recién entonces mapearlo a `ACCEPT`. Un callback que
simplemente devuelve ese literal no satisface el contrato ni autoriza remover
el interlock. R188 físico tampoco reemplaza ese recibo de cleanup.

## Wiring posterior necesario, no aplicado en este cambio

1. Integrar R188 y obtener su evidencia física por la Action existente.
2. Implementar los tres adaptadores `verify_release`, `retained_resources` y
   `final_cleanup`. Separar provenance instalada de provenance destino. El
   cuarto vínculo es el journal O_EXCL/fsync: atar el digest R188, el digest de
   pins y los manifiestos al intent antes del primer efecto. No reescribir
   journals históricos ni heredar una lease de otro run.
3. Construir coordenadas desde la observación/binding actuales, no desde IDs
   de formulario ni constantes históricas. Resolver explícitamente si la
   observación fresh usa el mismo run; hoy `PairCoordinates` exige IDs
   distintos. No fingir un run de observación para satisfacer esa validación.
4. Añadir el nuevo módulo y sus imports exactos al bundle, ejecutar el ZIP con
   Python aislado y verificar allowlist/límites/imports. El lector source debe
   aceptar el Compose objetivo sin sustituir el archivo histórico.
5. Sólo entonces cambiar el interlock, conectar la operación existente y
   someter el candidato integrado a PR/CI/política/review exact-SHA. No nueva
   Action SSH, deploy por push, red del host ni cambios a Porota.
6. Release dual del SHA fusionado y operación autorizada serializada, con
   postflight y cleanup en el mismo run. El panel/passkey y POST móvil siguen
   necesitando aceptación física. Ningún paso inicia Chromium, navega Boca,
   valida URLs de tokens, compra, reserva ni activa Telegram.

## Evidencia local de esta preparación

**Repetibilidad E2E: NO_VERIFIED.** La prueba de dos coordenadas sucesoras
comprueba únicamente que los creators retenidos no se vinculan de nuevo al
attempt del plan; no ejecuta dos secuencias completas park/create/bind/commit/
cleanup ni dos upgrades físicos. La aceptación E2E permanece pendiente de
adaptadores reales, laboratorio transaccional integrado y dispatch protegido
con evidencia física. El nombre reutilizable del actor describe su objetivo,
no certifica hoy su repetibilidad operacional.

TDD observado: 9 pruebas RED por actor inexistente, luego 9 GREEN. Una segunda
regresión reprodujo ACCEPT indebido si cleanup cambiaba el binding: RED
`ACCEPT != INDETERMINATE`, luego revalidación post-cleanup. Otra reprodujo la
aceptación de config-hash viejo adulterado: RED por ausencia de rechazo,
luego comparación contra el binding. Los contratos focales finales se deben
ejecutar y reportar por SHA exacto al integrar; no son una prueba del host.

Baseline de esta rama: 7180 PASS +34 subtests; un SKIP preexistente en
`test_r177_fixture_probe_transport.py:72` por AF_UNIX EPERM del sandbox. No se
relajó el test. Ese límite local no certifica el transporte físico ni vuelve
mergeable por sí solo el candidato. Este documento tampoco es un permiso para
invocar el actor aún bloqueado.

## Incremento CODE_ONLY: journal durable del sucesor

`host_boca_repeatable_journal.py` agrega un cuarto archivo O_EXCL/fsync al
journal R179: `.evidence`. Su contenido canónico tiene versión, coordenadas
del par, digest de ambos manifiestos de la release y doble captura física
de las identidades del par anterior, volumen IPC, volumen SITE, egress e inode
del directorio control. El archivo `.intent` incluye `evidence_sha256`;
`.commit` sigue siendo SHA256 del intent, `.terminal` conserva el formato
anterior. No admite un intento reutilizado ni reescribe journal histórico.

La captura es una interfaz explícita **sin implementación productiva**: debe
venir de observación rootless real bajo el **mismo** lock de la transacción.
`ReleaseEvidence` se admite sólo cuando un autenticador Actions real acreditó
los dos ZIP y manifests; tener el dataclass no autentica un artifact.
La Step Summary del run R189 `43281507903` no es un artifact firmado ni un
transport autenticable por `verify_custody_seed`. Se la puede citar como
antecedente, pero no como autoridad para hacer upgrade. R189 informó IPC
creado en `42806447101` y SITE/egress en `43217075287`; el observador fresco
debe volver a comprobar sus labels, inodos y ausencia de conexiones ajenas.

Las pruebas locales de journal cubren drift, capturas no coincidentes,
falla de transporte, replay y vínculo SHA256. Sigue **NO_GO**: sin transporte
de release autenticado, CLI protegido, cleanup V2 y comprobación transaccional
de extremo a extremo no se habilita `requires_persistent_receipt` ni se copia
ningún archivo al host. Se reutilizará el selector existente
`boca-pair-upgrade-apply`; nunca se agregará un selector de deploy competidor.
