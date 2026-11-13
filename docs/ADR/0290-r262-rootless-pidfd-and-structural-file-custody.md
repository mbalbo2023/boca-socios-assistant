# ADR 0290 — R262: UID mapeado y namespace real en custodia estructural

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** CODE_ONLY / DEPLOY NO_GO.

## RCA y contrato

El lector estructural R247 exigía `st_uid/st_gid == 10001:10001` en el
**host**, aunque un archivo creado por UID10001 **dentro** del contenedor
rootless puede tener propietario subordinado diferente. Una comparación
host-only causa falso rechazo; aceptar cualquier propietario o calcularlo
desde `/etc/subuid` crearía un falso PASS. La Action READ_ONLY
`boca-rootless-mapping-observe` todavía no ha acreditado los tres archivos
en el droplet; su ejecución #43362162288 terminó NO_GO genérico, sin causa
física identificable. No inferir de ella el mapeo actual.

## Decisión implementada en fuentes, sin activar APPLY

1. `host_boca_rootless_mapped_custody.read_container_mapped_owner` toma
   exclusivamente el CID del controlador ya atestado por los dos observadores
   del par Boca, exige su PID Docker positivo antes/después, obtiene `pidfd`
   y comprueba que el proceso no haya terminado. Lee el **inode real** de
   `/proc/<PID>/ns/user` mediante el enlace kernel `user:[inode]`, verifica
   que sea diferente del namespace del proceso host, y repite namespace,
   `uid_map` y `gid_map` efectivos. Rechaza mapas ambiguos, ausencia de
   permisos, cambio de PID, namespace o lectura. No usa `/etc/subuid`.
2. La lectura estructural de los tres archivos Boca usa propietario
   `MappedOwner` obtenido de la identidad de ese controlador bajo la misma
   lease, y lo vuelve a atestar tras capturar inodes con `O_PATH` y
   `O_NOFOLLOW`. Compara UID **y** GID, dev/inode, modo privado, nlink único
   y raíz/volúmenes previamente autenticados. El hash estructural de SQLite
   y sesión conserva el dominio V2; el archivo de clave conserva el dominio
   V1 con `size/mtime/ctime` para detectar sustitución. No se abre el
   contenido de DB, clave o sesión ni se serializan UIDs subordinados.
3. La captura previa a PARK revalida el mapa del **controlador anterior**
   identificado por el recibo R177, los tres volúmenes local/labels/mount,
   y el mismo mapeo después de leer metadatos; su observación externa de par
   antes/después y la lease original siguen siendo obligatorias. Una
   ausencia, diferencia o excepción es NO_GO previo a mutación.
4. El observador preliminar READ_ONLY R259 retiene los cotejos de PID Docker
   con el par exacto y pasa a usar este mismo testigo `pidfd`/namespace para
   ambas lecturas de propietario. No puede emitir `PRELIMINARY_PREDEPLOY`
   si el PID se reutilizó, el namespace cambió o el sensor rechaza la lectura.
   En ningún caso ese estado preliminar autoriza el deploy.

## Frontera y evidencia faltante

El selector de APPLY del CLI permanece incondicionalmente NO_GO y el
postflight técnico no sustituye aceptación Chrome/passkey, SITE_URL,
worker/monitor/SQLite ni cleanup V2. La disponibilidad física de `pidfd`,
lectura `/proc/<PID>/ns/user` por UID10001, ausencia de mounts idmapped
inesperados y titulares reales de los tres inodes **no están comprobados**.
Si el host niega alguno, no escalar permisos ni suponer igualdad UID host;
se exige observación Boca-only separada y RCA sin secretos.

Pruebas TDD locales ejercitan fallo sin mapeo explícito, equivalencia de
hash de clave, drift de mapas/inodes, PIDFD terminado, cambio de namespace,
igualdad sospechosa con namespace host, symlinks y lease. Sobre la rama
aislada reconciliada con main `4bc9447`, `pytest -q` obtuvo **8186 PASS,
1 SKIP AF_UNIX EPERM del sandbox, 34 subtests**; las 14 pruebas especiales
de transportes autenticados pasaron, Ruff formato/check, MyPy de cuatro
módulos y política del repositorio pasaron. El ZIP PAIR verificado tiene
82 entradas, 354722 B comprimidos, 1402851 B expandidos (reserva posterior
a código >50 kB); el ROOTLESS 62 entradas, 358575 B comprimidos y
1397350 B expandidos, 2650 B debajo del máximo de 1,4 MB. No se modifica
el límite protegido de 1,5 MB ni su reserva de 50 kB; una compilación
local no equivale a un release o host ACK.

Porota y Docker ajeno no forman parte de este cambio, sin reservas reales,
bypass de fila, TLS relajado, SSH, host writes ni repetición del incidente R186.
