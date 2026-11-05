# ADR 0176 — Plan de limpieza Docker post-APPLY exclusivamente READ_ONLY

**Fecha:** 2026-11-05 ART. **Estado:** candidato CODE_ONLY / host NO_GO.
**Ownership:** issue [#386](https://github.com/mbalbo2023/boca-socios-assistant/issues/386)
y contrato de limpieza [#323](https://github.com/mbalbo2023/boca-socios-assistant/issues/323).

## Evidencia física y problema que resuelve

El Cutover A físico [#42096941815](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42096941815)
terminó NO_GO y su resultado durable declaró `cleanup=INDETERMINATE`,
`commit_started=false` y `original_restored=true`. La lectura posterior
[READ_ONLY #42104978077](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42104978077)
observó únicamente el contenedor Boca histórico RUNNING/healthy, revisión
`cabce9f1e452e63ded115f447559a358dc0f4d1b`, puerto
`127.0.0.1:8443`, sin candidato ni worker y sin directorio de stage.
Ese observador **no** verificaba el catálogo completo de imágenes, redes,
volúmenes y los dos sistemas de archivos del finalizador; por eso no podía
convertir `INDETERMINATE` en limpieza aprobada. El estado histórico del
Docker permanece no certificado.

## Decisión acotada: clasificar sin eliminar

Se reutiliza la operación protegida **existente** `cutover-a-reconcile` del
único workflow `boca-first-deploy.yml`, sin añadir otro dispatch/puerto,
sin activar Cutover y sin solicitar un identificador al propietario.
Después del primer JSON recibido mediante SSH pinado y validado por
`host_cutover_postapply_reconcile.verify_runner`, el runner extrae únicamente
el ID64 del contenedor legacy restaurado. Sólo continúa si intent/result
están presentes, `commit_started=false`, `original_restored=true`, y el
contenedor exacto sigue RUNNING/healthy. Un segundo SSH **READ_ONLY**
transmite por stdin `host_boca_cleanup.py`, desde el mismo SHA de `main`,
al usuario privado UID/GID 10001 de Boca; los argumentos son sólo el
ID de incidente y el ID64 ya verificado.

El nuevo modo `host` reutiliza **sin modificarlos**:

1. `capture_inventory`: socket Docker rootless UID10001 fijo, censo global
   exclusivamente por IDs, rechazo si hay objetos ajenos antes de inspección,
   lectura de metadatos allowlisted sólo de Boca, doble métrica libre
   bytes/inodos para staging Boca y Docker root, sin `Config.Env`.
2. `plan`: conserva el contenedor legacy + su imagen exactos, no autoriza
   retiradas (conjunto `retire_containers` vacío) y distingue candidatos
   positivos de objetos `INDETERMINATE`.
3. Dos inventarios estables de objetos con topología de discos idéntica;
   las métricas de espacio pueden variar legítimamente.

El modo **no llama a `delete_exact`, `execute` ni `execute_protected`**, no
adquiere lease con escrituras, no hace `docker exec`, `stop`, `rm`, `prune`,
`compose down`, ni accede a otros daemons, servicios, secretos, SQLite o
BLACKBOX. El verificador runner comprueba JSON ASCII canónico y acotado
(8192 bytes), tipos, identificadores exactos, no duplicados, identidad de
storage antes/después y los flags invariables
`status=READ_ONLY_NO_GO`, `cleanup_executed=false`, `observer_writes=0`,
`go_for_retry=false`. El recibo permite tres clases:

- `NO_CONFIRMED_REMNANTS`: no hay objetos positivamente elegibles ni
  inciertos **en estos dos inventarios**; no valida retrospectivamente
  el finalizador del APPLY anterior.
- `BOCA_REMNANTS_IDENTIFIED`: existen IDs exactos positivamente elegibles
  para revisión posterior; este observador no los elimina.
- `INDETERMINATE`: imagen u objeto de identidad/proveniencia incompleta;
  conservarlo y no efectuar limpieza automática.

El JSON solo reporta los IDs Boca del plan, razones acotadas de incertidumbre,
cuentas y métricas de Docker/Boca. Los IDs de imágenes globales sin etiqueta
ni referencia revisada **no** se inspeccionan o publican: sólo se reporta su
cantidad agregada y `INDETERMINATE`. Ningún volumen owner/key/data/Telegram es
elegible. Si la comparación/UID/socket/lectura falla, el workflow queda rojo
con `readonly_inventory_unavailable`, conservando el original y el antiguo
NO_GO. No hay retry automático.

## QA y límites

Pruebas sintéticas cubren los tres estados, preservación del controller e
imagen sin OCI-source histórica, detección de estado original ajeno/parado,
deriva Docker/storage, JSON adulterado/duplicado y selección exclusiva de
la operación existente en YAML. Ejecutar los gates sobre el **SHA final**
del PR; ningún PASS local se extrapola a Actions o al droplet.

El observador nunca resuelve `STAGE_COMPOSE_INODE_MODE`, ni certifica que el
APPLY histórico no haya tenido otros efectos. Una operación física posterior
debe seguir el workflow protegido y registrar sus dos recibos sanitizados;
sólo un análisis posterior puede decidir si hay residuos que retirar en una
transacción nueva, con licencia exacta de identidad y postflight físico.
No borrar ni reintentar Cutover a partir de un mero resultado READ_ONLY verde.

Sin modificaciones de Porota, otros servicios, puertos, HTTPS, backups,
reservas/compras ni módulos BLACKBOX. Regla 84: actualizar #386/#323 con
SHA, QA exacto y recibo físico *cuando exista*; el merge no es despliegue.
