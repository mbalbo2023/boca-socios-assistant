# Estado de integración BETA

**Corte:** 2026-10-29 (America/Argentina/Buenos_Aires). Base de esta revisión: `main`
`bfe4a3c830cff963e1668add05f50c50d0cbf2e8`. Issue #24, PR #30.
Este documento describe el candidato offline; no acredita una BETA operativa.

**Revalidación del 2026-10-30 (UTC):** #30 se integró en `main`, junto con el
outbox durable #34 y el worker Chromium offline #43. Los PRs #36, #38, #40 y
#44 siguen en borrador; sus checks históricos no acreditan una integración
actual. El semáforo y los límites de este documento siguen excluyendo
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
