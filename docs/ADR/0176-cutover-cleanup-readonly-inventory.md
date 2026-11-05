# ADR 0176 — Plan de limpieza Docker post-APPLY exclusivamente READ_ONLY

**Fecha:** 2026-11-05 ART. **Estado:** R25 integrado #392; R26 CODE_ONLY.
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

## R25.2 — RCA presupuesto del preflight anterior a SSH

La operación protegida READ_ONLY
[#42110047550](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42110047550)
falló en `Require verified protected environment and matching main commit`
**antes de configurar SSH**. El workflow ya enumeraba `cutover-a-reconcile`
en el `case` de identidad y entradas, pero no en el `elif` de presupuesto
`1.5cpu-1024m-192pids`. Por ello caía al `else` que exigía
`0.5cpu-256m-64pids`, contradictorio con el budget 1.5 seleccionado para
diagnóstico Cutover. No hay evidencia nueva de lectura del host ni de
operaciones Docker de ese run, por lo que `cleanup=INDETERMINATE` persiste.

La corrección agrega **únicamente** `cutover-a-reconcile` a la condición
existente de presupuesto 1.5, sin cambiar caps del contenedor ni políticas
de otro workflow. Una prueba ejecuta offline el fragmento Bash verdadero
del YAML: reproduce RED con el budget correcto y exige GREEN con 1.5 y
NO_GO con 0.5. Otra prueba ejecuta el paso entero de validación de entorno
con valores públicos ficticios y sin credenciales/host; una tercera acredita
que una observación válida con `stage_preflight.reason=STAGE_COMPOSE_INODE_MODE`
**sí permite** pasar al segundo lector Docker READ_ONLY del mismo run.

La continuación no usa `always()`: si falla SSH, marcador o validación del
primer lector, el segundo permanece SKIPPED. Si el primer JSON es válido
pero Stage reporta NO_GO, el primer paso verifica y retorna éxito *como
lectura*, por lo que se puede inspeccionar Docker sin autorizar retry ni
limpieza. La evidencia física final requiere un despacho nuevo sobre main
con este parche revisado, CI exacta, merge protegido y mismos límites Boca.

## R26 — Dos imágenes físicas: procedencia y espacio insuficientemente probados

El run protegido READ_ONLY
[#42112927157](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42112927157)
**SUCCESS como observación**, desde `main=b0a731a5b9f9115713bb39e48218653ed4035d76`,
acreditó: un controller original y su imagen
`sha256:12d492da545566a13ba4faec6afd99a3d6fe1990657d2e0981420c429c36d5c1`
preservados; dos imágenes rootless, una red, tres volúmenes, cero remanentes
con propiedad positiva y una imagen incierta
`sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`.
`classification=INDETERMINATE`, `cleanup_executed=false`, métricas antes/después
estables. El run NO prueba que `a444...` sea basura de Boca ni autoriza borrarla.

### RCA del observador anterior

`capture_inventory()` selecciona imágenes por la etiqueta OCI source exacta
**o** por `docker image ls --filter reference=ghcr.io/mbalbo2023/boca-socios-assistant*`.
La segunda imagen ingresó por la referencia, pero no por `org.opencontainers.image.source`;
el contrato R25 intencionalmente fabricaba un placeholder
`boca-socios-assistant:unverified` sin consultar sus etiquetas/referencias exactas.
Por tanto `plan()` la retiene como `unverified-provenance-or-shared-reference`.
Ese resultado es seguro pero no permite discernir una imagen legítima anterior,
un alias ambiguo ni el costo lógico de almacenamiento.

### Extensión únicamente READ_ONLY, sin promoción de confianza

R26 no cambia `plan()`, `delete_exact`, `execute()` ni la clasificación. Para
**sólo** un ID que ya apareció como referencia Boca en el daemon rootless
UID10001, fue inventariado sin recursos ajenos y está sin referencias de
contenedor, lee con `docker image inspect --format` exclusivamente:

- Identidad `Id`, `RepoTags`, `RepoDigests` y `Size` (bytes lógicos);
- **sólo** `org.opencontainers.image.source` y `.revision` con plantillas
  `index` exactas, nunca `Config.Labels` completo, `Config.Env`, host paths
  ni secretos;
- cantidad de contenedores del inventario Boca que referencian el ID.

Se redactan todos los aliases no públicos: solamente se publican tags
`sha-` de 40 hex y digests SHA256 del repositorio oficial Boca; los demás
se cuentan como `untrusted_alias_count`, sin mostrar nombres o valores.
Source sólo se expresa `BOCA` / `ABSENT` / `UNVERIFIED`; revisiones no
hexadecimales quedan nulas. El ID debe pasar el filtro Boca antes **y
después** de leer; se consulta dos veces y se comparan los valores, con
fallo cerrado ante drift, formatos ambiguos o recibo alterado. Los IDs globales
sin referencia Boca siguen sin ser inspeccionados ni publicados.

El nuevo campo canónico `image_provenance[]` siempre lleva
`deletion_authorized=false`; no hace que desaparezca `retained_uncertain`, no
autoriza un `docker image rm`, ni convierte `INDETERMINATE` en GO. Los recibos
físicos permitirán buscar la tupla exacta digest/revisión/ID en una release
de GitHub verificable o decidir **retención expresa** si sigue faltando prueba.

### Capacidad: cálculo reproducible y próximo gate

`docker_bytes_free=5,106,962,432` bytes, por encima del mínimo contractual
pre/post-pull `4*1024^3=4,294,967,296` sólo en **811,995,136 bytes
(774.38 MiB)**. Los `2,873,314` inodos libres superan 50,000; no sustituyen
al margen de bytes. Los siete release runs publicados contrastados
`41873165726`, `41893887078`, `42072022371`, `42076459492`,
`42080305773`, `42083597885`, `42090471891` contienen image IDs de build
distintos a `a444...`; una búsqueda negativa no prueba procedencia externa.

Los artefactos duales de release #42090471891 registran digest, SHA y tipo
de imagen, pero **no** bytes lógicos verificados de controller/browser ni
peak de capas. No se declara espacio suficiente para descargar ambas nuevas
imágenes: la combinación de bytes de extracción, capas compartidas y reserva
física no está medida. Medición propuesta **en runner descartable**, sin
pull al droplet: resolver dos digests release exactos, registrar `image inspect
.Size` de cada imagen y su delta real de bytes después del pull en el
runner, y comparar contra margen de 774 MiB con reserva. Incluso entonces
se exige el gate físico de 4 GiB y 50k inodos antes/después de cualquier pull
protegido, sin eliminar otra imagen para crear espacio por intuición. Si la
capacidad no alcanza, STOP seguro y tratar almacenamiento/capacidad como
dependencia específica, sin purgas ni efecto sobre Porota.
