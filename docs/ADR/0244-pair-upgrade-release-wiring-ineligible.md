# ADR 0244 — Release dual autenticada y ruta sucesora aún inelegible

Fecha: 2026-11-12 (ART). Issue #417. Estado: **CODE_ONLY / NO_GO / NO HOST APPLY**.

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
