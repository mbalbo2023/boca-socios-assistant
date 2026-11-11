# ADR 0231 — R174: alternativa firmada para APT de la imagen Chromium

**Fecha:** 2026-11-11 ART. **Alcance:** solo compilación de `Dockerfile.browser`.
**Estado:** propuesta técnica CODE_ONLY, pendiente de Actions sobre SHA exacto.
Continuidad: [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417)
y [PR #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478).

## Evidencia y causa delimitada

El primer HEAD del PR pasó cinco workflows. En los dos HEAD posteriores,
cuatro trabajos independientes fallaron al construir el navegador, antes de
ejecutar Chromium: `apt-get update` no resolvió
`azure.archive.ubuntu.com` ni `security.ubuntu.com`; la caché incompleta
no ofrecía los paquetes APT fijados. La imagen base, instrucciones y
versiones exactas de `Dockerfile.browser` no cambiaron entre la ejecución
anterior satisfactoria y los fallos. Reintentar una vez el HEAD intermedio
reprodujo el mismo síntoma en cuatro regiones de runners.

Un [incidente público contemporáneo de GitHub runner-images](https://github.com/actions/runner-images/issues/15296)
reporta la misma resolución DNS fallida en instalaciones Playwright el
11/11/2026. [Canonical status](https://status.canonical.com/) también
registró incidentes durante esa jornada. Son corroboraciones, **no una
atribución definitiva de la causa DNS interna del BuildKit de Boca**.

## Decisión acotada

Mantener los repositorios Ubuntu del fabricante como primera elección.
Si su actualización de índices falla, usar únicamente en el build Chromium
el espejo `https://mirrors.edge.kernel.org/ubuntu/` de Linux Kernel
Archives, conservando las suites Noble y la verificación criptográfica
Ubuntu (`Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg`).
Rechazar configuraciones APT de forma no reconocida en lugar de editar
fuentes arbitrarias.

Los índices `InRelease` de `noble-security` y los archivos de los paquetes
`apt`, `libapt-pkg6.0t64` y `libbrotli1` con las versiones fijadas
estaban visibles en el espejo durante la revisión. Eso **no prueba** que
GitHub/BuildKit pueda resolverlo o que la construcción termine correctamente;
ambas cosas requieren logs auténticos del próximo SHA.

## Opciones evaluadas y límites de seguridad

1. **Solo esperar y reintentar:** es seguro, pero no mitiga una nueva caída
   externa y ya hubo un reintento reproducido sin éxito.
2. **Espejo secundario con firma Ubuntu (opción seleccionada para ensayo):**
   cambia la ruta de descarga, no la clave de confianza, las versiones ni el
   código ejecutable del worker. Requiere comprobación efectiva en GitHub.
3. **Desactivar escaneo, bajar el pin APT o usar Docker `--network host`:**
   se descarta por no corregir la causa con evidencia y degradar aislamiento
   o protección frente a CVE-2026-109518.

Quedan intactos: bloqueo de CVE HIGH/CRITICAL con Trivy, pinned Playwright,
`uv.lock`, imágenes por digest, contratos IPC, `SITE_URL`, cgroups,
redes rootless Boca, secreto de Telegram, inmutabilidad de release y
Cutover único por Actions. El cambio no añade una ruta de salida a Internet
para el worker instalado ni implica navegación a ningún sitio.

## Criterios de aceptación

- Test RED→GREEN del parser de fuentes APT y rechazo de URIs/esquemas o
  firmas no esperadas; cambios limitados al Dockerfile y helper build-only.
- En el runner GitHub exacto: resolución del espejo, `InRelease` aceptado
  por APT, instalación **exacta** de `apt=2.8.4ubuntu0.1`,
  `libapt-pkg6.0t64=2.8.4ubuntu0.1` y `libbrotli1=1.1.0-2ubuntu0.1`.
- Build de Chromium, smoke offline, Trivy y demás workflows sobre el mismo
  SHA realmente `SUCCESS`; no heredar comprobaciones de otro commit.
- Revisión independiente de QA/Arquitectura/Seguridad, PR listo para merge
  solo con los checks requeridos; física del droplet y censo rootless
  permanecen aparte.

**Hasta esos recibos el estado continúa NO_GO de imagen, merge y deploy.**
