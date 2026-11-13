# ADR 0296 — R281: restitución PRECOMMIT del par original sin volver a desplegar

**Fecha:** 13-NOV-2026 (ART). **Estado:** candidato CODE_ONLY; ejecución física pendiente.

**Autoridad:** [handoff R277](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861598271),
[RCA R276](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861462459),
[R278](0295-r278-postpark-incident-custody-readonly.md).

## Hechos separados

- Un despliegue anterior dejó un par genuino funcionando; la release #863 del
  código nuevo y el APPLY #1085 no equivalen a una actualización instalada.
- El APPLY [#1085](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43479367282)
  estacionó el control anterior, falló en el guard del inode canónico después
  de ese `PARK`, dejó ambos contenedores antiguos detenidos y no llegó a COMMIT.
- La observación READ_ONLY
  [#1090](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43489690300)
  confirmó `OBSERVED_PARKED`, `PRECOMMIT_NO_GO_TERMINAL`, CIDs anteriores
  exactos, inode de control estacionado, puerto sin salud y **cero escrituras**.
  No certificó todos los inodes de DATA/KEY/OWNER ni autorizó RESTORE.
- Un error de comparación de rutas SQLite surgió **en el primer candidato de
  recuperación R281**, no en el motor SQLite ni como causa de #1085. La
  instalación guarda la ruta física `home / service._DB`; `/data/boca.sqlite3`
  es la ruta del contenedor. Se corrigió antes de cualquier ejecución física y
  se agregó una prueba con `OnDemandInstallation` auténtica.

## Decisión de recuperación

Introducir una operación manual **distinta** `boca-precommit-restore-one-shot`,
con entrada memfd SHA-pinned de cierre mínimo. No reutiliza #1085, no llama
R186, no genera ni descarga imágenes y no toca otro daemon/servicio.

Antes de cualquier efecto debe acreditar bajo un **lease Boca nuevo**:

1. Los tres registros inmutables del journal de #1085, sin COMMIT, con hash
   conjunto estable; binding original auténtico y ambos CIDs/IDs OCI exactos.
2. Directorio estacionado con su inode original; ausencia de control canónico,
   unidades systemd antiguas desvinculadas, socket estacionado **vacío** y
   puerto `127.0.0.1:8443` exclusivamente libre. Que HTTP esté caído no prueba
   por sí solo la disponibilidad del puerto.
3. Inventario global del daemon rootless igual a los **dos CIDs originales**;
   etiquetas y montajes de los volúmenes Boca, hashes históricos IPC/SITE,
   identidad de egress y límites de red, sin contenedores foráneos.
4. DATA/KEY/OWNER no tenían hashes de inode anteriores a PARK persistidos:
   se verifica su custodia por etiquetas, montajes de CIDs originales, estado
   actual seguro `nofollow` y estabilidad **antes/después**, sin representar
   esto como una comparación histórica inexistente.
5. Dos preflight idénticos, más un tercer preflight inmediatamente antes del
   primer efecto, bajo el mismo lease; todo drift es `NO_GO` sin escribir.

Solo después se escribe con `O_EXCL`, `fsync` y lectura de retorno una marca
persistente específica del incidente. La única transición admitida restaura
el binding desde PARK, renombra los **dos CIDs originales**, arranca solamente
el controller y conserva el worker en `CREATED` sin reinicio automático.
Comprueba salud física, puerto exclusivo y exacto, continuidad de recursos y
journal inmutable; publica recibo `RECOVERED_OLD_PAIR`. Tras la marca, cualquier
error, incluso de confirmación, queda `INDETERMINATE` sin reintento automático.

## Lo que R281 no hace

- No promueve la nueva versión ni declara BETA técnicamente certificada.
- No elimina imágenes, volúmenes, perfiles, credenciales ni bases de datos.
- No habilita navegación ni reservas reales (`SIMULATION_ONLY`).
- No ejecuta dos operaciones simultáneas en el droplet. No toca Porota ni PPI Watch.
- No considera el éxito de CI ni del workflow de recuperación una prueba de
  aceptación funcional del titular.

## Lecciones para CI/CD y siguientes fases

- La identidad de inode debe ser **dependiente del estado**: `STAGED` apunta a
  la ruta canónica; `PARKED`, al testigo estacionado; `RESTORED`, a la raíz
  original. Un guard que consulta una ruta movida por su propia transición
  provoca un bloqueo artificial y puede impedir la compensación.
- Separar `observe`, `recover`, `release`, `apply` y `postflight` en recibos
  inequívocos y estados distintos; no repetir automáticamente operaciones
  con efectos inciertos.
- Tratar los paquetes e imágenes como artefactos inmutables reutilizables:
  arreglar el orquestador nunca exige reconstruir el controller o el worker.
- Pruebas focalizadas que cubren condiciones reales de PATH, socket residual,
  puerto ocupado y postflight. No repetir suites completas sin cambio de
  alcance ni contenedores/digests ya comprobados.
- Publicar RCA y evidencia en issue #417 y el ADR versionado en la misma PR.

**Dictamen:** esta implementación no ejecutó RESTORE físico. La operación
solo podrá despacharse tras revisión, PR, CI y aprobación de los guards,
con una observación posterior independiente del servicio recuperado.
