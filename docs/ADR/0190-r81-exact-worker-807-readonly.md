# ADR 0190 — R81: observar únicamente el preflight fallido #807

**Fecha:** 2026-11-07 ART. **Estado:** propuesta CODE_ONLY hasta PR, revisiones,
CI y ejecución física protegida. **Ownership:** issue #417 / checkpoint #45.

## Hechos y causa identificada

- El `main=1199c46fee8053e637b220ad9365ce3af15eb8e5` publicó controller y
  Chromium browser en el [release dual #723](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42340930071)
  con escaneos, digests y manifiestos verificados.
- El preflight único [#807](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42341290485)
  (attempt `42341290485`) terminó `failure`/exit 3. Summary:
  `BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED phase_claim=CLEANUP cleanup_claim=INDETERMINATE next=read_only_boca_inventory no_retry=1`.
- `host_cutover_worker_preflight.py` ejecuta el cleanup en `finally` y eleva
  `PreflightFailure("CLEANUP", "INDETERMINATE")` si falla la eliminación del
  seccomp temporal, alguna lectura/stop/rm/postlectura del probe o la
  revalidación final del controlador legacy. **La categoría borra el punto de
  falla original**. No está demostrado cuál fue el fallo, si hubo borrado, si
  queda un contenedor o si el legacy está sano ahora.
- R80 [#806](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42340750343)
  sí había retirado y verificado el **otro** probe histórico #795; ese éxito
  previo no sirve para presumir limpieza de #807.

## Decisión: extender el observador existente, no repetir operaciones

El observador R78 `host_cutover_worker_inspect.py` ya usa socket rootless del
UID/GID 10001, `lstat` sin seguir symlinks, `docker ps` por nombre exacto y
hasta tres `inspect` compactos por CID, siempre con límite de tiempo/bytes,
sin Docker writes. R81 añade un mapa inmutable de dos incidentes históricos,
conservando #795 y admitiendo **sólo** #807 como segundo objetivo:

| Identidad | Preflight histórico #795 | Nuevo #807 |
|---|---|---|
| Attempt | `42329475083` | `42341290485` |
| Source SHA | `92624ed6b7e75c6010f59670c866df00a29766dd` | `1199c46fee8053e637b220ad9365ce3af15eb8e5` |
| Browser digest SHA256 | `3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9` | `c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04` |

El único legacy permitido para el nuevo observer es el CID
`27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`,
SHA `cabce9f1e452e63ded115f447559a358dc0f4d1b` y su digest histórico
`cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59`.
No aceptar CID de probe como input: se descubre **por nombre exacto de #807**
y se mantiene como candidato no autorizado para mutaciones.

Se reutiliza la operación manual `cutover-a-worker-inspect` del workflow
protegido, con `protected_action_context=42341290485`, los tres pins legacy
exactos, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`, todos
los campos restantes vacíos. La validación del workflow impide un tercer
incidente o la utilización de imagen arbitraria. El host recibe sólo una
observación por SSH de hasta 75 segundos y cuatro lecturas Docker acotadas,
sin `pull`, `create`, `start`, `stop`, `rm`, `exec`, `prune`, otros sockets ni
intervención sobre el controlador original.

## Criterios de interpretación y salida

- **Probe y seccomp ausentes + legacy HEALTHY/LOOPBACK_8443:** prueba ausencia
  puntual de esos residuos, *no* aislamiento funcional ni GO de nuevo
  preflight/PREPARE/APPLY.
- **Probe exacto detenido/presente:** identidad compacta observada, no
  autorización de limpieza. Requerir revisión de aislamiento completo,
  recuperación quirúrgica separada y recibo antes de cualquier nueva prueba.
- **Probe running, mismatch, socket/legacy UNVERIFIED:** STOP, no inferir
  cleanup, no mutar ni reintentar.
- **Cualquier resultado del observador:** `READ_ONLY_NO_GO`,
  `observer_writes=0`, `cutover_authorized=false`, sin alterar ningún estado.

## Evidencia por completar

Pruebas adversariales para #807 y regresión de #795, contract workflow,
parser YAML, Ruff, MyPy, política de aislamiento, revisión QA/Arquitectura/
Infra, checks exactos del PR, merge y postmerge. Hasta entonces no hay
resultado físico nuevo. Toda lectura futura debe registrarse en [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
y [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
No tocar módulos BLACKBOX, datos/volúmenes, otras apps, Porota ni puerto 8443.
