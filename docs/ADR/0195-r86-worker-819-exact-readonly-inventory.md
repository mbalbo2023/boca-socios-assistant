# ADR 0195 — R86: inventario READ_ONLY exacto del worker #819

**Fecha:** 2026-11-07 ART. **Estado:** candidato CODE_ONLY hasta PR/CI/revisión/merge; ninguna observación #819 realizada con esta versión. **Ownership:** RCA #417, continuidad #45.

## Evidencia física y límites del RCA

El único preflight R85 [#819 / 42353468231](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231) fue despachado por el dueño sobre `main=0538b3fb29cc0245a8387b7023c394883d0ea9a8` tras CI, release dual [#732 / 42352641660](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42352641660), PR0 y consenso Arquitectura/Infra/QA. La Action terminó **FAILURE**, con recibo protegido:

```text
BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED phase_claim=CLEANUP cleanup_claim=INDETERMINATE primary_failed_phase_claim=NONE cleanup_failed_stage_claim=STOP next=read_only_boca_inventory no_retry=1
```

El host afirma haber completado la prueba principal de aislamiento de un worker temporal; durante cleanup leyó un CID con nombre/digest/etiquetas correspondientes, observó `Running=True`, e intentó `docker stop --time 5 <CID>`. Un error, timeout o ACK distinto del CID llevó a STOP y omitió `docker rm` y confirmación de ausencia. **No se puede concluir si el stop hizo efecto**, si el proceso expiró posteriormente, si queda un contenedor, si persiste el seccomp o si el legacy mantiene la salud de #818. El runner etiqueta el relato del host como `UNVERIFIED`. No repetir #819 ni avanzar PREPARE/GO_B/APPLY.

## Alternativas y decisión del equipo

- Reusar `cutover-a-observe` no identifica un probe presente; no proporciona la evidencia requerida.
- Introducir otro inspector/workflow duplica una superficie privilegiada y contradice las prácticas de mantenimiento.
- **Elegido por Arquitectura/Infra/QA:** ampliar únicamente la lista de identidades inmutables del inspector existente R78/R81 y el `case` de `cutover-a-worker-inspect` para #819. Se reutilizan los cuatro Docker `ps`/`inspect` de lectura, los límites de 12s/2048 bytes, `lstat` del seccomp, el recibo JSON v3, verificación del controlador original y SSH protegido de 75s.

| Pin inmutable | Valor |
| --- | --- |
| Intento #819 | `42353468231` |
| Probe esperado | `boca-socios-cutover-preflight-42353468231` |
| Source SHA del probe | `0538b3fb29cc0245a8387b7023c394883d0ea9a8` |
| Imagen browser release #732 | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619` |
| CID legacy | `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` |
| Source legacy | `cabce9f1e452e63ded115f447559a358dc0f4d1b` |
| OCI legacy | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59` |

El workflow exige los tres pins legacy exactos y **vacíos** los campos de nueva imagen, browser y release; sólo `protected_action_context=42353468231`, `service=controller`, presupuesto `1.5cpu-1024m-192pids`. La Action no instala imagen ni usa GO_B. Añade nombre visible propio `BOCA-R86-WORKER-819-READONLY` y captura runner en directorio privado de nombre aleatorio, con `umask 077` y `ulimit -f 4` **antes** de iniciar SSH, evitando salida host ilimitada o ruta preplantada. No se declara ejecución única por nombre: cada ejecución física requiere revisión de propósito y no admite `re-run jobs`.

**Acoplamiento de empaquetado:** `host_cutover_worker_inspect.py` también integra el bundle histórico de *recovery*. Al ampliar el mapa cambian su ZIP y SHA256; deben recertificarse las siete entradas/cotas/segregación. **No** cambia el bundle completo de Cutover ni el bundle de preflight, ni se añade #819 a los objetivos de `host_cutover_worker_recovery.py`. Ninguna recuperación puede derivarse de este ADR.

**Comparación reproducible local (no evidencia de host):** el ZIP Cutover conserva SHA256 `f52fb7d4338ae02f534e5523abc355639d289ad0939ed7058a2f8c8535722ad9` (207.943 B); el preflight conserva SHA256 `a8835d47ae755d65d6f120832f6a53cb5ee70ff232c70494d24f323222a31a75` (100.538 B). El ZIP recovery cambia a SHA256 `56aaff504e23302357df8b5f44e6e03ab3710c7233da2520a4cbe950e1c4d5df` (40.692 B), con exactamente siete archivos autorizados y sin target #819. Todos están dentro de los límites existentes. Los checks Actions del SHA final deben repetir esta validación.

## Interpretación del inventario futuro

- `ABSENT`, seccomp `ABSENT`, legacy `RUNNING_HEALTHY` y loopback: ausencia puntual de residuos; preflight #819 sigue NO_GO histórico, sin GO automático de Cutover o de nuevo preflight.
- `PRESENT_PIN_MATCH`, `probe_running=false`: no tocar; considerar otro diseño de recuperación no forzada sólo por CID exacto y posterior revisión independiente.
- `PRESENT_PIN_MATCH`, `probe_running=true`: no sirve la recuperación stopped-only; no intentar STOP/removal sin nueva evidencia, diseño y gate.
- `PRESENT_UNVERIFIED`, `PARTIAL`, seccomp de pertenencia incierta o legacy no saludable: preservar todo, NO_GO e investigar.

En todos los casos  `READ_ONLY_NO_GO`, `observer_writes=0`, `foreign_resources_touched=false`, `cutover_authorized=false`. No Docker write, otros proyectos, BLACKBOX, Boca real, Telegram ni 8443 nuevo. No nueva release OCI para esta observación de metadata; un futuro Cutover effectful sobre nuevo `main` sí necesitará dos imágenes autenticadas de su SHA.

**Pruebas locales del candidato exacto:** `uv run pytest -q` → **4.899 PASS +34 subtests PASS** (90,14 s), `uv run mypy src` → 136 fuentes sin errores, Ruff lint/formato y política de aislamiento PASS; subconjunto inspector/recovery/paquetes **363 PASS**. `tests/test_r86_exact_worker_819_observer.py` ejecuta también Bash real con SSH falso y salida excesiva. Estas pruebas no acreditan checks remotos del PR ni estado del droplet.
