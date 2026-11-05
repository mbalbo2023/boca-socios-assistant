# ADR 0159 — Único Actions protegido para ACK bot/Chromium y Telegram post-Cutover (#352)

**Fecha:** 2026-11-05 ART. **Estado:** PR DRAFT / QA SOURCE_ONLY; LIVE HOST NO_GO sin GO independiente.
**Ownership:** solo workflow boca-first-deploy.yml, runner gate check_protected_action_context.py,
pruebas test_protected_*_r26.py y este ADR. Interfaces host son propiedad
de #351 (bot/Chromium) y #315 (Telegram). Integración canónica solo por #319.

## RCA y alcance funcional

- El panel localhost:8443 registra REQUESTED; no despacha automáticamente
  GitHub Actions. El adaptador rootless #348 ya implementa exact-ID, CLAIM y ACK,
  pero falta ejecutor protegido. **Botón no significa APPLIED inmediato.**
  La fase aprobada es una operación manual lifecycle-apply después del botón
  que produce recibo host APPLIED/REFUSED/UNCERTAIN. Una futura solución
  con efecto en un clic requiere arquitectura distinta: este PR no crea broker,
  token GitHub en panel ni socket Docker en controlador.
- El controller legacy cabce9f no admite Telegram stage V2. Tras Cutover A
  IPC y sender OFF, Tincho puede cargar token en Samsung Chrome y enviar /start.
  La interacción humana no debe ocurrir con la antigua lease/SSH abierta.
  La segunda operación telegram-activate requiere **nueva lease** en el
  mismo workflow y excluye los pasos telegram-* legacy de start/stop daemon.
- El workflow R24 utilizaba **24 de 25** inputs workflow_dispatch, máximo
  confirmado en documentación oficial de GitHub. Ambas operaciones
  comparten un solo campo adicional, protected_action_context (ahora 25/25), apto para
  copiar/pegar como bloque único sin docenas de coordenadas en Android.

## Contrato de autorización

El único input nuevo es base64url **sin padding** sobre JSON ASCII
canónico (claves ordenadas, sin espacios ni duplicados). Payload decodificado
de 1–2048 bytes, tipos string y lista de claves exacta por
kind=lifecycle|telegram. Claves/valores secretos, comando shell, token,
nonce o tiempo humano inventado son NO_GO antes SSH.

Campos comunes públicos: version, kind, source main,
digest GHCR controller/browser, IDs exactos, browser attempt, hashes
Compose y data_mountpoint. El host no confía en input: reatesta Docker
rootless Boca UID10001, manifests release, configuración, IDs y almacenamiento.
No adivinar host data-root a partir de pruebas sintéticas; lifecycle exige
ruta absoluta normalizada y comparación exacta con Docker volume inspect
del volumen boca-socios_boca_data. Telegram monta /data exclusivamente.

- Lifecycle incluye expected_component=bot|chromium y
  expected_target=start|stop. Deben corresponder a la única REQUESTED
  vigente en el ledger legacy antes de CLAIM/effect/ACK. El UUID no es
  autorización por sí mismo.
- Telegram incluye recibo Cutover A previo, pins de propietario y destinatario,
  y sender inactivo. La hora stage auténtica nace del archivo server-side 0600
  y de la firma HMAC owner, no del input Actions; la ventana /start se ata
  a ese timestamp y nonce O_EXCL/antirreplay.
- Cada operación tiene variable distinta en Environment protegido:
  BOCA_LIFECYCLE_GO_BINDING_SHA256 o
  BOCA_TELEGRAM_ACTIVATE_GO_BINDING_SHA256. El SHA esperado liga repo,
  actor, ref main, source SHA, release, PREPARE-run/attempt, operación y SHA
  del contexto canónico. El APPLY-run ID es generado por el runner después del
  dispatch y no participa del GO humano configurable. Ausente o diferente: NO_GO pre-SSH.
  Los GO cutover/import no autorizan lifecycle/Telegram.

## Secuencia

1. PR ejecuta solo CI offline, host_calls=0. Host exige dispatch manual
   main SHA exacto, propietario original, intento 1 y Environment protegido.
2. Runner autentica release/manifests, contexto estricto, GO y revalida main.
   No material privado en argv, artifacts ni resumen.
3. Un único SSH Boca recibe bundle verificado por stdin. Host adquiere una
   flock nueva y reatesta UID, config/ID, ledger/nonce, salud y sender OFF.
   Bot START/STOP usa AF_UNIX interno y worker solo Docker ID exacto.
4. Recibo host terminal es obligatorio; ausencia, timeout o incertidumbre
   implican NO_GO sin reintento, prune ni borrados por inferencia. Cutover A
   conserva su postflight Docker selectivo success/failure; los seis
   instaladores legacy permanecen bloqueados pre-SSH.
5. Cutover, stage Chrome, segunda activación y observación Samsung/Termius
   se prueban físicamente en etapas separadas. Ningún GREEN PR instala
   o comprueba Telegram por sí solo.

## Fronteras, evidencias y límites

No tocar BLACKBOX synthetic.py/ipc_worker.py, Porota, otros workloads,
kernel/servicios/puertos/volúmenes, backups, ni legacy SQLite 0008. Sin
login/fila/reserva/compra reales ni nueva navegación externa por agentes;
origen privado exclusivo 127.0.0.1:8443 por Termius. Seguridad adicional P2,
sin relajar identidad, source, autorización ni limpieza.

Baseline inicial de este satélite #359 fue #319 SHA 3c4880df (R21.9.2).
Base canónica actual de PR #359 al abrirlo: #319 R21.11 SHA
5903ded0790ab7254bf68572af47fe75c6e08889, 7/7 Actions SUCCESS
exactos según checkpoint #45; los checks de #359 R26 son independientes
por SHA. Ningún host real. Referencias: issue #45
A45-R12/R12.1, #315, #328, #351, #352; ADR0151/0152/0154.
Los resultados de QA R26 y cualquier recibo real son PENDIENTES y deben
documentarse por SHA/run exactos (Regla84).


## RCA P0 adicional: GO ligado a un run todavía desconocido

**Evidencia 05/11, issue #352 comment 6660456966:** el gate actual de
Cutover A `scripts/check_cutover_a_go.py:authorization_digest()` incluye
`GITHUB_RUN_ID` e intento 1. `host_official_notice_actions.py:expected_go_sha256()`
de la importación oficial #349 también incluye `operation_run_id=GITHUB_RUN_ID`.
Las variables `BOCA_CUTOVER_A_GO_BINDING_SHA256` y
`BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256` deben estar configuradas en
Environment antes de que el preflight permita el primer SSH. En el workflow
despachado el identificador se genera *después* de la pulsación Run workflow.
Sin pausa/handoff tras conocerlo, ambos GO exactos son imposibles de
preconfigurar, incluso si todo el CI está GREEN. Los dos GO propuestos
para lifecycle/Telegram presentan el mismo obstáculo; además, el contexto
manual inicial pide `attempt_id=GITHUB_RUN_ID`, dato no conocible al
construir ese input. El PR DRAFT #359 ahora **sí añade** las opciones de dispatch a un único
workflow, con PREPARE inerte y lifecycle APPLY efectivamente condicionado al
GO B independiente, revalidaciones exactas y ACK físico. Ningún job PR puede
acceder al host, no se ha despachado operación física y Telegram activate se
rechaza siempre en el case inicial, antes de SSH. La identidad host solo se
confía después de backend rootless #356 con marcador O_EXCL por PREPARE.

| Operación | Dependencia GO del run actual | Disponibilidad del actor | Bloqueo para despacho hoy |
| --- | --- | --- | --- |
| `cutover-a-apply` | Digest sobre run, owner y manifests/ZIP | Backend/CLI code-only | Sí, GO dinámico imposible sin pausa verificable |
| `official-notice-import` | Digest sobre run, fuente pública y artifact | Importación #349 ya en candidato | Sí, mismo deadlock GO |
| `lifecycle-apply` | Digest nuevo sobre run y contexto con `attempt_id=run` | Host #356 code-only; REQUESTED no crea dispatch | Sí, input también incognoscible y no hay ACK físico |
| `telegram-activate` | Digest nuevo sobre run y contexto con `attempt_id=run` | Host #357 fase2 no tiene caller effectful probado | Sí, GO/input incognoscibles y falta backend same-lease |

### Dos alternativas con GO independiente (pendiente GO arquitectónico)

**A — required reviewers verificablemente activos.** El job de host queda
retenido antes del runner, nunca se abre SSH durante la espera. Una fase
READ_ONLY de preparación obtiene el run ID y receta del digest exacto.
Tincho aprueba la configuración vinculada y luego libera el environment.
Esto exige verificar en la UI *configuración actual*, posibilidad de editar
y consumir la variable protegida después de la espera, y que el gate real
exija revisión sin bypass. Además lifecycle/Telegram **no pueden** exigir
`attempt_id` en el input original: el runner debe completar el run ID tras
el dispatch y entregar el contexto resultante al host. Los comentarios
históricos #45 6509894858/6511103286 indican reviewers desactivados al
29/10; #45 6603446482 declara settings actuales desconocidos por connector.
La existencia de `environment: boca-first-deploy` sola no acredita espera.

**B — prepare/apply en dos despachos dentro del MISMO workflow (recomendación
provisional, NO autorizada para efectos).** Primera operación
`protected-go-prepare` **READ_ONLY, host_calls=0** produce un recibo
inmutable atestando repo/owner/main/source SHA exacta, componente,
release/manifests/ZIP, operación específica y `prepare_run_id` conocido.
Este recibo debe tener identidad, digest canonizado, evidencia de Actions,
ventana de validez y marcador de consumo único; los secretos owner HMAC
permanecen en custodias protegidas (nunca artifact). Tincho revisa resultado
y deposita el digest GO específico de ese PREPARE en el Environment. Segunda
operación APPLY separada verifica recibo, GO, SHA/hash de las fuentes sin
deriva, origen, intento 1, `prepare_run_id` conocido y bloqueo de replay,
y recién entonces puede habilitar la única operación host sobre nueva lease.
Su nuevo `GITHUB_RUN_ID` **se atesta y se agrega por el runner después de
iniciado APPLY**, para que el contexto entregado al backend exact-ID incluya
`attempt_id` sin pedirle al usuario que lo adivine antes del dispatch.
La autorización humana firma el PREPARE conocido, no un ID futuro. Cada
fase mantiene autorización separada, sin GO booleano, reusable o derivado
únicamente de un input; no se guardan secretos en argv/logs.

**No confundir:** un paso `prepare` y `apply` secuenciales dentro de
*una sola corrida* sin retención de aprobación entre ambos no sirve: es
preparación y efecto automáticos en el mismo trigger, por lo que no hay GO
independiente. El diseño B usa dos despachos humanos diferenciados, un único
archivo de workflow y un único control host por el segundo despacho.

**Estado de la decisión:** comparar A contra B no cambia el gate Cutover A
existente, que sigue fail-closed. Falta GO arquitectónico de Tincho antes
de modificar semántica del gate o instalar/desplegar. Referencias oficiales:
[GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[review deployments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/review-deployments)
y [workflow dispatch REST](https://docs.github.com/en/rest/actions/workflows).


## Implementación R26 en PR DRAFT #359 (sin ejecución host)

- Nuevo input opcional único `protected_action_context` (25/25) y tres
  operaciones explícitas en `boca-first-deploy.yml`: `protected-go-prepare`,
  `lifecycle-apply`, `telegram-activate`. La última se rechaza
  deliberadamente PRE-SSH; además se excluye de los cinco pasos
  `startsWith(inputs.operation,'telegram-')` que podrían iniciar/apagar
  el daemon legacy. No se crea otro workflow, puerto, broker, host service ni
  credencial en UI.
- PREPARE acepta b64url JSON canónico estático **sin** `attempt_id` (futuro)
  ni `prepare_run_id` (aún desconocido), lee manifests release controller+
  browser ya verificados, revisa Option B ZIP desde fuente exacta, owner SHA
  sin revelar owner y crea `boca-lifecycle-prepare.receipt.json` canónico
  + `boca-lifecycle-apply-context.txt` con `prepare_run_id` REAL ya conocido.
  Artifact GitHub `boca-protected-go-prepare` retención 2 días y recibo
  TTL 24h. El GO_SHA256 visible en Summary representa SHA domain-separated
  del recibo entero; no es un secreto ni una autorización por sí solo.
- Tincho revisa PREPARE en Actions, configura únicamente el GO digest exacto
  en `boca-first-deploy` Environment como variable
  `BOCA_LIFECYCLE_GO_BINDING_SHA256`, y luego dispara APPLY con el texto
  canónico de `boca-lifecycle-apply-context.txt`. Ni PIN, token Telegram,
  passkey ni clave de SSH se solicitan en un input. El connector GitHub
  actual permite leer PR/Actions pero **no expone** aquí escribir variables
  del Environment ni despachar manualmente workflows; esos dos pasos de
  interfaz protegida siguen siendo interacción de propietario, no terminal.
- Runner APPLY vuelve a descargar PREPARE por `prepare_run_id`, valida
  `workflow_dispatch` exitoso `attempt=1`, owner/main/SHA, `path`, ZIP,
  releases, hashes, reloj 24h y GO. Solamente entonces injerta su propio
  `GITHUB_RUN_ID` como `attempt_id` en contexto host. Backend #356 reatesta
  rootless Docker UID10001, volumen y IDs exactos, consume marcador durable
  O_EXCL de `prepare_run_id` bajo lease, procesa una REQUESTED actual y
  devuelve un JSON terminal de diez campos `APPLIED/REFUSED` +
  `physical_ack`. El runner rechaza cualquier falta, duplicado, señal
  incierta o ACK no exacto, sin reintentos/cleanup adivinado.
- PREPARE no tiene SSH (ni lee credencial host); `pr-validation` solo tests
  offline y declara NO_GO ante cualquier archivo de recibo físico inyectado.
  `Cutover A` e importación #349 mantienen gates originales sin cambios.

**Dependencias P0 para GO B total (owner #360):** helpers puros
`cutover_prepared_context_sha256` y
`official_prepared_context_sha256` de PR #361 validan evidencia legacy
pero **no** implementan consumo de PREPARE host. Cutover A conserva solo
O_EXCL sobre `plan.attempt_id` de APPLY, y la importación #349 es
idempotente en datos pero no agota un GO PREPARE global. Por tanto **ambas
quedan NO_GO en la práctica** hasta que el backend físico de cada operación
consuma `prepare_run_id` de modo atómico y exista migración revisada de
sus gates; estas operaciones no se han incorporado a PREPARE #359 ni se
ha alterado su implementación.


### Retiro de la ruta GO v1 inejecutable del helper público

`scripts/check_protected_action_context.py` conserva exclusivamente codec
canónico, shape guard y escritura O_EXCL del runner. Se eliminaron
`expected_go_binding()`, `require_go_binding()` y su CLI `--from-actions`
que aprobaban por un SHA ligado a un `GITHUB_RUN_ID` todavía desconocido en
el primer dispatch; ejecutar directamente el módulo siempre responde NO_GO.
El único gate operativo nuevo lo implementa
`scripts/check_protected_go_prepare.py --prepare/--apply`, con dos runs
humanos, digest del PREPARE conocido y permiso Environment independiente.
No existe fallback GO booleano ni input autoautorizante.
