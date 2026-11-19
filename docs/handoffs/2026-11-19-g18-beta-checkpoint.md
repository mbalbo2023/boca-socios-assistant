# Boca Socios Assistant G18 — checkpoint de continuidad, RCA y certificación BETA

**Fecha de corte:** 19-Nov-2026 (UTC/ART; verificar horas en cada Action).
**Clasificación:** handoff operativo y documental; **NO** orden de build, deploy ni BETA_GO.
**Ledger vinculante:** [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417), en particular
[D4.0](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6996778290),
[D4.8](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6997206009),
[D4.10](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6997418063),
[D5.0](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6998086501)
y [D5.1](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6998105414).
**Contexto extendido:** [handoff canónico original](../HANDOFF_G18_2026-11-18.md),
[estado BETA](../BETA_INTEGRATION_STATUS.md), [AGENTS.md](../../AGENTS.md)
y [README.md](../../README.md).

## 1. Estado verificado al corte (no confundir instalación con certificación)

| Dimensión | Estado acreditado | Límite |
| --- | --- | --- |
| **G18 instalado** | **ACCEPTED** en [Boca Action #1262/run 44437268809](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44437268809); `commit_started=true`, `cleanup=ACCEPT`, `failed_phase=NONE` | No repetir el deploy. |
| Identidad exacta | Fuente `main@afb0ac0acadbd67e6ccfb7875be4927aaeb43eb8`, [release dual #877/run 44431435425](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44431435425); controller `sha256:c1d72dec3dafba99e4f0256647087c82e3b4fedf7bf621050536319f16198642`, worker `sha256:252a78346d107d5ad08a20f453a1a03f6c37785143253b6b6393a6e4dfc61e7f` | No inferir que una revisión documental posterior es un binario nuevo. |
| CIDs aceptados | Controller `cc058236f6f9e5372661c80355ae9454ddc643ed705fcb93c54e3d0741b7c167`; worker `0e0b0c8f1f82f965900bfa462665cfdfb42b8d47e8f089c0d9170d0dc9790548` | El recibo acredita el par exacto, no su navegación. |
| Postflight | [#1263/run 44438577710](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44438577710) SUCCESS, controller `HEALTHY`, motor `STOPPED`, worker `CREATED/PID0` | No hay START, visita de URL o login DOM certificados. |
| Administración | [#1264/run 44438834319](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44438834319) SUCCESS: `PROVISIONED`, schema sectores 2, `legacy_writes=0` | Telegram `configured/paired/human_receipt=UNVERIFIED`, sender `ABSENT`; no mensaje real. |
| Origen HTTP | [#1265/run 44439039068](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44439039068) SUCCESS: dos GET loopback `127.0.0.1:8443`, `HEALTH_HTTP_200` | `site_files=PRESENT_UNVERIFIED`, `OBSERVED_NO_GO/deploy=NO_GO` limitan al **lector**; no revocan #1262 ni prueban sesión/UX. |
| Playwright de UI | [CI del SHA instalado/run 44420384820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44420384820), artefacto `14480658260`, `PASS` sintético en Chromium 412×915, 800×1280 y 1536×960 | Sin host ni Samsung. Motor B queda bajo primer pliegue en vertical; no inventar PASS físico. |
| **BETA funcional** | **UNVERIFIED / BETA_GO=NO** | Pendientes worker activo, A/B, socio/DOM, URL/HTTP/intentos, eventos/colas/tokens, Telegram y Samsung/control por voz. |

**Verificación remota fresca de este corte:** `main@afb0ac0...`, **cero PR abiertos**, última actividad de Actions #1262–#1265 con `completed/success` y ninguna Action física nueva que cierre las brechas. No se ha realizado un segundo deploy.

## 2. RCA del incidente histórico #1251 — qué está demostrado y qué no

1. [APPLY #1251/run 44352430452](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44352430452) falló en `ATTEST`: `commit_started=false`, `cleanup=INDETERMINATE`, ningún CID sucesor. Es un incidente **anterior** al deploy correcto #1262; prohibido reintentarlo.
2. La **única** lectura forense [#1255/run 44365905614](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44365905614), agregada por [PR #553](https://github.com/mbalbo2023/boca-socios-assistant/pull/553), halló marcadores auténticos `evidence,intent,terminal`, sin `commit` ni postflight. Estado `PRECOMMIT_TERMINAL_NO_GO`, `CANONICAL_ATTEST_NO_GO`, `observer_writes=0`.
3. La revisión de `host_boca_pair_upgrade.py` y su CLI y la reproducción D2 mostraron **dos rutas con recibo schema 1 indistinguible**: error/resultado inválido de `backend_factory` **o** error posterior de `backend.attest`. El RCA exclusivo histórico es **`ATTEST_ROUTE_UNDETERMINED` / `exclusive_cause=UNPROVEN`**, no un permiso, URL, Docker, SQLite, IPC o worker probado.
4. `ATTEST` **ya existía en G17 desde el 11-Nov**, no fue una protección recién inventada. El [PR #555](https://github.com/mbalbo2023/boca-socios-assistant/pull/555) integrado en `afb0ac0...` incorporó **`ATTEST_FACTORY` prospectivo** para separar la factory de `attest` en futuros recibos, con las guardas intactas. No reinterpreta retrospectivamente #1251 ni demuestra su causa.
5. `cleanup=INDETERMINATE` no prueba destrucción. El éxito posterior #1262 no transforma una hipótesis histórica en RCA confirmado. [D4.10](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6997418063) corrigió explícitamente el error documental de afirmar que `ATTEST_FACTORY` aún no estaba implementado.

**RCA operativo de la brecha de aceptación actual (D5.0):** no existe en el inventario revisado una Action Playwright de **panel físico autenticado y SHA G18** que pueda despacharse sin riesgos o falsear su alcance. `beta-browser-acceptance` es sintética y su `if: always()` llama `stop-test`; `worker-physical-once` y `worker-diagnose-once` fijan instalación/releases históricos (`42806447101`, entre otros); `boca-panel-exact-origin-observe` sólo cubre HTTP200 y ya se ejecutó. GET guest de `/control`, `/control/actividad`, `/configuracion` sólo muestra proyecciones redactadas; GET `/ingresar` genera challenge de passkey. Esto demuestra **incompatibilidad/insuficiencia de las herramientas antiguas**, no un defecto demostrado del runtime G18.

## 3. Ownership y límites vigentes

- **Tincho** disolvió inmediatamente el comité 4GO y ordenó a **Root** decidir y continuar autónomamente. La revisión de Arquitectura/QA/Operaciones es evidencia histórica, **no** requisito de consenso nuevo. Cuando exista reparación concreta, separar autor y verificación técnica para evitar autocertificación.
- **Operar el droplet exclusivamente mediante GitHub Actions de Boca**. Sin SSH/Docker directo, sin navegador remoto al panel fuera de ese circuito, sin tocar Porota, otros servicios, puertos, volúmenes, cuentas ni claves. No desactivar `ATTEST` o mecanismos de seguridad sin defecto demostrable.
- **SIMULATION_ONLY**: sin reservas/compras reales, CAPTCHA/WAF bypass ni inferencia de login por token. Nunca publicar secretos de socio, `Queue-it`, cookies, passkeys, URLs privadas, Chat ID/Token Telegram, HAR ni DOM privado en issues, PR, Actions, capturas o logs.
- **Trabajo cerrado que NO se repite**: APPLY #1251, Action #1255, #1257, #1262; releases #876/#877, CI/builds ya certificados, observadores #1263/#1264/#1265 y aceptación sintética ya auditada. No nuevos PR o builds de diagnóstico especulativo.

## 4. Bloqueantes reales y trabajo en curso

| Prioridad | Bloqueante/pendiente | Evidencia necesaria y salida segura |
| --- | --- | --- |
| P0 | **No hay Playwright físico seguro para G18** | Antes de dispatch, verificar fuente/workflow, instalación #1262 y efectos. Sólo si agrega evidencia útil, diseñar **un único** candidato QA-only para GET guest vía Boca Action, Chromium aislado, sin cookies/POST/START/STOP ni secretos, con capturas saneadas; no confundirlo con aceptación owner. No ejecutar selectors históricos. |
| P0 | **No hay sesión owner/voz Samsung atestada** | Requiere observación legítima de Tincho en Samsung Android (vertical/horizontal y control por voz), acceso passkey privado, navegación Control/Actividad/Configuración; capturas redactadas. No pedirle comandos de shell ni divulgar credenciales. |
| P0 | **Motor A/B físico no atestado** | Con herramienta Boca Action compatible con SHA/CIDs y simulación acotada, verificar START/STOP y recibos específicos, intentos hasta tres **por sesión**, URL inicial/final, HTTP, evento/no-evento, cola, token presente/ausente, errores y auto-stop. `STOPPED/PID0` hoy sólo acredita espera. Ninguna reserva real. |
| P1 | **DOM/login y socios** | Comprobar estado de cada socio desde sesión privada; `has_auth`, tokens y formulario no acreditan DOM autenticado. Separar por socio y no filtrar secretos. |
| P1 | **Telegram real** | La UI de token/Chat ID existe; el sender figura `ABSENT`. Acreditar configuración, custodia, pairing y recibo físico específico antes de afirmar enviado/conectado. Sin mensajes externos de prueba por presunción. |
| P1 | **UX e interacción** | Los tres tamaños sintéticos están auditados; defecto de jerarquía vertical Motor B observado. Confirmar con Samsung real antes de un cambio. Evaluar copia privada de token, densidad, errores, URL, estado del motor, `Ingresar`/passkey sin relajar autenticación. |
| P2 | **Documentos no integrados en main** | Rama sólo documental `docs/417-g18-accepted-20261119`; sin PR/merge. `classify_exact_internal_pr_docs.py` excluye los cuatro Markdown canónicos de la vía docs-only, por lo que un PR podría iniciar CI/builds duplicados. Preservar `main@afb0ac0...` hasta integración deliberada sin reinstalación automática. |

**Trabajo en curso exacto al entregar:** investigación D5.0 y su checkpoint D5.1 documentados; **ningún** cambio productivo, PR nuevo, Action física adicional ni reserva iniciada. La siguiente persona debe reconciliar el ledger #417 **después** de esta entrega y el HEAD remoto antes de actuar; si aparece evidencia nueva, actualizar este cuadro. No convertir supuestos de diseño en BETA_GO.

## 5. Camino crítico de continuación — ejecutar sólo lo no terminado

1. **Reconciliar** `main`, PRs, últimos Actions, #417 y rama documental. Confirmar instalado #1262 y no duplicar operaciones ni tareas completadas.
2. **Cerrar la brecha de observación** con el medio menos invasivo. La única posible Action guest Playwright requeriría contrato nuevo limitado y revisión independiente; no la crear si no agrega evidencia neta. Una prueba guest nunca certifica tokens/login privados.
3. **Coordinar la única aceptación que depende del dispositivo real**, desde Samsung con passkey del titular y voz, capturas sin datos privados; usar esa evidencia para localizar defectos concretos de UX.
4. **Certificar motores físicos en simulación** únicamente si hay Action compatible/pineada al deploy y sin riesgos de reserva: START/STOP exactos, URL, intentos, resultados HTTP, eventos/cola, tokens, socio/DOM, errores y auto-stop. Si no existe, registrar el bloqueante: no forzar los scripts viejos.
5. **Cerrar Telegram** por recibos de configuración y sender, sin asumir que PROVISIONED equivale a conexión.
6. **Corregir sólo defectos reproducidos**, reutilizar módulos existentes, un autor diferente del verificador y **un solo candidato** de producto si realmente requiere PR/CI/release/deploy; nunca reconstruir G18 instalado por comodidad documental.
7. **Certificación final**: evidencias del host y del titular para cada fila de [matriz BETA](../HANDOFF_G18_2026-11-18.md#7-matriz-mínima-para-declarar-beta-go), sin reservas reales ni tocar Porota. Hasta entonces `G18_INSTALL=ACCEPTED`, `BETA_FUNCTIONAL=UNVERIFIED`, `SAMSUNG_OWNER_UX=UNVERIFIED`, `BETA_GO=NO`. Publicar cada avance en #417.

## 6. Lecciones aprendidas y riesgos recurrentes

1. Un error de fase `ATTEST` **no demuestra su subcausa**: dos rutas produjeron bytes idénticos. Separar causa observada, hipótesis y cambio de observabilidad futuro.
2. **Release ≠ deploy ≠ HEALTHY ≠ BETA_GO**: son capas de evidencia diferentes y ninguna sustituye navegación, DOM o uso accesible real.
3. El identificador de **instalación** importa tanto como el SHA del código de diagnóstico. No despachar workflows con pins históricos sobre otro par de contenedores.
4. Un test aparentemente visual puede tener limpieza con **efectos de estado** (`stop-test`); revisar `if: always()` y condiciones de cleanup antes de ejecutarlo.
5. Playwright **sintético/offline** sirve para regresión/maquetación, no para certificar host, cookies de socio ni voz Samsung.
6. Vistas **guest** redactadas no son equivalentes a sesión owner; el passkey no debe eludirse por comodidad del test.
7. `CREATED/PID0`, `has_auth`, `HTTP200` y `PROVISIONED` requieren interpretaciones estrechas. No derivar actividad real, login DOM, salud integral o Telegram conectado de etiquetas parciales.
8. Evitar repetición preserva tanto seguridad como presupuesto: un solo candidato, ningún build/PR inútil, `main` fijado al SHA instalado y documentos versionados en rama separada.
9. Una errata en el checkpoint anterior (`ATTEST_FACTORY` no implementado) fue **corregida públicamente** en D4.10. Mantener la fe de erratas y auditar código antes de heredar conclusiones.
10. Una certificación útil debe contemplar accesibilidad del titular: Samsung con control por voz, pasos mínimos y nunca exigirle comandos de infraestructura que puede ejecutar una Boca Action.

## 7. Texto breve para abrir un nuevo chat (copiar una sola vez)

> CONTINUAR BOCA G18 desde `docs/handoffs/2026-11-19-g18-beta-checkpoint.md`,
> `docs/HANDOFF_G18_2026-11-18.md` y últimos comentarios de issue #417.
> Tincho disolvió comité; Root decide. G18 **ya desplegado** desde
> `main@afb0ac0...`: release #877, APPLY #1262 `ACCEPTED`, postflight #1263
> HEALTHY/STOPPED/PID0, admin #1264 PROVISIONED/Telegram sin sender, origen
> #1265 HTTP200. Playwright CI sintético PASS, **no** certificado en host/Samsung.
> #1251 ATTEST histórico sin causa exclusiva probada; no repetir #1251,
> #1255, #1257, #1262, releases ni builds. D5.0 demuestra que los workflows
> antiguos de worker/browser son incompatibles o tienen efectos. BETA_GO=NO:
> falta prueba física A/B, URL/intentos/HTTP, cola/eventos/tokens, DOM/socios,
> Telegram y UX Samsung/passkey/voz. Reconciliar main/PR/Actions; no duplicar
> código ni PR, no reservas reales, nada de Porota. Todo host sólo por Boca
> GitHub Actions; publicar avances en #417 y mantener Markdown. Rama documental
> `docs/417-g18-accepted-20261119` sin PR/merge para evitar build duplicado.

## 8. D5.3 — reconciliación de código de QA y protocolo de evidencia BETA (19-Nov-2026 ART)

**Revalidación de GitHub sin ejecución:** `main@afb0ac0acadbd67e6ccfb7875be4927aaeb43eb8`, **0 PR abiertos**; los últimos runs del repositorio son #1262–#1265 `completed/success`, sin Action nueva ni cambio de instalación. La rama de documentación parte del mismo SHA instalado y conserva sus identificadores y recibos.

**Código previo recuperado, sin duplicarlo:**

- `scripts/qa_guest_navigation_playwright.py` **ya existe en main** (blob `e9dce390d89ded45566e2c8f61575bda078ea666`). Abre Chromium sobre una instancia WSGI **sintética del runner**; `mode=OFFLINE_FIXTURE`, `owner_auth=WSGI_SYNTHETIC_ONLY`, bloquea destinos externos y no captura el droplet. No es la Action física que falta; no ejecutarlo nuevamente como supuesto test host.
- La rama residual `feat/417-guest-readonly-fast-ci` está **divergida de main** (3 commits ahead / 11 behind según GitHub compare). Ya contiene ese tipo de navegación **offline** y cambios históricos de panel; **no** es un candidato limpio para G18 ni una Action host. No revivirla ni duplicar su script; no hay PR abierto asociado. No se modificó esa rama.
- `panel/engine_view.py` en main contiene las tarjetas lógicas A/B y sus campos para URL configurada, último intento, URL final, evento, cola, tokens y autenticación de B. La leyenda distingue expresamente «Actividad física actual: No comprobada en esta vista». `_forms` deshabilita START si SITE_URL no está disponible, y B además requiere socio con credencial activa. Esto es **código instalado**, no prueba de que la URL/socio estén listos o que una sesión haya navegado.
- `beta-browser-acceptance` sigue haciendo `stop-test` en cleanup; los selectors físicos heredados continúan pinneados a un par anterior; `boca-panel-exact-origin-observe` ya agotó su alcance en #1265. No se despachó ninguno de ellos.

**Ruling autónomo Root:** preservar el G18 aceptado y no agregar aún un workflow/PR/build para capturas guest que seguirían sin certificar sesión privada, worker, DOM, Telegram ni voz. Preparar primero una observación **sin efectos** desde la Samsung del titular para distinguir defectos de visualización reales de falta de configuración y de falta de evidencia física. No tratar la ausencia de una captura como fallo del producto. Si después la prueba física precisa código, usar un **solo** contrato nuevo de QA de Boca Actions, con SHA/CIDs de #1262, GET guest sin cookies/POST ni datos privados y recibos tipados; activar motores sólo mediante una operación compatible y acotada de **simulación** con START/STOP exactos. Nunca reutilizar pins antiguos ni quitar controles para conseguir PASS.

### Secuencia de aceptación pendiente (sin secretos ni reservas)

| Orden | Superficie y observación | Evidencia esperada | Sin inferir |
| --- | --- | --- | --- |
| 1 | Samsung real: sesión passkey ya establecida; Control/Actividad/Configuración vertical y horizontal, navegación con Voice Access | Visibilidad de A/B, foco, lectura de estado y botones, densidad y cambio entre las tres pantallas; captura saneada | Un Chromium offline no prueba voz ni dispositivo |
| 2 | Configuración privada (solo observación): SITE_URL listo/no listo; socio con credencial activa presente/ausente; Telegram editable | Estados **sí/no/no verificado** sin publicar URLs, nombres, IDs ni tokens | «Formulario presente» no prueba fuente ni sender |
| 3 | Boca Action compatible con instalación #1262 **por diseñar si hace falta** | Identidad de controller/worker, inicio/parada controlado, cada intento, URL/HTTP, evento/cola/token o ausencia observada con procedencia | STOPPED/PID0 no es visita; requests/contextos no son navegación |
| 4 | Sesión privada legítima de socio y DOM | Resultado de login **DOM**, URL/estado por socio, reserva **sólo simulada** | `has_auth` o token no acreditan DOM |
| 5 | Telegram con custodia y recibo real revisado | configured/paired/sender/human receipt separados | PROVISIONED no significa «conectado» |

**Instrucción mínima para Tincho ahora:** abrir el panel privado con su acceso habitual en la Samsung; visitar **Control → Actividad → Configuración** en vertical y horizontal; probar Voice Access para activar la navegación y localizar A/B; remitir únicamente observaciones y capturas **ocultando URL privada, credenciales, socios, tokens y Chat ID**. En esta primera pasada no pulsar **Iniciar/Detener motores, Guardar Telegram o Reservar**; la fase física del worker será por Boca Actions compatible. No requiere terminal ni comandos. Tampoco hay necesidad de modificar passkey.

**Límites y avance de esta entrada:** auditoría GitHub + trazabilidad de código + protocolo de aceptación, **cero** nuevos Actions, builds, PR, modificación de host, motor, Telegram, reserva o Porota. `BETA_GO=NO`, `OWNER_SAMSUNG=UNVERIFIED`, `MOTORS_PHYSICAL=UNVERIFIED`. RCA #1251 permanece `exclusive_cause=UNPROVEN`.
