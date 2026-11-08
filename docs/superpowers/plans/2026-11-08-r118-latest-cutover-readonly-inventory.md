# R118 — Plan de instrumentación de solo lectura

**Objetivo:** reaprovechar `cutover-a-reconcile` para el incidente exacto
`42426260583` con recibo terminal V3 y Docker planner Boca-only, sin host ops.

**Diseño:** `docs/superpowers/specs/2026-11-08-r118-latest-cutover-readonly-inventory-design.md`.
**Límites:** BLACKBOX prohibidos; código + fixtures offline exclusivamente;
NO_GO físico, no deploy ni Telegram, nada fuera de Boca, una rama/PR.

- [x] TDD RED: extender `tests/test_host_cutover_postapply_reconcile.py`
  para terminal V3 con evidencia exit/OOM tipada y rechazo adversarial.
- [x] Implementación mínima del parser read-only V3, sin alterar productor.
- [x] TDD RED: `tests/test_v3_cleanup_inventory.py` para #878, autenticación
  de run/SHA y binding exacto en el YAML real, con falsos positivos rechazados.
- [x] Extender el selector existente `cutover-a-reconcile` a los dos IDs V3;
  no introducir otros dispatchers ni cambiar el procedimiento de Cutover V3.
- [x] Pin nuevo del ZIP protegido si sus bytes cambian; preservar pin R116.
- [ ] ADR/operaciones, Ruff, MyPy, policy, suite focal y completa, QA
  independiente exact-SHA, un PR, CI, documentación #417/#45.
- [ ] Sólo después de integración y nueva decisión de observación: inventario
  físico protegido vía Actions, el cual tampoco constituye GO de despliegue.
