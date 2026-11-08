# ADR0213 — R118: inventario Boca tras terminal V3 con ExitCode

Fecha: 2026-11-08 ART. Issues #45, #417, #386. Decisión: **GO CODE_ONLY**;
**NO_GO físico**, sin nueva Action ni limpieza ejecutada.

## RCA comprobable

El [último Cutover V3 #878](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426260583)
terminó `PREPARE_WORKER/HEALTH_EXITED` con `ExitCode=1` y `OOMKilled=NO`;
fuente `f57173862df3143062a136452f2ffc7e3cc51d35`. Su observación posterior
[#879](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42426527816)
mostró legacy operativo, worker ausente, pero **no** certificó residuos
de imágenes/volumen IPC/Stage ni cleanup terminal. La causa interna del
`ExitCode=1` permanece desconocida; la observación no ejecuta BLACKBOX.

El selector existente `cutover-a-reconcile` se limitaba al V3 anterior
`42405706503`; para #878 pedía un ID PREPARE que Cutover V3 ya no usa.
Además `scripts/host_cutover_postapply_reconcile.py` sólo aceptaba resultados
terminales v1/v2, pero R114 persiste v3 cuando captura ExitCode/OOMKilled.
Por lo tanto un intento de inventario sobre #878 habría fallado antes de
producir una clasificación conservadora de cleanup.

## Solución mínima en el circuito existente

- Sin crear workflow, operación, permiso ni SSH distintos, el formulario
  `cutover-a-reconcile` reconoce únicamente V3 #853/`42405706503` y
  #878/`42426260583` **con sus SHAs inmutables**. La API de GitHub prueba
  la identidad del run real: owner, intento uno, branch `main`, evento,
  resultado, nombre del workflow y SHA exacto. El SHA no lo ingresa el usuario.
- El lector de recibos acepta terminal v3 además de v1/v2, con las dos
  evidencias nuevas estrictamente tipadas: entero exacto 0–255 o `UNKNOWN`,
  booleano exacto o `UNKNOWN`, sólo `HEALTH_EXITED`. Rechaza claves extra,
  identidades alteradas, campos parciales y bool-en-lugar-de-int. El modo
  histórico con PREPARE rechaza ahora un terminal v3. El productor
  del recibo y la semántica de fail-closed del Cutover no cambian.
- La atestación GitHub pasó de `assert` heredado a validaciones explícitas
  `if/raise SystemExit` que **también fallan con Python `-O`**. Se ensayaron
  ambos incidentes con metadatos válidos y falsificados en modo normal y
  optimizado; jamás se imprimen secretos ni se obtiene GO por la prueba.
- El flujo antiguo con PREPARE sigue como evidencia histórica. Para V3,
  se conserva el CID original de intent/result, receipt v2 del observador,
  dos snapshots Boca-only del planificador y sus controles de loopback y
  restauración. El inventario será **sólo lectura**; ni un recibo limpio
  habilita un nuevo Cutover (`READ_ONLY_NO_GO`, `go_for_retry=false`).
- La imagen histórica atestada del [ADR0209](0209-r108-attested-historical-quarantine.md)
  sigue retenida. Imágenes/volúmenes IPC o Stage desconocidos continúan
  `INDETERMINATE`: esta extensión no borra ni reduce las barreras de cleanup.

## Verificación y alcance pendiente

Las pruebas fueron escritas primero y fallaron RED por terminal v3 no aceptado,
ID V3 nuevo ausente y autenticación del incidente nuevo. Otras pruebas RED
reprodujeron el bypass con `-O` y exigieron un handoff integral offline:
recibo terminal v3→`host-v3`→`verify-v3`→CID exacto→parser real de planner,
con alteración de intent/replay rechazada. Las pruebas focales posteriores
registraron **81 PASS** en los dos módulos principales. La validación de ZIP
detectó RED del pin histórico y fijó un pin **nuevo** R118
`a34535af33d9e7073d16a97c50ce1e0a529db39dae35302b79c0cb0ecb152e77`;
R116 se conserva sin alteración. Registrar resultados posteriores de CI/PR
y suite completa en #45; **CODE_ONLY no equivale a host validado**.

En el último árbol local candidato, suite completa `uv run --frozen pytest
-q -n auto`: **5570 PASS +34 subtests** (22,54 s); `ruff check .`,
`ruff format --check .` (709 archivos), MyPy de 136 archivos,
`check_repo_policy.py` y `git diff --check`: **PASS**. Los tests dirigidos
previos del observador/planificador fueron 192 PASS; el SHA exacto de PR y
los gates de Actions aún se deben registrar separadamente.

No tocar `synthetic.py` ni `ipc_worker.py`, no ejecutar navegación real,
Telegram sender, comandos manuales, Docker global, Porota ni apps ajenas.
No se despacha el inventario ni se realiza Cutover durante este cambio.
El planner exige `NO_GO`, cleanup `INDETERMINATE`, restauración positiva,
commit no iniciado y legacy sano en loopback; el resultado real #878 todavía
podría no cumplirlos, caso en el que **se abortará sin cleanup**. Un terminal
de worker `ExitCode=1` no demuestra esas otras condiciones.
Revisión/CI exact-SHA y eventual decisión separada sobre **una** observación
física protegida deben preceder cualquier cleanup preciso. Resolver el contrato
de arranque externo del BLACKBOX, custodia Telegram y aceptación funcional
continúa siendo independiente y obligatorio antes de BETA integral B.

Diseño y plan:
[R118](../superpowers/specs/2026-11-08-r118-latest-cutover-readonly-inventory-design.md),
[plan](../superpowers/plans/2026-11-08-r118-latest-cutover-readonly-inventory.md).
