# ADR 0253 — Caché BuildKit temporal, con frontera main/PR

**Fecha:** 2026-11-12 ART. **Alcance:** Boca Socios Assistant, #417, R247.
**Estado:** candidato CODE_ONLY; no implica CI alojado exitoso, release nuevo ni
instalación en el droplet.

## Problema y evidencia

La reducción previa a un par local controller/browser por PR eliminó builds
duplicados de otros workflows, pero no aceleró por sí sola la latencia total.
Como referencia histórica, el PR R245 tardó aproximadamente 5m31s y R246
5m35s; estas mediciones no prueban que R247 mejore el tiempo. Cada runner
efímero comienza sin capas locales. Los builds son todavía una fuente de
trabajo repetido, y las imágenes Playwright requieren dependencias APT.

## Decisión acotada

1. En `CI / image-build`, el setup Buildx y los dos `build-push-action` están
   fijados a SHA inmutable. Construyen **dos imágenes distintas**, `Dockerfile`
   y `Dockerfile.browser`, con etiquetas OCI de origen y revisión exactos,
   `push: false` y `load: true`. Los alias locales que consumen los tests,
   Trivy y el observador siguen vinculados al mismo SHA.
2. El backend GitHub Actions cache API v2 (`type=gha`) mantiene **dos scopes
   separados**: `boca-main-controller-r247` y `boca-main-browser-r247`.
   Tanto CI de PR como los dos jobs independientes de Image Security pueden
   **importar** esas capas. **Sólo** un evento `push` del repositorio canónico
   a `refs/heads/main` puede **exportar** (`mode=max`), con error de exportación
   ignorado por ser un acelerador. El PR no exporta a main ni obtiene
   permiso de publicación. Image Security no exporta nunca.
3. El setup Buildx o su build opcional pueden fallar. Un fallback `docker
   build` sin caché por cada imagen sigue compilando el Dockerfile exacto,
   sin omitir escaneo ni contratos posteriores. La ruta fría no es un tercer
   artefacto publicado: reemplaza únicamente la ejecución fallida de su rol.
4. `release-image.yml` sigue **sin** cache-from, cache-to ni Buildx: recompila
   desde el `main` actual, comprueba etiquetas de ambas imágenes, ejecuta
   Chromium offline, escanea controller/browser con Trivy antes de login y
   publica sólo bajo su Environment protegido, dos digests/manifests exactos.
   No se importan capas o artefactos de PR a esa autoridad.

## Fronteras de confianza y fallos

- Cache no es identidad de imagen: el SHA de Git, labels, tests, Trivy y
  digest de release son controles separados. El valor de `cache-to` es vacío
  en PR, `workflow_dispatch` u otro ref; no se usa el cache PR para release.
- El setup y build de caché tienen `continue-on-error` **sólo** para que el
  fallback frío sea obligatorio; el fallback, los dos escaneos, los labs y
  los contextos de calidad mantienen fallo bloqueante. Falta de caché no
  autoriza omitir validaciones.
- GitHub-hosted runner solamente: no contacto con droplet, Docker rootless,
  SQLite, sesiones Chrome, Porota ni otros proyectos. No se crean builds
  effectful en el host y el release sólo existe por dispatch protegido.
- La caché de CI no declara ni prueba higiene de imágenes en el droplet;
  limpieza Boca-only R108 y postflight conservan sus gates propios.

## Verificación y seguimiento

Las regresiones estructurales R247 deben probar ambos scopes y los dos
`cache-from`; guardia canónica de `cache-to`; setup y cold fallback para
controller/browser; Image Security estrictamente sin exportación; release
frío, dos Trivy y dos manifest; las dos etiquetas OCI sin sustituciones.
Además se exigen Ruff, formato, política y suite aplicable del candidato.

**Pendiente de medición alojada:** ejecutar en GitHub el SHA final del PR
con caché inicialmente fría y luego observar un `main`/PR posterior con
caché caliente. Registrar por rol hit/miss, segundos de build, ambos Trivy,
laboratorios, cola y latencia total; comparar con R245/R246. El PR puede
mejorar o empeorar tiempos: no proclamar velocidad conseguida sin datos.
Una falla de importación debe registrar fallback, conservar los checks y
dejarlo documentado como RCA concreto.

**NO_GO despliegue:** este ADR no cambia el procedimiento de
`boca-first-deploy.yml`, su única transacción protegida, certificados de
controller/worker ni la evidencia física exigida en #417. No reemplaza el
GO operativo ni acredita BETA instalada.
