# Estado de integración BETA

## Estado comprobado y límites

La release sigue en **simulación solamente**. La HEAD y los checks de cada
operación deben revalidarse en el [checkpoint vigente #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
El corte de código incluye #136/#140/#141 y componentes #130/#128/#134/#148/#149/#150/#152 hasta
`6be606f83c5a6afe0ba7226abbca6a09276d1ca1`; la preparación #120 usó este SHA; la inspección #98 corresponde a su corte anterior.
Las referencias exactas siguientes conservan su alcance histórico; no se
presentan como pruebas de un SHA posterior. Rige la Regla 84: documentación
impactada en el mismo PR y continuidad reconciliada antes de cerrar el trabajo.

Evidencia operacional: [recibo120](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756);
la HEAD y decisiones posteriores se mantienen en #45.
[Antecedente de Regla84](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551338776)
y [dirección vigente de BETA](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142).

| Área | Integrado/comprobado | Límite o pendiente |
| --- | --- | --- |
| Componentes offline | Cola/estados, navegador sintético, guardia/outbox, coordinador130 y comandos149 integrados; esquema0005/0006 opt-in | Sin conexión de comandos web/runtime ni flujo real; ninguna migración sobre DB real |
| Panel/Site | Demo113, proyección121, lectura128 y formulario/handler148 integrados; identidad default-deny | Sin listener/identidad real/TLS, lista socios ni DB/Site conectado. Panel propio aprobado para preparación; opciones de identidad/bootstrap/acceso pendientes |
| Notificaciones | Outbox durable y dispatcher sintético #134 integrados, sin red | Sin runtime/avisos panel conectados ni Telegram real; crash antes de settlement requiere reconciliación antes de transporte externo |
| Chromium | #43/#44 prueban arranque/cierre y presupuesto offline sin egress | No capacidad del droplet ni visita real; falta frontera de egress y observación pública específicamente autorizada |
| Claves/recuperación | #40 integró recifrador dormido y migración0004 opt-in; runtime migra0001 | No rotación real; faltan coordinación de escritores, protección DELETE, custodia y recuperación. Backup/restore diferido por el dueño |
| Host | Preparación150 ejecutada en120: servicio rootless dedicado READY, sin app. Preflight #124 PASS sobre contrato actual 0.5 CPU/256 MiB | No prueba presupuesto BETA funcional/Chromium; sin app/DB/volúmenes/clave creados. Location globalUNVERIFIED; BETA/deploy aún NO_GO. Stop-test #157 es candidato, no ejecución |
| Concurrencia Actions | #136 separó grupos PR y retuvo mutex manual constante | Operaciones host seriales; no habilita infraestructura ni elimina límites de runners |
| Migración P1 | #141 integrado: validación de ledger/checksum antes de DDL/WAL/chmod, recheck y creación exclusiva | Sólo código/fixtures; mode=ro puede interactuar con SHM, no es auditoría integral ni exclusión de toda carrera; ninguna migración real ejecutada |
| Release/calidad | Gates de SHA/intento/digest, CI frozen, build, scan, policy y RCA | CI no prueba publicación GHCR ni salud del droplet; autorización de un fix no habilita release |
| Reserva real | NO_GO | Sin cuenta/canal habilitados, evidencia del flujo legítimo ni conciliación de resultado externo ambiguo |

## Plan aprobado para la próxima entrega

[ADR0056](ADR/0056-approved-simulation-beta-delivery.md) y
[BETA_DELIVERY_PLAN](BETA_DELIVERY_PLAN.md) registran el desarrollo aprobado de
la BETA privada funcional. **Socios > Agregar socio** es obligatorio: servicio
cifrado existente, clave externa, acceso privado y E2E con datos sintéticos.
La [matriz de alcance UI](BETA_DELIVERY_PLAN.md#matriz-completa-de-alcance-ui-panel-propio-y-site-complementario)
conserva alta/consulta, ciclo de credenciales, eventos/sesiones, avisos, diagnóstico,
calidad, operación y diferidos. El Site113 sigue demo; contemplar una función
no prueba que sea operativa desde la primera BETA.
Se preparan panel propio y rootless dedicado; la ubicación lógica delegada es
`/data/boca.sqlite3` en `boca-socios_boca_data`. La existencia global actual
sigue UNVERIFIED y no se sustituirá una DB encontrada por inferencia.

Los componentes integrados incluyen formulario/handler de alta y comandos;
las cuatro pruebas de composición152 operan en proceso con identidad/browser
dobles. No acreditan login real, listener, tablet, runtime funcional desplegado
ni BETA terminada. Se
miden rapidez/recursos manteniendo checks exactos e integridad. La dirección
vigente permite completar los pasos rutinarios aprobados sin repetir permiso.

## Evidencia host y ubicación de datos

[Preparación #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418), attempt1,
source `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`, job124718888659, finalizó SUCCESS.
A las 22:49:24 ART del 2026-10-31 emitió SERVICE_READY,
application_database=not_accessed y application=not_installed. Se creó/arrancó/
habilitó sólo el daemon dedicado y su bookkeeping; postflight probó rootless,
cgroupv2-systemd, overlay2, data root privado, cero contenedores y namespace
Boca vacío. [Recibo](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).
La capacidad informativa antes/después no prueba presupuesto de aplicación.
DEPLOY ready se añadió sólo al entorno protegido; no hubo release/pull,
contenedor, SQLite, volúmenes de app/clave, clave ni backup. No repetir
prepare-rootless sobre la configuración que ahora existe.

[Preflight #124 / 41268626135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41268626135),
attempt1, source `213be4903669c6e88122a536ad8fee6785c997ac`,
ejecutó `preflight` de sólo lectura y terminó SUCCESS. Recibo:
`mem_kib=853288`, `stage_disk_bytes=8009560064`, `stage_inodes=2902623`,
`cpu_headroom=1.60`, `namespace=empty`. Esto prueba el gate rootless/capacidad
para el controlador dormido del Compose vigente, no el candidato BETA ni
presupuesto Chromium; no instaló aplicación ni accedió a SQLite/clave.

La siguiente evidencia de #98 es **histórica**: el estado de servicio ausente
fue reemplazado por el recibo #120; el alcance limitado del inventario DB sigue
vigente como límite de lo observado.


La [inspección #98 / 41258754195](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258754195)
ejecutó `inspect-prerequisites`, attempt1, sobre
`5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e`. Observó UID10001, runtime y bus
propios, controladores cpu/memory/pids, socket rootful no escribible y rootless
ausente. `load=not-found active=inactive sub=dead result=success` corresponde a
la unidad de usuario docker.service; Docker/dockerd/wrapper/setup fueron
hallados por búsqueda de ejecutables. Esto no dice «Docker desinstalado» ni
prueba un daemon sano. No se ejecutó Docker, instalación, release ni backup.
La metadata emitida a las 21:54:17 ART del 2026-10-31 (job124707449992) informó
candidate-absent para DB/WAL/SHM en rootless_default, staging_root y staging_data.
Son sólo las tres hipótesis fijas de ADR0054: no una búsqueda general. El recibo
retiene `location=UNVERIFIED scope=fixed_paths_only`; no se abrió, creó, movió
ni migró ninguna base. El job falló después por el gate del socket ausente.
#92 es evidencia histórica previa, sin el inventario de candidatos de #140.

Compose configura `/data/boca.sqlite3` dentro del controlador y monta `/data`
desde `boca-socios_boca_data`. SQLite es embebida en Python y no necesita un
servidor de base separado. El volumen permite persistir el archivo fuera del
ciclo de vida del contenedor; su configuración no prueba su existencia real.
Se inspeccionaron sólo metadatos de rutas candidatas y no se confirmó ni leyó
una DB Boca en el droplet; las DB de CI son temporales.
`Database.migrate()` es una función del código: desarrollarla o corregirla no
crea una base operativa ni ejecuta una migración en el droplet. Las reproducciones
del defecto P1 usaron exclusivamente bases temporales sintéticas; no datos reales.

El runtime valida la clave, aplica la migración inicial y espera con
`engine=off` y `site_calls=0`. Un controlador saludable sólo probaría ese
alcance. No sería una BETA funcional sin coordinación durable, interfaz
aprobada y autenticada, notificaciones y pruebas correspondientes.

## Autorización y próximos gates

La [dirección aprobada de BETA](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142)
amplía los alcances ya completados a la preparación y desarrollo del plan.
Las decisiones ya registradas no requieren aprobación repetida; nuevas
alternativas fuera del alcance sí conservan opciones/recomendación/decisión.
Identidad/bootstrap/acceso concreto y publicación/instalación final quedan
sujetos a sus opciones, candidato y gates, no a la mera aprobación del plan.
No se autorizan migraciones reales, credenciales/login/cola/reserva ni cambios
en Porota/PPI Watch.
La ausencia de una aprobación humana obligatoria en el ruleset es un dato de
GitHub, no una delegación general de decisiones. Cada PR requiere revisión
registrada del agente y checks del candidato exacto.

La secuencia posible del host, sujeta a decisiones aprobadas, es diagnóstico
acotado → remediación elegida → preflight apto → release por digest/manifiesto
→ instalación → postflight. La preparación120 ya completó su alcance; no
repetir #98/120 ni recrear secretos SSH. Las pruebas
de scopes independientes aprobados pueden avanzar en paralelo; host y merges
permanecen serializados. Backup/restore está diferido hasta versión productiva
fiable y no se convierte en un bloqueo de simulación ni permiso de alta real.

## Registro histórico del candidato #24

**Corte original:** 2026-10-29 (America/Argentina/Buenos_Aires). Base de esta
revisión: `main`
`bfe4a3c830cff963e1668add05f50c50d0cbf2e8`. Issue #24, PR #30.
Todo el texto bajo este título describe aquel candidato offline; no acredita
el estado vigente ni una BETA operativa.

**Revalidación intermedia del 2026-10-30 (UTC):** #30 se integró en `main`,
junto con el outbox durable #34 y el worker Chromium offline #43. Los PRs
#36, #38, #40 y #44 seguían en borrador; sus checks históricos no acreditan
una integración actual. El semáforo y los límites de aquel corte excluían
credenciales, reserva real y despliegue por un merge.

## Integración efectivamente realizada

| PR | Componente | Estado al corte |
| --- | --- | --- |
| #18 | Auditoría de Actions y Dependabot | Integrado en `main` |
| #22 | Intención SQLite, única por socio y evento | Integrado |
| #23 | Imagen fijada y lectura defensiva de clave | Integrado; 0444 sólo compatibilidad transitoria, sin secretos reales |
| #21 | Cola determinista en memoria | Integrado como modelo, no Queue-it |
| #20 | Outbox seguro en memoria | Integrado; claim ligado a su instancia, sin Telegram ni persistencia |
| #26 | Flujo de navegador ficticio | Integrado; aviso sin ID de socio/evento, Chromium real no probado en CI |
| #19 | Instrumento de benchmark opcional | Integrado; sin cifra medida de capacidad |
| #28 | Diseño de alta privada | Integrado como ADR, sin interfaz operativa |
| #29 | Renderizador accesible de estados ficticios | Integrado offline; sin endpoint privado ni prueba manual de lector de pantalla |
| #33 | Observador público opt-in | Integrado como script; nunca ejecutado contra Boca en este gate |
| #96 | Diagnóstico público manual por Actions (issue #94) | Integrado como semáforo asesor, separado de CI y despliegue |
| #51 | Dependencia cryptography y lockfile | Integrado con CI exacta |
| #104 | Actions oficiales fijadas a Node 24 | Integrado en CI y semáforo público |
| #31 | Servicio interno de alta de socios | Integrado como biblioteca transaccional; sin endpoint ni enrolamiento real |

Las PR fundacionales fueron revisadas por el agente y pasaron los jobs
`quality-and-tests` e `image-build` para sus HEAD exactas. El ruleset
`protect-main` activo exige PR, checks y conversaciones resueltas, con cero
aprobaciones humanas requeridas, según la revalidación en
[GITHUB_SETUP.md](GITHUB_SETUP.md). ADR 0038 reemplaza el lenguaje histórico
de aprobación humana en issues y ADR previos.

PR #30 conserva su historia original de verificación, pero el árbol candidato
añade **únicamente** seis rutas propias de #24 sobre el `main` actual:
`src/boca_socios/integration/{__init__,offline}.py`,
`tests/test_offline_integration.py`, ADR 0015, este estado y el registro
histórico de observación pública. No vuelve a introducir versiones antiguas
de los siete componentes.

## Contrato cruzado

`OfflineSimulation` requiere una admisión sintética vigente de la misma
identidad/evento, valida el alias antes de mover el reloj compartido, registra
una única intención local de cantidad 1 en SQLite, ejecuta el puerto de
navegador ficticio y crea una notificación estática deduplicada por ID opaco.
Un fallo de navegador no envía éxito; el intento local puede reutilizar el
mismo ID. La fila de DB sigue en estado `planned`. La cola y el outbox son
volátiles y no comparten transacción con la DB: no se promete una reserva
externa exactamente una vez ni entrega después de un reinicio.

Las pruebas cruzadas cubren alias duplicados, socio/evento y cantidad
inválidos, TTL, fallos/reintentos, cifrado AES-GCM tras reabrir SQLite y
fallo cerrado ante clave mal montada. La CI del SHA exacto del candidato
se registra en la conversación de PR #30 antes de cualquier merge.

## Semáforo de alcance

| Área | Estado | Evidencia o pendiente |
| --- | --- | --- |
| Librerías offline | GO para integración revisada | Tests cruzados y CI exacta del candidato |
| Portada pública | Observación histórica acotada | [Registro del 2026-10-28](BOCA_PUBLIC_OBSERVATION_2026-10-28.md); no revela flujo autenticado |
| Fuente externa | Asesor, no gate de despliegue | `boca-source-status.yml` manual en Actions; informar color, UTC y run o UNKNOWN |
| BETA operativa | NO_GO | El servicio #31 no tiene endpoint; faltan endpoint autenticado del panel, outbox durable #34, guardia #38, rotación #40 y wiring |
| Reserva real | NO_GO | Sin identidad verificada, autorización de sitio, flujo observado ni reconciliación de resultado ambiguo |
| Capacidad del host | No verificada | #19 no ejecutó Chromium real; preflight rootless/cgroup/disco debe venir de Actions |
| Despliegue | No ejecutado | Sólo workflow manual Boca en `main` y gates de SHA/digest/aislamiento/recursos pueden habilitarlo |

Un incidente de fuente externa se diagnostica primero con el workflow manual
de Actions y se informa como semáforo. Su fallo no bloquea por sí solo un
despliegue seguro del controlador dormido ni justifica uno nuevo. Un defecto
de código probado requiere PR y CI nueva. Nunca se habilita login, cola o
checkout real por una señal de salud pública.

El protocolo de observación #15 permanece separado. El renderizador del
panel #29 y el servicio interno #31 están integrados, sin interfaz privada
operativa. El observador #33 no fue ejecutado contra Boca en este gate.
Las PR encadenadas #34/#36/#38/#40
necesitan revisión propia y actualización sobre `main` en orden; su mera
existencia no completa el runtime. No hay credenciales reales, tráfico autenticado,
reserva, Telegram, cambios del droplet ni de otros proyectos en este candidato.

