# Backlog comprobado y decisiones pendientes

Este documento separa código integrado, evidencia de ejecución y propuestas.
El [checkpoint vigente #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
identifica la HEAD y los runs que deben revalidarse antes de operar. Un candidato
con CI verde no cuenta como integrado ni como servicio funcionando en el host.
Rige la [Regla 84](../AGENTS.md#rule-84--documentation-must-remain-factual-and-current):
actualizar la documentación afectada en el mismo PR y reconciliar el checkpoint
antes de cerrar el alcance; conservar cortes anteriores sólo como históricos.

El corte de código reconciliado incorpora #136/#140/#141 y los componentes
#130/#128/#134/#148/#149/#150/#152, hasta `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`. Esto identifica el código revisado;
la inspección #98 citada abajo corresponde a su propio SHA anterior.

Evidencia operacional: [recibo120](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756);
la HEAD y decisiones posteriores se mantienen en #45.
[Antecedente de Regla84](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551338776);
la dirección vigente de esta etapa se enlaza a continuación.

## Etapa de entrega aprobada

El [plan versionado BETA](BETA_DELIVERY_PLAN.md) y ADR0056 incorporan la nueva
[dirección del dueño](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142).
La [matriz UI completa](BETA_DELIVERY_PLAN.md#matriz-completa-de-alcance-ui-panel-propio-y-site-complementario)
conserva todas las funciones conversadas y distingue diseño, código integrado,
operación, diferidos y necesidades sin definición; no promete Site operativo
ni «gestiona todo». Se comienza según las recomendaciones: alta privada obligatoria de socios,
coordinación/avisos, preparación rootless dedicada y panel propio, pruebas E2E
y medición de rapidez/recursos con integridad. No pedir otra vez permisos para
pasos rutinarios dentro del alcance. La ubicación lógica delegada queda decidida:
`/data/boca.sqlite3` en `boca-socios_boca_data`, clave externa. La existencia
global actual continúa UNVERIFIED; no reemplazar almacenamiento encontrado.

Esta autorización de desarrollo no habilita credenciales/login/cola/reserva
real, migraciones sobre una DB existente ni publicación/instalación sin el
candidato concreto y sus gates. Identidad/bootstrap y acceso privado se
presentarán con opciones verificables antes de activarlos. El plan mantiene
recibos por entrega; no promete un robot de actualización separado.

## Fundación y componentes integrados

| Área | Comprobado en el repositorio | Lo que aún no demuestra |
| --- | --- | --- |
| Persistencia | SQLite WAL, migraciones, unicidad socio/evento y cantidad 1; vault AES-256-GCM con clave externa | Existencia de DB en el droplet, alta real ni recuperación operativa |
| Simulación | Estados/cola, navegador sintético, guardia/coordinador130 y comandos149 integrados; migraciones0005/0006 opt-in | Sin runtime/comandos web conectados, reserva externa ni exactamente una entrega; ninguna migración real aplicada |
| Notificaciones | Outbox en memoria/SQLite y dispatcher sintético #134, límites/fencing/retry y reporte transitorio de ambigüedad | Sin wiring runtime, transporte externo/Telegram/recibo; crash antes de settlement aún puede reintentar |
| Panel | Renderizador, preview/proyección local #121 y adaptador GET128 y formulario/handler148 integrados, default-deny | Sin listener, identidad real/TLS, lista socios, Site conectado ni controles operativos |
| Site #113 | Demostración privada publicada con datos sintéticos | Gestión real ni acceso nuevo de visitantes |
| Chromium | Imagen separada, smoke sin egress y medición de un arranque offline #43/#44 | Capacidad del droplet ni una visita real a Boca |
| Calidad | CI frozen, Ruff, mypy, tests, policy, auditoría Actions, Dependabot y escaneo de imagen Trivy | Todos los servicios de code/secret/dependency scanning habilitados: verificar sus permisos por separado |
| Entrega | Workflows manuales protegidos, digest/manifiesto, controles de SHA/intento, pre/postflight y limpieza selectiva | Publicación, instalación o salud real del controlador |
| Concurrencia Actions | #136 separó validación por PR y preservó un mutex constante para operaciones manuales | Paralelismo ilimitado de runners ni permiso de operación host |

## Host: servicio preparado, aplicación pendiente

PR #150 integró prepare-rootless; [run #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418)
lo ejecutó una vez sobre `6be606f83c5a6afe0ba7226abbca6a09276d1ca1` y produjo
SERVICE_READY con application_database=not_accessed/application=not_installed.
Se verificó el daemon rootless propio, cgroupv2-systemd, overlay2, data root
privado, cero contenedores y namespace Boca vacío; no se instalaron aplicación,
imágenes, SQLite ni volúmenes/clave. [Recibo completo](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).
La capacidad fue informativa (application_budget=not_checked); faltan capacidad
y postflight efectivos de la BETA. No reejecutar primera preparación sobre la
configuración existente. El marcador DEPLOY se añadió sólo al entorno protegido
para esta operación; no habilitó release ni constituye aceptación de la BETA.

#124 corrigió SSH y #132/#140 agregaron diagnósticos. La inspección histórica98
había hallado el servicio ausente y candidate-absent para DB/WAL/SHM en tres
rutas fijas. #120 resuelve el servicio, pero no convierte ese inventario acotado
en una prueba de inexistencia global de DB. Ubicación global sigue UNVERIFIED.

La base configurada es `/data/boca.sqlite3`, persistida por Compose en
`boca-socios_boca_data`. SQLite corre embebida en Python; no exige un servidor
DB separado. Ese montaje previsto no prueba que archivo/volumen existan. Las
bases temporales de CI son fixtures, no la base del servicio.
`Database.migrate()` es una función del código: desarrollarla o corregirla no
crea una base operativa ni ejecuta una migración en el droplet. Las reproducciones
del defecto P1 usaron exclusivamente bases temporales sintéticas; no datos reales.

Los diagnósticos/fixes anteriores están integrados. El alcance aprobado ahora
incluye preparar la BETA según el plan enlazado, con destino lógico definido y
alta privada obligatoria; la aceptación final todavía requiere evidencia.
Las decisiones fuera de ese alcance conservan opciones/recomendación/aprobación.
No se autorizaron credenciales reales ni migraciones sobre una DB real; release
y primera instalación se deciden sobre el candidato concreto validado.

## Pendientes reales y orden

| Frente | Próximo resultado verificable | Dependencia o decisión |
| --- | --- | --- |
| Diagnóstico host | #140 integrado y #98 ejecutado: recibo limitado a tres rutas candidatas, sin contenido ni Docker | Completado ese alcance; existencia global sigue UNVERIFIED. Preparación rootless completada en120; presupuesto/capacidad de aplicación aún por probar |
| Infraestructura | Servicio rootless preparado y verificado en120 | Preparación cerrada en ese alcance; presupuesto/preflight y aceptación de aplicación siguen pendientes |
| Controlador en droplet | Preflight daemon/cgroups/capacidad apto; luego release por digest, instalación y postflight de salud/red/mounts/límites efectivos | Alcances aprobados y gates sucesivos; sigue NO_GO |
| Migración P1 | #141 integrado: valida ledger/checksum existente antes de DDL/WAL/chmod, con recheck e inicialización exclusiva de archivo nuevo | Corrección de código probada con fixtures; no auditoría completa de esquema ni migración de DB real |
| Simulación funcional | Módulos130/149 y composición en proceso152 integrados; runtime/HTTP aún por conectar | Integración de biblioteca no habilita motor; migraciones0005/0006 opt-in, loop persistente y recuperación exclusiva |
| Panel y alta/Site | Panel propio con Socios > Agregar socio obligatorio; servicio cifrado, acceso privado y comandos sintéticos | #128/148 son adaptadores integrados; lista/servidor/identidad/bootstrap/acceso pendientes. Site sigue complemento |
| Notificaciones | Conectar avisos locales al panel/recorrido; reconciliación durable antes de transporte real | #134 sintético integrado; Telegram pendiente explícito, sin entrega externa exactamente una vez |
| Chromium | Egress de sistema acotado y capacidad de una sesión antes de observación pública real autorizada | Los filtros Playwright no sustituyen una frontera de red; no usar página Boca ficticia como evidencia |
| Alta sintética / flujo real | Alta privada incluida en BETA con datos sintéticos; flujo real conserva identidad/consentimiento/custodia/login/cola/confirmación | No confundir biblioteca interna con formulario operativo ni alta local con validación Boca; credenciales y acciones reales excluidas |
| Calidad/continuidad | Retener regresiones RCA ejecutadas; mantener este backlog y #45/#113 coherentes | Regla 84; un escritor por scope y evidencia exacta antes de cierre |
| PR históricos | Reconciliar #77/#83/#87; evaluar docs #75/#67/#15 y solapamiento mypy #3/#101 | No fusionar árboles viejos ni contar issues abiertos como funcionalidades necesariamente faltantes |

El controlador actual valida clave, aplica la migración inicial y espera con
`engine=off`, `site_calls=0`. Validarlo en el droplet no completaría una BETA
funcional. Los componentes de guardia, adaptador de lectura y dispatcher sintético
integrados no alteran ese hecho. El backend de acceso al SQLite puede pertenecer al mismo
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
