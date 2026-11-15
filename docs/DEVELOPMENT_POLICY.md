# Development and merge policy

## 2026-11-15 — R300, migración explícita con identidad instalada

[RCA520](https://github.com/mbalbo2023/boca-socios-assistant/issues/520)
parte del recibo1142 real SCHEMA_0007_REQUIRED, sin stop/provisión. PR519
ya cerró el import; main O y CI1262/Security1086 están aprobados. No repetir
el defecto anterior ni sus certificaciones como si fueran trabajo nuevo.

El [contrato R300 y unanimidad previa](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6891021673)
permite conectar el CLI de esquema existente al backend instalado bajo lease.
W y M permanecen independientes. No retocar SQL, helper de imagen, MOUNTS,
caps ni source para acomodar la ruta legacy. La solicitud es explícita y fija;
prepare permanece sin DDL. El autor no cuenta como revisor independiente.

La retirada acreditada del helper escritor precede a restore. Primario y cleanup
se conservan separados; incertidumbre no permite restart, rm por nombre o retry.
Éxito exige restore HEALTHY_ENGINE_OFF, verificación0007 readonly y sender OFF.
Regresión conductual de ruta W/M, frontera ejecutable, preservación y fallos;
ZIP aislado con entradas/caps actuales, gates del SHA exacto y recibo físico
posterior. No backup supuesto, permisos nuevos, activación ni mensajes.

## Histórico — 2026-11-15, R299, import del guard anterior a SSH

R297 está instalado y [STATUS1138](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43684726506)
ya aceptó el estado tras PR518. TG1139/1140 fallaron antes de SSH y no deben
reescribirse ni reintentarse a ciegas. El marcador de entorno faltante quedó
configurado por su vía normal; TG1140 demuestra el siguiente defecto local.

[RCA519 y consenso](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6890476164)
autorizan sólo `PYTHONPATH: src` en el env del paso Telegram. Conservar checker,
shell, controles y verificador ZIP aislado. Probar el comando y env reales en
un subprocess limpio: W vigente distinto de M instalado pasa; stale/invalid
rechazan semánticamente antes del marcador de efectos. No aceptar ImportError
como resultado negativo válido ni depender del paquete importado por pytest.

Revisión independiente y gates del SHA exacto preceden merge y nuevo prepare.
Sin nuevas imágenes, paquetes de host, release/APPLY/admin/STATUS ni mensajes.

## Histórico — 2026-11-15 — R298, mantenimiento del lector posterior al despliegue

[APPLY 1134](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43681576798) y [ADMIN 1135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43682305029) certifican instalación y
provisión de R297/5281efa. [STATUS 1136](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43682391989) conserva su NO_GO.
El [diseño previo unánime](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6889977546) limita #518 a la frontera de ruta
host/controller del lector portable y su regresión. No se cambian los
controles de acceso, esquema, fingerprint, lease, doble lectura ni formato.
Pruebas focales y pin de los paquetes afectados, revisión independiente y
checks del SHA exacto. La reparación viaja con Actions; no otra release/APPLY.
La lectura nueva debe acreditar su resultado antes de proseguir Telegram.
Los siguientes cortes no reabren instalaciones ni gates ya completados.

## Histórico — 2026-11-15 — R297, implementación del QA en el mismo candidato

El [titular autorizó dos motores funcionales independientes](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6886406162)
y un objetivo global de 50 contextos. ADR0302 y el plan R297 fijan responsabilidades
y consenso antes del código; sustituyen el alcance de sesión única para este
delta. Conservar PR517, módulos ya implementados, SIMULATION_ONLY, BLACKBOX,
datos y aislamiento. La ejecución lógica puede ser concurrente; las operaciones
físicas conservan una autoridad y el workflow protegido serializado existentes.

No migrar al abrir 8443. La autoridad por motor se registra en audit_events con
namespace separado y holds/releases compatibles con el ledger físico. Revisar
atomicidad, frío/reinicio, STOP, credencial reemplazada/revocada y publicación
tardía. El pool comparte procesos por tipo y limita contextos realmente vivos;
50 solicitados no equivalen a 50 creados o 50 lugares de cola.

Verificar el delta local y cierres de paquetes afectados sin repetir la suite
base certificada. Mantener los caps y añadir el nuevo pin fullZIP conservando
los históricos. Revisión independiente final y checks del SHA publicado exacto.
Durante la consolidación QA no se opera host/proveedores ni se envían mensajes;
la aceptación física posterior no puede sustituirse por mocks, Chromium local
o CI. No pedir otra autorización rutinaria para el desarrollo ya encargado.

La QA visual por Actions pedida durante R297 usa la imagen exacta del candidato
y fixtures ficticias en el CI existente. Toda captura del panel instalado
necesita su acceso legítimo y una extensión revisada del recorrido protegido;
el observador de salud no es un navegador autenticado. Conservar esta distinción
en artifacts, recibos y comunicación al titular.

## Histórico 2026-11-14 — R296, consolidación antes del QA y de la promoción

El titular pidió preparar un único candidato mientras aún no realizó su QA.
Continuar PR517, integrar correcciones verificadas y preservar la instalación
R294. No merge/release/host/START/STOP/proveedor/mensaje durante esta preparación.
Las decisiones [R296](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6881603931)
y [recuperación por fase](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6882197549)
autorizan el desarrollo, no inventan evidencia física. No volver a pedir permiso
para este trabajo ni duplicar los módulos, ramas, tests o incidentes cerrados.

El paso físico futuro usa únicamente los selectores protegidos y una lease Boca:
`telegram-prepare`, `telegram-activate`, `telegram-renew-stage`,
`telegram-complete-sender` y `telegram-sender-recover`. Son fases administrativas,
no nuevas releases. Prepare/activate no reutilizan el camino histórico que
iniciaba/detenía el daemon. La renovación explícita conserva ciphertext y nonces;
la continuación conserva la identidad ORIGINAL de aceptación y nunca reenvía un
intento ambiguo. Recover no envía. Ningún éxito de la custodia equivale a sender
incorporado ni a recepción humana.

La evidencia del estado Telegram se publica sólo después de verificar/restaurar
el par y se vuelve histórica al vencer su ventana. Un downgrade de custodia se
conserva como diagnóstico e impide certificar PREPARED/READY. No migrar SQLite
durante preparación o publicación de estado. El cambio compatible de binding
se limita al sender y conserva el archivo ejecutable, controller, worker y datos;
su secuencia no es una transacción atómica entre archivos y requiere journal,
fence de socket, compensación exacta y recuperación explícita.

Probar el cierre real de imágenes/ZIP, incluidas importaciones diferidas. Las
proyecciones del paquete dedicado seleccionan nodos canónicos sin cambiar sus
guardas; verificar igualdad AST, allowlist/digest y límites existentes. No elevar
caps/reservas. Revisión independiente por alcance y final, pruebas focales y
checks requeridos del SHA exacto preceden la promoción consolidada posterior al QA.

## 2026-11-14 — R295, desarrollo paralelo sin perturbar aceptación

R294 fue instalada y certificada físicamente por release #865 / APPLY #1117;
main/instalada `c5a143541ccfcaf26f29cf252a4cb33fd7c540f7`. El titular autoriza
desarrollar pendientes mientras prueba desde Samsung. La decisión R295 de
[#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6878044872)
asigna archivos exclusivos y exige reutilización antes de escribir.

Conservar estable el host durante esa aceptación: sin nueva release, APPLY,
START/STOP, preparación Telegram ni mensajes. El código R295 se revisa en rama
y no se describe como instalado. Mantener controles de main y checks del SHA
exacto; ejecutar localmente sólo regresiones pertinentes y dependencias reales.
No repetir el despliegue R294, suites locales sin cambios ni algoritmos validados.

El lector diagnóstico puede separar un STOP terminal sin binding actual sólo
con worker CREATED/PID0 y motor STOPPED; nunca usar esa proyección como permiso
de recuperación/admisión. El lector estricto y CURRENT_RETAINED no se relajan.
El transporte Boca histórico habilita desarrollo offline, no certifica conexión.
La sesión, deadline global y fences START/STOP son dependencias de su wiring.
El observer Telegram compatible no autoriza activar su selector: backend,
custodia V2, sender y recepción humana conservan evidencias independientes.
ADR0300 documenta las regresiones, la closure real de los paquetes y límites.

Antes de publicar un cambio de una fuente incluida en el full host ZIP, la
selección focal debe incluir
`tests/test_r82_recovery_bundle.py::test_current_cutover_zip_is_pinned_and_excludes_preflight`.
Su ubicación histórica no hace histórico su pin ACTUAL. Medir caps/imports no
sustituye comprobar ese digest revisado. Conservar los pins anteriores y añadir
uno nuevo sólo tras contrastar los bytes del paquete y su diff autorizado;
nunca quitar la aserción o aceptar cualquier hash calculado por el builder.

## 2026-11-14 — R294, continuidad funcional autorizada

R293 cerró la prioridad CI/CD por PR #515. El titular autoriza completar el
trabajo funcional, promover un único SHA definitivo y validar físicamente.
Su aclaración exige detección automática por el worker: no sustituir el
productor por carga manual o un estado desconocido permanente. ADR0299 fija
el diseño único, reutilización, estados y criterios de aceptación.

La sesión ordinaria se activa por START del titular; nuestras pruebas continúan
sin navegación real Boca/Queue-it. Tickets SIMULATION_ONLY, sin reservas,
compras, evasión ni modificaciones de algoritmos protegidos. Revisión independiente,
checks exactos, ruleset main, identidad de release, lease y recuperación por
fase siguen obligatorios. Operaciones de host únicamente por Actions serializadas.

APPLY técnico y provisión administrativa posterior tienen resultados separados:
no usar continue-on-error ni repetir instalación por un fallo de preferencias
o del recibo Telegram. La aceptación funcional exige ambos resultados y la
evidencia del titular; CI GREEN no los sustituye. Fuente main/release/instalada,
productor Queue-it y transporte de login Boca se informan por separado.

## 2026-11-13 — prioridad CI/CD R293 y certificación física vigente R291

La continuación autorizada por el titular en
[#417/R293](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869386141)
prioriza medir y simplificar CI/CD antes de nuevas funciones o promociones.
Reutilizar R282 existente; no recrear módulos, pruebas, imágenes ni
recuperaciones ya certificadas. La instalación de `0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe`
fue aceptada por APPLY #1102 y R291; R186 y #1085 son historia cerrada.
Una mejora de pipeline/documentación no requiere otra release ni despliegue.

Cada alcance tiene un escritor; paralelizar auditorías independientes y
serializar operaciones de host mediante la Action protegida existente.
Antes de crear o modificar: buscar implementación, SHA, validación previa,
dependencias y trabajo faltante; registrar decisión y evidencia en GitHub.
Usar pruebas focalizadas localmente y la suite requerida del candidato exacto
en Actions. Mantener `quality-and-tests` e `image-build`, ruleset estricto,
checks GitHub Actions y revisión técnica; nunca bypass ni verde por omisión
de un precheck fallido. Clasificador documental desde base confiable,
historia insuficiente => FULL; documentos consumidos por tests => FULL.

Las métricas separan PR, push, lectura, publicación y APPLY, así como duración
de pared y tiempo agregado de jobs. Medir también el coste secuencial de R282;
no atribuir aceleración al gate sin datos. ADR 0297 concentra el plan y la
línea base; #417 registra resultados de Actions sin otro commit sólo para
anotar tiempos. SIMULATION_ONLY, sin navegación real Boca/Queue-it ni
operaciones sobre aplicaciones ajenas. La aceptación Samsung es posterior
y distinta de CI y certificación física.

## 2026-11-12 — compatibilidad de formularios móviles en el panel 8443

Por autorización específica del titular para resolver `Origen no autorizado`
en Configuración, el panel privado admite `Referrer-Policy: same-origin` en
sus formularios HTML nativos. No se relajan la autenticación passkey, el
origen exacto exigido en el POST, CSRF, permisos ni la protección anti-replay.
La política evita divulgar el `Referer` a sitios externos. Las páginas
Telegram sin formulario nativo permanecen `no-referrer`. La recepción física
en Chrome requiere evidencia separada de las pruebas offline. ADR 0237.

La solicitud del dueño de acelerar cambios pequeños **no** autoriza por sí
misma saltar los checks requeridos ni modificar el workflow de producción.
La ruta selectiva R245 reconoce únicamente PR enteramente documentales de
paths explícitamente permitidos, conservando ambos *jobs* requeridos con
conclusión exitosa sólo tras clasificación positiva. Push a `main`, workflows,
Docker, tests, scripts y mezclas desconocidas ejecutan la ruta completa.
El clasificador se verifica con fixtures Git sintéticos; la ganancia temporal
requiere medición alojada y no se extrapola de los tests locales.

## 2026-11-12 owner direction — consolidate #12 and #417 without source gates

**R186 operational continuation:** the single physical dual-pair APPLY
occurred in [#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287).
It passed its irreversible commit and left `RETIRE_OLD/INDETERMINATE`:
another full upgrade or rollback is forbidden. R185 corrected the stopped
worker Health observer, and three subsequent READ_ONLY runs verified the
new pair, systemd binding and SQLite inode. R186 may add **only** one
postcommit archival finalizer operation inside the existing protected Boca
workflow (same mutex and SSH identity), with new lease, O_EXCL claim,
exact-file retirement and postflight. No separate SSH workflow is permitted.
Its code inclusion is governed by syntax/TDD/CI/PR, independent of Queue-it
and Boca provider availability; installation acceptance still needs a
genuine host receipt and private panel acceptance.

The owner assigned the active agent responsibility for completing the **one**
Boca simulation BETA deployment because the previous #417 chat stalled.
This explicitly supersedes the historical separate-chat ownership boundary;
no parallel writers, merges or host Actions may run against a shared scope.

The accepted #12 code-only candidate (#484) may be merged into the single
release once exact-SHA checks and technical review are satisfied. Unavailable
live Queue-it URL/token validation, a missing genuine Boca login endpoint,
and a missing optional sector-preferences SQLite sidecar **do not block a
controller BETA deployment with included Queue-it and Boca contracts**.
By the owner's later clarification on 2026-11-12, **do not require an
additional live-provider test, separately reviewed endpoint or activation
approval to ship/enable those code paths**: syntax, imports, offline TDD,
ordinary CI and contractual repository checks are the release bar. An
unconfigured producer/transport must report unavailable at runtime, without
turning that fact into a deployment veto or inventing a token or response.
The sector page must be honest about unprovisioned storage. Do not conduct
live URL/token checks while the external services are unavailable; ticket
reservation/navigation stays SIMULATION_ONLY and queue bypass forbidden.

This is **not** a waiver of required protected workflows, final PR/merge
provenance, dual release integrity, positive-identity Boca-only host checks,
passkey/CSRF, one-ticket restriction, cleanup or postflight. The stalled
release with incomplete artifacts is still unusable; create and verify a
fresh single release from the final merged main, then perform one controlled
pair upgrade through the dedicated Action.

## Why this exists

Past incident classes include accidental deploy on documentation changes,
overlapping writers and deployment leases, status gates being skipped,
SQLite writer contention, excessive disk/memory pressure and the danger
of mistaking a green CI unit test for a verified live deployment.
The reviewed manual Boca Actions workflow is the sole remote operation path.
Read-only inspection has executed; this does not establish that installation
prerequisites or runtime are ready. Infrastructure and business-logic choices
outside an already approved scope require concrete options, a recommendation
and owner approval before changes.
Earlier blanket autonomy statements do not authorize a new operation. The
current scoped approvals and verified state are recorded in issue #45.

The owner's [2026-11-02 continuity instruction](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6591142632)
requires continuing agreed work without repeatedly asking permission. Recover
and carry forward that authorization across turns and handoffs. The concrete
public diagnostic described in that record was still blocked by platform
approval review after this reiteration; no new run was created. Its existing
map, budgets and isolation remain binding. Record steps and results immediately in
GitHub. Platform blocks are documented, not bypassed, and do not suspend
independent work or justify asking the same question again.

## Approved delivery and maintenance

**Owner resource-gate correction (2026-11-02):** Numeric pre-release
CPU/RAM/PID buffers without an actual BETA benchmark are now advisory and
cannot veto installation merely for being below a chosen estimate. The
approved engineering correction is tracked in [issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
and candidate [ADR0112](ADR/0112-postdeploy-resource-observation.md).
All isolation/cgroup caps, exact image provenance, positive-identity rootless,
loopback port, real storage safety and fail-closed/cleanup requirements remain
binding. Measure actual synthetic BETA resource use **after deployment**;
record metrics before approving any future dimensioning change. This is not
authorization to affect another application or to bypass platform controls.

[ADR0056](ADR/0056-approved-simulation-beta-delivery.md) and
[BETA_DELIVERY_PLAN](BETA_DELIVERY_PLAN.md) record the approved next stage,
including private enrollment and synthetic E2E/restart/one-ticket acceptance.
Do not ask again for routine development/tests within that scope. Identity and
private-access activation decisions and final release/install candidate gates
remain explicit. Evidence of code approval is not evidence of a created DB.

Module writers update their contract/ADR, changed behavior, limits and exact
checks in the same PR. The central documentation owner coordinates plan/status
and the root owner updates #45/#113 on integration. Rule84 does not require
concurrent writers to duplicate identical global summaries; it requires their
facts to remain consistent and the assigned update to complete before closure.
Parallel checks may continue while independent source work advances.

Efficiency work measures queue/execution/build/scan/test and end-to-end latency
on exact candidates. Consolidate changes before publishing, parallelize
independent jobs and serialize final integration/host operations. Do not omit
required checks, substitute old evidence, relax gates or promote untrusted PR
artifacts to privileged release merely to reduce elapsed time.

## Agile PR and Actions governance (R68, 2026-11-06 ART)

Keep one source-of-truth integration branch per reviewed release. Before opening
a PR, query all open PRs and compare changed paths/hunks with `main` and active
owner scopes; do not create replacement code where an existing feature is being
reviewed. Default base is `main`. A PR against another feature branch must
state its parent, why that dependency is needed and the planned promotion or
closure; stacked PRs do not independently certify a final release.

Every PR must carry issue/scope owner, current base and head SHAs, status
(ACTIVE/BLOCKED/SUPERSEDED/EXPERIMENT), tests and last evidence. A centralized
backlog review reconciles open drafts with `main` at each release freeze.
Close only an *exactly demonstrated* superseded or abandoned PR, with linked
replacement/merged commits and an explanatory comment; never bulk-close by
age, title similarity or number alone. Dependency bumps must satisfy the
current Python/runtime constraints before being considered mergeable.

Batch logically related file changes into **one atomic commit** before opening
or refreshing a PR; avoid file-by-file commits that trigger four redundant
GitHub Actions waves. All required checks must still complete against the
final reviewed SHA. Avoid workflow-level path filters for required contexts,
which can leave required checks pending; any future docs-only fast path must
retain the named required job with an explicit, tested classification.

Measure queue, uv sync, controller/browser builds, scans, PR wall time,
protected publish, PREPARE, APPLY and postflight separately. GitHub-hosted
runner checks may run in parallel; only Boca's single physical deploy mutex
may mutate the shared host. Reuse caches or immutable artifacts only after
proving provenance and branch-trust separation; never consume an untrusted
PR cache in the protected release without rebuilding/verifying by digest.
Do not confuse remote GO wait, dispatch latency and container startup time.

## Branch protection contract

### Single-pair CI execution (ADR0239)

The image-dependent PR checks execute together in `CI / image-build`, using
one locally built controller/browser pair for code-bearing changes. This
includes both Trivy scans, source/revision labels, offline Chromium,
image-size evidence and disposable deployment/lifecycle smoke. R245 adds a
strict docs-only PR classification *inside* the required `CI / image-build`
job, not a
workflow-level `paths` filter: an unclassified or mixed change takes the full
path and both required contexts always report honestly. The superseded release,
image-security, first-deploy-runtime-smoke and public-browser-isolation PR contexts are retired, not
replaced with green placeholders. Verify and record the actual branch rules
before merging this migration. The protected manual release still independently
builds, verifies and scans both published images; it consumes no PR artifacts
or caches. Source checks do not prove hosted Docker success or physical deploy.
The public-observer isolation probe remains PR-only and offline in the shared
image job. Only its offline PR mode permits attempt 2; manual public observation
and protected release/deployment keep their first-attempt restrictions.

- Default branch: main; no direct pushes, branch deletion or force-pushes.
- Require a PR and a recorded agent technical review; no human approving
  review or code-owner approval is required by the ruleset. This does not
  replace owner approval of infrastructure/business scope. Resolve conversations.
- Required contexts: CI / quality-and-tests and CI / image-build,
  after the first workflow run.
- No merge of draft PRs, skipped tests or unknown candidate SHAs.
- Enable secret scanning, Dependabot and dependency review if supported.
- Require up-to-date CI for the exact merge candidate; avoid stale artifacts.

GitHub rulesets need to be configured in repository Settings; merely
committing this document or CODEOWNERS does **not** enforce them.
The public personal plan supports enforcement, but no agent should claim
main is protected before verifying GitHub's **actual ruleset state**. See
[GITHUB_SETUP.md](GITHUB_SETUP.md) for required administrative checks.

## Work protocol

1. Each issue has explicit owner and narrow scope; parallelize independent
   issues and read-only checks, with no concurrent overlapping source writers.
   Single candidate SHA per decision.
2. First commit includes tests/contract, implementation follows in small
   increments. A red test triggers root cause analysis, not a weaker guard.
3. CI needs no Boca credentials and does not probe third parties. A separate,
   bounded read-only Actions source diagnostic may check a public endpoint
   when needed; its outage result is advisory, not a required deploy check.
4. Use dependency lock, pinned Actions, no CI jobs on untrusted self-hosted
   runners, no broad GITHUB_TOKEN scopes or unreviewed scripts.
5. Do not merge until the exact SHA is green and has a documented agent
   technical review. Main pushes rerun CI but must **never** deploy.
6. Releases are build-once with immutable image digest and verified source
   provenance. An installation uses the sole manual GitHub Actions workflow,
   exact SHA/digest/service inputs and a Boca-only resource preflight. The
   owner must have approved that concrete operation scope. Approval of code
   tests or a read-only diagnosis does not authorize release or installation.
7. On any unexpected condition, stop/fail closed, record NO_GO and fix forward.
8. If staged `first-install` or `beta-install` fails, the same protected Boca
   Actions job must immediately attempt a positive-identity stop and selective
   cleanup of disposable Boca artifacts. Inventory disk/inodes before and
   after, keep the original failure red, preserve owner/key/data volumes and
   uncertain resources, and never use host-wide prune. Runner/SSH/daemon loss
   may prevent cleanup: report NO_GO, require new Boca-only inventory and
   never silently retry. Other protected host phases retain their own
   non-destructive failure/stop and preservation contracts.
   **Permanent owner rule (2026-11-04): run bounded, positively identified
   Boca-only postflight cleanup after EVERY successful or failed install,
   deploy and update, not only after failure.** The same protected Actions job
   must inventory disk/inodes and exact attempt-owned resources before/after,
   remove only disposable Boca artifacts and obsolete images proven unused by
   every container (never remove the image currently serving), then verify
   exact IDs are absent. Keep owner/key/data volumes and anything uncertain.
   No host-wide prune, force-removal, other Compose project or unrelated
   workload; if cleanup cannot run or prove the result, record
   NO_GO/INDETERMINATE and require a new read-only Boca inventory before retry.
   A successful application start alone does not satisfy final acceptance.

   **Narrow R108 Cutover V3 exception:** the single historical Boca image
   `sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`
   may be quarantined as forensic evidence only when its immutable historical
   release proof, lack of references and fresh same-lease rootless inventories
   match exactly. Report `retained_attested` in canonical cleanup V2;
   this is **not** literal deletion of every obsolete image. All other images,
   known residues and uncertain resources retain the normal acceptance gates.
   The failed historical retirement Action #746 must not be blindly retried.
   See [ADR0209](ADR/0209-r108-attested-historical-quarantine.md).
9. Diagnose source failures through Actions before deciding on code changes.
   Report source health as a timestamped semaphore. A source outage cannot
   turn a safe dormant-controller deploy into NO_GO or justify redeployment;
   a demonstrated code defect can justify a new PR and deploy.

## No parallel deployment paths

### Cutover V3 authority (2026-11-07)

The owner replaced the Cutover-specific manual GO_B and two-dispatch
PREPARE/APPLY process with a single authenticated owner dispatch. The reviewed
`cutover-a-apply` route now resolves source, dual immutable GHCR images and
installed legacy identity automatically; the user must not copy hashes or
PREPARE run IDs. Its generated digest binds the reviewed bytes to this run,
not an independent approval. Environment secrets/main restrictions remain;
no changes to reviewer settings, auto-approval or credential recovery are
part of the implementation. Official-import/lifecycle policies are unchanged.
Source/CI/PR0, single lease, UID10001, protected storage/passkey, localhost8443,
no real navigation/login/tickets and mandatory physical cleanup/ACK still
gate acceptance. See [ADR0206](ADR/0206-single-dispatch-cutover-v3.md).

There must remain **exactly one** controlled deploy workflow. Never add
automatic push-based deployment, personal SSH procedures, host cron jobs,
any unrelated deployment integration or Docker cleanup of another project.
If a proposed feature requires any of those, stop for an architecture review.

## Synthetic panel preview artifacts

A manual Actions preview of the owner panel may upload a short-lived HTML
artifact built only from fixed sample states in source. It must not accept a
database, credential, member, event or host input, read runtime data, call
Boca, publish a website or add a service port. The artifact is public-repo
material, so it must contain no actual personal data. A preview checks the
panel's presentation only; it is not an authenticated operating interface or
evidence of a reservation. Real enrollment and status serving retain their
separate security gates.

## Rule 84 — factual documentation in the delivery contract

[ADR 0055](ADR/0055-factual-documentation-and-scoped-approval.md) records the owner instruction and the historical
autonomy clauses it supersedes.

Every PR updates the documentation affected by its final behavior, evidence,
authorization and limitations. Distinguish configuration from observed state,
main from an unmerged candidate, synthetic tests from host/site evidence, and
local results from provider confirmation. Exact SHA/run references identify
what was actually checked; a successful old run is never current evidence.

Before task closure, the assigned writer reconciles the relevant README,
operations guide, roadmap, integration status and continuity checkpoint. State
what remains pending and what decision is required. Label historical snapshots
explicitly instead of mixing their instructions with the current contract.
Do not close while a required update is unrecorded. This rule does not add an
automatic documentation updater, a periodic schedule or approval authority.

## Acceptance criteria per PR

Explicit requirement, tests, redacted evidence, doc/ADR updates, security
impact, resource budget, failure mode, idempotency and handoff. A screenshot
or agent narrative alone never replaces a test report.

## RCA lessons enforced by CI

For a reproduced code or deployment-contract defect, preserve the failing
case as a deterministic regression before the fix. Once reviewed and merged,
record the issue, fixing PR, cause, prevention and test selectors in
`docs/quality/rca-lessons.json`. The quality job reads the pytest report
from its single full-suite run; a listed test that did not execute and pass,
or a removed accepted lesson/test, fails the gate. A changed finding needs
another reviewed PR with new evidence. No automated finding edits code,
merges a PR or dispatches deployment. See ADR 0044.

