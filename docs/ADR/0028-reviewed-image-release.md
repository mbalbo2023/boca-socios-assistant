# ADR 0028: publish a reviewed, scanned image once by OCI digest

**Status:** Integration candidate for issue #60, 2026-10-29 (Argentina). No publication performed.

Add a Boca-only manual image release workflow on `main`. Build the controller
once on a GitHub-hosted amd64 runner, scan that local image using the same
pinned Trivy action and HIGH/CRITICAL OS/library fail gate as #55, and only
then push the scanned image to GHCR using the job-scoped `GITHUB_TOKEN` with
`packages: write`. A PR job executes the build and scan but has read-only
permissions and no registry login or push. The manual release job references
the protected `boca-image-release` environment; its actual configuration and
readiness variable must be verified in GitHub before any dispatch. Checkout
uses the repository's pinned Node 24 Action.

Tag with the full commit SHA for traceability. Parse and validate the digest
reported by the actual push; fail the pipeline if `docker push` fails before
parsing its output. Record the immutable OCI reference, commit SHA
and Actions run ID in the summary. The tag is merely a locator; a later
deploy must use the digest. The workflow does not reach any host, create
keys, visit Boca or deploy. GHCR visibility/read access and the target host's
architecture must be verified separately before a deployment candidate. The
scan covers the controller, not the separate Chromium worker image.

Limitations: the vulnerability database changes over time; the runner's
amd64 image is not a multiarch release. GitHub environment configuration,
package visibility, actual branch ruleset, exact-SHA checks and recorded
agent technical review remain gates. The first-attempt and fresh-main checks
for manual publication are being added separately in #98/#99; no dispatch is
permitted before those guards are integrated and tested. A green PR check
does not permit publication or deployment by itself.

## Extensión propuesta para BETA: dos imágenes, un solo release protegido

**Estado al revisar el candidato (2026-11-01):** rama rebasada sobre main
`46f184fc49747f98246ac82047d9786b65239168`, que integra el worker IPC
de PR #237; la autorización comprende
desarrollo, pruebas y revisión, **no** ejecutar `workflow_dispatch`, crear el
paquete GHCR ni instalar nada en un host. Lo anterior describe el diseño
histórico que publicaba sólo el controlador.

El mismo `.github/workflows/release-image.yml` suma el worker de Chromium de
`Dockerfile.browser`, sin crear otro workflow de despliegue ni iniciar releases
en cada CI. En PR se construyen y escanean **ambas** imágenes en runner
desechable, con checkout sin credenciales persistidas y token de solo lectura;
no se hace login ni push. La publicación conserva el gate manual exclusivo de
`main`, dueño, entorno `boca-image-release`, primer intento, SHA todavía
actual y único dispatch para ese SHA. Se fijan los labels de revisión de
**ambas** imágenes al SHA exacto y se verifican antes del escaneo. Dos acciones
Trivy fijadas por commit y versión deben aprobar HIGH/CRITICAL sin excepciones
antes del primer login a GHCR. No se añaden permisos de token ni se configura
attestación Sigstore/SLSA firmada.

En ambos jobs, antes de Trivy, un `docker image inspect` también exige que
`Config.Cmd` del browser sea exactamente
`["python","-m","boca_socios.browser.ipc_worker"]`. Una imagen antigua cuyo
`CMD` aún es el smoke de Chromium falla el gate; primero debe integrarse el
worker IPC revisado. El label SHA se comprueba aparte. No se modifica el
Dockerfile ni el servicio host en este frente.

El paquete browser propuesto es distinto del controlador:
`ghcr.io/mbalbo2023/boca-socios-assistant-browser:sha-<SHA>`. Esa etiqueta
identifica la imagen para el push, pero **no** es un identificador apto para
instalar. El push debe devolver un digest `sha256` único, asociado al encabezado
exacto del paquete browser, y el controlador conserva su parser/imagen histórica.
La publicación del browser ocurre primero y la del controlador después, sólo
tras ambos escaneos; una falla intermedia deja el run en FAIL/NO-GO aunque
algún tag OCI pudiera quedar publicado y no autoriza un reintento automático.

Se conserva **sin cambios de esquema** `boca-release-manifest`, con sus campos
exactos `image_ref`, `source_sha` y `release_run_id`, para no romper el gate
existente de `first-deploy`. El mismo run prepara un artifact compañero
`boca-browser-release-manifest` con JSON estricto de cuatro campos:

```json
{
  "source_sha": "<40 caracteres hexadecimales lowercase>",
  "run_id": "<ID decimal del workflow_dispatch>",
  "controller_digest": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:<64 hex>",
  "browser_digest": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:<64 hex>"
}
```

Ambos `*_digest` son referencias OCI **completas**, no etiquetas ni hashes
sueltos. El validador exige nombres exactos sin duplicados, archivo regular
acotado a 1024 bytes y sin symlinks, repositorios de rol correctos, digests
distintos, SHA y run exactos. Se escriben y verifican antes de subir los dos
artifacts separados, sin sobrescritura y con retención de 30 días. El futuro
gate host/browser debe descargar y validar el compañero y el estado exitoso
del release antes de usar `browser_digest`; este PR **no** modifica ese gate.
El CLI reutilizable y sin salida sensible para esa validación futura es
`python scripts/parse_browser_release_manifest.py verify <artifact_path> <source_sha> <run_id> <controller_digest> <browser_digest>`
(con `PYTHONPATH=src`); imprime únicamente un resultado PASS/NO_GO y reutiliza
el parser bounded del manifest v1. El gate host C debe usar este CLI antes
de preparar SSH y no derivar el digest del tag mutable.
Ni el scan, un PR verde o el JSON prueban accesibilidad de GHCR, controles
físicos del browser, ausencia de CVE en fecha futura ni instalación real.
