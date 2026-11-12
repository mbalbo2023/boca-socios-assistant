# ADR 0236 — R186: cierre único postcommit del binding Boca

**Estado:** propuesto en PR R186, pendiente de CI/ejecución física.
**Fecha:** 12/11/2026 ART. **Incidente:** issue #417, APPLY 43217075287.

## Contexto

El upgrade de par cruzó commit, instaló dos CIDs nuevos y eliminó los
históricos. Su paso `RETIRE_OLD` falló por la lectura no resguardada del
campo Docker Health del worker detenido; R185 corrigió ese observador. Tres
capturas físicas READ_ONLY posteriores probaron el nuevo par, binding y
SQLite, pero el respaldo/intent históricos permanecen. Repetir el APPLY
destruiría el límite de recuperación y no es una operación equivalente.

## Decisión

Agregar **una opción específica** `boca-postcommit-finalize` al workflow
manual `boca-first-deploy.yml`, que ya dispone de mutex, propietario,
entorno Boca y SSH fijado. Mantener separado del pipeline de upgrade y de
las observaciones sin efecto.

El nuevo actor verifica journal original, ID/digests nuevos, binding,
archivo histórico e inode SQLite bajo lease Boca reciente. Crea una claim
única e irreversible en rootless UID10001 (`O_EXCL+fsync`) y reutiliza
exactamente el código de retiro de archivos ya existente. Tras el retiro,
requiere mismo par, binding e inode, ausencia exacta del respaldo e intent,
y un terminal propio `BOCA_POSTCOMMIT_FINALIZE`. El journal APPLY original
continúa `NO_GO`; no se reescribe ni se recicla su lease.

No se admite una nueva Action con SSH: el guard del repositorio lo impide.
No se relajan usuario rootless, host key, actor, main SHA, revisión de PR,
CI y seguridad postmerge, ni acceso al volumen privado de otros proyectos.
El worker queda detenido y ninguna función consulta tokens, fila, sitio,
credenciales ni ejecuta reservas reales.

## Alternativas descartadas

1. **Segundo `boca-pair-upgrade-apply` o rollback:** no es seguro tras el
   marcador irreversible y desaparición física de los CIDs originales.
2. **Borrado recursivo del directorio viejo:** no demuestra propiedad ni
   inodes; podría afectar datos ajenos.
3. **Reusar la lease/ID del APPLY anterior:** falsificaría provenance;
   la recuperación es un nuevo run con identidad propia.
4. **Un nuevo workflow con SSH:** viola la política `check_repo_policy`
   de canal único; la opción del workflow autorizado evita duplicarlo.
5. **Completar automáticamente a partir de un archivo parcialmente borrado:**
   exige un journal adicional por paso. En R186 se elige at-most-once y
   cuarentena tras cualquier efecto incierto, con RCA READ_ONLY posterior.

## Verificación exigida

- Pruebas negativas de journal, symlink, archivos, lease, claim, replay y
  cortes simulados; ejecutar el ZIP en Python aislado para descubrir imports
  faltantes además de comparar la allowlist.
- Ruff, formato, MyPy, política, suite íntegra y PR técnico exact-SHA.
- **Antes de SSH:** CI y Image security `push` con resultado SUCCESS para
  el nuevo SHA fusionado de main, aparte de tres testigos físicos previos.
- Una sola Action y terminal `ACCEPTED`; luego READ_ONLY del par, binding,
  SQLite y panel/passkey antes de declarar BETA integral instalada.

Referencia operativa: [handoff R186](../handoffs/2026-11-12-r186-postcommit-finalizer.md).
