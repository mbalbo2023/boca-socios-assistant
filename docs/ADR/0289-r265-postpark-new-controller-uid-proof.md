# ADR 0289 — R265: propietario remapeado del sucesor vivo antes de COMMIT

Fecha: 13-NOV-2026. Estado: CODE_ONLY, DEPLOY NO_GO.

## Problema y RCA

R262 cambió la captura estructural para atestar el UID/GID efectivo
desde `/proc/PID/uid_map`, `gid_map`, un `pidfd` vivo y el inode del
namespace de usuario. R264 agregó la doble comprobación de los tres
archivos Boca inmediatamente antes del marcador irreversible.
Las dos ramas pasaban aisladamente, pero su unión habría llamado la
captura **pre-PARK** después de detener el controlador original.
El PID del antiguo contenedor sería cero: un NO_GO permanente.
Corregir sólo la firma de la función no resolvía el problema temporal.

## Decisión

1. Antes de PARK, el productor `_before_park_storage(plan, lease)`
   exige el PID/namespace vivo del **CID antiguo**, custodia de los tres
   volúmenes Boca y doble verificación bajo la lease.
2. Después de `replace_binding`, y antes de COMMIT, el productor
   `_candidate_storage(plan, new_controller_id, new_worker_id, lease)`
   exige la vinculación instalada del intento/SHA/imágenes/CIDs exactos,
   comprueba el **CID nuevo** con PIDFD/namespace/mapeo real y relee la
   vinculación tras capturar tres inodes. Nunca consulta el viejo PID.
3. El backend guarded repite dos veces esa captura y la compara con la
   huella del seed pre-PARK, sin aceptar tamaños/tiempos cambiantes de
   SQLite/sesión. La clave preserva su hash V1 estricto; los otros dos
   archivos preservan V2 estructural.
4. Cualquier UID/GID, PID, namespace, volumen, CID, imagen, lease, inode o
   huella divergente produce `NO_GO/INDETERMINATE`. La existencia de un
   recibo técnico **no** acredita passkey del propietario ni BETA GO.

## Pruebas y límites

- Regresión TDD: una lectura ligada sólo al viejo PID hace fallar
  el caso válido; el productor corregido recibe el CID nuevo autenticado.
  Casos negativos cambian el CID del controlador y el worker y verifican
  que no se lee ningún inode nuevo antes de rechazar.
- Suite completa, formato, tipos, política y ZIP protegido deben aprobar
  en el SHA integrado de este alcance; pruebas aisladas no bastan.
- No se despacha operación de host, se publica release ni se toca Porota.
  R186 es irrepetible; APPLY conserva su NO_GO explícito.

## Pendiente físico

Probar en el droplet bajo la lease real el PIDFD, el namespace, el
remapeo y la custodia de los volúmenes, luego la identidad del par,
manifestos de release, passkey nueva y postflight 8443/worker/monitor/
SQLite. Un Action READ_ONLY fallido no otorga procedencia.
