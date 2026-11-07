# Plan R83 — diagnóstico primario/compensación del preflight Boca

**Contexto:** #807 NO_GO y causa inicial enmascarada; #811 limpia únicamente residuo exacto. Partir de `main=16512f953d81a96ab7a492244b19d3bea8f00c27`, sin retomar ramas viejas ni crear un preflight físico por intuición.

## Trabajo paralelo sin solapar ownership

1. **QA — pruebas RED primarias**, `tests/test_r83_primary_phase.py`: GHCR_PULL/WORKER_CREATE con falla posterior, frontera de worker con limpieza exitosa, final de legacy. Sin tocar producción.
2. **Infra — pruebas RED limpieza**, `tests/test_r83_cleanup_stages.py`: PS/INSPECT/OWNERSHIP/STOP/RM/POST_ID/TEMP_SECCOMP/LEGACY, identidad ajena no se toca, sin reintentos ni stdout crudo. Sin tocar producción.
3. **CI/CD — pruebas RED parser**, `tests/test_r83_preflight_workflow.py`: receipt NO_GO exacto y `UNVERIFIED` ante faltantes, duplicados, truncamiento y campos desconocidos; invariantes de Gates intactos. Sin tocar workflow.
4. **Arquitectura — revisión independiente** del diseño, categorías y carácter fail-closed. Ninguna operación de host.
5. **Implementación integrada — owner principal:** ampliar `PreflightFailure` de forma compatible; capturar primera excepción antes de salida de context manager; etiquetar cada subfase de `_cleanup_exact` sin nuevas llamadas Docker; actualizar recibo NO_GO y parser en el único workflow. Nunca tocar `src/boca_socios/browser/synthetic.py` o `ipc_worker.py`.
   **Subpaso arquitectónico obligatorio C:** retirar script preflight del ZIP Cutover, crear build + bootstrap dedicados de siete entradas y límites 480000/128000; conservar Cutover 860000/512000, recovery 256000/128000 y el host release exacto. Validar 3×3 rechazos cross-mode y que el workflow construya el paquete correcto. El aumento de los caps Cutover (opción B) se descarta por relajación de una barrera.
6. **Verificación y consensus:** RED→GREEN focal, regresión completa local, policy/format/MyPy/YAML, diff y revisión QA/Arquitectura/Infra/CI; remediar defectos con fix-forward.
7. **GitHub única fuente de verdad:** publicar ADR, plan, tests y código en una única PR; comprobar 4/4 Actions, merge único, cero PR abiertos, postmerge CI/seguridad, documentar #417 y #45.
8. **Gate físico posterior separado:** reconciliar main y release dual exactos; comprobar gates/ownership/evidencia. Un preflight nuevo sólo con decisión técnico-física propia; si no hay prueba suficiente: NO_GO y evidencia en issues. GO_B/PREPARE/APPLY jamás se infieren del preflight.

## Criterios de aceptación

- Un fallo `GHCR_PULL` seguido de `RM` fallido conserva simultáneamente `primary_failed_phase=GHCR_PULL cleanup_failed_stage=RM` y `failed_phase=CLEANUP cleanup=INDETERMINATE`.
- Un fallo sólo en `STOP` genera `primary_failed_phase=NONE cleanup_failed_stage=STOP` y no toca otros contenedores.
- Una caída del seccomp durante el `__exit__` no borra un fallo primario que ya se capturó dentro del `with`.
- El parser NO_GO no convierte un receipt inválido en aceptación; jamás imprime la salida remota no saneada.
- Ningún cambio de acciones, permisos, identities, required checks o contrato de PASS; el resultado físico queda separado de lo que pueda comprobar CI.
- La nueva variante preflight no puede importarse ni ejecutarse desde el ZIP Cutover, y ningún paquete se acepta en el modo de los otros dos.
