# ADR 0252 — R247: limpieza exclusiva de fallos Boca V2

**Fecha:** 2026-11-12 ART. **Issue:** #417. **Estado:** CODE_ONLY,
sin PR, sin workflow ni ejecución en el droplet; BETA físico **NO_GO**.

## Causa raíz

En R245, la interfaz de `final_cleanup` del actor reutilizable podía entrar
en una implementación de limpieza diseñada exclusivamente para SUCCESS tras
una restauración del par anterior o una prueba final incierta. Su `NO_GO` de
retorno ocurría *después* del límite potencialmente destructivo. R246 separa
ese acceso y bloquea el executor SUCCESS cuando no está confirmado el par
nuevo. R247 aborda de manera independiente el finalizador para FAILURE,
con el requisito permanente de cleanup en la misma Action protegida.

La función genérica `host_boca_cleanup.execute` es capaz de clasificar
imágenes Boca obsoletas sin pertenencia al intento fallido, por lo que **no
se puede invocar su ejecutor productivo sin restringir sus `delete_exact`**.
Tampoco se debe inferir restauración a partir de un simple parámetro o del
texto de un receipt. La unidad de autorización sigue siendo la lease física
y el journal inmutable del intento, no un SHA que alguien escribió en un
formulario.

## Decisión implementada

`host_boca_upgrade_failure_cleanup_v2.py` es una ruta FAILURE separada del
`host_boca_upgrade_cleanup_runtime.py` de SUCCESS:

1. Verifica la lease protegida antes de efectos, que el directorio privado
   pertenece al UID Boca y que los archivos `intent` y `evidence` originales
   del **mismo intento** poseen enlace hash y coordenadas completas iguales
   a `PairCoordinates`, incluida la huella de los recursos retenidos.
   Rechaza symlinks, replay y un journal terminal previo. Si se afirma una
   restauración, la presencia de `commit` bloquea esa ruta.
2. Escribe un `failure-cleanup-v2.intent` **por intento** con `O_EXCL`, modo
   `0600`, fsync de archivo/directorio y readback SHA, antes de cualquier
   posible remoción. Una interrupción consume el intento y no se reintenta
   a ciegas. Otros intentos legítimos no reutilizan ni sobrescriben ese nombre.
3. Si no hay restauración comprobada, captura únicamente inventarios Boca
   con evidencia R108 y guarda un receipt V2 `outcome=FAILURE`,
   `status=NO_GO`, sin eliminar nada.
4. Si la compensación afirma `RESTORED`, exige el *binding* instalado anterior,
   sus CIDs, imágenes, hash de configuración, fuente, rol, montaje exacto de
   datos/clave/dueño/SITE/IPC, SQLite lógico `/data/boca.sqlite3`, controlador
   en marcha, worker CREATED/PID0, grafo de red y R108 en cada lectura.
   La remoción requiere un `retained_io` explícito del lector READ_ONLY
   revisado de R188; sin él se conserva `NO_GO` antes de eliminar recursos.
   La lectura física comprueba UID/rootless, destinos y permisos exactos de
   los montajes, nombres de redes por rol, ID y propietario de egress, y las
   huellas de inode **actuales** de SITE e IPC contra las del journal.
   Cualquier nuevo candidato en marcha, papel inexacto, identidad desconocida
   o cambio de binding aborta antes de nuevos efectos.
5. La allowlist de remociones se congela desde un inventario autenticado:
   únicamente contenedores detenidos del intento fallido con imagen OCI
   exacta, sus dos posibles imágenes de release cuando estén sin referencias,
   y volumen/red descartables con etiqueta del mismo intento y sin uso.
   Se **excluyen** todos los volúmenes protegidos, el par anterior, sus
   imágenes, R108 y cualquier imagen ajena o identidad incierta.
6. Reutiliza el bucle de inventarios y presupuesto (`MAX_DELETIONS=32`) del
   motor genérico, pero intercepta **cada** `delete_exact` con revalidación
   de journal, lease, binding, CIDs/montajes, R108 y allowlist. Un `Target`
   de volumen/red no basta por nombre/ID: congela el objeto íntegro del
   inventario inicial y exige que **etiquetas, propietario del intento,
   nombre/ID y adjuntos** coincidan otra vez justo antes del borrado.
   Para imágenes por ID inmutable exige además igualdad del objeto `Image`
   congelado (referencias y fuente), pertenencia actual al par de refs OCI
   candidatas y ningún contenedor referenciante. Un nuevo alias de otro
   servicio sobre el mismo ID no autoriza eliminarlo.
   La verificación
   de ausencia se hace por ID exacto. No hay Docker prune, `--force`,
   Compose global, SSH ajeno ni operaciones sobre Porota.
7. Convierte el mismo primer/último inventario en recibo canónico V2 de
   FAILURE con contadores de espacio/inodos, IDs eliminados, residuos y
   cuarentena R108. Persiste un terminal por intento con fsync/readback.
   Su objeto de retorno tiene **siempre** `state=NO_GO` y
   `apply_authorized=False`; aunque `cleanup_status=ACCEPT`, eso significa
   solamente que el subconjunto de residuos verificables fue procesado,
   **nunca que el deploy fue aceptado**.

## Evidencia y límites

- TDD RED inicial: el módulo no existía y 2 pruebas no podían importarlo.
  TDD RED de restauración: la primera implementación se negó a borrar los
  únicos candidatos verificables; la implementación final conservó el
  rechazo cuando esos candidatos estaban activos, su origen cambió o se
  perdió la lease.
- 21 pruebas sintéticas nuevas cubren: journal faltante o manipulado,
  `restored=False` sin efectos, restauración con retiro de un contenedor
  detenido e imagen suelta, redes/volúmenes descartables exactos, R108,
  cambio de binding, lease perdida, candidato activo, commit previo, imagen
  sobrevenida, symlink, replay y no interferencia entre distintos intentos.
  La revisión P1 independiente reprodujo **dos borrados no autorizados**:
  el mismo nombre de volumen o ID de red se reetiquetaban a otro intento
  entre el plan y `delete_exact`. Otra regresión detectó al worker antiguo
  unido a `boca_private`; el chequeo previo sólo validaba montajes. Se
  conservaron las tres pruebas RED y se añadieron rechazo de testigo físico
  ausente, drift del inode SITE y cambio del ID de egress.
- La revisión adicional del PR #496 reprodujo otro P1: entre el plan y
  `delete_exact`, la imagen candidata con el mismo ID recibía una referencia
  ajena o perdía su procedencia. El SHA anterior `cd3d93e0482a791eb803cc13de3552ea74745e59`
  intentaba eliminarla y terminaba con `cleanup_status=ACCEPT`. Dos pruebas
  nuevas (`foreign_reference` y `missing_source`) fallaron RED por ese motivo;
  luego de comparar identidad completa inmediatamente antes de cada borrado,
  el módulo pasó 23/23 pruebas locales. Esta evidencia sigue siendo CODE_ONLY.
- Validación completa local tras revisión P1: `PYTHONPATH=src pytest -q -n 4`
  = 7774 PASS, 1 SKIP
  (AF_UNIX restringido por kernel del sandbox) y 34 subtests PASS. Ruff,
  Ruff-format (980 archivos), mypy (188 módulos) y `check_repo_policy.py`
  pasaron. Esto **no** sustituye el postflight de host.
- El estado físico del droplet, del SQLite real, de Chrome/passkey y del
  worker no se certifica mediante estas pruebas. No hay Actions ni host
  escrito por R247.
- Falta un único integrador futuro que conecte esta ruta FAILURE al
  finalizador protegido en el punto exacto posterior a compensación,
  compruebe el journal de preflight/terminal en la misma lease y obtenga
  prueba física fresca. `requires_persistent_receipt=False` permanece
  intacto. R246 no se sustituye ni se evita.

**Resultado operativo:** NO_GO. Fix-forward; prohibido reintentar el APPLY
histórico R186 o aceptar por una línea verde del receipt de limpieza.
