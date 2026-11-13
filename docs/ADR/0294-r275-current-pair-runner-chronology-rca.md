# ADR 0294 — R275: cronología invertida en el ejecutor protegido

**Fecha:** 13-NOV-2026 (ART). **Proyecto:** Boca Socios Assistant.  
**Fuente:** [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).  
**Clase:** RCA de fallo determinista **pre-SSH**; NO es una instalación aceptada.

## Evidencia y causa raíz

- El árbol `main=85e66546cba86e252b801f671a9649589fcafda1` y sus dos
  imágenes se publicaron por la release única
  [#862](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43471994769).
- La Action [#1079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43472874879)
  certificó el par **anterior** `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`:
  controlador `healthy`, worker `Created`, puerto 8443 solamente en
  loopback, sin escrituras. La Action
  [#1080](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473379911)
  confirmó los recursos retenidos y sus inodos, con `observer_writes=0`.
- El APPLY único [#1081](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473805164)
  terminó `exit 3` en el guard de GitHub Actions; el flujo salió antes de
  `ssh boca-target` y antes de cualquier operación remota.
- **Defecto exacto:** `scripts/attest_current_pair_v2.py`, validación inicial
  de `attest_runner()`, conservaba la condición antigua
  `historical_run < pair_run < apply_run`. El bridge de recursos corregido
  en R274 exige `pair_run < historical_run < apply_run`. Los recibos reales
  satisfacían el segundo orden, por lo que el primer guard los rechazaba
  antes de leer cualquier ZIP. Las pruebas previas construían fixtures con
  el orden anticuado y no ejercitaban el ejecutor completo en la cronología
  física de #1079/#1080.
- Se descargaron **solo para replay offline** los ZIP genuinos de #1079,
  #1080, #862 y de la release previa #851, comprobando sus SHA-256 de
  archivo; los verificadores independientes de observación, release,
  catálogo anterior, custodia y par V2 pasaron. El replay del ejecutor
  completo reprodujo exactamente el NO_GO en la cláusula de orden, y tras
  el cambio mínimo pasó con los mismos recibos.

## Corrección y prevención permanente

1. Unificar el orden en el ejecutor con
   `pair_run < historical_run < apply_run`, sin relajar validaciones de
   origen, actor, SHA, artefactos, job, ZIP, lease, recursos ni identidad.
2. Las pruebas de corredor usan una observación retenida **posterior** al
   par y anterior al APPLY para dos generaciones de actualización; incluyen
   negativos para retenida anterior, simultánea o posterior al APPLY y
   verifican `catalog.reads=0` y **cero archivos nuevos** ante rechazo.
3. Antes de despachar futuros APPLYs, verificar **la misma comparación en
   cada módulo del grafo**, ejecutar el test del runner integrado más un
   replay offline de recibos reales y fijar los cuatro run IDs exactos.
4. No reconstruir perfiles ni reinstalar contenedores para diagnosticar.
   Una promoción de código que cambia `main` requiere una única release
   nueva vinculada al nuevo SHA; no reutilizar fraudulentamente imágenes de
   otro commit. Reducir CI por alcance, no sustituir la proveniencia.
5. Separar en reportes `main`, `release`, `installed` y
   `OWNER_PENDING`. Un APPLY previo a SSH **no instala**. Después de
   iniciar SSH, cualquier resultado incierto exige observación/journal
   físico, nunca reintento automático ni reejecución de R186.
6. Mantener Boca confinado a rootless/puerto 8443 y
   `SIMULATION_ONLY`, sin tocar Porota, PPI Watch, otros contenedores,
   credenciales o reservas reales.

Este documento es RCA y prueba de regresión, **no una certificación de
despliegue**. La certificación requiere recibo `BOCA_PAIR_UPGRADE ACCEPTED`
y una observación READ_ONLY posterior del SHA y los dos digests físicos.
