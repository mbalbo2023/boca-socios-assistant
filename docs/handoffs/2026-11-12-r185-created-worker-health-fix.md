# R185 — RCA físico del `RETIRE_OLD`: Health ausente del worker creado

**12/11/2026 ART · issue #417 · scope exclusivo Boca · código fix-forward.**

## Evidencia que distingue causa de hipótesis

- El único APPLY [#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287)
  instaló los nuevos CIDs y quedó `NO_GO`, `failed_phase=RETIRE_OLD`,
  `commit_started=true`, `cleanup=INDETERMINATE`.
- El primer observador [R183 #43224539079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43224539079)
  comprobó dos CIDs nuevos y ausencia de los antiguos, pero no discriminó
  `OTHER_UNVERIFIED`.
- El segundo observador [R184 #43227066989](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43227066989),
  sobre `main=8e4a92979f315bfa2c82c7f9d8dccf7fe4560b77`, obtuvo:

  `pair=NO_GO`, **`pair_reason=WORKER_HEALTH_UNAVAILABLE`**,
  `new_pair_only=true`, `old_ids_absent=true`, `parked=DIRECTORY`,
  `intent=FILE`, `socket_directory=DIRECTORY`, `socket_node=ABSENT`.
  Los cinco archivos antiguos (`attempt`, `binding.json`, `handler.pyz`,
  las dos unidades) siguen con tipo `FILE`. Sin escrituras sobre host ni
  recursos ajenos.

Este recibo localiza **la lectura Docker del campo State.Health.Status del
worker** como fallo actual reproducible del verificador. No demuestra el
mensaje concreto del daemon ni todo el estado en el instante del APPLY.

## RCA de código y corrección mínima

`host_boca_pair_observe._fields_from_proven_boca()` delegaba la lectura de
`State.Health.Status` al `ProductionCutoverInventoryIO.field` común, que
construía el template sin guarda `{{json .State.Health.Status}}`.
Para un worker detenido `CREATED/PID0`, Docker puede no disponer todavía de
`.State.Health`; el lector convierte el fallo a `CutoverInventoryNoGo`,
no a `PairNoGo`. R184 lo detectó como `WORKER_HEALTH_UNAVAILABLE`.

La reparación R185 cambia **únicamente esa lectura del observador de par**
al template limitado ya empleado por el inspector Boca:

`{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}`

Cuando no existe el objeto, retorna JSON `null`. El propio `_snapshot()`
existente lo representa como `health=none`, sin inferir que el worker está
running o healthy. El controlador todavía debe estar running+healthy en
`_new_pair_only()`, y el worker CREATED/PID0; la verificación de CIDs,
imágenes, montajes, redes, labels, raíz Docker y doble lectura permanece.
Una lectura Docker fallida, JSON malformado o valor no permitido sigue
terminando en `NO_GO` con razón acotada, nunca en aceptación falsa.

## Verificaciones y siguiente fase

Tests TDD RED→GREEN:

- La proyección sin guarda falla con `CleanupError` al simular Health
  ausente; el template protegido devuelve `None`.
- Una pareja creada con Health `None` sigue `status=created`, `pid=0`,
  `running=false` y recibo canónico `health=none`.
- Docker devuelve un valor malformado: `PairNoGo`, sin filtrar bytes.

El PR debe pasar revisión independiente, Ruff, MyPy, suite y checks
exact-SHA. Después del merge, una única Action READ_ONLY
`boca-postcommit-observe` debe mostrar `pair=PASS` atado al **par exacto**
del APPLY previo; un PASS no cambia el recibo histórico `NO_GO` ni
autoriza limpiar. Primero contrastar binding, SQLite y respaldo aparcado;
solo después diseñar un finalizador posterior al commit con lease,
anti-replay y retirada selectiva de metadatos Boca, **sin reintentar APPLY**.

El código funcional #12 de Queue-it/Boca sigue incluido en BETA, sin gate
de disponibilidad del proveedor ni validación de URLs con token.
Navegación/reserva real, Telegram y worker bajo demanda continúan bajo
sus contratos independientes; ninguna prueba aquí los activó.
