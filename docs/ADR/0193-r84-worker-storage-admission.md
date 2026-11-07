# ADR 0193 — R84: capacidad de disco en el preflight worker de Cutover A

**Fecha:** 2026-11-07 ART. **Estado:** diseño CODE_ONLY, sin despliegue.
**Owner:** [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417); continuidad [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Evidencia y decisión

R83 `main=f709508c64c821a5452224fb4ce7bc23d5c909a7`, release dual
[#727](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42347255399),
no está instalado. En `scripts/host_cutover_worker_preflight.py`, la función
`_pull_observing_capacity` efectuaba los dos `docker pull` y comprobaba
continuidad de identidad del almacenamiento con `require_capacity=False`.
No se exigían bytes ni inodos mínimos. Esta omisión preventiva es real;
**no se ha probado que fuera la causa física del fallo #807**.

La enmienda R50 de [ADR0183](0183-postpull-boca-beta-emergency-residual.md)
ya está implementada en `host_first_deploy._browser_pull_both` y probada:
4 GiB/50.000 inodos en staging **y** Docker rootless antes de la primera
descarga; 1 GiB/50.000 inodos y misma topología después de cada imagen y
antes de la segunda. Reutilizar esa función desde el preflight sustituye
la lógica duplicada y no agrega comandos Docker, efectos host ni excepciones
en el contrato de seguridad. Se conservan los dos pulls de 120 s, validación
source/digest, cleanup por ID, singleton y fases de error de R83.

**Alternativas descartadas:** mantener `require_capacity=False` (riesgo ENOSPC
no admitido), duplicar los umbrales en otro script (deriva de políticas),
exigir 4 GiB antes del segundo pull (contradice la enmienda R50).

## Contrato de regresión

- Rechazar 4 GiB menos un byte o 49.999 inodos antes del primer pull: **0 pulls**.
- Aceptar umbrales inclusivos; rechazar residual inferior a 1 GiB o 50.000
  inodos tras controller: **1 pull, no iniciar browser**.
- Rechazar bajo residual o deriva de dispositivo/inode/socket tras browser:
  **2 pulls, NO_GO**; sin nuevos contenedores ni limpiezas especulativas.
- Conservar `primary_failed_phase=GHCR_PULL` y `cleanup=VERIFIED` si no hubo
  fallo de compensación; cualquier error cleanup sigue INDETERMINATE.
- Verificar que Cutover full y recovery ZIP permanecen byte-idénticos a R83,
  y que solo el ZIP preflight cambia; sin ampliar límites R83.

**Comparación determinista CODE_ONLY contra `origin/main=f709508...`** mediante
`git archive` de la fuente baseline y el mismo builder, sin ejecutar el ZIP:
Cutover full **207.943 B**, SHA256
`f52fb7d4338ae02f534e5523abc355639d289ad0939ed7058a2f8c8535722ad9`
en ambos; recovery **40.471 B**, SHA256
`6ee6fe0a10f162f38246bb4920cc0710e89d82c4b7c1c08fd5e863b385309c53`
en ambos. El preflight aislado R83 **100.597 B** / SHA256
`898e752bfd80f41c06f0401d05f82e8f03485ff31ba528c7574203b4128e4e01`
cambia en R84 a **100.538 B** / SHA256
`a8835d47ae755d65d6f120832f6a53cb5ee70ff232c70494d24f323222a31a75`.
Las tres variantes respetan sus caps sin alterar la allowlist.

## Prevención de dos nuevos despachos del mismo SHA (consenso 4/4)

`GITHUB_RUN_ATTEMPT=1` impide reejecutar un run, pero NO un segundo
`workflow_dispatch` con otro ID. Arquitectura, QA, Infra y CI/CD decidieron
agregar un gate **pre-SSH** al mismo workflow protegido, con identificador
visible `BOCA-R84-WORKER-PREFLIGHT-ONCE`: consultar el historial REST de
`boca-first-deploy.yml` filtrado por `workflow_dispatch` y `head_sha`, y los
PR abiertos. La respuesta debe ser completa y acotada (1–100 registros,
`len(workflow_runs)==total_count`), sin identidad repetida ni SHA distinto.
Debe haber **exactamente un** run con ese título: el actual, de primer intento,
`main`, actor y repo exactos. Un segundo despacho del **mismo SHA**, aun si el
primero falló o fue cancelado, aborta sin SSH. Un SHA nuevo derivado de un PR
FIX-FORWARD y una release nueva es una decisión independiente; no establecer
un veto global irreversible a futuros arreglos.

Se reutiliza el parser de JSON REST acotado de `check_release_dispatch.py`
con rechazo de claves duplicadas/symlink/archivo sobredimensionado. Cualquier
error de API, paginación, PR abierto o run ambiguo permanece NO_GO.
No se crea otro workflow, lease ni operación Docker. Este guard es preventivo;
no reemplaza el historial/consenso previo a cada acción física.
Si el gate se rechaza o salta, la verificación terminal informa
`dispatch_gate=NOT_PASSED ssh=NOT_ATTEMPTED_BY_RUN`, sin inferir un estado del
host a partir de un paso SSH que nunca comenzó. Si SSH sí se intentó, el
recibo conserva el formato de fases/cleanup R83 y `host=UNVERIFIED`.

## Límites y entrega

Un chequeo previo no reserva espacio en el filesystem compartido. Si el pull
falla por ENOSPC, no borrar imágenes o recursos de otros proyectos; conservar
NO_GO y obtener inventario Boca READ_ONLY. Si cambia el código y SHA, la release
#727 queda histórica; se requieren nuevo PR/CI/merge, cero PR abiertos y
**release dual fresca** antes de una sola observación protegida de host.
La observación no autoriza preflight físico, GO_B, PREPARE ni APPLY.
Sin navegación Boca real, Telegram real, modificaciones BLACKBOX o scripts
de mantenimiento ajenos.
