# Boca A45-R21.22 — documentación de release y candidato consolidado

Fecha: 2026-11-05 ART. Estado CODE_ONLY; main legacy sin cambios físicos. Nunca interpretar Actions PR como deploy o GO.

## Identidad del corte

- PR canónico DRAFT #319, main físico cabce9f1e452e63ded115f447559a358dc0f4d1b intacto.
- Padre de consolidación R21.21: 3cbe31703d74413f8de66ac8783ec68b1b7f8a87 TREE 208a75e0c7310ea25db55ca509563f0b57972f42. **7/7 Actions SUCCESS exact SHA**, CI 3718 PASS +34, Ruff/format547/MyPy128/imagebuild, FirstDeploy PR+runtime GREEN y host SKIPPED, release publish SKIPPED.
- PR #363 docs-only source exact HEAD 3e0df6d96c137dabacf6a39513a8122b16b1b44a TREE 04f91f0fd598797b0539ceefbb3781ccba40f1df, parent R21.21; cambios exactamente README.md, docs/BETA_DELIVERY_PLAN.md, docs/BETA_INTEGRATION_STATUS.md, docs/OPERATIONS.md. 4/4 Actions SUCCESS CI 3718 PASS+34; owner/liberación Rule84.
- Rama candidata actualizada por GitData CAS fast-forward a docs commit 3e0df6d96c137dabacf6a39513a8122b16b1b44a sin modificar otros componentes. Este archivo se agrega por Contents API para sincronizar PR y lanzar 7 Actions NUEVAS. HEAD final del checkpoint será commit posterior, no heredar QA del padre ni del PR docs.

## Release/GO pendientes (NO operaciones físicas)

1. Reconciliar HEAD/tree del commit que contiene este documento y certificar 7/7 GH Actions del SHA exacto; guardar log de CI+smoke, no asumir artefactos de release PR-only.
2. Dejar el PR DRAFT mientras faltan GO y predeploy gobernado. Sólo tras GO aplicable, preparar mark-ready/merge único a main, release artifact/image immutable y GitHub protected workflow.
3. Para Cutover A/Official: PREPARE inerte en workflow Boca, autoobservación rootless Boca READ_ONLY + GitHub release/source receipts; APPLY requiere el decimal corto del PREPARE, GO Environment SHA independiente y host O_EXCL replay/ACK. No pedir JSON/64hex a Tincho.
4. Comprobar recursos reales del droplet compartido, 127.0.0.1:8443 por Termius, Samsung Chrome y passkey persistente; no alterar Porota, otros contenedores, volúmenes ajenos ni puertos adicionales.
5. Verificar limpieza selectiva Boca POSTDEPLOY en Cutover COMMITTED/recovery con recibo bytes/inodos/IDs exactos. Las seis operaciones de instalación legacy siguen NO_GO antes SSH.
6. Telegram fresh WebAuthn owner stage está implementado; sender permanece OFF/NO_GO hasta atestación host same-PID/UID/flock, cuatro GET Bot API reales bajo GO y ACK. El satélite fase5 sigue trabajo CODE_ONLY separado, no autoriza egress físico por sí mismo.

Políticas permanentes: 0 compras/reservas reales, 0 backups, BLACKBOX synthetic.py/ipc_worker.py protegidos, sin HTTPS ni nuevos puertos, seguridad adicional P2 diferida. Regla84 en issue #45, #371, #373, #362, #323.
