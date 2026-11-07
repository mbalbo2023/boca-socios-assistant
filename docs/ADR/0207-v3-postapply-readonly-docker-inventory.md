# ADR0207 — Inventario Docker Boca de Cutover V3, solo lectura

Fecha: 2026-11-07 ART. Scope owner: auditoría de residuos #417; continuidad #45.
Estado: **CODE_ONLY**, hasta PR/QA/merge y un recibo físico posterior.

## Hallazgo verificable

El Cutover V3 #853 (`42405706503`) terminó `NO_GO`, con la fase gruesa
`PREPARE_WORKER` pero sin su subcausa durable. La observación READ_ONLY #858
(`42410321231`) halló el controlador antiguo sano, ningún worker/candidato
activo, `cleanup=INDETERMINATE` y Stage pendiente. La operación posterior #860
acreditó `STAGE_CLEARED`, pero eso **no** acredita ausencia de imágenes GHCR
descargadas ni del volumen IPC de ese intento. Stage y limpieza Docker son
alcances físicamente independientes.

El workflow `.github/workflows/boca-first-deploy.yml` ya contiene un planner
de limpieza **sin borrado** que transporta `host_boca_cleanup.py`, observa dos
snapshots rootless UID10001 y produce IDs/volúmenes/imagen propia con
clasificación conservadora. Sin embargo, el paso estaba explícitamente
omitido para #853 porque extraía el CID mediante el verificador v1 con
PREPARE, y V3 deliberadamente no tiene PREPARE.

## Decisión

Reutilizar el **mismo** `cutover-a-reconcile` y el inventariador existente.
El runner extrae `legacy_id` exclusivamente de su recibo de observación
atestado: v1 enlazado al PREPARE histórico o v2 enlazado a SHA del incidente
V3, que un paso anterior obtiene mediante GitHub y comprueba contra el run.
No se acepta otro CID o SHA aportado por el operador. La elección de versión
exige exactamente una coordenada no vacía y rechaza v1/v2 cruzados.

Para V3, el derivador exige intent/result presentes, terminal `NO_GO`,
`cleanup=INDETERMINATE`, ausencia de commit irreversible, restauración
positiva, mismo CID original en resultado y observación, nombre de controlador
legacy, running/healthy y binding exacto `127.0.0.1:8443`. Para v1 se
mantienen las comprobaciones históricas originales sin reinterpretarlas.
La ausencia de Stage después de #860 se tolera: intent/result durables siguen
presentes y son las identidades que certifican el controlador a observar.
El propio planner mantiene su segunda identidad y doble snapshot antes de
clasificar solo recursos Boca, sin Docker writes y sin exponer recursos ajenos.

## Límites y aceptación

- Esta operación no limpia imágenes, volúmenes, redes, stages ni contenedores,
  no instala ni promueve software, y siempre informa `READ_ONLY_NO_GO` y
  `go_for_retry=false`.
- Recursos sin procedencia positiva se preservan como `retained_uncertain`;
  nombres/tags coincidentes no bastan para borrar. Prohibidos `docker prune`,
  `docker rm`, `docker volume rm`, Compose global y tareas de otro proyecto.
- La acción depende de que el observer precedente haya superado todos sus
  gates; no se usa `always()` para enmascarar un fallo físico.
- TDD regresivo: `tests/test_v3_cleanup_inventory.py`,
  `tests/test_host_cutover_postapply_reconcile.py` y
  `tests/test_host_boca_cleanup.py`. La inclusión del derivador en el ZIP
  protegido modifica de forma determinista el pin SHA256 de ese ZIP; se
  recalcula y verifica en `tests/test_r82_recovery_bundle.py`, preservando
  los pines anteriores como evidencia histórica. Pruebas offline no equivalen a inventario
  ni a aceptación del droplet. Tras merge deberá ejecutarse una única
  observación física protegida y cotejar el recibo con #417/#45 antes de
  decidir si queda residuo exacto que reparar.

La fase física exacta original de #853 sigue desconocida; ni el Stage ni el
volumen IPC residual, si aparece, demuestran por sí mismos por qué falló
`PREPARE_WORKER`. Fuente primaria: [#417 R102.3](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6712680082).
