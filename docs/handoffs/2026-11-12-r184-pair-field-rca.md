# R184 — clasificación limitada del bloqueo `RETIRE_OLD`, issue #417

**Fecha:** 12/11/2026 (ART). **Scope:** exclusivamente lectura física y
diagnóstico de la actualización Boca #43217075287, sin efecto Docker/systemd.
**Base antes del PR:** `main=42c767294dcb9bc2140249fac9eaf522005ab579`.

## Nueva evidencia observada en el droplet

- [R183 READ_ONLY #43224539079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43224539079):
  workflow SUCCESS **como diagnóstico**, no como despliegue.
- Recibo ligado a `failed_attempt=43217075287`, `new_pair_only=true`,
  `old_ids_absent=true`, `parked=DIRECTORY`, `intent=FILE`,
  `socket_directory=DIRECTORY`, `socket_node=ABSENT`.
- `pair=NO_GO`, `pair_reason=OTHER_UNVERIFIED`,
  `observer_writes=0`, `foreign_resources_touched=0`,
  `cutover_authorized=false`.
- El nuevo controlador está HEALTHY y el worker CREATED/PID0 según el
  observador separado [#43218455801](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43218455801).
  El recibo original de APPLY permanece `NO_GO`/`cleanup=INDETERMINATE`.

## RCA, certeza y límite

`retire_old()` elimina los dos contenedores históricos antes de llamar
`commit_binding()`, y este último requiere `_new_pair_only()`, que usa
`host_boca_pair_observe.observe()`. La revisión estática comprobó que los
38 textos explícitos `PairNoGo` del observador tienen traducción acotada
en R183. Por tanto `OTHER_UNVERIFIED` es compatible con una excepción de
un lector interno de censo, campo Docker o etiqueta OCI, o de su
verificador, **no** con una discrepancia de perfil expresada normalmente
como `PairNoGo`. No es prueba de la excepción concreta.

Hipótesis prioritaria todavía por probar: el worker CREATED/PID0 carece
de `.State.Health` y la lectura legada
`{{json .State.Health.Status}}` rechaza esa ausencia en vez de producir
`null`. El código de `host_boca_pair_observe` sí contempla `health=None`,
pero delega la lectura a `ProductionCutoverInventoryIO.field`, que no
protege ese acceso. Alternativamente podría fallar otra lectura. No
modificar esa lógica hasta recibir un diagnóstico físico más fino.

**Corrección factual importante:** `socket_directory=DIRECTORY`, no
`ABSENT`. La limpieza pudo haber fallado antes de eliminar archivos
aparcados; la ausencia de `control.sock` es una precondición legítima de
`commit_binding`, no evidencia de un borrado final ya completado.
También se verificó que `cleanup.HEX_ID` **sí** acepta `sha256:` opcional:
el prefijo del ID de imagen no es un RCA acreditado.

## Contrato nuevo del observador R184

Conserva exactamente la misma operación manual `boca-postcommit-observe`,
los mismos dos CIDs y el mismo ZIP/memfd de solo lectura. Las llamadas del
verificador de par delegan sin cambio a sus lectores originales, pero en
caso de excepción no `PairNoGo` publican **solo** categoría fija:

- `CENSUS_UNAVAILABLE`/`CENSUS_EXCEPTION`;
- campo permitido por rol, por ejemplo `WORKER_HEALTH_UNAVAILABLE`,
  `CONTROLLER_MOUNTS_EXCEPTION`, o `WORKER_OCI_LABEL_UNAVAILABLE`.

No se publica la excepción, Docker stderr, valor de campo ni ningún dato
personal. Si el verificador emite una razón existente, se conserva sin
cambios. Además lee **solo tipos de archivos**, por `openat(O_NOFOLLOW)`
anclado, de `attempt`, `binding.json`, `handler.pyz` y ambas unidades del
respaldo aparcado; no lee contenido, enlaces ni datos SQLite. El recibo
queda limitado a 768 bytes y mantiene doble snapshot de censo/rutas.

Pruebas TDD adicionales simulan un campo `State.Health.Status` inaccesible
y una falla del censo; demuestran códigos finitos sin exponer mensajes
privados. Se exige CI exact-head, revisión, PR y merge antes de un **solo**
diagnóstico READ_ONLY desde `main`.

## Decisión posterior, sin efectos aún

1. Con el nuevo recibo físico, corregir exclusivamente la lectura/profilado
   que demuestre fallar, con pruebas de regresión. El siguiente test de par
   debe atestiguar los CIDs, hashes, networks, mounts y estados correctos.
2. Verificar aparte el binding systemd, datos/SQLite, marcador de commit y
   contenido permitido del respaldo, sin tocar recursos ajenos.
3. Si todo está íntegro, diseñar un finalizador *postcommit-only* con
   lease, anti-replay y archivo histórico verificado; no repetir el
   `boca-pair-upgrade-apply`, borrar contenedores, reiniciar worker ni
   restablecer los antiguos después del commit.
4. Mantener `NO_GO` hasta recibos físicos positivos de par, binding,
   SQLite, limpieza selectiva y BETA privada. Boca/Queue-it no disponibles
   **no bloquean el código #12**; no consultar URLs con tokens, no fabricar
   tokens y no reservar entradas reales.
