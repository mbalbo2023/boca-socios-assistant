# Repository settings to configure after bootstrap

## RCA #275 — fallo de firewall del Docker rootless (corte 2026-11-03)

La prueba de host [#329](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41629150243), sobre `main=eee0173ebafebf31d372bba3816ca6aadd138ffd`, devolvió **`BOCA_NETWORK_PROBE result=NO_GO reason=firewall cleanup=VERIFIED`**. El `network_create` de [#317](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41573026189) ya había fallado. En #329 la verificación de limpieza y la parada del daemon Boca finalizaron `SUCCESS`; no se desplegó la BETA ni se creó la passkey. El código `firewall` solo acredita que el error de Docker menciona iptables/nftables/netfilter; **no identifica aún permisos, backend, tabla, cadena o módulo**.

El [PR #277](https://github.com/mbalbo2023/boca-socios-assistant/pull/277) integró la prueba aislada de red; el [PR #278](https://github.com/mbalbo2023/boca-socios-assistant/pull/278) y [ADR0115](ADR/0115-rootless-firewall-subcause.md) son un **candidato en rama** que precisa las categorías de error con pruebas sintéticas, sin modificar Docker, firewall global, Porota ni servicios ajenos. Los tests de rama no son evidencia de ejecución en el droplet. Se conserva el único workflow de host protegido y su verificación de identidad/limpieza; no iniciar `owner-enroll` hasta que el RCA real esté resuelto.

## Decisión vigente sobre recursos (2026-11-02, PR #273 integrado)

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 fue integrado y verificado en `main=0e830e3eed941de1da70cef8b42bda9f20258b65` con CI y seguridad postmerge GREEN. La decisión sigue vigente.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

Creating CODEOWNERS and CI files is not enough to enforce policy.

**Public repository target, 2026-10-29:** GitHub Free supports enforced
protection of public branches. The owner directs the agent to do and record
technical review without requiring a different human account. Verify each
control's actual state in Settings rather than inferring it from this file.

1. Confirm repository is PUBLIC with a **new sanitized initial history**
   and the default branch is main. Verify branch and job names directly.
2. Settings → Rules → Rulesets → New branch ruleset:
   - Name: protect-main
   - Enforcement: Active; target: default branch (main).
   - Block deletion and force pushes.
   - Require pull requests and conversation resolution; zero required GitHub
     approvals. Record the agent's technical review and exact-SHA CI in the PR.
   - Require status checks `quality-and-tests` and `image-build`, after
     CI first reports their exact GitHub check context names.
   - Prevent bypass except for a documented break-glass owner decision.
3. Enable Issues and Discussions only if useful; do not permit public
   personal-data issues or unaudited external collaborators.
4. Settings → Actions → General: require actions pinned to complete SHA,
   restrict GITHUB_TOKEN to read-only and disable Actions-created PR
   approval. Never expose secrets to untrusted fork PR workflows.
5. Security → secret scanning, push protection, Dependabot alerts and code
   scanning if plan supports them. Do not substitute unavailable plan features
   with a false claim of enforcement.
   On public repositories, GitHub documents automatic secret scanning and
   free push protection, but **push protection must still be verified as
   enabled** for this specific repository. Sources:
   [secret scanning scope](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-scope)
   and [public push protection](https://github.blog/changelog/2023-05-09-secret-scannings-push-protection-is-available-on-public-repositories-for-free/).
6. Environments for future Boca host operations must restrict deployment to
   main, hold a dedicated SSH identity and pinned host key, and be marked ready
   only after those settings are verified. No required human reviewer.
7. Do not recreate or rotate the existing SSH key secret while reconciling
   settings. A pin configured in GitHub is not evidence of host connectivity.
8. Run and verify CI; then activate required status checks.

## Observed environment state on 2026-11-02

The GitHub Settings UI was inspected during recovery from verified
`main=032de0ebb923b4f80154e93cee3dfd1b254687ed`:

| Control | Observation |
| --- | --- |
| `boca-image-release` branch policy | `main` only; required reviewers off; administrative bypass available |
| Release variables | `BOCA_RELEASE_ENV_READY=ready`; no release secret configured |
| `boca-first-deploy` branch policy | `main` only; required reviewers off; administrative bypass available |
| Deploy variables | `BOCA_DEPLOY_ENV_READY=ready`, `BOCA_HOST_READONLY_ENV_READY=ready`, and the existing host variable |
| Deploy secret names | Only the existing dedicated SSH key and pinned known-hosts secrets; values were not disclosed |
| Missing activation configuration | `BOCA_BETA_ENV_READY`, `BOCA_BROWSER_ENV_READY`, Telegram readiness markers, owner origin/subject and protected bot/destination assertions |

The release and host workflows are integrated on `main`. No new SSH key is
needed. These observations do not authorize bypass, publication, installation
or a readiness marker change. A concrete candidate and the owner's specific
protected-operation approval remain required. Do not enable BETA or browser
readiness while the corresponding host/code gates are unresolved. The latest
host evidence is [inspection 41495516709](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495516709)
at 2026-11-02 14:54:42 ART (daemon inactive/dead, socket absent, prerequisite
NO_GO, capacity NOT_EVALUATED) and [port check 41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298)
at 15:04:45 ART (`127.0.0.1:8443 FREE reserved=no`); neither installs the application.

Branch-ruleset, Actions-policy and security-feature observations below retain
their historical dates; this environment inspection did not reverify them.

## Activation coordinates and frozen source

The documented main cut `6f7fa0939d28df7c315440bba15237b0c1bfbe77` includes
merged PRs #253/#263; CI 41511631024 and security 41511631004 passed. PR #261's
historical `42eb497e8b597cd86035d08370dc935cba9b0f17` checks precede the CPU
correction. [Status](BETA_INTEGRATION_STATUS.md) keeps those receipts separate
from final-candidate checks, including the reviewed
[owner argv fix](ADR/0107-opaque-owner-cli-operands.md). At the documented cut
#261 was unmerged and its host operation had not run. Subsequent main/checks
are recorded in #45; PR validation does not publish images or verify GitHub settings.

This version includes #266/[ADR0106](ADR/0106-sanitized-public-render-denials.md),
the sanitized diagnostic correction for RCA #264. It requires exact-SHA checks
and hosted offline smoke evidence. The previous public capture remains UNKNOWN;
a new capture requires specific authorization, with no new GET authorized here.

PR #255 integrated `/telegram/configurar` and proved its synthetic browser-local
sealing flow in CI 41481913145, with security 41481913075 PASS. Owner entry stays
on `http://localhost:8443`; do not add HTTPS/certificates or another port.
The approved `telegram-prepare` public receipt supplies the fragment link.
The private form produces ciphertext for input `telegram_envelope`, plus
`BOCA_TELEGRAM_EXPECTED_BOT_ID` and `BOCA_TELEGRAM_EXPECTED_CHAT_HMAC` for
Secrets in `boca-first-deploy`. It never sends token/chat plaintext to GitHub.
Use the existing SSH secrets; never request or rotate them as routine setup.

Before protected operations, verify actual values/presence of
`BOCA_BETA_PANEL_ORIGIN`, `BOCA_BETA_OWNER_SUBJECT`,
`BOCA_BETA_ENV_READY`, `BOCA_BROWSER_ENV_READY`, `BOCA_TELEGRAM_ENV_READY`
and `BOCA_TELEGRAM_OWNER_READY` under their approved phase. A marker is not
proof of configuration, identity, capacity or permission. Do not enable a
sender solely because a form generated ciphertext.

The lifecycle integrated in PR #253 requires both digest refs, the same successful
release, exact current `source_sha`, `service=controller` and reviewed budget.
`beta-browser-install` uses `1.5cpu-1024m-192pids`; existing browser/dual Telegram
operations use the full `1.75cpu-1152m-224pids` once owner Telegram is ready.
Sender-start/recover require that full budget. `failed_telegram_run_id` is
required only for `beta-browser-telegram-recover`; GitHub validates the exact
completed failed first attempt and its successful effect marker. Never use
Re-run jobs as recovery or present a new run as ownership of old resources.

This version implements #261's `operation=infrastructure-preflight` before release. After
integration and specific approval, it uses exact current `source_sha`,
`service=controller`, either pair/full-three budget above and blank image/release
inputs. Both existing deploy/read-only READY markers are required: temporary
start of the verified empty Boca daemon is a protected effect. No BETA/browser/
Telegram marker, private owner context or release is inferred from this check.
Its required verified final state is stopped. Under the updated owner decision
[ADR0112](ADR/0112-postdeploy-resource-observation.md), CPU/RAM/PID buffer
comparisons are **advisory observations**, not required minimum headroom:
`BOCA_INFRA_POLICY result=OBSERVED` reports reference thresholds and flags.
The structural `cpu_ceiling` and load are not a benchmark of actual BETA use.
Identity, topology, storage safety, release provenance and verified restoration
remain hard requirements. See historical [ADR0103](ADR/0103-pre-release-infrastructure-observation.md)
and the [operation contract](OPERATIONS.md#pre-release-infrastructure-observation).
No setting was changed by the candidate or these documentation updates.

Freeze main after final documentation/review/checks and before release.
Keep it frozen through owner enrollment, install, Telegram and recovery;
record final SHA, digests, checks and real receipts in
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6563012208).
A later SHA requires separate reviewed upgrade/recovery handling; no old
Telegram readiness proof or manifest is automatically reusable.

## Historical revalidation on 2026-10-29

- `protect-main` ruleset 26163295 is active on the default branch. It
  requires a PR, linear history and exact required `quality-and-tests` and
  `image-build` checks; required approving review count is zero.
- `main` still contains only `ci.yml`. The manual Boca host workflow exists
  only in draft PRs, so it cannot be dispatched from the default branch yet.
- The private `boca-first-deploy` environment has the pre-existing SSH key
  secret and separately authorized host/key pin. Its branch restriction is
  main-only; required reviewers are off, administrative bypass is available,
  and its readiness variable remains absent. Host readiness and other
  privileged paths are unverified. Do not call this environment ready yet.

Record any subsequent settings changes as observed facts; neither this
document nor CODEOWNERS enforces GitHub settings by itself.

## Historical administrative observation on 2026-10-28

- The new repository is **public**, contains a clean initial history and
  GitHub-hosted `quality-and-tests` / `image-build` checks succeeded.
- At that time `main` ruleset enforcement was **not yet active**. GitHub
  requested account re-verification. The revalidation above supersedes this
  historical state.
- The observed Actions policy had a read-only default `GITHUB_TOKEN` and
  disallowed Actions-created or approved PRs; the setting that requires
  all third-party actions to be pinned to complete SHAs was **not** enabled.
  The current CI uses pinned action SHAs, but this is not equivalent to a
  repository-wide enforced policy.
- Secret-scanning/push-protection settings are **unverified**; do not mark
  them complete based solely on GitHub's public-repository entitlement.
- The CI-based `zizmor` security audit proposed in ADR 0009 is preventive
  static analysis. It does not replace recorded agent technical review,
  provider-side branch protection or GitHub secret scanning.

## Repository access

Only give contributors minimal required repository permissions. The single
owner is mbalbo2023. For every development agent, record issue, branch,
scope, status and handoff. Never grant unrelated infrastructure
access merely because this repository exists.

