# Estado de integración BETA

## Estado vigente — 2026-10-31 (America/Argentina/Buenos_Aires)

Base verificada: `main` `dc6c69f9746cc4514c7e268846dece9ff30842b5`.
La release sigue en **simulación solamente**. Los merges no demuestran un host
apto ni habilitan login, credenciales, cola, Telegram o reserva real.

| Área | Estado vigente | Evidencia y límite |
| --- | --- | --- |
| Componentes offline | GO para revisión y pruebas sintéticas | #30/#34/#36 integraron contratos y outbox durable; #36 impide dos ejecuciones del navegador ficticio en una misma instancia; #38 agregó una concesión local SQLite, aún sin conexión a un flujo externo de reserva |
| Panel y alta privada | Demostración privada publicada; NO_GO operativo | #113 tiene un Site privado con datos sintéticos. #121 aporta lectura local agregada en modo read-only; no hay endpoint ni conexión al Site. #31 sigue como servicio interno. Falta una capa servidor mínima con identidad, permisos, TLS y protección de sesión/CSRF; no acceso del navegador al archivo SQLite |
| Chromium y fuente pública | Sólo prueba offline y observación pública acotada | #43 arrancó/cerró Chromium sin egress y #44 midió un arranque, no capacidad del droplet ni visita real. #33 no se ejecutó contra Boca en este gate; #96 ofrece un semáforo manual asesor, no prueba de flujo autenticado |
| Claves y recuperación | NO_GO para credenciales/rotación reales | #40 integró un recifrador interno dormido y migración 0004 opt-in; el runtime sigue en 0001. Pruebas sintéticas cubren transacción/rollback, escritor viejo, nueva clave, reinicio y DDL. Los triggers no cercan DELETE ni prueban por sí solos la posesión de la clave nueva; faltan coordinación de escritores y recuperación operativa. El dueño difirió backup/restore hasta versión productiva fiable; #47 es sólo biblioteca offline. Persisten canal privado, identidad y custodia de ADR 0012/0022 |
| Controlador y host | Inspección ejecutada; NO_GO instalación | #124 corrigió argv SSH. Run #70 pasó readiness, SHA y SSH; observó UID10001, runtime privado, user manager y D-Bus propios, socket rootful no escribible y controladores cpu/memory/pids. El socket rootless está ausente: falta distinguir daemon no instalado, detenido o fallando, y luego probar capacidad/aislamiento reales. #116 sólo aporta pruebas CI de límites/red y capacidad tras pull/up |
| Release y calidad | GO para CI; host pendiente | #99 rechaza reruns/main obsoleto; #117 rechaza dispatches duplicados de release. #124 pasó 564 pruebas y deja 8 lecciones RCA/21 selectores. CI y escaneo de main son SUCCESS; no acreditan publicación GHCR, instalación ni runtime del droplet |
| Reserva real | NO_GO | No hay cuenta autorizada, orden real de login/cola/eligibilidad, confirmación de Boca ni conciliación externa de un resultado ambiguo; una intención local `planned` no es ticket |

Cada PR necesita revisión técnica registrada del agente, checks exactos y
conversaciones resueltas. ADR 0038 no exige una aprobación humana adicional.
Las operaciones de host usan el workflow manual Actions con sus gates
comprobados; un merge o un semáforo público no las dispara. La BETA de
simulación y el alta real tienen puertas distintas: postergar backup/restore
no convierte la primera en un bloqueo ni autoriza la segunda.

### Ubicación de datos y significado del primer despliegue

Compose configura `/data/boca.sqlite3` dentro del controlador y monta `/data`
desde el volumen persistente `boca-socios_boca_data`. Es una configuración,
no evidencia de que ese archivo o volumen ya exista en el droplet. La
inspección #70 no ejecutó Docker ni inventarió datos. Las bases temporales de
CI tampoco son una base operativa del servicio.

El runtime actual valida la clave, aplica la migración inicial y espera con
`engine=off` y `site_calls=0`. Un primer controlador saludable demostrará ese
alcance, no una BETA funcional: faltan coordinación de módulos, guardia durable
conectada, interfaz autenticada, transporte de notificaciones y las pruebas
correspondientes. La API mínima puede pertenecer al mismo backend; no requiere
un sistema independiente ni bloquea validar primero el controlador dormido.

La siguiente secuencia del host es diagnóstico del rootless ausente →
preflight apto → release por digest/manifiesto → instalación → postflight.
Código, pruebas y documentación de ámbitos independientes avanzan en paralelo;
fusiones y operaciones host permanecen serializadas. No se recrean secretos
SSH ni se relajan los gates para ocultar una carencia real del host.

Evidencia: [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551007644),
[run #70](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255522108),
[CI main](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255414416)
y [escaneo main](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41255414443).

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
