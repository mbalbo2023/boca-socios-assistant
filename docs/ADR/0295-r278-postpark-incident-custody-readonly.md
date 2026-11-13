# ADR 0295 — R278: custodia forense después de PARK fallido

**Fecha:** 13-NOV-2026 (ART). **Estado:** OBSERVACIÓN READ_ONLY; no recuperación autorizada.

**Autoridad:** [issue #417, R277](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861598271),
[R276-a](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861462459).

## Evidencia separada por nivel

- `main 3a933f0ac7f51043e9d69a185558345e0a31a77d` y release dual
  [#863](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43478524966)
  están publicadas, pero no instaladas ni certificadas.
- Un único APPLY [#1085](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43479367282)
  falló después de PARK y antes de crear worker: `NO_GO`,
  `commit_started=false`, `old_restored=false`, `cleanup=INDETERMINATE`.
- El censo #1087 conserva conteos 1+1, no las identidades; los
  observadores de par/binding requieren nombres canónicos que PARK retiró.
- [#1088](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43485103759)
  hizo una nueva observación, sin escrituras: `HEALTH_UNAVAILABLE`,
  `OBSERVED_NO_GO`, `BOTH_FILES_ABSENT`; su observación de UID de
  almacenamiento no equivale a un testigo de mapeo rootless.

## Causa raíz y cambio R278

`park_binding()` mueve el directorio de control a una ruta específica del
intento. El guard de recursos seguía leyendo el inode desde la ruta canónica,
que está ausente legítimamente mientras el par original está estacionado.
El mismo chequeo impedía `restore_old()` y dejó `INDETERMINATE`.

Antes de modificar el guard o emitir una recuperación se requiere un
testigo físico nuevo, porque ningún observador existente cubre journal,
identidad parked e IDs originales conjuntamente. R278 agrega **únicamente**
el modo `boca-park-incident-observe`, fijado a `43479367282`, y el fuente
inmutable `host_boca_park_incident_readonly.py` transmitido por SSH como
`python -I -B -`, sin persistencia en el servidor.

El testigo exige: UID/GID exclusivos de `boca-deploy`; evidence/intent
hasheados y terminal NO_GO exactos sin COMMIT; SHA original/anunciado,
release, CIDs y OCI pins; dos originales detenidos con nombres parked,
sin terceros en el proyecto; mismo hash del inode de control estacionado;
binding/archive históricos bajo directorio reservado; presencia de nombres
DATA/KEY/OWNER/IPC/SITE/EGRESS; dos lecturas estables y salud loopback.
Los fallos sólo publican una categoría redacted `NO_GO`. No se leen miembros,
claves, URL, cookies ni tokens en la evidencia pública.

La presencia de volúmenes **no** acredita todavía su custodia completa,
ni autoriza RESTORE; el recibo lleva expresamente
`retained=NAMES_PRESENT_INODES_UNVERIFIED` y `restore_authorized=false`.
Una recuperación futura debe tener **nuevo lease, claim O_EXCL duradero**,
revalidación de inodos/etiquetas/volúmenes bajo ese lease y recibo específico,
sin reusar el APPLY fallido ni R186. El guard de PARK/RESTORE y COMMIT se
corregirá por una prueba de transición de estados separada.

## Prevención permanente

1. No aplicar un testigo de path canónico a un recurso renombrado dentro de
   una transacción; cada transición conserva identidad de inode y fase.
2. No impedir compensación por un preguard que consulta una ruta que la
   propia transacción acaba de mover.
3. Ningún `GREEN` de Actions equivale a servicio disponible: separar
   observación, recuperación, release, instalación y aceptación del titular.
4. Si el estado es parcial o ambiguo, detener el flujo, preservar el host y
   registrar el `NO_GO` en issue #417; ninguna limpieza amplia ni retry.
5. Limitar todo a Boca rootless/8443, `SIMULATION_ONLY`, sin tocar Porota,
   PPI Watch ni otros recursos.

**Pruebas focalizadas:** `tests/test_host_boca_park_incident_readonly.py` y
`tests/test_r278_park_incident_workflow.py`.
