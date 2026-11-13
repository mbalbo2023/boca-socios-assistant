# ADR 0293 — R274: bloqueo pre-SSH en sucesor Boca, compatibilidad histórica

**Fecha:** 13-NOV-2026 (ART). **Proyecto:** Boca Socios Assistant.
**Fuente canónica:** issue #417. **Alcance:** runner de GitHub Actions; cero
modificaciones autorizadas sobre Porota, puertos/servicios ajenos o R186.

## RCA basado en evidencia real

La release del nuevo commit `0b9820f270e326672b777e36cd712c3c60247a5e`
fue publicada satisfactoriamente una sola vez por Action
[43465575452](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43465575452).
Conserva dos manifiestos de imágenes inmutables.

El par Boca anterior (`b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`)
permaneció instalado en observaciones de solo lectura. Un paso CI GREEN no
equivale a ese `INSTALLED_SHA`.

1. La primera Action
   [43466413414](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43466413414)
   terminó en el paso `Upgrade Boca-only rootless pair under one lease` con
   `exit 3` **antes** del SSH. El par observado por 43464710404 se capturó
   después de la observación de recursos 43464488963: esa cronología es
   rechazada explícitamente por `_coordinates()` de
   `host_boca_upgrade_retained_bridge.py`.
2. Se realizó una sola nueva observación READ_ONLY posterior al par:
   [43467281965](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43467281965),
   `SUCCESS`, `observer_writes=0`, recursos e inodos estables.
3. La segunda Action
   [43467640849](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43467640849)
   también terminó `exit 3` en el guard local, sin terminal ni SSH. El
   siguiente bloqueo determinista identificado en código es la comprobación
   `_verify_release_job()`: exigía `total_count=1`, incompatible con la
   release histórica genuina
   [43215180354](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43215180354).
   Dicha release contiene exactamente `publish-reviewed-image=success` y
   `release-image-pr-validation=skipped`, ambos con el mismo run/SHA; los dos
   manifiestos siguen presentes. El fixture anterior solo incluía un job,
   lo que dejó pasar el defecto por CI.

El `exit 3` de estos dos intentos proviene del `NO_GO` de verificadores
locales capturado con `set -e`; el único comando remoto de este paso está
después de la autenticación del par, las dos releases y la custodia histórica.
Las etapas posteriores de aplicación, journaling y postflight **no se
alcanzaron**. No cambiar el estado a `ACCEPTED` sin una futura evidencia
física nueva.

## Decisión y regresión obligatoria

`_verify_release_job()` acepta únicamente:

- Formato actual: un job `publish-reviewed-image` exitoso, con run/SHA y
  todos sus pasos de publicación y escaneo autenticados.
- Formato histórico: el mismo job exitoso **más exactamente uno** llamado
  `release-image-pr-validation`, `completed/skipped`, `steps=[]`, con idéntico
  run/SHA. Este segundo job no publica ni autoriza nada.

No se aceptan jobs adicionales, publicación duplicada, validación activa,
nombre ajeno, run o SHA desigual, total incongruente, ni alteración de
artefactos, manifiestos o digests. La regresión RED anterior fallaba ante
los dos jobs históricos; tras el parche pasa junto a ocho negativos.

## Lecciones para todos los próximos despliegues

1. Verificar **antes del pase** el *formato real del workflow anterior*, no
   suponer que la última CI representa todas las releases conservadas.
2. Exigir la cronología exacta `observación par < observación recursos <
   intento APPLY` antes de despachar una Action costosa; no emitir recibos
   nuevos si el comprobante vigente es válido y está correctamente ordenado.
3. Diferenciar `MAIN_SHA`, `RELEASE_SHA`, `INSTALLED_SHA` y aceptación del
   dueño en todo reporte. No decir «desplegado» por un merge o release.
4. Ante `exit 3` pre-SSH, señalar la cláusula de precondición con un test
   de regresión y **no** reintentar a ciegas. Si alguna ejecución cruza SSH
   o inicia `commit_started`, detener retries y recuperar journal físico.
5. Evitar la reconstrucción de imágenes por una inspección READ_ONLY y
   mantener la reducción de CI por alcance, sin saltarse las pruebas del
   guard ni sus negativos de seguridad.
6. La certificación final requiere el terminal `BOCA_PAIR_UPGRADE` canónico,
   identidad física de los dos nuevos contenedores, puerto 8443/loopback,
   invariancia de recursos ajenos y aceptación funcional posterior del dueño.

**Este ADR documenta causa y remedio de preflight; por sí solo no certifica
un despliegue.**
