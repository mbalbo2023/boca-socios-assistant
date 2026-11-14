# ADR0300 — R295: estado postdeploy, transporte Boca y compatibilidad Telegram

Fecha: 2026-11-14 UTC. Estado: DESARROLLADO EN RAMA, verificado offline; sin
promoción ni operación de host durante la aceptación Samsung.

## Contexto y fuentes canónicas

El titular pidió desarrollar los pendientes en paralelo mientras prueba, después
de comprobar que no existe implementación equivalente. R294 ya está instalado:
main/instalada `c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`, árbol
`a3498beafc614f3c59c4bac24a3d5708dcde55c3`, PR #516, release #865 y APPLY #1117
ACCEPTED. Administración #1118 y observación del par #1120 tuvieron éxito.
STATUS #1119 fue NO_GO; no se cambia ni oculta esa conclusión histórica.

- [Handoff R294 y evidencia física](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6871954660).
- [Matriz funcional #12](https://github.com/mbalbo2023/boca-socios-assistant/issues/12#issuecomment-6871968858).
- [Inicio R295](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6877933578).
- [Inventario, decisión y responsables](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878044872).
- [Dependencias de producción encontradas](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878127760).
- [Hallazgos de revisión y correcciones](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878174240).
- [Decisión de closure Telegram](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878184919).

Los tres agentes tienen scopes exclusivos; root conserva integración, documentación
y escrituras GitHub. Se reutilizó el worktree aislado y se creó
`feature/417-r295-beta-followups` desde main. No se repitió la suite local completa
del árbol base ya certificado. El plan está en
[R295 postdeploy followups](../superpowers/plans/2026-11-14-r295-postdeploy-followups.md).

## 1. Diagnóstico del par actual con ledger preservado

El status-current llamaba al lector estricto de autorización. Éste rechaza
correctamente un STOP asociado a otra huella, pero ese rechazo impedía observar
el par nuevo después de preservar SQLite durante el upgrade. La solución no
relaja `read_panel_status` ni `CURRENT_RETAINED`.

El observador lleva un programa fijo, acotado y de sólo lectura al controller
exacto, UID10001, mediante Python `-I -B -c`. Utiliza helpers ya instalados en
R294: ledger en `mode=ro`, `query_only`, transacción, comprobación de esquema y
checksums, e identidad del inode. No instala un archivo ni requiere otra imagen.
El recibo current pasa a schema 3, separando `installed.operation` de `ledger`:

| Alcance ledger | Significado |
| --- | --- |
| `NONE` | No hay una operación on-demand para proyectar. |
| `CURRENT_INSTALLATION` | Operación vinculada a la huella actual, validada con su detalle. |
| `NOT_BOUND_TO_CURRENT_INSTALLATION` | STOP/APPLIED genérico preservado sin vínculo actual; no es un recibo del nuevo par. |

El último caso sólo se admite con worker CREATED/PID0, no healthy, y motor
STOPPED. No permite recuperar la huella anterior ni atribuir notas históricas
desconocidas. REQUESTED, CLAIMED, UNCERTAIN, un START antiguo, corrupción o una
nota de la huella actual sin binding actual producen NO_GO. La lectura doble de
estado físico y ledger y la revalidación del binding rechazan carreras.

TDD usó SQLite real migrado, STOP/APPLIED de A y lectura con B. El caso pasó de
NO_GO incorrecto a una proyección separada, conservando inode y contenido lógico.
La revisión independiente reprodujo una nota actual huérfana; se añadió su
regresión y se cerró sin alterar el lector estricto. El resultado histórico
#1119 no se transforma en una observación física exitosa.

## 2. Transporte concreto de login Boca

Ya existían `BocaMemberAuthService`, vault, parser estricto de token/refreshToken,
monitor privado y UI. Faltaba un transporte concreto. El catálogo del cuerpo de
#12 contiene las referencias y la autorización del titular para reutilizarlas.
Se recuperaron estos nodos históricos, sin ejecutarlos:

- [Pany constants.js](https://github.com/pany100/bocasociosv2/blob/f107a88dba195fead329616529fa074df33be083/constants.js), blob `7478f8ea47f412578769543f41301fa45d1f937b`.
- [Pany login.js](https://github.com/pany100/bocasociosv2/blob/f107a88dba195fead329616529fa074df33be083/login.js), blob `adb052e68d416d51b0c501545c0dfac30559b3d4`.

`BocaHttpLoginTransport.login(email=..., password=...) -> bytes` implementa
originalmente ese contrato: POST al destino HTTPS fijo
`bocasocios-gw.bocajuniors.com.ar/auth/login/baas`, JSON email/password y
Origin/Referer del portal. Sólo devuelve 200 JSON de hasta 65.536 bytes al
parser existente. TLS verificado, una petición, sin redirects ni retries,
errores categóricos y timeout de socket finito (5 s por defecto, máximo 15 s).

El guard predeterminado exige el perfil automatic-observation, identidad/cgroups
del worker y sus interfaces existentes. El constructor es inerte. El módulo es
una hoja stdlib y `worker_health`: no incorpora vault, SQLite ni cryptography a
la imagen worker. La prueba de importación aislada detectó y eliminó esa
dependencia accidental antes de publicar.

Las cookies sólo provienen de un snapshot inyectado de la sesión legítima
existente. Se filtran dominio, path, HTTPS y expiración; se acotan cantidad,
metadatos y encabezado; se rechazan inyección y nombres ambiguos. Una cookie
host-only del dominio padre no se transmite al gateway. No se copió
`validate(true)`, TLS inseguro, fingerprints ficticios, logs ni creación de otra
sesión Queue-it. No se inventa un endpoint refresh.

**Pendiente de integración:** adaptar el contexto Chromium legítimo, transmitir
credenciales de manera privada desde su custodia actual, correlacionar una única
invocación con START/APPLIED y STOP, aplicar el deadline total del ciclo y publicar
en el monitor existente sólo si la operación sigue vigente. El timeout de socket
no es un deadline total. Un protocolo inyectable no prueba procedencia de sesión
ni propiedad física de red. Esta rama no presenta el transporte como un productor
conectado ni acredita login real.

## 3. Observer Telegram compatible y sin proyección falsa OFF

Se reutilizan el observer, caller de custodia, stage, passkey, nonce, cuatro GET,
outbox y sender existentes. El controller on-demand utiliza `unless-stopped` y
un bind canónico de control; el observer anterior sólo admitía `restart=no` y
cinco mounts. Ahora admite ambos perfiles coherentes, con mount bind exacto, RO,
`rprivate`, puerto loopback, identidad/config hash y lease intactos. No admite
mezclas ni mounts extras. Docker puede representar los puertos del worker
CREATED como null; el attestor existente ya define ese caso.

TDD y revisión encontraron dos problemas adicionales reales: la normalización
podía confundir un volume con el bind, y el inventario detenido podía contradecir
`State.Running` de worker/sender. Se exige tipo bind antes de normalizar y los
tres servicios deben confirmar Running/Restarting exactamente False. El lector
productivo permite únicamente el campo adicional `NetworkSettings.Ports`, ya
consumido por el attestor; no se amplía cleanup global ni se autoriza una mutación.

El witness sigue siendo `TOPOLOGY_OBSERVED_NOT_AUTHORIZED`, sender OFF y
`authorized=False`. Los pins se contrastan con IDs/labels/imágenes exactos;
el futuro backend debe derivarlos y autenticar su procedencia mediante el binding
actual. Una coordenada sintáctica no sustituye esa atestación.

## 4. Closure real de Telegram y límites intactos

El ZIP de Telegram necesitaba dos imports dinámicos que su selftest anterior no
ejecutaba: `host_on_demand_service.control_directory` y el validador de egress de
`host_first_deploy`. Incluir completo este último añadiría 373.558 bytes al
paquete de aproximadamente 429 kB, excediendo el tope de 450 kB.

Se incluye el módulo de control y se seleccionan por AST cuatro nodos existentes
de first_deploy: import ipaddress, constante de red, excepción y función de
validación. El módulo privado del ZIP contiene exactamente esos nodos, sin
entrypoints de deploy. La implementación canónica sigue única e intacta; no se
modifica su uso standalone ni se mantiene una copia manual del algoritmo.
La selección exige nodos únicos/completos e igualdad AST. El builder reutiliza
el compactor existente de comentarios sólo si hace falta, comprobando AST,
bytecode y líneas, sin elevar caps.

Una prueba `python -I -S` ejecuta la comprobación real del perfil on-demand desde
el ZIP, con datos ficticios y sin checkout, Docker ni efectos. Incluye negativos
de egress; el selector `activate` continúa NO_GO. No basta con importar módulos.

Medición local de los paquetes afectados, antes de publicar el candidato:

| Paquete | Fuente expandida | Archivo ZIP | Tope fuente | Margen |
| --- | ---: | ---: | ---: | ---: |
| Full protegido | 1.144.644 B | 272.825 B | 1.158.144 B | 13.500 B |
| Admin/status instalado | 838.466 B | 204.692 B | 900.000 B | 61.534 B |
| Telegram | 446.293 B | 126.083 B | 450.000 B | 3.707 B |

El bundle de pair-upgrade no contiene `host_on_demand_status`; no se le atribuye
un cambio ni se repite su certificación sin dependencia. Las cifras anteriores
son de packaging, no tiempos de CI, publicación o despliegue. Los tiempos de
Actions del SHA definitivo se registran en #417 sin otro commit documental.

## Verificación y revisión

Se ejecutaron conjuntos focales, con solapamientos; sus cantidades no se suman
como si fueran pruebas únicas:

- Status/lifecycle/egress/CURRENT_RETAINED: 79 PASS iniciales; admin/workflow 12
  PASS. Después de corregir la nota huérfana: 47 PASS del conjunto afectado,
  incluidas sus dos variantes. Revisión independiente cerrada.
- Transporte Boca y contrato de autenticación existente: 59 PASS, incluida la
  importación aislada. Revisión independiente cerrada.
- Telegram observer/reader/topología/callers/owner-lease: 135 PASS después de la
  corrección; el reviewer verificó las 32 variantes nuevas del estado físico.
- Closure Telegram: 7 PASS, después de reproducir dos fallos reales de ZIP.
- Packaging full/admin y texto privado: 5 PASS focales.
- Ruff, formato, mypy pertinentes y diff-check se completan sobre el candidato;
  Actions conserva los checks obligatorios del SHA exacto y el ruleset de main.

Se reemplaza el texto “al finalizar la simulación” por “al finalizar el ciclo”
en la detención automática. El motivo concreto sigue en Monitor/Actividad.
No se añadió una prueba que sólo replique ese texto trivial.

## Estado y continuación

| Alcance | Estado al corte |
| --- | --- |
| R294: instalación del par, provisión y observación física | IMPLEMENTADO Y VERIFICADO mediante #1117/#1118/#1120; no repetir. |
| Flujo automático Queue-it, actividad, auto-stop, SITE_URL | IMPLEMENTADO; aceptación funcional posterior del titular pendiente. |
| START/STOP nuevo y Chromium durante la prueba | PENDIENTE de evidencia posterior; CREATED/PID0 no certifica un START nuevo. |
| Diagnóstico actual y compatibility Telegram de R295 | DESARROLLADO EN RAMA, verificado offline; sin verificación física nueva. |
| Transporte login Boca | DESARROLLADO EN RAMA, verificado offline; wiring automático PENDIENTE. |
| Activación Telegram | PENDIENTE: backend/attestor físico, preparación pública, custodia/sender V2, observador final y aceptación sin borrar historia. |
| Recepción Telegram por el titular | PENDIENTE; API accepted nunca equivale a recepción humana. |
| Refresh automático Boca | PENDIENTE de contrato acreditado; no se inventó. |
| Repetir deploy R294 o reutilizar STOP anterior como prueba nueva | DESCARTADO. |

No hay un bloqueo externo para revisar/publicar este código. La aceptación del
titular y las operaciones físicas posteriores se mantienen separadas. No ejecutar
release, APPLY, operaciones de host o mensajes durante su prueba. El siguiente
paso funcional exige un diseño serial del wiring privado Boca y del backend
Telegram, reutilizando los contratos auditados y conservando la única sesión,
custodia, límites y recuperación por fase. No eliminar un NO_GO para simular esa
integración.
