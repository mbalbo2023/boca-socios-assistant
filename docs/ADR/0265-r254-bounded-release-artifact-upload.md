# ADR 0265 — R254: plazo acotado para los dos artefactos del release

**Fecha:** 2026-11-13 ART. **Ámbito:** publicación protegida de imágenes
controller/browser de Boca (#417). **Estado:** fix-forward CODE_ONLY en
revisión; sin release, dispatch, instalación ni observación física nuevos.

## Incidente y evidencia verificable

La publicación [#43094715916](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43094715916),
job `130780470753`, sobre `b8f9a8c8daa246ea39fd206397ec27fd6bcf652b`,
publicó ambas imágenes y pasó `BOCA_RELEASE_MANIFEST_PASS` y
`BROWSER_RELEASE_MANIFEST_PASS` a las 20:18:41 UTC del 11/11/2026. El paso
`Preserve exact published digest for the guarded install` tardó 923,062 ms
(20:18:41.092–20:34:04.154 UTC): respuestas HTML `<!DOCTYPE` donde la API
esperaba JSON, múltiples esperas/reintentos y finalmente
`Failed to FinalizeArtifact: (404) Not Found: artifact not found`. La carga
constaba de 338 bytes. El run terminó `FAILURE` y el paso de manifiesto
browser no se ejecutó.

La consulta posterior de artefactos muestra el manifiesto controller parcial
`13891095561` (338 B; SHA256 del *ZIP* `2de201b922372a4669cc526d9e2316c83c7bad79f2cdab527f7bef87278066c5`),
pero **no** el artefacto browser. Su presencia no convierte un run rojo en
release apto para el instalador: faltan el segundo manifiesto y el resultado
terminal exitoso del mismo primer intento. Tampoco se debe confundir ese
SHA del ZIP con el digest OCI de una imagen publicada.

Como control, la publicación [#43215180354](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43215180354),
job `131172496907`, sobre `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`,
subió/finalizó el controller en ~1,13 s y el browser en ~0,85 s; ambos
artefactos quedaron presentes (`13942499787`, `13942534781`) y el run fue
`SUCCESS`. El archivo `release-image.yml` es el **mismo blob Git**
`950b09ef170a1a328372b66801125c8d0bd10de6` en ambos commits. El fallo
observado está en el protocolo/servicio de artefactos, no en la verificación
de SHA ni en Trivy/Docker. No hay HTTP upstream preciso ni RCA interno del
proveedor; una degradación externa es hipótesis compatible, no hecho probado.

## Decisión

Agregar `timeout-minutes: 5` **por separado** a los dos pasos existentes
`actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9`
(v7.0.2) de `.github/workflows/release-image.yml`. GitHub Actions admite
el timeout por paso también para `uses:`. Cada subida conserva:

- Nombres separados `boca-release-manifest` y
  `boca-browser-release-manifest`, rutas e identidad del mismo run.
- `if-no-files-found: error`, `overwrite: false`, `retention-days: 30`;
  **sin** `continue-on-error` ni `if: always()` en las subidas.
- Dos `verify` exactos después de push/digest y **antes** de subir; los
  scans y gates previos de main, owner, primer intento y Environment.
- Release `FAILURE` ante timeout, manifest ausente o subida fallida; la
  instalación exige un nuevo run SUCCESS completo con ambos artefactos,
  source SHA y OCI digests exactos. **Sin retry automático** de un run rojo.

La cota baja la espera de un *primer paso bloqueado* de ~923 s a un máximo
configurado de 300 s (ahorro teórico ~623 s en ese incidente). **No acelera
el camino sano** de ~1 s por artefacto ni resuelve la indisponibilidad del
proveedor. Cinco minutos es un compromiso explícito: una subida que podría
haberse recuperado después de ese tiempo falla antes, siempre cerrada;
si la primera finaliza tarde y falla la segunda, ambas consumen sus propias
ventanas de tiempo. El job conserva su cota de 30 minutos.

## Prueba y límites de aceptación

Regresión focal `test_both_release_manifest_uploads_are_bounded_and_fail_closed`:
RED sin la cota, GREEN con `timeout-minutes: 5` en ambos pasos, pin y
opciones de fallo intactos, ambos validadores ordenados antes del upload.
La suite/política local comprueba el contrato YAML; **no simula** la API
remota ni demuestra el comportamiento temporal en GitHub hospedado. El
commit final deberá atravesar CI exact-SHA y el review/merge protegido
antes de su uso en una publicación futura, sin cambio ni permiso de host.
