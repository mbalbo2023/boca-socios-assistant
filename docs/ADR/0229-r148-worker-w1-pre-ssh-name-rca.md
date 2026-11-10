# ADR 0229 — R148: W1 #932 NO_GO antes de SSH por identidad dinámica de Actions

Fecha: 2026-11-10. Alcance exclusivo: Boca worker W1 y su preflight. RCA canónico: issue #417.

## Evidencia observada

- [Action #932](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42837509274), commit `3843057865e2b58b9131419bc58f80823fc0e1eb`, `workflow_dispatch`, intentó `worker-diagnose-once` una sola vez. La etapa **Prove single W1 owner dispatch and exact successful installed Cutover before SSH** imprimió `BOCA_WORKER_W1_GATE state=NO_GO`, exit 3. La etapa SSH y el arranque del worker constan como **skipped**.
- [Action #926](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42806447101) fue la instalación exitosa en `03df9a14bdd78cf768386a865876fed9d5656911`; metadatos REST reales: `id=42806447101`, `workflow_id=400115324`, `path=.github/workflows/boca-first-deploy.yml`, `event=workflow_dispatch`, `head_branch=main`, `run_attempt=1`, `actor=mbalbo2023`, `conclusion=success`.
- En el REST de #926 el campo `name` **no es** `Boca first deploy`: es el nombre dinámico `BOCA-SIMULATION-DEPLOY-V3`. Por el contrario, #932 se presenta como `Boca first deploy`. La comparación de `name` con una constante de texto en `scripts/check_worker_w1_dispatch.py` provocó el rechazo incorrecto de #926.

## Causa y arreglo mínimo

El campo `name` de GitHub Actions puede reflejar el `run-name` dinámico. No constituye identidad estable de workflow. Para admitir la instalación histórica, el preflight debe autenticar juntos `workflow_id`, `path` y `repository.full_name`, además de ID/SHA/resultado/actor/evento/rama/primer intento, y exigir exactamente un despacho manual en el nuevo SHA. El flujo de Actions debe proyectar esos campos en su JSONL. La comprobación continúa antes de SSH y falla cerrada ante datos incompletos.

Regresión: test con los campos reales de #926, test con un nombre de run actual distinto y rechazo de ID/path/repo incorrectos. Se ejecuta toda la suite y CI antes de promover cualquier cambio.

## Estado y límites

**#932 no realizó un arranque físico.** Este RCA corrige únicamente un bloqueo del preflight; **no explica ni soluciona** el `MODULE_NOT_FOUND_ERROR` del worker observado en [#899](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42730562010). Sigue sin conocerse el nombre exacto del módulo porque no hubo captura W1. No iniciar otro Action W1 sin un GO nuevo y una revisión de su alcance; no reutilizar o reejecutar #932.

No se llamó a Docker en el droplet, no se modificaron sockets, sudoers, usuarios o contenedores; tampoco Porota ni PPI Watch. Los archivos `synthetic.py` e `ipc_worker.py` siguen BLACKBOX sin apertura ni modificación. Origin #465 y Cutover quedan congelados.
