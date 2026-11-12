# ADR 0244 — Release dual autenticada y ruta sucesora aún inelegible

Fecha: 2026-11-12 (ART). Issue #417. Estado: **CODE_ONLY / NO_GO / NO HOST APPLY**.

**Actualización R245:** esta ADR documenta el transporte tal como existía en
R244. R245 elimina, sólo para el selector sucesor, la extracción inicial de
ambos ZIP por `gh run download` y autentica íntegramente sus bytes en memoria
antes de crear archivos privados. R186 sigue prohibido y el interlock sucesor
permanece NO_GO. Ver [ADR 0248](0248-r245-consolidated-gates-and-followup.md).

## Decisión de seguridad

El selector protegido existente `boca-pair-upgrade-apply` **ya no invoca**
`host_boca_pair_upgrade_backend.apply`, la migración inicial R179. Ese backend
fija una fuente y run históricos, admite worker EXIT1 y presupone la ausencia
de SITE/egress. Reejecutarlo sobre el par instalado produciría condiciones de
riesgo R186. No se crea una segunda Action ni una segunda máquina de estados.

Se conecta el transporte y la autenticación dual de release **solamente** a
una ruta de preflight sucesora. Aunque los artefactos auténticos superen ese
preflight, la ruta emite recibo canónico `NO_GO`, `cleanup=INDETERMINATE`,
`commit_started=false`, `failed_phase=ATTEST`, código 3. No ejecuta Docker,
no obtiene lock, no escribe journal y no mueve el par. El interlock concreto
`ReusablePairUpgradeBackend.requires_persistent_receipt=False` sigue intacto.

## Frontera runner/host

La única Action original, condicionada al selector `boca-pair-upgrade-apply`,
mantiene sus gates independientes de owner, rama/main, checks, Environment,
run attempt 1 y pins exactos. Antes de SSH, descarga los **dos artefactos ZIP
reales** del run de release mediante `gh run download`. En directorio privado
0700, `host_boca_upgrade_release_bridge` utiliza el transporte GH REST R242:
para ambos roles verifica run/repo/workflow/commit/steps, metadata y digest
del artifact ZIP, bytes del miembro manifest y ref main antes y después de
cada rol. El token `GH_TOKEN` permanece exclusivamente en Actions.

Un testigo canónico de tamaño limitado vincula el SHA, run de release,
referencias controller/worker y hashes SHA256 de ambos manifests. Se crea
con `O_EXCL`, permisos 0600 y fsync; nunca contiene bearer. El builder
incluye exactamente esos tres archivos `release/*` más las fuentes explícitas
necesarias. El bootstrap verifica SHA256 del ZIP completo antes de ejecutar
Python aislado desde memfd. El host vuelve a comprobar estructura, hashes,
manifests y pins; **esa comprobación es integridad de transporte, no una
autenticación GitHub independiente**. Sólo el runner protegido que acabó de
autenticar R242 puede producir un bundle con procedencia confiable. Un
directorio de release ausente produce placeholders `NO_GO`, nunca una release
implícitamente aceptada. No existe entrada de usuario para elevar privilegio.

El CLI evita incluso evaluar el backend histórico al recibir el selector.
No obstante, el estado **NO_GO** es obligatorio también si se transportó la
release auténtica: la autenticación de imágenes no equivale a evidencia de
par instalado, recursos retenidos ni eliminación segura.

## Bloqueos para una futura habilitación

1. Falta un proveedor productivo de dos snapshots físicos independientes del
   par, IPC, SITE, egress, control inode y binding, capturados **bajo la misma
   lease que cubra todos los efectos**. El journal R243 tiene contrato
   `.evidence` O_EXCL/fsync y comparación, pero ninguna integración effectful
   captura esas identidades de manera duradera; no se simula el witness.
2. La Step Summary R189 `43281507903` no es un artifact autenticado. Falta
   resolver la procedencia de observación fresca y el `observation_run_id`
   distinto de los otros tres run IDs de `PairCoordinates`, sin inventar uno.
   El observador histórico de exactamente dos CIDs no sirve durante la
   coexistencia transitoria de cuatro IDs.
3. Faltan lectores/escritores productivos de Compose objetivo, stage, archivo
   antiguo y custodia R108, con postflight fail-closed tras la mutación. Una
   clase reusable y adaptadores puros no son una instalación física.
4. Cleanup V2 ofrece serializador/verificador puro de inventarios y excepción
   R108. El motor `execute_protected` actual no devuelve los snapshots before
   y after *internos* a la misma ejecución bajo lock. Una relectura independiente
   posterior no prueba `before.disk == receipt.before` ni
   `after.disk == receipt.after`, ni la ausencia global de referencias de
   imágenes. No se acepta un callback que devuelva simplemente `ACCEPT`.
5. No hay dos upgrades físicos repetibles, postflight de ambos servicios,
   rollback/compensación operativa del sucesor ni prueba del transporte real
   autorizado. Sólo después de cerrar cada contrato y revisión/CI exact-SHA
   se podría considerar cambiar el interlock. **No se cambió aquí**.

## Alcance de pruebas

El TDD local incluye fallos antes de implementar autenticación/ZIP/CLI,
tampering de cada manifest y proof, checks negativos de run/main/steps,
runner privado, rechazo de symlinks/extra files, importación y allowlist de
bootstrap, rechazo de bundle default ineligible, y regresión que demuestra
que el selector existente no puede volver a la migración inicial. Son pruebas
herméticas de contratos, **no** prueba de una transacción en el host, ni
certificado de limpieza R108 ni autorización de deploy. Las gates y el SHA
exacto deben registrarse al integrar este commit con Cleanup V2/UI/CI.

No hubo SSH al droplet, dispatch de GitHub Action, publicación de release,
push, navegación de Boca ni cambios de datos del host durante este trabajo.

## R244 — Closure adicional del sucesor sin activación

Tras autenticar un segundo observador independiente de recursos R188 y agregar
los contratos de captura *same-lease* y postflight, la allowlist cerrada del
bundle sucesor incorporó `host_boca_upgrade_same_lease`,
`host_boca_upgrade_postflight`, `host_boca_cleanup_v2` y sus dependencias
estáticas `host_boca_pair_postcommit`, `host_cutover_inventory_observe` y
`deploy_inputs`. La prueba TDD falló primero por ausencia de módulos,
posteriormente por importación transitiva desde un ZIP aislado; ambas
condiciones se resolvieron sin relajar el verificador de entradas exactas.

Medición con placeholder de release deliberadamente inelegible: **1 190 690
bytes** de fuentes frente al presupuesto fijo de **1 300 000** y ZIP
**304 965 bytes** frente al tope fijo de **480 000**. No se aumentaron cuotas
ni se modificó el `PAIR_UPGRADE_MAIN` de salida `NO_GO`. La importación de
ambos contratos desde `python -I` sobre el ZIP, las dos firmas autenticadas
simuladas y el bootstrap estricto quedaron cubiertos por pruebas focales.
Estos tamaños no son medición de un nuevo artefacto instalado ni de release
físico; el trabajo continúa sin utilizar el host.

La incorporación posterior de los dos adaptadores productivos **inertes hasta
que el runner aporte I/O autenticada** (`host_boca_upgrade_postflight_runtime`
y `host_boca_upgrade_cleanup_runtime`) no importó `host_first_deploy.py` ni
amplió los topes. Nueva medición reproducible del ZIP inelegible:
**1 216 421 bytes** contados (fuentes, `__main__` y recibos placeholder)
frente al tope de 1 300 000; los archivos fuente solos suman 1 215 990.
ZIP físico **312 279 bytes** frente al tope de 480 000. El test de
importación aislada y la allowlist exacta cubren también ambos módulos.

El contrato posterior `host_boca_upgrade_successor_runtime` se agregó a la
misma allowlist sin crear otro actor: `OneShotFinalCleanupBridge` vincula la
única ejecución del cleanup V2 con su recibo tipado, mientras
`PostflightGatedSuccessorBackend.finalize` impide devolver `ACCEPT` sin
postflight durable bajo la misma lease. El interlock de APPLY continúa
**False/NO_GO**. Medición del ZIP inelegible con los 68 miembros exactos:
**1 231 333 bytes** contados / 1 300 000 y **316 631 bytes** ZIP / 480 000.
La integración effectful del runner/host y la passkey física aún no existen.

### Regresión real de los 25 inputs de Actions y corrección R244

La primera corrida **conjunta** de la suite integrada halló 7 fallos pese a
7 688 pruebas aprobadas: tres contratos detectaron 26 entradas de
`workflow_dispatch` (límite de GitHub: **25**), y cuatro fixtures históricos
ejecutaron Bash con `set -u` sin la variable nueva de observación. No es un
problema de Docker ni justifica una reconstrucción o un APPLY de diagnóstico.

Se eliminó el input extra `retained_observation_run_id` y se reutiliza, **sólo
para `boca-pair-upgrade-apply`**, el input existente `official_news_run_id`
para el ID decimal autenticado R188 de observación retenida. Las dos variables
internas son excluyentes: `BOCA_RETAINED_OBSERVATION_RUN_ID` sólo recibe ese
valor en pair-upgrade; `BOCA_OFFICIAL_NEWS_RUN_ID` sólo lo recibe en operaciones
ajenas a pair-upgrade. El importador histórico conserva sin cambios la
semántica oficial de noticias; los campos no pertinentes continúan rechazados.
La admisión Bash histórica usa expansión `${BOCA_RETAINED_OBSERVATION_RUN_ID:-}`
para probar ausencia sin alterar `set -u`. Los 166 tests focales de esos ocho
archivos resultaron PASS tras un primer TDD RED. El chequeo integral y el CI
en runner GitHub deben confirmar la promoción; **NO_GO físico permanece**.

## R244 — Presupuesto de bundle tras la API de cleanup protegida

`execute_protected_with_inventories` incrementó `host_boca_cleanup.py` de
113 630 a 116 397 bytes (+2 767). El ZIP Cutover completo conservó sus **47
entradas exactas**; la única entrada con bytes nuevos es ese módulo de cleanup.
La compacción de comentarios ya revisada deja 1 157 003 bytes descomprimidos.
Se limitó **sólo** el presupuesto Cutover a 1 158 144 bytes (margen 1 141),
con el mismo límite en el bootstrap y prueba negativa un byte por debajo del
tamaño medido. No cambian el ZIP cap de 512 000 bytes, los presupuestos de
recovery/worker ni las allowlists. Los dos tests beta antiguos que exigían
eliminar IPC ahora comprueban que ese volumen retenido sobrevive a SUCCESS y
FAILURE incluso si una etiqueta histórica coincide con el attempt de limpieza.

Dos builds independientes del ZIP nuevo dieron exactamente
`487b55b5989ca7fd96ed09884ff5284697518b368b43fe61c23ae8ed51c7d20b`.
El pin R178 anterior
`80c458fbe314eadbd47e474dbdefa9d2f055f2e70137ef28110cc9ad241568fb`
queda intacto como antecedente histórico. El nuevo pin documenta una **nueva
compilación de fuente**, no modifica ningún archivo instalado en el host ni
habilita la migración histórica o un APPLY sucesor.
