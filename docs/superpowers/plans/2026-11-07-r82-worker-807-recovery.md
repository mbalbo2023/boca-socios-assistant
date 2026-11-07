# R82 exact stopped-worker #807 recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Each task follows TDD.

**Goal:** recuperar exactamente un contenedor Boca residual detenido del preflight #807, sin repetir R80 ni habilitar Cutover.

**Architecture:** Perfil R82 inmutable en el recuperador existente; nueva entrada de operación y ZIP/memfd ya existente; mismo contrato de inspección dual/lease y una mutación Docker como máximo. Gate GitHub REST anti-replay específico R82, sin copiar su lógica compartida.

**Tech Stack:** Python 3.12, Bash GitHub Actions, Docker rootless; pytest/Ruff/MyPy.

**Spec:** `docs/ADR/0191-r82-exact-stopped-worker-807-recovery.md`.

## Global Constraints

- **BASE exacta:** `main=8146ab94c1fedf02fbe0ba14e225bbce61339044`, 0 PR abiertos.
- **R82:** attempt `42341290485`, CID `06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d`, SHA source `1199c46fee8053e637b220ad9365ce3af15eb8e5`, image browser digest `c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04`.
- **Legacy:** CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`, `RUNNING_HEALTHY`, `127.0.0.1:8443`.
- **Prohibiciones:** no BLACKBOX, Porota, Docker ajenos, GO_B/PREPARE/APPLY, reservations/ingreso real, retry, shell o contenido Docker en logs; sólo Actions protegidas para host.
- **Compromiso:** R80 #795 no cambia de comportamiento, `RECOVERY_SOURCES` sigue mínimo, 0 duplicados.

## Review Focus

1. Probe con CID o metadata casi correcta pero `Running=true` -> rechazo sin `rm`.
2. Race entre dos verificaciones o posterior al `rm` -> `NO_GO_PRECHECK` o `INDETERMINATE`, respectivamente.
3. Seccomp diferente/BOCA_ENV extra/mount/port/network o full JSON grande -> no escritura.
4. Segundo dispatch R82 o run history parcial -> abortar antes de SSH.
5. Receipt de otro incidente o ACK perdido -> rechazo terminal, sin retry.

## Task 1 — RecoveryTarget y aislamiento compartido (TDD)

**Files:** Modify `scripts/host_cutover_worker_recovery.py`; create `tests/test_r82_exact_worker_807_recovery.py`.

**Interfaces:** Configuración estática immutable `RecoveryTarget`, dos targets #795/#807; `execute(target=...)` con #795 default; `_validate_snapshot`, `_validate_isolation`, `_remove_exact`, `_cid_present`, `verify_runner` fijados al target elegido, sin targets ni nombres provenientes del host/usuario.

- [x] Primero escribir regresión RED para #807 pin exacto; correr pytest y ver fallo funcional esperado.
- [x] Refactor mínimo del recuperador compartido y aplicar perfil R82. Comprobar RED->GREEN y regresión #795.
- [x] Incorporar matrix negativa/positiva QA: 2 prechecks bajo lease, full inspect, único `rm` no forzado; postflight ID+name, legacy; statuses y ACK terminal.
- [x] Ejecutar test focalizado, Ruff y mypy; no simular acceso al host.

## Task 2 — Bundle mínimo y entrada de modo R82 (TDD)

**Files:** Modify `scripts/build_protected_boca_bundle.py`, `scripts/boca_protected_memfd_bootstrap.py`; test `tests/test_protected_boca_bundle_recovery.py` y tests R82 nuevos.

**Interfaces:** modo interno fijo `cutover-worker-807-recover` sin argumentos; mantenido `cutover-worker-recover` histórico. Mismo SHA/allowlist/cap del ZIP mínimo.

- [x] RED ante modo nuevo, coordenadas de host extras, ZIP alterado y perfil ajeno.
- [x] Añadir la rama mínima de selección de perfil, no copiar el bundle ni cambiar tamaño del paquete Cutover global.
- [x] GREEN + regresión ZIP #795 y auto-rechazo de payload accidental.

## Task 3 — Gate GitHub REST y workflow protegido (TDD)

**Files:** Modify `scripts/check_worker_recovery_dispatch.py`, `.github/workflows/boca-first-deploy.yml`; tests `tests/test_r82_exact_worker_807_recovery.py` y `tests/test_r80_recovery_gate.py`.

**Interfaces:** nuevo comando de verificación R82 explícito con JSON REST acotado de: PRs OPEN, #807 run failure, #809 run success, #723 release dual success, history completa de dispatch, jobs #809 y main ref. `BOCA-R82-WORKER-807-RECOVER-ONCE` único, `run_attempt=1`, actor/source exactos. Aceptación runner del recibo canónico R82 y artefacto con ID propio.

- [x] RED de replay, historia incompleta, fuentes/actores equivocados, gate Bash y recibo falsificado.
- [x] Extender gate compartido, rama de operación fija y SSH/memfd único. Preservar operación y run-name R80.
- [x] GREEN de gate real con fixtures REST y protección de boundaries; no host mutation en PR.

## Task 4 — Documentación, revisión y publicación

**Files:** Update `README.md`, `docs/OPERATIONS.md`, `docs/BETA_INTEGRATION_STATUS.md`, ADR0191 con estado de código, no afirmar limpieza física.

- [x] Pruebas focalizadas y **suite completa**; Ruff check/format, MyPy, política, YAML (`python3` con PyYAML) y `git diff --check`.
- [x] Revisión independiente QA, Arquitectura, Infraestructura, CI/CD; 0 Critical/Important.
- [ ] Un PR no draft, cuatro Actions exact-SHA GREEN, merge único, 0 PR, postmerge CI y seguridad GREEN.
- [ ] **Único** dispatch R82 tras evidencias físicas/REST y gates protegidos. Recibo `VERIFIED` o `INDETERMINATE` con prohibición de retry.
- [ ] Comentar #417 y #45 en cada transición; Cutover permanece NO_GO hasta RCA/GO separado.
