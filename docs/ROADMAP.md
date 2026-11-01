# Backlog comprobado y decisiones pendientes

Este documento separa código integrado, evidencia de ejecución y propuestas.
El [checkpoint vigente #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
identifica la HEAD y los runs que deben revalidarse antes de operar. Un candidato
con CI verde no cuenta como integrado ni como servicio funcionando en el host.
Rige la [Regla 84](../AGENTS.md#rule-84--documentation-must-remain-factual-and-current):
actualizar la documentación afectada en el mismo PR y reconciliar el checkpoint
antes de cerrar el alcance; conservar cortes anteriores sólo como históricos.

El corte de código reconciliado incluye #136/#140/#141, hasta
`07cf424c92384a42e820b73befcaaeeaca87e8d9`. Esto identifica el código revisado;
la inspección #98 citada abajo corresponde a su propio SHA anterior.

Evidencia consolidada: [corte operativo #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551442762).
[Dirección acotada y Regla 84](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551338776).

## Fundación y componentes integrados

| Área | Comprobado en el repositorio | Lo que aún no demuestra |
| --- | --- | --- |
| Persistencia | SQLite WAL, migraciones, unicidad socio/evento y cantidad 1; vault AES-256-GCM con clave externa | Existencia de DB en el droplet, alta real ni recuperación operativa |
| Simulación | Máquina de estados, cola determinista, navegador sintético, coordinador offline y guardia SQLite son módulos integrados | Coordinador durable conectado al runtime, reserva externa ni exactamente una entrega |
| Notificaciones | Outbox en memoria y SQLite con deduplicación, leases, rate limit y backoff | Transporte externo, Telegram ni recibo de proveedor |
| Panel | Renderizador accesible, preview sintética y proyección local agregada SQLite de #121 | Endpoint privado, identidad, autorización, conexión Site/DB ni controles operativos |
| Site #113 | Demostración privada publicada con datos sintéticos | Gestión real ni acceso nuevo de visitantes |
| Chromium | Imagen separada, smoke sin egress y medición de un arranque offline #43/#44 | Capacidad del droplet ni una visita real a Boca |
| Calidad | CI frozen, Ruff, mypy, tests, policy, auditoría Actions, Dependabot y escaneo de imagen Trivy | Todos los servicios de code/secret/dependency scanning habilitados: verificar sus permisos por separado |
| Entrega | Workflows manuales protegidos, digest/manifiesto, controles de SHA/intento, pre/postflight y limpieza selectiva | Publicación, instalación o salud real del controlador |
| Concurrencia Actions | #136 separó validación por PR y preservó un mutex constante para operaciones manuales | Paralelismo ilimitado de runners ni permiso de operación host |

## Host: evidencia y decisión requerida

#124 corrigió la pérdida del argumento vacío por SSH; #70 alcanzó UID10001.
#132 añadió diagnóstico fijo de ejecutables y estado de la unidad de usuario.
La [inspección #98](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258754195),
sobre `5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e`, observó runtime/bus propios,
controladores cpu/memory/pids, socket rootless ausente y socket rootful no
escribible. Docker, dockerd, wrapper y setup fueron encontrados; la unidad
`docker.service` del usuario dedicado informó `not-found/inactive/dead`.
No corresponde afirmar que Docker no está instalado. Tampoco se probó un
daemon apto, capacidad suficiente ni una base Boca operativa. El inventario
acotado de #140 informó candidate-absent para DB/WAL/SHM en los tres candidatos
rootless_default, staging_root y staging_data; ubicación global UNVERIFIED.
No se abrió, creó, movió ni migró SQLite. El gate del socket mantuvo NO_GO.
Recibo: 2026-10-31 21:54:17 ART, attempt1, job124707449992. No repetir #98.

La base configurada es `/data/boca.sqlite3`, persistida por Compose en
`boca-socios_boca_data`. SQLite corre embebida en Python; no exige un servidor
DB separado. Ese montaje previsto no prueba que archivo/volumen existan. Las
bases temporales de CI son fixtures, no la base del servicio.
`Database.migrate()` es una función del código: desarrollarla o corregirla no
crea una base operativa ni ejecuta una migración en el droplet. Las reproducciones
del defecto P1 usaron exclusivamente bases temporales sintéticas; no datos reales.

El dueño aprobó diagnóstico acotado de archivos, corrección P1 de preflight de
migración, #136 y mantenimiento documental. La elección de infraestructura o
lógica de negocio exige opciones, recomendación y aprobación explícita del
alcance. No se autorizaron instalación, release ni migraciones sobre DB reales.
Una aprobación específica permite completar sus pruebas sin volver a pedirla;
no constituye autonomía general para los hitos siguientes.

## Pendientes reales y orden

| Frente | Próximo resultado verificable | Dependencia o decisión |
| --- | --- | --- |
| Diagnóstico host | #140 integrado y #98 ejecutado: recibo limitado a tres rutas candidatas, sin contenido ni Docker | Completado ese alcance; ausencia global de DB y remediación siguen sin demostrar/decidir |
| Infraestructura | Opciones de remediación con impacto, aislamiento y recomendación | Decisión del dueño antes de modificar el host |
| Controlador en droplet | Preflight daemon/cgroups/capacidad apto; luego release por digest, instalación y postflight de salud/red/mounts/límites efectivos | Alcances aprobados y gates sucesivos; sigue NO_GO |
| Migración P1 | #141 integrado: valida ledger/checksum existente antes de DDL/WAL/chmod, con recheck e inicialización exclusiva de archivo nuevo | Corrección de código probada con fixtures; no auditoría completa de esquema ni migración de DB real |
| Simulación funcional | Conectar guardia durable y coordinación; probar reinicio, concurrencia y resultados ambiguos | #130 es candidato abierto, separado de main y sin runtime habilitado |
| Panel/Site | Elegir capa de acceso, identidad, autorización y conexión privada; lectura agregada primero | Presentar opciones/recomendación antes de decidir; #128 es adaptador propuesto, no listener ni Site conectado |
| Notificaciones | Ejercitar consumo sintético; diseñar reconciliación durable antes de transporte real | #134 es candidato sintético abierto; no habilita Telegram ni entrega exactamente una vez |
| Chromium | Egress de sistema acotado y capacidad de una sesión antes de observación pública real autorizada | Los filtros Playwright no sustituyen una frontera de red; no usar página Boca ficticia como evidencia |
| Alta y flujo real | Canal privado, identidad, custodia, coordinación de escritores, login/cola/eligibilidad y confirmación legítima | Hito separado; sin credenciales, sesiones, reservas ni compras reales ahora |
| Calidad/continuidad | Retener regresiones RCA ejecutadas; mantener este backlog y #45/#113 coherentes | Regla 84; un escritor por scope y evidencia exacta antes de cierre |
| PR históricos | Reconciliar #77/#83/#87; evaluar docs #75/#67/#15 y solapamiento mypy #3/#101 | No fusionar árboles viejos ni contar issues abiertos como funcionalidades necesariamente faltantes |

El controlador actual valida clave, aplica la migración inicial y espera con
`engine=off`, `site_calls=0`. Validarlo en el droplet no completaría una BETA
funcional. La guardia, API mínima o transporte sintético de candidatos abiertos
no alteran ese hecho. El backend de acceso al SQLite puede pertenecer al mismo
servicio; no está aprobada una nueva arquitectura de servicios independientes.

Los alcances autorizados con rutas disjuntas se prueban en paralelo; merges y
operaciones host se serializan. No tocar Porota/PPI Watch. Un fallo de fuente
pública se informa como semáforo asesor, sin justificar otro despliegue ni
relajar gates de código, imagen, host o autorización.

## Pendientes históricos por reconciliar, no completados por esta actualización

El [backlog anterior](https://github.com/mbalbo2023/boca-socios-assistant/blob/07cf424c92384a42e820b73befcaaeeaca87e8d9/docs/ROADMAP.md)
contenía estos requisitos específicos. El resumen de componentes integrados
no los elimina ni acredita su aceptación funcional. Revisarlos contra código,
pruebas y objetivo aprobado antes de cerrarlos o cambiar su alcance:

- Horarios de eventos en America/Argentina/Buenos_Aires e ingesta de avisos
  oficiales con procedencia verificable de cada fuente.
- Trazas estructuradas redactadas y objetivos medibles de visibilidad y
  notificaciones (SLA); no hay un SLA operativo demostrado por la CI.
- BrowserContext aislado por sesión aprobada y límite configurable de sesiones;
  múltiples contextos no prueban múltiples posiciones Queue-it ni autorizan
  concurrencia real sobre Boca.
- Retry, backpressure y diagnóstico observer-only del coordinador, además de
  las políticas ya implementadas por el outbox; probar su integración y fallos.
- Revisión de modelos de identidad, evento y categoría y su coherencia con la
  cuota de una entrada por socio/evento; la restricción DB no prueba todos los
  modelos ni su conexión a una interfaz.
- El backlog de flujo real incluía un paso de reserva con intervención humana
  y rastro de auditoría. Sigue como decisión de producto pendiente de discutir
  con opciones y recomendación; esta actualización no lo impone, elimina ni
  habilita reservas. También siguen sin verificarse el orden real login/cola,
  vínculo de sesión, elegibilidad y confirmación legítima del proveedor.

## Recuperación diferida por el dueño

Backup/restore operativo se retoma después de una versión productiva fiable.
#47 aporta una biblioteca offline; no prueba custodia ni restauración. El hito
no bloquea la simulación, pero ADR0012/0022 mantienen recuperación, custodia,
canal privado y ciclo de claves antes de alta real. #40 ya integró recifrado
interno dormido con migración0004 opt-in; faltan coordinación de escritores y
protección de DELETE para rotación real. No ejecutar backups ahora.
