# ADR 0262 — R253: revalidación de identidad OCI antes del cleanup SUCCESS V2

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** `CODE_ONLY / NO_GO`;
ningún actor, CLI, workflow, APPLY ni host fue habilitado o ejecutado.

## RCA reproducido con TDD

`host_boca_upgrade_cleanup_runtime.execute_durable_final_cleanup` invoca la
limpieza protegida genérica. El motor toma un inventario, selecciona un
`Target("image", exact_id)` y después lo pasa a `delete_exact` sin repetir la
identidad OCI dentro de esa última ventana. Con un fake Docker que cambia
`source` o `RepoTags`/`RepoDigests` entre la selección y el borrado, los cuatro
casos RED demostraron que SUCCESS podía emitir `ACCEPT` después de borrar una
imagen ya asociada a otra procedencia. Si un nuevo contenedor la referenciaba,
el resultado acababa `NO_GO` **después** del intento de borrado. Ni un ACK de
Docker ni un inventario post-borrado reponen la oportunidad de preservarla.

## Decisión de alcance mínimo

Se amplía **sólo** el método protegido con evidencia
`host_boca_cleanup.execute_protected_with_inventories` mediante un callback
opcional `image_predelete_guard(first, selected, fresh, target)` cuyo tipo es
`Callable[[Inventory, Inventory, Inventory, Target], None] | None`. El valor
por defecto `None` conserva intactos los callers previos, incluidos FAILURE,
Cutover y las operaciones de contenedor, volumen y red. El motor genérico
sigue siendo el único que decide el `plan()` y llama a `delete_exact`.

El bridge de **SUCCESS V2** es el único que inyecta ese callback. Para cada
imagen candidata, el motor vuelve a verificar la lease Boca, captura un nuevo
inventario que también reatestigua R108 y, tras el callback, revalida la lease
otra vez antes del borrado. El callback exige:

1. Mismo objeto `Image` completo en el inventario inicial, el seleccionado y
   el inmediato pre-delete: ID, referencias/alias y fuente OCI exactos.
2. `source == BOCA_SOURCE`, sin excepción `historical_legacy_attested` y con
   el ID en el censo rootless global; no imagen del nuevo par ni R108.
3. Ningún contenedor, aun detenido, referencia el ID; la topología de discos
   permanece idéntica y el `plan()` puro sigue autorizando el `Target` exacto.
4. Toda discrepancia produce fallo cerrado, conserva el intent `O_EXCL` del
   intento y no escribe un receipt positivo. Sin retry ni `prune`.

No se crea un segundo motor de Docker, ni un atajo de host. La ventana de
mutación entre la última lectura y el syscall de eliminación no desaparece
físicamente; el contrato exige la revalidación más próxima posible bajo la
única lease cooperativa. La coordinación de cualquier mutador externo del
daemon sigue siendo precondición operativa de un futuro APPLY protegido.

## Presupuesto fijo de bundles y comentarios conservados

El archivo genérico `host_boca_cleanup.py` forma parte de varios bundles
inmutables; PRE-FLIGHT tenía sólo **255 bytes** de margen antes de este
callback. Para evitar cambiar allowlists, caps o el actor, cinco comentarios
históricos largos fueron *condensados sin alterar sentencias ni controles*.
Las explicaciones completas que se conservan aquí son:

- **Replan tras cada eliminación:** un contenedor detenido puede ser la única
  referencia a una imagen obsoleta o volumen efímero; sólo el nuevo censo
  decide el siguiente objetivo, nunca el plan inicial.
- **ACK no implica ausencia:** una etiqueta, attachment o estado en ejecución
  puede cambiar y hacer que el objeto parezca inelegible; el motor exige la
  ausencia por ID/nombre exacto para contenedores, imágenes, redes y volúmenes.
- **Identidad de retiro drifted:** perder la prueba positiva de propiedad de
  un CID retirado es `NO_GO`, no justifica otro intento de borrado.
- **Cutover A READ_ONLY:** su diagnóstico post-APPLY continúa separado de
  toda mutación/lease; el workflow protegido transmite el inventariador por
  stdin al usuario rootless Boca.
- **R46 histórica:** la imagen proviene de APPLY `#42236673419`, PREPARE
  `#42217108000`, release `#41559973013`, manifest `#13196392925` y READ_ONLY
  `#42237830418`. Ningún replay R28, tag móvil o ID arbitrario la reemplaza.

Medición local de fuentes reales a partir de `main=0007d8c` tras el cambio:

| Bundle | Fuente / límite fijo | Margen |
| --- | ---: | ---: |
| Worker PREFLIGHT sin compacción | 519.735 / 520.000 B | 265 B |
| Cutover completo con compacción de comentarios | 1.158.066 / 1.158.144 B | 78 B |
| PAIR_UPGRADE offline con placeholders NO_GO | 1.286.552 / 1.300.000 B | 13.448 B |

El ZIP Cutover completo determinístico ahora tiene SHA-256
`976e703b51f454a084394cd8877bad5c8c0da8ea46b183f797cea789b854393c`;
el pin histórico R245 queda explícitamente preservado en tests, sin
autorizar una nueva ejecución física de Cutover.

La integración futura con cualquier nuevo módulo del bundle debe medirse
sobre el árbol **combinado**. Esta medición individual no prueba que quepan
otras fuentes simultáneamente ni autoriza elevar límites.

## Pruebas y límites de aceptación

- RED observado en `foreign_alias`, alias Boca distinto, `source=None` y
  referencia nueva de contenedor: tres `ACCEPT` indebidos y un borrado previo
  a `NO_GO` contra el código sin guard.
- GREEN: seis variantes de drift (incluye fuente extranjera y desaparición),
  no se llama a `delete_exact`; imagen legítima sí se borra por ID único con
  recibo V2 `ACCEPT` y R108 retenida; lease perdida tras nueva lectura impide
  el borrado; volúmenes y redes conservan su conteo de probes anterior.
- Validación offline con pytest, Ruff, formato, mypy, repo policy y builders;
  jamás se abrieron sockets Docker ni se navegó Boca/Queue-it.

Este ADR **no** resuelve la colisión entre intent/receipt globales de
SUCCESS en upgrades sucesivos ni la aceptación física humana mediante
Chrome/passkey; ambas requieren cambios/testigos independientes posteriores.
