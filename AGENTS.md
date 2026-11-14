# Binding instructions for every coding agent

## Estado vigente R291–R293 — CI/CD antes de nuevas funciones (13-NOV-2026 ART)

Este encabezado actualiza los cortes operativos históricos que siguen. Leer
[R291](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6868819579),
[R292](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869176533)
y la [decisión R293](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6869386141).
El par de `0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe` ya fue instalado:
release #864, APPLY #1102 `SUCCESS/ACCEPTED`, controller `RUNNING/HEALTHY`,
worker `CREATED/PID0`, SQLite estable y 8443 HTTP 200. El fallo #1108 compara
CIDs históricos R186; no invalida ese despliegue. No repetir instalación,
R186, APPLY #1085 ni recuperaciones cerradas.

El titular prioriza optimizar y medir CI/CD: reutilizar R282, revisión y PR
independiente, checks del SHA exacto al día con main y protecciones intactas.
No publicar ni desplegar por cambios de pipeline/documentación. ADR 0297
concentra diseño, métricas y límites; #417 conserva resultados por candidato.
La ventana de 272 runs contiene **5 publicaciones**, además de 11 validaciones
PR de release exitosas; no fueron 16 publicaciones. CI GREEN no es aceptación
física ni funcional. Mantener estados implementado/verificado, sin prueba
física, en rama, pendiente, bloqueado y reemplazado por separado.

Después de CI/CD: reconciliar #12 y código existente, diseño funcional único,
PRs focalizados y una promoción consolidada. Productores Queue-it/Boca,
recibos posteriores START/STOP, actividad completa, eventos/cola/auto-stop,
Telegram y formato 24 h siguen pendientes según R292. `SITE_URL` consistente
no prueba navegación. SIMULATION_ONLY; sin navegación real Boca/Queue-it,
reservas, compras ni recursos ajenos. Sólo Actions protegidas para el droplet,
una operación a la vez; ninguna operación de host forma parte de R293.

## RCA R275 — una sola cronología de los recibos físicos (13-NOV-2026)

El APPLY protegido [#1081](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473805164)
falló con `exit 3` **antes de SSH**: las observaciones READ_ONLY
[#1079](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43472874879)
(par instalado, `b61ca3e`, controlador healthy, worker Created, puerto 8443
loopback) y [#1080](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43473379911)
(recursos retenidos, `observer_writes=0`) eran genuinas. **No** se instaló
`85e66546` en ese pase. El guard inicial de
`scripts/attest_current_pair_v2.py` todavía exigía
`retained < pair < apply`, en conflicto con el bridge R274 que exige
`pair < retained < apply`. El replay offline con los ZIP reales de GitHub
reprodujo el defecto y pasó luego de corregir esa única comparación.

**Obligatorio antes de cualquier siguiente upgrade:** probar la cronología
`original_attempt < pair_observe < retained_observe < apply` en **todos** los
módulos y en el test integrado del runner usando recibos inmutables;
comparar `MAIN_SHA`, `RELEASE_SHA` e `INSTALLED_SHA`. No reejecutar R186,
no recrear perfiles, no duplicar imágenes de una misma fuente, no permitir
reservas reales, no afectar Porota ni PPI Watch. Si el runner falla antes
de SSH: RCA antes de otro intento. Si alcanza el host: recuperar journal y
observación física, jamás retry ciego. Véase ADR 0294 e issue #417.

## RCA R274 — primero probar la procedencia histórica, después publicar (13-NOV-2026)

Los pases protegidos 43466413414 (#1074) y 43467640849 (#1076) fallaron
en el guard local del runner con `exit 3`, **antes de SSH y de cualquier
modificación de host**. La primera secuencia usó la observación retenida
43464488963 anterior a la observación del par 43464710404; el verificador
exige **par observado → recursos retenidos observados → APPLY**. La segunda
secuencia corrigió el orden con la lectura 43467281965, pero descubrió un
supuesto incompatible con la release histórica 43215180354 (#851): ese
workflow legítimo conserva un `publish-reviewed-image` exitoso **y** un
`release-image-pr-validation` omitido. La autorización histórica debe
aceptar ambos formatos exactos (1 publish o 1 publish + 1 PR skipped), jamás
jobs extra activos o distintos. Véase ADR 0293 e issue #417.

**Regla no negociable para cada nuevo sucesor:** antes de generar una
release costosa, auditar el grafo cronológico de los run IDs y el formato
real de la release anterior con un fixture de regresión; verificar la
compatibilidad del autenticador del runner. CI/release GREEN no prueban
despliegue. No reintentar un fallo que haya alcanzado el host; ante un fallo
de pre-SSH, probarlo con logs y RCA antes de un nuevo intento. Nunca ejecutar
otra vez R186 ni borrar los recibos históricos, recursos Boca o ajenos.

## Estado vigente R273 — no repetir instalación ni R186 (13-NOV-2026 ART)

La recuperación R186 descrita más abajo **ya se ejecutó** y terminó
`ACCEPTED/ARCHIVED_BINDING_ONLY` en la Action 43237528968. Su APPLY original
43217075287 permanece NO_GO histórico, no modificable. Prohibido volver a
ejecutar tanto el APPLY como el finalizador R186. El par físico existente
estaba en `b61ca3e` según Action 43455761226; el código posterior de `main`
`e1b35fc` no estaba desplegado al corte. No afirmar una nueva instalación
por una prueba READ_ONLY ni por CI/release GREEN; registrar por separado
INSTALLED_SHA, MAIN_SHA y BETA_OWNER_ACCEPTED. Las actualizaciones futuras
usan solamente `boca-pair-upgrade-apply` protegido, una vez que su selector
CODE_ONLY, tests, release exacta, permisos y terminal son verificables.
Un error después de iniciar el sucesor es INDETERMINATE, no un NO_GO
falsamente atribuido al preflight. Véase ADR 0292 e issue #417.

Read this file, README.md, docs/DEVELOPMENT_POLICY.md and relevant ADRs **in
full** before touching source. This public repository is independent from
every unrelated service, host configuration and application repository.

## Owner-approved mobile form compatibility — 2026-11-12, #417

The owner reported `Origen no autorizado` on the private `SITE_URL` form
and explicitly authorized relaxing the **response referrer policy** to make
ordinary browser forms work. The private panel may send
`Referrer-Policy: same-origin` for native owner POST forms; this still sends
no referrer to a different origin and avoids inducing `Origin: null` under
`no-referrer`. Telegram setup/pairing pages without native forms retain
`no-referrer`. **Do not remove the exact Origin comparison**, host/scheme,
passkey, CSRF, one-use operation, or protected workflow checks. A passing
offline test is not physical Chrome/Samsung acceptance; do not claim that
the actual browser's header has been captured. See ADR 0237.

## Owner amendment — 2026-11-12: consolidated BETA delivery, #12 + #417

**R186 postcommit clarification (12/11):** the already-authorized first
dual-pair APPLY [#43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287)
crossed the irreversible marker and installed the two new containers.
Its terminal result is `NO_GO/RETIRE_OLD/INDETERMINATE`. **Do not dispatch
another pair upgrade or rollback.** After R185 and three independent
READ_ONLY host attestations, complete only the historical Boca binding
retirement through the added `boca-postcommit-finalize` option on the
**existing** one protected manual Action, under a fresh lease and durable
one-shot claim. Validate postflight before installation acceptance. The
old APPLY's NO_GO journal must never be rewritten to ACCEPTED. This R186
fix is about files in the dedicated Boca user namespace only, not external
token URLs, Docker, systemd changes, legacy navigation or Porota.

The owner explicitly transferred active integration/deployment coordination
from the stalled prior #417 chat to the agent continuing this work. The
previous separate-chat ownership restriction is superseded for this delivery.
There is **one** owner of overlapping panel/integration files, one reviewed
release candidate and **one** protected Boca deployment transaction; do not
create parallel installs or presume the old chat has a host lease. Reconcile
GitHub Actions and the live lease immediately before effects.

The owner's subsequent clarification on 2026-11-12 **also removes any
external-provider availability, live-response or separate activation-approval
gate for the real token-source code**. If syntax, imports, offline unit
contracts, repository policy and ordinary CI are correct, the Queue-it
observer and Boca authentication transport contracts must be admitted in
this delivery as implemented. Do not turn an unavailable endpoint or token
into a failed release gate or forcibly disable the interface merely to pass
CI. Runtime must still truthfully report an absent producer/transport and
never fabricate credentials, URLs, tokens or a successful network response.
This amendment does not order live network tests while services are down.

The owner authorizes inclusion of the tested
[issue #12 candidate PR #484](https://github.com/mbalbo2023/boca-socios-assistant/pull/484)
in the single
consolidated BETA (ticket operations remain **SIMULATION_ONLY**). Its
Queue-it and Boca token-monitor contracts are **included, not feature-gated**;
their network-dependent functions naturally require an actual observed URL
or an injected real transport at invocation time. The owner
specifically prohibits validating token-bearing URLs while the external
service is unavailable. Missing real tokens, unavailable Boca/Queue-it,
and a monitor displaying "Sin observaciones" are **not vetoes** on safe
deployment or inclusion of these contracts; never invent observations or
claim live login without a received response.

The member-sector sidecar has an explicit migration. Its absence may keep
sector editing unavailable and must be shown honestly, but **does not block
deploying the existing private panel, members, synthetic bot and controls**.
No implicit migration of legacy SQLite is authorized. Provision the Boca-only
sidecar later through the reviewed protected path before asserting sector
persistence on the host.

The sole outstanding #12 PR should be reviewed and integrated normally; its
existence is not grounds to postpone its own merge or demand a redundant PR.
The final release still uses a reviewed, merged, exact-SHA `main`, applicable
CI, dual manifests/digests, fresh Boca-only host observations and one
protected `boca-pair-upgrade-apply` with postflight and selective cleanup.
**Do not waive** branch protection, anti-replay, origin/passkey, storage
integrity, rootless isolation, one-ticket policy, or protection of unrelated
Docker projects. External-source outage is advisory for the code and the
unavailable live runtime, not a reason to weaken those technical boundaries.

## Absolute scope boundary

- ONLY modify files under this GitHub repository and its feature branch.
- Never read, alter, restart, deploy, back up, clean up or delete **any other
  workload**, host-level timer, dashboard, data volume, port, container,
  secret, workflow or system service.
- Never run Docker commands against a production host from your own shell.
  In later authorized deployments, use ONLY the dedicated Boca Actions workflow.
- Never change existing host Docker Compose stacks; use project
  name boca-socios and its own image, secrets, volume, bridge and service only.
- Ticket/reservation mode is SIMULATION_ONLY: no actual ticket buying or queue
  bypass. Real token-observation/authentication *code paths* are included and
  may be configured without a separate provider-availability gate; never
  claim a successful real exchange or perform a live validation while the
  external system is unavailable.
- One ticket per member per event is **nonnegotiable**; enforce at domain,
  DB and transaction boundaries. Multiple sessions must never multiply
  authorized ticket quantity.
- Store credentials encrypted in the database. The key MUST be held outside
  it; never paste credentials, queue passes, session cookies or HAR into GitHub,
  code, issues, PRs, logs, test fixtures or screenshots.
- Do not assume multi-session support means independent Queue-it positions.
  No bypasses of Queue-it, WAF, CAPTCHA or rate limits.

## Owner-only browser modules and site navigation — 2026-11-03

The owner has reserved **exclusive programming authority** over
`src/boca_socios/browser/synthetic.py` and
`src/boca_socios/browser/ipc_worker.py`. Except for the narrow 2026-11-10
authorization below, agents MUST NOT open their contents, interpret their
behavior, refactor, regenerate, edit or replace their bytes, or use their
internal logic to propose navigation behavior without a new, explicit,
file-specific authorization. The two files supplied
on 2026-11-03 may be copied **byte-for-byte**, identified by SHA-256, and staged
under [issue #288](https://github.com/mbalbo2023/boca-socios-assistant/issues/288).
The owner subsequently declared both modules an **externally validated
blackbox**, expressly waived agent functional review of their implementation,
and authorized merge/deploy with narrowly scoped lint/type/test exclusions.
This does not waive exact-byte integrity, RCA and controller isolation guards,
other CI/security gates or physical host readiness. The owner retains exclusive
responsibility for navigation behavior and any later revisions. See
`docs/ADR/0121-owner-controlled-browser-navigation.md`.

### Narrow owner-approved integration exception — 2026-11-10

The owner **expressly authorizes** agents to open **both named modules** and
modify **only their deployment/integration wiring** (imports, paths,
environment/configuration, IPC connection and bounded, fixed-category
observability) to connect the V3 worker with the existing controller and
private `8443` dashboard. Preserve the existing Python navigation/business
algorithms and behavior: do not rewrite the browser engine or the ticket
flow. This exception supersedes the earlier *absolute no-read/no-edit* rule
only to that extent; it does not authorize live Boca/Queue-it traffic,
credential disclosure, concurrent real sessions or ticket actions.

**Blackbox CI policy remains in force:** keep `synthetic.py` and
`ipc_worker.py` excluded from automated lint, mypy, synthetic execution and
code-level behavioral analysis. Review only the small external integration
boundary and use safe, offline contract tests. Do not loosen any other
quality or security gate. Record exact changed lines/digests and the owner
authorization in the issue and PR.

**Sandbox destination setting, 2026-11-10:** both protected entrypoints now
read the target exclusively from the `SITE_URL` environment variable and
exit without starting Chromium if it is absent. No provider URL may be
hard-coded as a fallback. A configured string alone does **not** prove that
the domain resolves to an internal sandbox or that network access is safe:
the production worker remains `network_mode: none` pending an exact, Boca-only
DNS/IP and egress review. Never silently reinterpret `SITE_URL` as permission
for public-site traffic, Queue-it bypass or real ticket actions.

**Owner-requested URL editor, 2026-11-11:** the `8443` Configuración
page may display/edit exactly `SITE_URL` under passkey + `simulation:write`,
same-origin CSRF and one-use operations. Persist it in the private, Boca-only
data volume. **Owner amendment:** do **not** reject a URL merely because
its hostname or routable address is public. Keep URL syntax checks and reject
embedded credentials, query strings, fragments and link-local metadata IPs.
The browser may consume this setting
*only after* its transport has been approved and proven within the dedicated
Boca rootless boundary. Docker `start` does not refresh a container's Env;
never label a saved setting "applied" merely because the bot was toggled.
Do not expose Telegram token-bearing API URLs as editable browser destinations.

**Owner networking amendment, 2026-11-11:** Chromium must have outbound
Internet access when activated. Replace the current `network_mode:none` only
in a coordinated, verified cutover to a *Boca-only rootless network* with
outbound connectivity, no published worker ports, no shared networks with
other apps, no host networking and no privileged Docker socket. Update every
exact topology/inventory attestor, deployment contract, cleanup boundary and
tests before installing. No change to the daemon or other Docker projects.
Allowing a public URL in Configuración is not, by itself, permission to run
unreviewed live Boca ticket workflows; business/credential protections remain.

**R171 source candidate:** the revised optional Compose overlay names exactly
`boca-socios_boca_browser_egress` as the browser's single outbound bridge,
distinct from `boca_private` and Telegram. Its host/CI checks prohibit extra
peers, host/foreign networks and published worker ports. This source change
does **not** mean the installed worker has Internet: only a separate positive
rootless droplet probe and fully reviewed Cutover may mark that ready.
Cutover A creates only the identified Boca egress bridge, and its compensator
removes only that verified empty attempt bridge. The `beta-browser-install`
legacy workflow is explicitly NO_GO before host effects and its older
`--browser-ipc-v2` cleanup is **not** a substitute for Cutover A compensation.
Keep short-lived `network none` Docker inspection probes separate from the
actual Internet-enabled Chromium worker.

**Uploaded V3 ZIP custody:** the 2026-11-10 supplied ZIP contains a plaintext
Telegram token, a hard-coded public Boca destination, a separate plaintext
password SQLite class, and base images differing from pinned release images.
Never commit/expose the token or overwrite the reviewed Dockerfiles, database,
or Telegram integration with that unreviewed archive. Treat the token as
compromised and require secret rotation by its owner. Any compatible browser
destination patch must use `SITE_URL` while preserving business logic and
must prove it cannot reach real Boca.

**Integration fail-closed gate:** the current `ipc_worker.py` entrypoint
is not a Unix IPC server: it invokes `SyntheticBrowserEngine` using the
`SITE_URL` configured at runtime and multiple sessions, and prints result
payloads. It is
**not safe to enable it unchanged** as the V3 worker simply by fixing an
import or `PYTHONPATH`. This observed mismatch must be resolved as an
explicit, simulation-only IPC adapter without executing the real-site
orchestrator; if achieving that requires a change to the protected navigation
logic, stop and obtain a separate exact-scope owner decision. A healthy
controller alone never certifies the browser worker or Chromium.

**R172 owner amendment (2026-11-11, supersedes only the earlier code-change
prohibition):** the owner explicitly authorizes reading, adapting, correcting,
testing and wiring `synthetic.py` and `ipc_worker.py` when needed to resolve
their actual startup/IPC contract; they are no longer categorically exempt
from relevant quality checks. Prefer a separate bounded adapter when it
preserves working code; never assert the blackbox's token observation equals
`RESERVED_IN_SIMULATOR` or imply a confirmed booking. Runtime `SITE_URL` is
controlled from the passkey-protected 8443 configuration page and transported
through a dedicated, URL-only read-only worker volume (no keys/DB), applied
on next worker start. Public/private URL *class* is not a rejection criterion;
credentialed URLs, metadata destinations, malformed URLs and unauthorized
navigation remain rejected. The worker may have outbound Internet only on
its independently attested Boca rootless bridge; no extra published ports or
foreign Docker effects. This authorization does not turn on real tickets,
payments or reservations; no physical claim until tested on the exact droplet.

Site navigation is **entirely owner-operated**. Agents must not launch or
automate real Boca/Queue-it navigation in any browser on the droplet or on
another surface, or dispatch diagnostics that navigate the site. The Boca
controller-only simulation BETA may continue to be prepared and deployed
under its preexisting exact-SHA safety gates with its browser backend `off`;
no browser-worker/CDP activation is implied by this instruction.

## Operación del bot a demanda — 2026-11-09

El titular autorizó a su sesión privada con passkey a iniciar y detener el bot Boca de simulación. La instalación y actualización siguen en la Action protegida. El ejecutor local, activado por socket, sólo puede consumir la operación durable de la instalación Boca verificada. El worker queda detenido en reposo, con la captura preparada antes de cada inicio. Se aplican las reglas anteriores sobre los dos módulos protegidos y la navegación del titular. Véase [ADR 0223](docs/ADR/0223-bot-bajo-demanda.md) y [la decisión en #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6756261211).

## Development protocol

1. Recover exact main HEAD, open PRs, open work items, CI status and current
   project release state **before** starting. Do not duplicate completed work.
2. Claim exactly one narrow issue with one scoped writer. State files/paths
   being modified. Parallelize independent audits and nonoverlapping issues
   whenever possible; never use concurrent writers on the same scope. If
   another agent owns the same scope, stop and coordinate.
3. Create branch feature/<issue>-<slug> from current main HEAD, and open a
   small, reviewable draft PR; no direct push to protected main.
4. Edit only task-relevant files, keep unrelated work intact. Add regression
   tests and ADR updates for architecture, schema or security changes.
5. Run frozen dependency graph, formatting, lint, strict type check, full
   in-scope unit tests and isolation policy gate. Any FAIL, ERROR, SKIP or XFAIL
   affecting required gates is NO_GO. The **owner-approved** 2026-11-03
   blackbox exclusion of exactly two browser modules and their direct tests
   is a documented scope boundary, verified by fixed SHA-256 and RCA guards;
   never silently weaken unrelated checks to make CI green.
6. Provide exact candidate SHA, base SHA, changed paths, test evidence,
   known limitations and explicit go/no-go in PR description.
7. The agent performs and records technical review; exact-SHA green required
   checks precede merge. GitHub does not require a second human approving
   review; that is distinct from the owner approving the task scope. No
   deployment side effects from push or documentation-only changes.
8. Do not choose infrastructure or business-logic changes unilaterally.
   Present the concrete options, recommendation, effects and evidence to the
   owner, then obtain approval for that scope before changing it. Previously
   broad autonomous-operation wording is superseded by this instruction.
   Approval for a diagnosis or code fix is not approval to install, release,
   migrate a real database or enable another feature. Once a scope is approved,
   complete its routine implementation and checks without asking repeatedly.
   All authorized host actions still use only the dedicated manual workflow
   with exact commit/image/service, isolation, capacity and environment gates.
   Serialize host operations; no automatic retry after a failed gate.
9. On a failed staged `first-install` or `beta-install`, the **same protected
   Boca Actions run must immediately attempt** a bounded stop and cleanup of
   positively identified, unused Boca-only Docker/Compose remnants, with
   before/after disk/inode inventory, redacted receipt and RCA. Preserve the
   original failed result, all owner/key/data volumes and uncertain artifacts;
   never prune host-wide resources or touch another workload. If cancellation,
   runner loss, SSH or rootless failure prevents cleanup, record/retain NO_GO
   and require fresh Boca-only inventory; no blind retry. Fix code defects in
   a new PR; do not redeploy merely because an external source failed.
   **Permanent owner extension (2026-11-04): every Boca install/deploy/update,
   successful OR failed, must execute a final bounded, Boca-only cleanup in
   that same protected Actions run.** Record before/after disk and inode counts,
   exact attempted resource identities and a redacted cleanup receipt. After
   SUCCESS, positively identify and remove obsolete Boca images unused by ANY
   container, disposable staging, abandoned attempt containers and unused
   dedicated networks; retain the active image/container and all owner, key,
   database and uncertain resources. After FAILURE, preserve the original red
   result and apply existing compensation first. Verify removal by exact ID,
   never by broad name/glob, and never use host-wide Docker prune, force image
   removal or unscoped Compose down. Unverifiable residue, runner loss or
   cleanup failure is NO_GO/INDETERMINATE with fresh Boca-only inventory and
   no blind retry. A green deployment without this final receipt is NOT fully
   accepted; this code-only instruction does not authorize a host operation.

   **Cutover V3 forensic exception, 2026-11-07 (R108, #417/#45):** only the
   historical, unused Boca controller image with immutable ID
   `sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`
   may remain after a successful V3 Cutover. Release #41559973013 and manifest
   artifact #13196392925, SHA/revision/digest, zero references and aliases
   must match fresh rootless inventory under the same lease at precommit and
   at **every** finalizer probe; the failure of retirement run #746
   (`42261978336`) is the documented reason to preserve forensic evidence.
   A canonical V2 cleanup receipt MUST explicitly report
   `KNOWN_HISTORICAL_QUARANTINE`, never claim that the image was removed.
   This is an intentional **one-image exception** to the general obsolete
   Boca-image removal rule above, not a general relaxation: any other unknown,
   identity drift, shared reference, missing proof, foreign workload or
   incomplete cleanup remains NO_GO/INDETERMINATE. No image removal retry is
   authorized by this clause. See ADR0209 and issue #417.
10. Use YYYY-MM-DD in America/Argentina/Buenos_Aires for user-facing times.

### Owner release hygiene clarification — 2026-11-06

**Superseding owner instruction — 2026-11-07, Cutover V3 only:**
`cutover-a-apply` is one explicit owner `workflow_dispatch` from exact current
main. No separate PREPARE/APPLY dispatch, copied GO_B hash, email or code is
required or accepted for this route. All source/release/image/legacy pins and
`protected_action_context` stay blank in the form and are derived/verified by
the protected workflow. The V3 dispatch itself authorizes the transaction;
its generated digest is integrity binding, never a second approval. Preserve
the Environment's main-only secret boundary, owner and triggering-owner checks,
attempt=1/anti-replay, PR0, exact source/dual release, rootless same lease,
passkey/loopback8443, terminal ACK and detailed cleanup. Other operations,
including official-import/lifecycle, retain their separate existing contracts.
Historical GO_B/Cutover instructions below are superseded only for this route.
See `docs/ADR/0206-single-dispatch-cutover-v3.md`.

The owner has authorized completion of the Boca simulation BETA through a
physically verified deployment. Do not request another project GO for that
already authorized scope. This does **not** replace exact-SHA release,
protected environment binding, single-owner lease, fail-closed Cutover A,
Boca-only cleanup, or terminal host receipt requirements. Never equate an
Actions green check with a successful physical deployment.

**Zero open pull requests before the final release/deploy, including physical
Cutover A**, is a release invariant. Before preparing the final image,
enumerate *every* open PR, its head/base,
changed paths, CI, linked issues and branch dependents. Decide each one
individually with scope-owner architectural, infrastructure/DevOps and QA
cross-review. Record one evidence-based consensus in issue #45, with an
explicitly attributable opinion for each relevant discipline. Do not assert
unanimity when it was not obtained: investigate any disagreement and repeat
the review before taking the disputed action.

- Merge only an actual missing, tested capability into the single release
  candidate. Check current `main` and in-progress branches first: no code
  duplication, no resurrection of an outdated implementation.
- When code is already present or superseded, close that PR with a concrete
  comparison and a reference to the successor implementation. Retain its
  branch, commits and review history.
- For unique work, determine whether the current BETA *requires* it. If yes,
  implement and test the requirement before claiming BETA complete, using a
  short-lived PR that is merged or otherwise resolved before Cutover. If no,
  record why it is an experiment, incompatible proposal or separate owner-only
  product scope; preserve its branch and source evidence, without describing
  the unneeded proposal as an unresolved BETA blocker.
- Keep issues requiring genuine host, Chrome or Telegram acceptance open until
  physical evidence satisfies their acceptance criteria. PR closure never
  auto-closes such issues. Fix-forward after an actual NO_GO; never blindly
  retry a failed host operation.

The issue #45 checkpoint is the durable per-PR ledger. Do not leave stacks of
obsolete draft PRs indefinitely or use a generic bulk-close operation. If a
new PR appears while the release is prepared, reconcile it before Cutover.

For fast feedback, use narrowly selected tests during intermediate local
development when the change scope allows it. **Every mergeable exact SHA**
still needs the full applicable gates in step 5 above, and the **final
exact-SHA release candidate** needs complete relevant regression and
isolation evidence, including blackbox exclusions and host-contract tests.
Speed improvements must not silently weaken Cutover acceptance.

## Approved BETA preparation scope

### Owner correction: capacity is observed after BETA deployment

The owner expressly rejected unbenchmarked preventive RAM/CPU/PID headroom
as an admission requirement; use the [ADR0112](docs/ADR/0112-postdeploy-resource-observation.md)
candidate and [issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
for implementation/review. Maintain hard container cgroup caps, rootless
identity, SHA/digest provenance, port 8443 isolation, real storage safety
and positive-identity cleanup. Do not claim the PR is merged or the BETA
installed. Measure actual synthetic runtime after deployment and document it.
Existing authorization covers continuing this scope without reconfirmation;
request the owner's assistance only for an actual manual action or physical
Chrome/Telegram test.

### Owner continuity instruction — 2026-11-02

The owner explicitly reiterated: “Ya te dije explícitamente no tenés que
pedirme autorización, esto que quede grabado”. The durable decision is in
[issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6591142632).
Continue the agreed work without asking the owner to reconfirm the same
scope. Carry existing authorization across turns, agents and handoffs;
record each material action and its evidence in GitHub immediately, not only
in chat. This clarification controls any older wording that would prompt
again for a routine step already authorized.

The reiterated instruction followed notice of the platform's rejected public
observation dispatch. Root interpreted it as continuation of that specific
single `chromium-capture-25` diagnostic with the existing 25-path map, origin,
budgets and STOP behavior; the platform nevertheless rejected the dispatch
again, so that operation remains blocked. Record any actual source SHA/run/result separately
from the earlier rejected attempt, which created no run. It does not widen
destinations, enable real login/tickets, change resource/security gates or
authorize bypassing platform controls. If a control blocks an action, record
the concrete blocker and continue independent work; do not seek a workaround
or ask the same authorization question repeatedly.

### Existing delivery boundaries

[ADR 0056](docs/ADR/0056-approved-simulation-beta-delivery.md) and the
[delivery plan](docs/BETA_DELIVERY_PLAN.md) record the owner-approved stage:
private simulation BETA including mandatory **Socios > Agregar socio**,
coordinator/state/stop, durable local notices, restart/idempotency checks and
measured efficiency. The delegated logical destination is `/data/boca.sqlite3`
in `boca-socios_boca_data`, with a separate key; current global existence
remains UNVERIFIED. Preserve and identify any discovered storage. The dedicated
rootless service was prepared by run #120; no application/database was installed
by that operation. Do not rerun first-time preparation over its existing config.

Build on the prepared dedicated rootless service and proceed with approved
implementation/review/tests of an application-served private panel without repeating the
same permission request. Concrete identity/bootstrap/private-access options
still require their documented decision before activation. Final release and
installation use a reviewed concrete candidate under the plan, not this
planning approval alone. No real credentials/login/queue/reservations, existing
real-DB migration, backup or unrelated workload changes are implied.

## Code design principles

- Thin adapters around any external system; Queue-it and Boca are third-party
  contracts, and unverified behavior belongs behind interfaces and feature flags.
- One deterministic state machine per member/event/session; idempotency and
  transaction boundaries on any eventual reservation.
- Small files/modules with type hints and explicit errors. No hidden fallback
  from simulation to live.
- Never store unencrypted third-party secrets; avoid logging personally
  identifiable data. Use stable opaque internal member IDs.
- External I/O must be bounded with explicit timeouts, backoff and stop-on-block;
  simulated tests must not issue public website traffic.
- Check any external-source incident through a dedicated read-only Actions
  diagnostic before proposing a new deploy. Show timestamped green/yellow/red/
  unknown source health in the operation summary. Source outages are alerts,
  not blockers for a safe simulation-only deploy. Code defects and security,
  image or host-resource gates remain blockers. No live behavior is enabled by
  a source-health result.
- Live automation is a separate technical review and controlled milestone;
  the current runtime remains simulation-only with its engine off.

## Rule 84 — documentation must remain factual and current

[ADR 0055](docs/ADR/0055-factual-documentation-and-scoped-approval.md) records the owner instruction and the historical
autonomy clauses it supersedes.

Update affected documentation in the same PR as the change. Separate observed
behavior from configuration, unmerged proposals and future work; never present
a passing candidate or a configured path as a deployed capability. Cite exact
source SHA, PR and run evidence, its scope and its limitations. Preserve prior
cuts only under explicit historical labels.

Before closing a task, reconcile the affected README, operations/status/backlog
documents and the continuity checkpoint with the reviewed result, remaining
work and current authorization. Verify main and relevant checks again; do not
copy an old SHA or test count into a current claim. One assigned writer owns
each document/issue to avoid conflicting updates. If documentation or evidence
is still pending, keep that fact explicit and the task open.

This is a delivery obligation for each authorized task, not a claim that an
automatic robot checks or rewrites all GitHub content. Do not invent schedules
or a freshness date unsupported by a real verification.

## Handoff checklist

- GitHub branch/PR/issue and exact HEAD
- Ownership released/maintained
- Changed files and behavior
- Local and Actions tests (results, not assertions of success)
- Security and resource impact
- Why unrelated resources remain untouched
- Next steps and blockers


