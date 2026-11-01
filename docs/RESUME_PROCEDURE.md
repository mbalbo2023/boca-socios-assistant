# Reanudar Boca Socios Assistant con «continúa»

Este procedimiento permite recuperar trabajo desde GitHub sin depender de la
memoria del chat. [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
es la entrada canónica; su responsable es el integrador/operador root. [ADR0062](ADR/0062-operational-beta-and-recovery.md)
registra la autorización operativa vigente. El [plan](BETA_DELIVERY_PLAN.md)
mantiene requisitos y aceptación; [#113](https://github.com/mbalbo2023/boca-socios-assistant/issues/113)
mantiene Site/audiencia/conexión. No copiar secretos ni identificadores de cuenta
a ninguno de estos registros.

## Recuperación antes de cualquier efecto

1. Leer #45 completo: checkpoint más reciente **y el anterior enlazado**,
   autorización posterior aplicable y pendientes. Leer AGENTS, README,
   DEVELOPMENT_POLICY, este procedimiento, plan y ADRs de los módulos afectados.
   Si el body apunta a un checkpoint anterior, inspeccionar los comentarios
   posteriores: no interpretar un resumen viejo como revocación del nuevo alcance.
2. Revalidar main exacto, PRs/issues abiertos, branches y checks del candidato,
   runs manuales, releases/manifiestos e inventario de recursos Boca de la última
   operación. Un run en cola/RUNNING no se duplica; inspeccionar su resultado.
   Un receipt previo no prueba que el servicio siga activo o parado ahora.
3. Recuperar owner/paths/branch de cada frente desde su issue/checkpoint y
   coordinar el relevo antes de editar. Preservar commits/WIP ajenos. No asumir
   que un PR antiguo abierto falta por integrar ni reintroducir su árbol viejo.
4. Priorizar cualquier STOP incompleto o estado de recursos UNKNOWN. Inspección
   y recuperación sólo por Actions Boca, con alcance positivo exacto. Nunca
   repetir prepare-rootless120 ni first-install sobre namespace existente.
5. Registrar checkpoint RUNNING de la siguiente fase, base/candidato y acción
   exacta. Completar pasos autorizados sin pedir otro GO genérico. Si falta un
   dato imprescindible, marcar BLOCKED con evidencia y seguir frentes realmente
   independientes; no sustituirlo por una afirmación de éxito.

## Estados de seguimiento

| Estado | Significado | Recibo requerido |
| --- | --- | --- |
| RUNNING | Writer/operador asignado está ejecutando una acción identificada | Inicio, SHA/branch/paths, operación/run si existe, último estado verificado y siguiente verificación |
| DONE | Criterio concreto de esa fase cumplido con evidencia exacta | Resultado, límites, PR/merge/run, recursos afectados y siguiente fase; no equivale a BETA completa |
| BLOCKED | Gate falló, dato/resultado es incierto o dependencia impide continuar | Motivo, evidencia, recursos que pueden seguir activos, siguiente acción segura y owner |

Son estados del seguimiento, no nuevas columnas de DB ni valores del outbox.
No marcar DONE si faltan CI/review, integración, aceptación operativa o STOP
exigidos para esa fase. Cancelar una tarea no demuestra que sus recursos pararon.

## Fases recuperables y dependencias

| Fase | Acción y criterio de cierre | Paralelismo / siguiente paso |
| --- | --- | --- |
| R0 recuperar | Revalidar autorización, main/checks, operaciones en curso y ownership; inventario del último estado | Antes de editar u operar; STOP incierto tiene prioridad |
| R1 contratos y componentes | Conectar UI/Site/acceso, alta/ciclo, eventos/sesiones, comandos, avisos/Telegram, navegador y contratos de host; tests y ADR de cada scope | Writers con paths disjuntos en paralelo; no prometer integración de ramas sin merge |
| R2 integrar candidato | Merges seriales; matriz completa con rutas/permisos/tests; CI/build/scan/review exactos, stop probado y métricas | Pruebas independientes en paralelo; luego preflight |
| R3 preparar operación | Verificar servicio existente, capacidad/cgroups, datos/clave/namespace, digest/manifiesto, acceso privado y plan de stop; configurar sólo requisitos Boca autorizados | Operador único Actions; ante diferencia de almacenamiento bloquear first-install |
| R4 release e instalar | Publicar imágenes exactas e instalar candidato por workflow protegido con postflight funcional | Recibo source→digest→proceso, datos/clave y alcance; no repetir run fallido |
| R5 aceptación operativa | UI/Site realmente conectados; matriz funcional completa, Telegram recibido, navegación real designada sin efectos excluidos; rechazo de terceros, reinicio/duplicados/latencia | Las suites sintéticas son evidencia complementaria; fallo conserva BLOCKED y pasa a STOP |
| R6 STOP obligatorio | Detener app/workers/Chromium/puente/contenedores y daemon dedicado; verificar cada estado y preservar datos/clave/config | Siempre después de tests o interrupción con recursos activos; no paralelo con otra operación host |
| R7 cierre | Site informa backend detenido; registro de versión, evidencia, límites, pendientes, STOP completo y siguiente acción exacta; actualizar docs/45/113 | Sólo cerrar entrega operativa con aceptación y STOP; no prometer ejecución futura automática |

R1 puede producir entregas parciales DONE sin cerrar R5. Toda función documentada
debe tener un resultado o bloqueo explícito; no desaparecer del plan por estar
incompleta. Backup/restore sigue diferido; reserva/compra/cambio de cuenta Boca
no forman parte de las pruebas autorizadas. No inventar funciones no definidas.

## Formato obligatorio de checkpoint en #45

```text
Fase/estado: Rn — RUNNING | DONE | BLOCKED
Autorización: enlace exacto y límites aplicables
Main verificado: SHA completo + checks/runs consultados + fecha ART
Candidato: issue/PR/branch/HEAD/base + paths + writer/reviewer
Decisión y acción: operación concreta, motivo y gates
Evidencia: run/attempt/job/artifact o prueba + resultado + límite
Recursos Boca: inventario propio observado; app/worker/bridge/daemon y datos/clave
Site: audiencia comprobada, versión/conexión y estado que muestra
STOP: no iniciado | RUNNING | DONE | BLOCKED; recibo por recurso
Pendiente/dependencia: qué falta y qué frentes independientes pueden seguir
Siguiente acción exacta: dato a revalidar y operación idempotente o nuevo candidato
Ownership: retenido/liberado/relevo y paths; checkpoint anterior enlazado
```

Registrar al inicio de fase y tras resultado/PR/ejecución, no únicamente al final
del chat. Los comentarios y bodies vigentes se reconcilian; lo anterior queda
histórico explícito. Si se interrumpe la sesión, el último checkpoint conserva
la incertidumbre real. No anunciar una ejecución nocturna garantizada.

## Acta STOP y persistencia

| Recurso propio | Antes / operación de parada | Verificación final |
| --- | --- | --- |
| App, coordinador y consumidores | Identidad exacta del proceso/container y versión | Sin proceso/tarea activa ni reinicio automático observado |
| Workers/Chromium | IDs propios del ensayo | Sin workers/browser vivos; no matar procesos ajenos |
| Puente/servicio auxiliar Boca | Identidad y mecanismo de ciclo de vida aprobado | Detenido y sin actividad saliente propia; no confundir timeout con parada |
| Daemon rootless dedicado | Unidad/socket/UID propios preservando configuración; diseño157 detiene y deshabilita sólo su unidad | Unidad y procesos propios detenidos, sin mecanismo propio que los reactive durante el cierre; implementación/recibo157 aún pendientes |
| Datos/clave/configuración | Nombres/procedencia y alcance sin contenido | Preservados; no backup, wipe ni reemplazo |
| Site | Último receipt/fecha y audiencia conservada | Muestra backend detenido/no disponible; no éxito inventado al enviar comandos |

El helper exacto y su evidencia deben definir cómo se comprueba cada fila;
esta tabla es un requisito, no un comando ya implementado. No declarar STOP
por un `stop` exitoso sin postflight. Si una fila no puede comprobarse, BLOCKED
con datos de recuperación sanitizados y atención prioritaria del operador.

## Ownership y punto inicial de esta etapa

Fuente revalidada al abrir #154: `213be4903669c6e88122a536ad8fee6785c997ac`.
Último receipt host: #120/41262650418 sobre6be606, servicio preparado sin
aplicación/DB creada por esa operación. No existe un STOP final comprobado en
ese receipt. Esto es punto inicial, no estado vivo de una ejecución posterior.

| Scope | Writer / branch verificado al iniciar | Acción siguiente |
| --- | --- | --- |
| Docs centrales + este procedimiento/ADR0062 | continuity_audit; #154; feature/154-operational-scope-recovery | Publicar/revisar/integrar actualización del alcance, después reconciliar evidencia de entregas |
| Panel/ciclo de socios | panel_backend; #155; ADR0064 | Branch/HEAD en issue155; API/contrato y pruebas, sin editar docs centrales |
| Runtime funcional | functional_integration; #156; ADR0065 | Branch/HEAD en issue156; composición/runtime/puente y pruebas |
| Parada final propia | host_diagnosis; #157; feature/157-stop-test; ADR0063 | Revisar/testear stop-test y disable sólo unidad Boca propia; conservar datos/clave |
| Telegram | pr_concurrency; ADR0066 reservado; issue/branch en checkpoint | Adapter y pruebas; bot/token/destino aún faltantes no prueban envío |
| Site y navegación real | root; recepción/cambios en #113/#45 | Mantener audiencia; implementar conexión elegida y evidencia privada; no efectos excluidos |
| Integración, #45/#113 y host | root; branch/PR de cada operación en su issue | Recuperar scopes activos de #45 antes de asignar o operar; único operador Actions |
| Componentes independientes | Owners/branches consignados en cada issue y checkpoint actual | Revalidar HEAD/paths, coordinar sin escritores superpuestos; no usar una lista antigua como lease |

Cada relevo registra las ramas activas con SHA y próxima acción en #45. Este
documento no congela una lista de agentes que pueda volverse falsa con el tiempo.
