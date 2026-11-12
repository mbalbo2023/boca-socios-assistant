# Adaptadores de evidencia de upgrade — preparación local NO_GO

Base: `95591d33134cf055f73f8739d51f9bb742064ee9`. Fecha: 2026-11-12 ART.
Scope exclusivo: un módulo nuevo, sus tests y este plan. No modificar actor
`8fb7dcb`, R188/R189, CI, workflows, selectores, bundles ni finalizador R186.

**Reconciliación local:** los commits actor `d6dee35`/`8fd87c0`/`8fb7dcb` y
adapters `6469560` se combinan ahora desde main
`1089de83492d517ca67979dba9c7a34436ffc376`. Los dos módulos y sus tests
originales se conservan byte por byte; la integración agrega sólo un test de
boundaries y este handoff. Las pruebas usan un bridge exclusivamente local al
test, no un proveedor/bridge productivo. `requires_persistent_receipt=False`
permanece intacto y el bundle effectful generado excluye ambos módulos.

## Decisión y límites

Preparar adaptadores de evidencia reutilizables, no otra ruta de ejecución:

1. Verificar dos manifests release y su metadata autenticada, con source SHA
   y digests por rol exactos. Un parser de JSON y un label OCI no autentican
   GitHub. La frontera de autenticación es explícita y obligatoria; no hay
   proveedor predeterminado ni lectura automática de credenciales/red.
2. Consumir el recibo canónico READ_ONLY R188/R189 V1 sólo como seed de custodia.
   Ese observer fija el par b61/43217075287 y exactamente dos CIDs; no usarlo
   durante coexistencia de cuatro CIDs ni parchear sus constantes por release.
3. Revalidar genéricamente el graph exacto autorizado por el journal y los
   mismos IPC/SITE/egress bajo la lease actual. Separar creator de instalación,
   comprobar mounts, worker CREATED/PID0, peers y dos snapshots estables. El
   IO es inyectado y sin default host. No leer Env, contenidos SQLite, URL o
   credenciales. El inode de control viejo se prueba sólo antes de park; el
   nuevo bind necesita su propio witness antes de commit, no igualdad falsa.
4. Verificar cleanup detallado contra snapshots antes/después y diferencias
   exactas, referencias globales e identidades conservadas; persistirlo una
   vez con O_EXCL/fsync/readback bajo lease antes de devolver evidencia.
   No agregar deleter: este adaptador no ejecuta ni acredita por sí solo el
   motor effectful de cleanup aún pendiente, ni acepta un literal ACCEPT.

Las salidas siempre mantienen `apply_authorized=false`. No CLI, selector,
dispatch, bridge al actor ni mutaciones Docker/systemd. La única escritura
implementada es `persist_cleanup`: **sí escribe un archivo LOCAL** de evidencia
con O_EXCL/fsync/readback y lease activa, en la raíz Boca validada; no es una
función de "zero effects". En esta tarea se prueba exclusivamente contra
directorios temporales locales, sin host wiring. No se invocará en
el host en esta tarea. No publicar ningún commit ni PR.

`CleanupEvidence.coverage=IMAGE_RECEIPT_ONLY`: ni siquiera su `status=ACCEPT`
equivale a la limpieza integral de una instalación. El puente futuro no puede
convertir ese estado en el string final del actor sin completar los witnesses
de stage/archives/retenciones, el journal y la excepción histórica R108. El
parser V1 rechaza deliberadamente V2/quarantine hasta contar con su adaptador
histórico auténtico. No reinterpretar ese rechazo como permiso de borrar la
imagen forense para simplificar el recibo.

## TDD y aceptación local

- RED de release sin autenticador, source/run/role/digest cruzados, JSON
  duplicado/contaminado y metadata de otra ejecución; GREEN mínimo.
- RED de witness V1 NO_GO/otro run/provenance falsa y de graph 2–4 CIDs,
  inode/network drift, peer ajeno, worker activo, mounts ajenos o snapshots
  inestables; GREEN sin I/O productivo.
- RED de cleanup string/duplicados, métricas ausentes, desapariciones no
  registradas, imagen todavía referenciada, IDs ajenos, receipt replay,
  symlink y pérdida de ACK; GREEN con inode/lease reales temporales.
- Ruff, formato, mypy, política, focales y suite completa con todo SKIP/FAIL
  registrado. Tests de contrato no equivalen a dos upgrades físicos.

## Integración futura, aún NO_GO

El integrador deberá implementar un proveedor autenticado que vincule la
respuesta real Actions, workflow/operation, actor, attempt=1, main/source,
artifact o transporte protegido y digest del payload exacto. Los digests de
archivos manifest NO son el digest del ZIP de artifacts: el proveedor debe
verificar archive digest y extracción/allowlist antes de autenticar el archivo.
Para R188/R189 no inventar un artifact: su recibo actual sale del transporte
protegido/summary; autenticar esa ruta real y su run/source.

Se requiere journal durable que ate ambos manifests, seed/witness y pins,
derivación de CIDs exclusivamente desde binding/journal, relectura en la
misma lease, motor de cleanup acotado y recibo duradero. Retener stage activo,
datos/key/owner/IPC/SITE/egress e imagen de cuarentena R108 hasta la prueba
histórica exacta; nunca inferir permiso de borrado del nombre o de un string.
Las imágenes no clasificadas y cualquier deriva quedan NO_GO.

La conversión a `RetainedResourcePins` del actor será un bridge explícito
posterior; este módulo no copia ni importa el actor ausente de esta base.
No cambiar su interlock FALSE hasta evidencia auténtica e integración revisada.
Repetibilidad E2E y aceptación física: **NO_VERIFIED**. Porota, host ajeno,
navegación real, tokens, reservas y Telegram quedan completamente fuera.

## Wiring mínimo y criterios exactos antes del primer efecto host

1. **Freeze de evidencia:** integrar R189 por PR/CI, obtener un recibo genuino
   de observación con `state=READ_ONLY`, provenance esperada true, worker
   CREATED/PID0 y recursos estables; autenticar el run y source del observer,
   distintos del source b61 instalado. Un failure frame o run incompleto es
   NO_GO. R186 debe quedar certificado sin reescribir el APPLY original.
2. **Integración de fuentes:** incorporar el actor bloqueado y estos adapters
   en una sola rama; agregar sólo un bridge que transforme ResourcePins al
   tipo exacto del actor. Mantener interlock FALSE mientras se implementan
   proveedor autenticado y el motor de cleanup faltantes. No nuevo selector.
3. **Provenance:** usar los artifacts reales `boca-release-manifest` y
   `boca-browser-release-manifest` de un único release first-attempt exitoso,
   source igual al main exacto; validar archive digest/member allowlist y los
   dos payloads antes del bridge. Validar además CI/Security/PR0/Environment y
   triggering owner conforme a las guardas existentes; no copiar booleanos
   del formulario ni reutilizar artifacts PR como release protegida.
4. **Journal y IO:** antes del primer stage/pull, O_EXCL/fsync del intent con
   digests de manifests/witness/pins y CIDs del binding; mismo lease rootless
   para el resto. El provider IO valida daemon/storage/socket real y lee los
   2–4 IDs exclusivamente del journal; no vuelve a llamar al observer V1
   fijado a dos CIDs durante park/create. Orígenes de recursos no cambian.
5. **Cleanup integral:** añadir el motor effectful de borrado exacto acotado,
   conservación del stage activo, verificación de stage/archives obsoletos,
   excepción R108 con su release/prueba física auténtica, detalles duraderos
   antes/después y reobservación final del par/binding/SQLite/pins. Este módulo
   no implementa ese motor. Cada error intenta cleanup seguro; incertidumbre
   se retiene y vuelve NO_GO/INDETERMINATE, sin retry automático.
6. **Laboratorio integrado previo:** ejecutar el ZIP en Python aislado para
   comprobar imports/allowlist/límites; probar rollback precommit y cortes en
   todos los boundaries, commit fsync incierto, retire ACK perdido, cleanup
   fallido, drift y replay. Exigir cero arranques de worker y cero navegación.
   Probar dos secuencias completas consecutivas con sources/attempts nuevos y
   recursos originales constantes. Hasta entonces repetibilidad E2E sigue
   NO_VERIFIED; los graphs de dos/cuatro CIDs de estos tests no la prueban.
7. **Habilitación revisada:** sólo después de esas pruebas y evidence chain,
   remover explícitamente el interlock en la misma revisión de wiring de la
   operación existente, sin cambiar permisos ni protección. Exigir todos los
   checks del SHA exacto; un SKIP local no es evidencia de runner/host.
8. **Instalación:** release dual del main integrado exacto, relectura fresh
   bajo lease y una única operación protegida autorizada, con receipt terminal
   y cleanup completo. Verificar luego panel/passkey/POST móvil por separado.
   No afirmar worker activo, egress real o reservas por haber instalado en
   reposo. Esta preparación local no autoriza ese dispatch.

## Evidencia de esta preparación local

TDD observado por incrementos: 13 casos release RED→GREEN, 16 seed/graph
RED→GREEN y 12 cleanup RED→GREEN, más regresiones de metadata Actions real,
network compartida, alcance de receipt, referencia OCI ambigua y revocación
de lease entre capturas. Focales finales: **48 PASS**. Suite final completa
`pytest -q -n 4`: **7280 PASS +34 subtests**, un SKIP preexistente en
`test_r177_fixture_probe_transport.py:72` por AF_UNIX EPERM del sandbox.
Ruff, formato (926 archivos), MyPy (175 fuentes), policy y diff-check PASS.
Estos son resultados locales del contenido preparado, no checks GitHub del
futuro SHA integrado, pruebas del host ni permiso de activación.

## Estado combinado y siguiente autorización real

Los cinco tests de integración se observaron RED en main por ausencia de los
módulos y GREEN tras combinar los cambios, con 73 contratos focales PASS
(20 actor, 48 adapters, 5 integración). La combinación no elimina ninguno de
los ocho gates anteriores. Antes del wiring, R189 debe estar fusionado y su
lectura física auténtica debe demostrar el seed esperado; un source parser
verde o un recibo fabricado por fixture no reemplazan esa observación.

El siguiente scope debe integrar un proveedor autenticado real y read-only IO,
atar sus payloads exactos al journal, definir expresamente la correlación del
run de observación con el run de APPLY, y completar cleanup stage/archives/R108
con recibo duradero. No resolver esos vínculos con constantes nuevas ni
booleanos de formulario. Después se exigirán laboratorio integrado/failpoints,
dos secuencias completas offline y tests del ZIP aislado, manteniendo el
interlock FALSE hasta una revisión explícita de habilitación. La operación
existente seguirá siendo la única ruta protegida; nada de esta rama autoriza
un dispatch, host o navegación real. E2E físico: **NO_VERIFIED**.
