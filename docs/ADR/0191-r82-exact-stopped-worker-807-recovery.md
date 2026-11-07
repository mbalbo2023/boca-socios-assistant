# ADR 0191 — R82: recuperación única del probe detenido #807

**Fecha:** 2026-11-07 ART. **Estado:** implementación CODE_ONLY revisada 4/4, sin ejecución de host ni GO de Cutover.
**Owner:** issue #417; continuidad y aprobaciones en #45.

## Evidencia física que delimita la operación

El único [inventario protegido #809](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42342822240)
(`main=8146ab94c1fedf02fbe0ba14e225bbce61339044`) devolvió un
recibo canónico v3 con `observer_writes=0`, `cutover_authorized=false`:

| Campo | Observado |
| --- | --- |
| Failed attempt | `42341290485` (#807) |
| Probe CID | `06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d` |
| Probe | `PRESENT_PIN_MATCH`, `probe_running=false`, `probe_full_json_stage=BELOW_CLEANUP_LIMIT` |
| Rootless socket | `PRESENT_OWNED`, `docker=OBSERVED` |
| Seccomp temp | `ABSENT` |
| Legacy | `RUNNING_HEALTHY`, `LOOPBACK_8443` |

El probe pertenece a la fuente
`1199c46fee8053e637b220ad9365ce3af15eb8e5` y a la imagen browser
`ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04`.
El legacy tiene CID
`27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`,
SHA `cabce9f1e452e63ded115f447559a358dc0f4d1b` y digest
`cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59`.
El [release dual #723](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42340930071)
fue GREEN. La observación compacta **no es autorización para `rm`**.

## Alternativas consideradas

1. Clonar el recuperador R80 y sólo sustituir constantes: **descartado**,
   duplica validaciones y rompe la regla de no repetir código.
2. Reutilizar la operación R80 ya consumida alterando su objetivo: **descartado**,
   confunde los marcadores de anti-replay y el incidente acreditado.
3. **Seleccionada:** recuperar con una operación fija nueva
   `cutover-a-worker-recover-807`, conservando intacta la ruta R80 #795,
   y compartir código bajo **dos perfiles inmutables**, sin targets libres.

## Contrato de implementación

- El workflow único de Boca añade sólo la operación R82 y el marcador
  `BOCA-R82-WORKER-807-RECOVER-ONCE`, siempre `main`, actor autorizado,
  Environment protegido, budget `1.5cpu-1024m-192pids`, todos los inputs
  de imagen, source, release, legacy, Telegram, owner y noticias **vacíos**.
  No amplía GO_B ni habilita PREPARE/APPLY.
- La comprobación REST previa exige `run_attempt=1`, HEAD actual,
  **0 PR abiertos**, despacho R82 exactamente único, evidencia exacta de
  #807 (fallido), #809 (READ_ONLY aprobado) y #723 (release publicado),
  actor/repo/paths correctos y corridas incompletas denegadas. El estado
  R80 histórico #795/#806 no se altera ni se vuelve a ejecutar.
  **El éxito REST de #809 es procedencia, no certificación del contenido del
  JSON:** las dos validaciones físicas frescas deciden si puede retirarse.
- Se mantiene el ZIP mínimo de recuperación, con entrada de modo R82
  fija (`cutover-worker-807-recover` → `host-807`), checksum calculado y
  allowlist, ejecutado de memoria mediante memfd/SSH;
  **sin parámetros de CID o imagen provenientes de formularios**. El
  paquete Cutover completo no crece ni altera su techo.
- Bajo un único lease Boca, ejecutar **dos verificaciones completas**
  del snapshot y de la identidad/aislamiento del Docker detenido: nombre,
  CID, digest, revisión, labels, status no running/restart/paused/dead/OOM,
  BOCA_ENV exacto, UID, namespaces, seccomp efectivo, capabilities,
  rootfs, montajes, puertos, redes, limites y legacy saludable 8443.
- Sólo tras pasar todas las verificaciones se admite **una** llamada
  `docker container rm 06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d`
  sin `--force`, `--volumes` ni target dinámico. Verificar ausencia por
  ID **y nombre**, seccomp ausente y original sano. No `stop`, `prune`,
  image/network/volume/daemon writes, ni otros Docker, Porota o puerto.
- Antes de cualquier intento de `rm`: fallar `NO_GO_PRECHECK`/writes 0.
  Desde el primer intento: ACK no válido, timeout, fallo postflight o
  pérdida de runner = `INDETERMINATE`/writes 1 y **ningún reintento**.
  Sólo un recibo terminal canónico, vinculado a las coordenadas exactas y verificado,
  puede acreditar `CLEANED cleanup=VERIFIED`.
- Aun con limpieza verificada, `cutover_authorized=false` y
  `retry_authorized=false`. El Cutover y un nuevo preflight requieren RCA
  y aprobación técnico-física separados. No reservas reales.

## Verificación de implementación y aceptación pendiente

RED/GREEN adversarial y validación local terminadas: **4668 pytest PASS +34
subtests**, política, Ruff, MyPy, YAML y `git diff --check` GREEN. QA,
Arquitectura, Infra y CI/CD revisaron el código sin Critical/Important
pendientes; los tres contratos históricos de workflow se ampliaron de modo
explícito sin desactivar gates. Ninguna prueba local constituye evidencia
de limpieza física.

**Todavía pendientes:** cuatro Actions del PR exacto, merge único (0 PR),
postmerge CI/seguridad y, **recién después**, un único despacho protegido R82.
Documentar receipts en #417 y #45. Cualquier inconsistencia conserva NO_GO
sin intentar corregir en el host.
