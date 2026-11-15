# R306 Mount witness order — Implementation Plan

> Ejecutar mediante superpowers:subagent-driven-development; autor separado,
> raíz conserva documentación, revisión, GitHub y host.

**Goal:** eliminar falso drift por orden sin descartar ninguna evidencia.
**Base:** b96db3a13ad50e663ae3eb8cde82345a72792aaf.
**Design:** docs/superpowers/specs/2026-11-15-r306-mount-witness-order-design.md
**Worktree:** reutilizar el checkout limpio existente, rama
fix/527-r306-mount-witness-order; no crear otro checkout ni repetir trabajo.

## Task1 — autor, dos archivos

- [ ] Leer diseño ratificado y el delta concreto. No releer BLACKBOX ni
  reauditar código base ya revisado. No host/GitHub.
- [ ] Añadir tests/test_r306_mount_witness_order.py con funciones estables:
  test_r306_mount_order_is_irrelevant_through_real_recovery;
  test_r306_mount_drift_is_rejected_despite_permutation;
  test_r306_mount_records_and_identities_preserve_all_evidence;
  test_r306_duplicate_mounts_refused_before_sort.
  Parametrizar pre/post-init y todos snapshots; incluir Source/RW/Mode/campo
  adicional/dev-inode/alias/extra. Puede agregar más tests útiles en ese archivo.
  Reutilizar fixture R305 y envolver sólo la frontera Docker para permutar JSON;
  no sustituir validadores o comparadores reales ni editar tests anteriores.
- [ ] Ejecutar positivos antes del parche y conservar RED causal (falso
  NO_GO/PREFLIGHT o VERIFY_INITIALIZATION, sin error de import/fixture).
- [ ] Insertar únicamente ordenación de copia por Destination después del
  contrato _mounts exacto y antes del recorrido que construye identities.
  Conservar registros íntegros y todas las guardas.
- [ ] Ejecutar test nuevo y tests/test_r305_telegram_initializer_recovery.py;
  controles focales de tests/test_r305_telegram_initializer_transport.py:
  test_real_zip_has_exact_reviewed_bytes_and_independent_allowlist,
  test_isolated_zip_verifier_accepts_canonical_zero_and_three,
  test_real_zip_host_and_memfd_entrypoint_deny_uid_before_effects,
  test_actual_summary_shell_uses_same_zip_and_strict_rc_pair.
- [ ] Reutilizar el único ZIP construido por la fixture de transporte,
  copiándolo a r306-evidence/author/boca-r306-initializer.pyz. Registrar hash,
 30entradas/tamaños; comparar con ZIP R305 previo: sólo módulo distinto,
 las29otras entradas byteidénticas. No reconstruir los otros paquetes.
- [ ] Ruff check/format2, mypy1, diff-check. Guardar diff, SHA256 de los2archivos,
 informe y comandos/logs bajo r306-evidence/author. Sin commit/push.

## Task2 — raíz, revisión y promoción

- [ ] Registrar cuatro votos sobre diseño/plan antes de autorizar código.
- [ ] Mantener RCA527 con20..300caracteres/1..8selectores,56lecciones previas
 intactas; correr los2tests reales de contrato RCA al cerrar documentación.
- [ ] Congelar árbol completo; cuatro revisiones del delta, reutilizando base
 y paquetes sin cambio. Corregir hallazgos focales sin pruebas redundantes.
- [ ] Reconciliar main/PRs. Publicar candidato atómico y convertir issue527 a PR.
 CI exacta, merge con head esperado, CI/security exactas del nuevo main.
- [ ] Reconciliar runs, despacho único corregido y verificador desde mismo ZIP.
 Guardar recibo/hash y checkpoint inmediato. NO_GO desconocido implica parar
 efectos y obtener diagnóstico acotado; nunca encadenar reruns.
- [ ] Tras ACCEPTED físico, prepare instalado R/release867 separado y su recibo.
 Registrar estado Docker/Telegram literal y pendientes funcionales auténticos.

## Límites comunes

Sin cambios de workflow/builder/bootstrap/caps/allowlists/codec. Sin otra
release/APPLY, helper, volumen, SQL, stop/start del par en recuperación,
BLACKBOX, sender, mensajes, proveedor o Porota/PPI. La normalización de orden
no permite llamar equivalentes a mounts con distintos campos o identidades.
