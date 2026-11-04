# Boca Socios Assistant

## Nuevo corte de desarrollo — 04/11/2026, después de las 19:20 ART

El propietario **confirmó acceso exitoso en Samsung Chrome** al panel privado
`http://localhost:8443` mediante Termius y passkey. Es una observación humana
puntual: **no** demuestra persistencia de sesión al reiniciar Chrome ni la
salud de un worker navegador. El controller-only instalado permanece anclado
al `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`; los avances siguientes
son **candidatos de código, no desplegados**.

Autorizadas: **Telegram privado** (#315, [PR DRAFT #317](https://github.com/mbalbo2023/boca-socios-assistant/pull/317)),
**pausa/reanudación general de simulaciones** y retiro de Site del panel
(#313, [PR DRAFT #318](https://github.com/mbalbo2023/boca-socios-assistant/pull/318)), y **fuentes oficiales de eventos/categorías/horarios**
(#314, [PR DRAFT #316](https://github.com/mbalbo2023/boca-socios-assistant/pull/316)).
La transición del controller hacia el worker navegador sigue en #227
([PR DRAFT #310](https://github.com/mbalbo2023/boca-socios-assistant/pull/310));
el [PR DRAFT #320](https://github.com/mbalbo2023/boca-socios-assistant/pull/320)
agrega observación de identidad histórica y compensación modelada, pero **no**
existe cutover físico aprobado ni instalado. La candidata integral conecta
`/telegram/emparejar` a la sesión autenticada y añade resolución privada de
chat por Bot API, pero exige recibo público de custodia y un workflow protegido
de instalación V2; **no** recibió token real ni envió aviso. Esta ruta tampoco
está desplegada en el panel actual. El catálogo oficial dispone de vistas
informativas offline, sin conectar categorías a reservas ni admisión.

**Nuevo requisito [#321](https://github.com/mbalbo2023/boca-socios-assistant/issues/321):**
mantener una sola sesión del dueño en el mismo Chrome al cerrar/reabrir pestaña
y reiniciar controller, sin reingreso rutinario de passkey. Código de custodia
y migración en desarrollo; el servidor físico aún usa sesión temporal.

**Descartadas por el propietario:** varias sesiones del navegador, rotación de
clave maestra y eliminación completa, login/fila/elegibilidad/reserva/compra
reales en Boca y backup/restauración. No reactivar ni presentar estas funciones
como pendientes para BETA. El Site complementario se retira **de la interfaz**,
sin modificar infraestructura ajena. Ningún PR de esta ola fue fusionado ni
desplegado; [checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6644301519).

## Estado operativo comprobado — 04/11/2026, 16:33 ART

**Controlador BETA instalado, aceptado y arrancado; BETA integral pendiente.**
GitHub `main=cabce9f1e452e63ded115f447559a358dc0f4d1b` (PR #308,
RCA #307 resuelto) publicó el par de imágenes en
[release #41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078).
El [install #41896871289](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41896871289)
registró `BOCA_BETA_INSTALL state=PASS`, controlador únicamente y HTTP
loopback verificado. La
[aceptación #41897278258](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897278258)
pasó 24 peticiones sintéticas en el contenedor, con 1 socio, 1 intención,
1 aviso local, p95 de 24,17 ms y pico de proceso de 43.648 KiB; sin contacto
con Boca ni envío Telegram. El
[start #41897569928](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897569928)
observó `BOCA_BETA_START state=RUNNING` en `127.0.0.1:8443`, datos/clave/owner
preservados y motor `off`. Este es un recibo puntual, **no** una prueba de
disponibilidad continua ni de acceso desde la Samsung.

Próximos cierres: Chrome Samsung por túnel SSH a
`http://localhost:8443/ingresar`, autenticación y cookie, panel/alta/SQLite
persistentes, navegador opt-in
(imagen publicada, worker no instalado ni activo), Telegram (off, sin recibo
de entrega), y aceptación integral/reinicio. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
sigue abierto para capacidad del conjunto; [issue #285](https://github.com/mbalbo2023/boca-socios-assistant/issues/285)
y [draft #287](https://github.com/mbalbo2023/boca-socios-assistant/pull/287)
no son un piloto autenticado aprobado. Módulos BLACKBOX y navegación real
reservados al dueño. Estado con evidencia y operaciones posteriores:
[checkpoint canónico #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355).
La passkey de Chrome ya fue registrada en el owner-enroll físico; la sesión
servida es temporal (15 min de inactividad, 8 h máximo, inválida tras restart).
Ninguna de esas propiedades acredita por sí sola la persistencia observada
en la tablet.

## Historial anterior al despliegue exitoso (NO es el estado vigente)

### RCA del primer beta-install físico — 04/11/2026 (issue #307)

`main=3c5a0da3df527cfe58a98442ea471be81f9f06ab` (PR #306) produjo un
release inmutable [#41873165726](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41873165726).
El dueño completó el alta de Chrome con PIN en el paso protegido
`owner-enroll` [#41887635433](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41887635433).
El primer `beta-install` [#41889141825](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41889141825)
fue rechazado por la variable de entorno vacía. Con el gate `ready`, el
segundo [#41890280818](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41890280818)
superó validaciones de SHA, release, daemon, owner, staging, configuración y
puerto `127.0.0.1:8443 FREE`. El `beta-preflight` observó 931.808 y luego
914.340 KiB de MemAvailable; el `beta-apply` posterior devolvió
`BOCA_NO_GO: insufficient available host memory` sin registrar su cifra final.
Las tres etapas de detención/limpieza selectiva pasaron, con volúmenes del
dueño preservados; sus recibos detallados no son públicos.

**BETA no instalada.** La causa de rechazo es el veto fijo de 768 MiB que
quedó en `validate_snapshot`, pese a la decisión del dueño de considerar la
holgura un dato observado y medir consumo real después de instalar. El veto
de 512 MiB/0,25 CPU en aceptación requiere la misma reconciliación. El
[issue #307](https://github.com/mbalbo2023/boca-socios-assistant/issues/307)
contiene RCA y propuesta fix-forward; hasta PR, CI, revisión, merge, nuevo
release y recibo protegido, **no repetir `beta-install`**. Límites estrictos
del contenedor, identidad rootless, almacenamiento, limpieza y aislamiento
siguen obligatorios. La sesión autenticada en GitHub se verificó en el
navegador interno para futuros despachos manuales; no se lanzó un reintento.

## Concurrencia del candidato de BETA #306 — 04/11/2026

[PR #306](https://github.com/mbalbo2023/boca-socios-assistant/pull/306)
incluye un ajuste de **validación de PR, no de despliegue**: las ejecuciones
anteriores del mismo PR en Image Release y First Deploy pueden cancelarse al
cambiar el SHA; las operaciones manuales `workflow_dispatch` siguen
serializadas. CI, escaneo de imágenes, revisión técnica, SHA exacto, ambiente
protegido y controles del droplet se conservan. Véase
[ADR0129](docs/ADR/0129-controller-only-beta-resume.md).
**No existe evidencia nueva de BETA instalada**; verificar cuatro checks
del candidato y seguridad postmerge antes de cualquier release físico.

## Contrato vigente para corrección del bloqueo rootless — 04/11/2026

**Actualización 04/11/2026 (Regla 84, RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)):** El [run protegido #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848) verificó `module=absent`, `nf_call_iptables=unavailable`, `index=listed`, `modules_disabled=0`, `write_ops=none` en `main=41fc15e261d002dc614124ac0f2d2e1bea81f896`; fue una **lectura exitosa**, no un deploy.

El propietario ordenó flexibilizar el obstáculo y llegar a BETA. [PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) / [ADR0128](docs/ADR/0128-boca-only-owner-enroll-icc-compat.md) implementan el cambio **solo en la red temporal de `owner-enroll`**: `ICC=true`, UID rootless Boca, cero masquerade, exactamente un peer autorizado, host loopback `127.0.0.1:8443`; limpieza positiva con opciones concordantes. El `network-probe` histórico ICC=false y la variante diferencial ICC=true siguen separados; **no** se cargan módulos ni se modifica kernel/firewall global, Porota u otros servicios. Riesgo residual: menor aislamiento entre potenciales contenedores de esa única red; ningún segundo contenedor está autorizado.

**Estado físico vigente: BETA NO instalada.** PR/CI, release dual exacto, alta Chrome real, `beta-install`, aceptación, recursos y Telegram todavía requieren evidencia. Además [issue #305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) rastrea arranque del daemon antes de instalación y reanudación controller-only después de aceptación. Nunca reutilizar `beta-install` para reanudar, ni activar el navegador BLACKBOX desde agente. Los apartados anteriores del 03/11 abajo son **cortes históricos**, no la instrucción operativa actual.


## Checkpoint rootless físico — 03/11/2026 (RCA #275)

El PR #298 fue **fusionado** en
`main=a83e105d4ccec2cc59dfabce77142750de733630`. Su diagnóstico protegido
[run #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589)
fue exitoso **como inspección de solo lectura** y emitió
`BOCA_KERNEL_BRIDGE state=OBSERVED ... module=absent nf_call_iptables=unavailable write_ops=none`.
La red temporal [ICC=true #41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622)
pasó sólo en modo diagnóstico; la red real de `owner-enroll`, con `ICC=false`,
[falló #41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453)
con `reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`. No se
instaló BETA. El módulo no está cargado o visible, pero todavía se desconoce
si está disponible para el kernel activo. [ADR0126](docs/ADR/0126-readonly-kernel-module-availability.md)
propone una **nueva candidata read-only**, no ejecutada ni fusionada en ese
corte, para distinguir disponibilidad de carga. No existe autorización para
cargar módulos, modificar kernel/firewall global o relajar `ICC=false`.
[Issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
son los registros de evidencia operativa.

## Nueva frontera de titularidad — 03/11/2026

El dueño se reservó en exclusiva la programación de
`browser/synthetic.py` y `browser/ipc_worker.py`, y toda navegación por el
sitio de Boca. Los agentes no pueden interpretar ni modificar esos dos
módulos sin autorización explícita posterior, ni navegar Boca desde el
droplet. Los dos archivos recibidos se preservan **byte por byte** en
[PR #289](https://github.com/mbalbo2023/boca-socios-assistant/pull/289)
con huellas SHA-256. Posteriormente el propietario los declaró **caja negra
validada externamente**, sin exigir a los agentes certificación funcional ni
permitirles inspección. Autorizó fusionar y desplegar con exclusiones
específicas de Ruff, Mypy, Pytest y el recorrido Chromium sintético que
dependía de esos módulos. Las pruebas de los demás componentes, controles de
seguridad y gates físicos siguen vigentes; no se declara un despliegue sin
recibo real. La BETA del controlador mantiene backend `off` y navegación
exclusivamente a cargo del dueño.

Ver [ADR0121](docs/ADR/0121-owner-controlled-browser-navigation.md) y
[ADR0123](docs/ADR/0123-owner-blackbox-rca-exception.md).

## Histórico sustituido el 03/11: Chrome físico y login público

El titular había priorizado la prueba del sitio real antes de las 12:00 ART. La autenticación de Fernando en Cloud Browser no quedó verificada pese a la confirmación del titular de que las credenciales son correctas. El bot de este repositorio **todavía no inicia una sesión real ni reserva entradas**. El [run físico #347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167) en main `4f9718d` confirmó **`google-chrome-stable` presente para UID 10001** con el PR #282 integrado. El [issue #283](https://github.com/mbalbo2023/boca-socios-assistant/issues/283) proponía un único GET público contra login, pero la nueva decisión reserva **toda navegación del sitio** al propietario. Los agentes no lo ejecutarán. Véanse [ADR0117](docs/ADR/0117-host-chrome-readonly-inventory.md) y [ADR0118](docs/ADR/0118-one-shot-public-login-chrome-smoke.md), como referencias históricas; no equivalen a sesión autenticada ni BETA instalada.

## RCA #275 — red Docker rootless, recibo real #342 (2026-11-03 ART)

El [run protegido #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050), sobre `main=d9ad6d492592c403eed70ae85af63f8b1821a67d` (PR #279 integrado), confirmó **`BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`**. La limpieza independiente y la parada del daemon exclusivo de Boca pasaron. Es más preciso que #337 (`firewall_unsupported`), #329 (`firewall`) y #317 (`network_create`), pero no prueba por sí solo el estado global del módulo `br_netfilter`. No se instaló BETA, Chrome ni Telegram. [CI postmerge](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640180891) y [seguridad](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640181029) pasaron.

El código del alta privada usa `enable_icc=false`; [Moby #50635](https://github.com/moby/moby/issues/50635) documenta una falla rootless compatible al faltar `bridge-nf-call-iptables`. El titular aprobó una **prueba diferencial nueva y exclusivamente diagnóstica** con `icc=true` en una red transitoria sin contenedores, puertos ni imágenes. Es sólo un candidato de código hasta contar con checks y recibo físico; la configuración real de `owner-enroll` permanece `icc=false`. No tocar kernel, Docker/firewall global, otras apps ni PPI Watch. Ver [ADR0116](docs/ADR/0116-rootless-icc-true-differential-probe.md) y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45). No habilitar BETA ni publicar release hasta acreditar los gates.

## Decisión vigente sobre recursos (2026-11-02, PR #273 integrado)

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](docs/ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 fue integrado y verificado en `main=0e830e3eed941de1da70cef8b42bda9f20258b65` con CI y seguridad postmerge GREEN. La decisión sigue vigente.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

La reiteración del dueño está registrada, pero la revisión automática volvió a bloquear el dispatch antes de ejecutarlo; no existe un nuevo run. Véase el [bloqueo actualizado](https://github.com/mbalbo2023/boca-socios-assistant/issues/27#issuecomment-6591174050). La captura sigue pendiente por ese control de plataforma.

Public, simulation-first engineering project for a consent-based Boca Juniors
membership and ticket-assistance workflow. This repository is owned by
**mbalbo2023** and remains isolated from **all unrelated applications and
infrastructure**.

> **SIMULATION ONLY. Code evidence and deployed acceptance remain separate.**
> Historical baseline `032de0ebb923b4f80154e93cee3dfd1b254687ed` already integrated
> #224/#226/#229 and #237/#239/#242–#249; do not redo those implementations.
> PR #254 merged as `b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8`; PR #255
> merged as `dada569a2d71ad4411a73ebdaca1186ed3be6936`. The latter adds the
> private Telegram setup form, browser-local encryption and owner pins.
> [PR #255 CI 41481913145](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913145)
> passed 1663 tests plus 31 subtests and the real offline Chromium UI proof;
> [security 41481913075](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481913075)
> passed. These are the PR's receipts, not a substitute for final-main checks.
> PR #253 integrated lifecycle/recovery and durable Telegram gates in
> `5ddfba568d0b53168f51c0e5b33c363ba24c505e`. PRs #261/#263/#266/#269/#270
> are integrated in main `fe70271f940dbc6fc1f422907f5e7254eb2ae508`:
> [postmerge CI 41544296010](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544296010)
> and [security 41544295980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41544295980)
> passed. The five #270 candidate checks passed, including 2283 tests plus
> 31 subtests; they are code/runner evidence, not host acceptance.
> [Status](docs/BETA_INTEGRATION_STATUS.md) preserves earlier cuts and failures.
> New candidates require their own checks; operational receipts belong in
> [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836).
> The owner-authorized preflight and public capture both ran. Infrastructure
> [41537794166](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166)
> failed its initial read-only check, before any marker, start, observation or
> restoration. RCA #268 records the lost diagnostic; its historical reason cannot
> be recovered. PR #269 integrated bounded, read-only `infrastructure-inspect`
> ([ADR0109](docs/ADR/0109-readonly-infrastructure-diagnostics.md)). Its authorized
> [run 41542349197](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017)
> at 20:03 ART returned `NO_GO`, `rc=1`, `transport=confirmed`,
> `reason=effective_preflight_unit_unverified`, `start_attempted=no`.
> [RCA #271](https://github.com/mbalbo2023/boca-socios-assistant/issues/271#issuecomment-6590959214)
> reproduces the parser's rejection of empty Exec arrays omitted by systemd's
> v255 renderer even with `--all`. The exact omitted host fields were not
> captured; this compatible defect does not prove the complete host cause.
> Historical RCA #271 was integrated by PR #272, with postmerge CI/security
> success on `main=ea753ccab29d112b374a07b167d92e68c714cddd`.
> Protected `infrastructure-inspect` #289 then PASSed with daemon stopped;
> infrastructure-preflight #290 subsequently failed its observation step,
> while the mandatory daemon stop succeeded. The resource decision is now
> tracked in issue #274/PR #273; BETA installation remains unverified.
> [Public capture 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470)
> fetched 25 permitted GETs, all HTTP 200. Chromium remained UNKNOWN after a
> denied script GET outside the exact accepted origin, with query redacted and
> no path disclosed; its host and function are unknown. Isolation and cleanup
> passed. The owner reaffirmed continuation of the same 25-GET diagnostic;
> no new capture result is established at this cut. No map expansion or automatic retry;
> see [the report](docs/quality/public-source-validation-2026-11-02.md).
> PR #270 integrated [ADR0110](docs/ADR/0110-public-denied-authority-metadata.md),
> adding bounded `scheme`/`authority`/`host_kind` metadata to the first denial,
> without DNS lookup, contact or a wider capture map. It cannot identify the
> authority omitted from 41537796470; the authorized continuation still needs its own receipt.
> [Read-only inspection 41538696464](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41538696464)
> at 19:36:40 ART found the daemon inactive/dead and its socket absent, with
> capacity not evaluated. It does not identify the earlier failed condition.
> [port check 41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298)
> saw `127.0.0.1:8443 FREE reserved=no`
> only at that instant. No BETA install, current dual release, real private
> activation URL, Chrome/GPM persistence or Telegram delivery is established.
> Finish documentation before release and freeze main through activation and
> recovery; subsequent operational evidence belongs in #45, without moving SHA.
>
> Historical preparation and release evidence follows; it does not validate
> the current candidate:
> The manual Boca workflow inspected the host and prepared its dedicated
> rootless service (#120), then passed a read-only preflight for the dormant
> controller (#124). The protected stop-test #156/41272785626 subsequently
> stopped the dedicated daemon, with no Boca container left running and data
> preserved. Its `containers=0` field counts containers stopped in that run;
> exited containers, if any, remain preserved.
> None of these receipts is application readiness.
> The protected [image release 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820) published `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
> for the pre-change #214 main `8fdbec97262a525821eb87f3fbc27f1841a5d2ec`
> (manifest 13086161844). Earlier releases 41301618285/#208 and
> 41302342233/`3ef7aff8...` are historical. This is GHCR publication only,
> with no droplet pull/install. This code change requires a new exact-main
> release before a future host install; recheck the [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
> The controller was never installed; no live login, Queue-it client or automated
> checkout is enabled. See [current integration status](docs/BETA_INTEGRATION_STATUS.md)
> and [continuity issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Non-negotiable product rules

1. One requested ticket per verified member, **per match**. Database constraint:
   unique member + event, with ticket quantity exactly 1.
2. The database may store membership usernames and recoverable passwords, but
   password values are **AES-256-GCM encrypted** with a key held **outside**
   the database, GitHub repository and image. No credentials from chat are
   committed or imported automatically.
3. Multiple browser sessions are a future configurable capability, not proof
   of multiple Queue-it positions or a way to bypass admission rules.
4. No scraping spikes, Queue-it token fabrication, CAPTCHA bypass, proxy
   rotation or unauthorized endpoint testing. A simulator is used until a
   specifically authorized live observation is possible.
5. The dedicated manual GitHub Actions workflow is the only host-operation
   channel. Release/install code exists; its exact image and host gates must
   pass before an installation can be considered validated.
6. No other project is a dependency, Compose service, networking peer, image
   registry, volume, credential source or deployment target.

## Architectural overview

- Runtime: Python 3.12, typed modules, no unsafe live action implementation.
- Persistence: dedicated SQLite WAL database with migrations and DB-level
  uniqueness. Compose configures `/data/boca.sqlite3` in the persistent
  `boca-socios_boca_data` volume; this describes the intended mount, not proof
  that a Boca database or volume already exists on the droplet.
- Security: AES-256-GCM credential vault with per-record random nonce,
  authenticated member-specific binding, external key volume, and key version.
- Default dormant runtime isolation: Compose project **boca-socios**; named volume
  and bridge network; nonroot, read-only container, dropped capabilities,
  CPU/memory caps, no exposed ports and no host Docker socket. A separate
  beta Compose candidate #171 and protected `beta-install` #191/
  `beta-acceptance` #200 contracts were tested on disposable runners. The
  model was integrated in PR #224/ADR0091 with certificate-free HTTP only
  on Boca host loopback behind SSH, with a private owner volume; no droplet
  install occurred. The isolated one-use browser enrollment #225/PR #229
  uses a separate disposable named Docker staging volume for encrypted
  envelopes, not the private owner volume. Its protected host operation is
  integrated **in code only**;
  no real owner link, Chrome passkey or host installation has been verified.
- CI: pinned checkout/setup actions, frozen dependency lock, lint, format,
  strict typing, tests, image build and repository-isolation checks.
- Delivery: small PRs, recorded agent technical review, exact-SHA status
  checks and immutable release artifacts. Boca-only host operations
  use the manual Actions workflow under the [current scoped authorization](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
  and proof of exact-input and isolation gates. Infrastructure and business
  choices outside the approved delivery plan require options, a recommendation
  and the owner's decision; routine work within that scope proceeds.

## Functional BETA being prepared

The [delivery plan](docs/BETA_DELIVERY_PLAN.md) makes private member enrollment
(**Socios > Agregar socio**) part of acceptance, together with simulation
start/stop/status, durable local notices and restart/idempotency tests. Reuse
the existing encrypted enrollment service; tests use synthetic credentials.
The own-application panel, entrypoint, owner preflight #189, and local
runtime libraries are integrated in code, without application installation.
PR #208 integrated protected owner custody; #224/#229 added the current
SSH-only HTTP and public-passkey-only enrollment path. Historical TLS tests
do not establish tablet access, and no certificate is required for this BETA.
The protected `port-check` choice in the manual workflow tests only the fixed
host-loopback `127.0.0.1:8443` by a short bind/close; a FREE receipt does not
reserve a port or establish tablet access.
The later protected [run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d` reported
`FREE reserved=no` at that instant. The owner chose a private tablet forward
to the local panel on 8443. **Merged PR #224/ADR0091 supersedes
the HTTPS-localhost route:** the only proposed BETA Compose origin is
`http://localhost:8443` (WebAuthn RP `localhost`) through Termius SSH, with
**no device certificate/CA installation**. The actual
forward and physical passkey remain untested;
the single stored credential also needs cross-device proof for Android/iOS.
The former tablet-local TLS WebAuthn emitter (#215, ADR0089) remains only as
historical code and is **not** the owner's enrollment procedure. The requested
one-time activation URL must instead be served from the droplet on the same
isolated Boca port, with a privately delivered single-use key. The integrated
#225/PR #229/ADR0092 code implements the **unserved** `/activar#key=…` flow and
WebAuthn proof, producing a v2 encrypted envelope in a separate disposable
staging volume without mounting the owner's X25519 private key. The #225
`owner-enroll` operation, positive rootless/volume checks, offline
`install-staged` and mandatory same-job selective cleanup after attempted
staging were integrated in PR #229 into the **existing** protected Actions
workflow, with disposable-runner smoke tests. This code is not evidence of a
completed host run: the single-use private URL has **not** been delivered,
nor has physical Chrome passkey creation, private handoff, iOS use or owner
install been verified.
The #217 correction requires a discoverable passkey during local enrollment.
The chosen Android credential manager holds its private key, not a Chrome
cookie. The panel session cookie is temporary (15-minute idle, 8-hour absolute
limit, and invalidated by process restart); Android storage/sync and iOS use
still require physical proof in #209. Chrome localhost cookie acceptance must
be tested on the actual tablet; Safari support remains unverified. No renewal
or generation of TLS certificates is required for the chosen SSH-only route.
Site decommission is deferred until the local replacement is validated.
Merged PR #220 (RCA #219) strengthens the existing Boca-only failed
deploy recovery: a failed staged `beta-install` invokes immediate selective
cleanup via the same protected Actions job. It can remove only verified
disposable controller/network/image/staged-Compose artifacts, while preserving
owner/key/data volumes and retaining the failed deploy status. This is
integrated code/test behavior, **not** proof of a cleanup or BETA installation on the droplet;
unknown or interrupted cleanup remains NO_GO and forbids blind retries.
The lifecycle integrated in PR #253 adds explicit existing-container start,
restart, status and acceptance, plus optional Telegram start and recovery;
see the [operation table](docs/OPERATIONS.md#protected-browser-lifecycle-contract).
The pair budget is `1.5cpu-1024m-192pids`; owner-ready Telegram lifecycle uses
`1.75cpu-1152m-224pids`. Neither is a claim of available host capacity.
This version implements #261/ADR0103: it separates aggregate observations
from numeric reserves, which remain unchanged. Its reviewed CPU criterion uses the container branch's
structural `cpu_ceiling`; load is advisory, not free CPU. ADR0104 measures the
existing CI workloads. Missing counters remain UNKNOWN and three-service
concurrency is unmeasured. Exact-SHA checks and the protected host operation
require their own receipts in #45.
Complete Telegram setup/test before the first persistent simulation; the
BETA acceptance probe uses temporary SQLite. The authenticated
`/telegram/configurar` form from PR #255 produces only ciphertext and the
protected bot/destination pins. It does not install or enable a sender.

The entirely synthetic Chromium journey (#25) and its on-demand and Unix IPC
contracts (#227, ADR0093/0094) are integrated for offline tests, never real
Boca navigation. The integrated optional `BOCA_BROWSER_BACKEND=ipc` uses a
separately isolated, UID10002 Browser Worker with a local Unix socket;
**the default `off` keeps the existing in-process simulation stub**. The
opt-in setting has no usable worker until a separately reviewed image,
Compose/host isolation and selective cleanup are approved, released and
installed. It never enables real tickets or login. Chromium sandboxing,
network isolation, 30-second coordinator budget and worker identity gates
are code-level safety requirements, **not** proof of deployed safeguards.
The command/restart/notification regression suite (#228/PR #231) is merged
and synthetic; Telegram #168 still needs dedicated bot custody, verified
destination and a protected one-message host/owner receipt. Both are
operationally unverified, and no other droplet workload may be affected.
The private Site v10 has a disabled D1 bridge and fails closed while host
credentials/poller are absent. PRs #181/#196 integrated protected ciphertext
custody and global daemon inventory checks, but no Site host phase ran.
Telegram's opt-in worker #188, safe stop recognition #194, sealed helper #199,
protected schema/custody #203 and one-shot Bot API test #204 are integrated,
with no host dispatch, configured bot, verified destination or real send.
The offline #25 Playwright CI smoke (PR #232), #227 synthetic adapter and
IPC/STOP guards (PRs #233/#236), #228 restart/notice regressions (PR #231),
and #168 Telegram identity pinning (PR #230) **are merged as code/tests**.
The Browser Worker runtime/image #237, security #242, dual release #239 and
Compose/install/cleanup #243–#249 are integrated. They do not prove a
running browser sidecar, real Telegram dispatch or BETA installation on the
droplet; see the [status table](docs/BETA_INTEGRATION_STATUS.md).

`/data/boca.sqlite3` in `boca-socios_boca_data` is the delegated logical storage
decision for this BETA, not proof that a database exists on the droplet. Actual
global location remains UNVERIFIED; existing data must never be replaced by
inference. Real credentials and Boca actions remain outside this delivery.

## Read before contributing

- [AGENTS.md](AGENTS.md): binding instructions, including Rule 84: keep affected
  documentation factual and current in the same PR and reconcile continuity
  before closing the task.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): modules and threat boundaries.
- [docs/DEVELOPMENT_POLICY.md](docs/DEVELOPMENT_POLICY.md): branch/PR/CI gates.
- [docs/SECURITY.md](docs/SECURITY.md): password, key and session policy.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): Docker isolation and deployment gate.
- [docs/ROADMAP.md](docs/ROADMAP.md): bounded development backlog.
- [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md): branch rulesets and GitHub settings.
- [docs/QUEUEIT_AUDIT.md](docs/QUEUEIT_AUDIT.md): known vs. unknown Boca infrastructure.

## Development check

The canonical CI command sequence (from a separate development environment):

~~~sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python scripts/check_repo_policy.py
~~~

No manual terminal commands on a production host are required by these
instructions. Host operations use only the gated Boca Actions workflow.

## Lifecycle

**Foundation → simulation → controlled test → recorded technical review →
gated Actions operation.** Offline and local components and the private Site
are integrated in different scopes, but the installed controller remains
absent. The Compose controller still initializes storage and waits with
its engine off. A green CI run is necessary but **not sufficient**
evidence for deployment or a functional BETA.

**Public-repository governance:** GitHub Free supports enforced branch rules
and free standard GitHub-hosted Actions runners on public repositories. The
ruleset must be **created and verified in GitHub Settings**; the existence of
this documentation never proves it is active. See GITHUB_SETUP.md.

