# Boca Socios Assistant — checkpoint de relevo por avisos de red

## 0. Punto de entrada y propósito

Este corte preserva el trabajo del chat «Estado de Telegram» y su continuación. Tincho pidió recuperar contexto, ownership, pendientes, bloqueantes y camino crítico; luego ordenó terminar lo pendiente antes de su prueba integral. El último pedido fue guardar un checkpoint completo y una instrucción breve para otro chat debido a avisos de pérdida de conexión. **El siguiente chat debe continuar el objetivo, sin reiniciar el proyecto ni repetir tareas cerradas.**

Repositorio único: **mbalbo2023/boca-socios-assistant**. No confundir con Porota Trading ni PPI Watch. Registro vivo canónico: https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6899119716 . Issue45 concentra entrega/ownership; issue12, brechas funcionales; issue531, capacidad50. Este documento es un corte congelado; reconciliar el registro vivo antes de efectos.

**Corte comprobado:** main b3200f7bc4391156205dab992989a609253ec6ee, árbol a730e2f595d2cf4dc762c41b021b2366674afccc; CI1283 y Security1094 SUCCESS. No PR abiertos. R309 NO despachado. Instalación R845f31ab sin cambios. R310 congelado y respaldado, con revisión final y medición física pendientes. La BETA integral todavía no está acreditada.

La comprobación remota de main/CI/seguridad/PRs/runs se hizo el 2026-11-16 a las00:36:37UTC. CI1283 terminó00:33:43UTC. No se atribuye la causa del aviso de red: GitHub sí respondió y aceptó el respaldo. No se abrió otra operación host durante este cierre.

## 1. Autoridad, restricciones y forma de trabajo

- Root es el único integrador de GitHub y operador de Actions. Los autores no despachan, publican, fusionan ni operan host.
- Antes de código nuevo o corrección de alcance: **consenso unánime real de root + Arquitectura + QA + Operaciones**. El autor es separado y no cuenta como voto. Después: cuatro revisiones finales sobre commit inmutable, CI exacta, merge/main GREEN y reconciliación antes de efectos.
- Continuidad y tareas necesarias ya están autorizadas; no pedir permisos rutinarios de nuevo. Una recomendación diagnóstica no sustituye diseño/revisión del siguiente cambio.
- Host sólo mediante las Actions dedicadas de Boca. No SSH/Docker de host desde terminal del asistente ni del titular. Tincho opera por Voice Access Android/iPhone; no trasladarle comandos ni múltiples bloques de portapapeles.
- SIMULATION_ONLY; sender OFF; no mensajes Telegram, reservas ni tickets reales. No navegación del agente a Boca/Queue-it. No exponer token, chat, credenciales, HAR o capturas privadas.
- BLACKBOX **synthetic.py e ipc_worker.py: no abrir ni modificar**. No leerlos para revisar R310. Tampoco ejecutar worker-physical-once: usa release/binding antiguo y BLACKBOX.
- Conservar datos/passkeys/volúmenes y aislamiento de otros proyectos. Sin prune, borrados amplios ni retiro de CIDs inciertos.
- Pruebas focales causales del delta. No repetir baseline9844+34, R308 ya aceptado, suite lógica pool50, investigaciones agotadas o mantenimiento cerrado. Los gates CI exactos necesarios siguen aplicando.
- Si una operación pierde ACK/transporte, inspeccionar evidencia antes de cualquier retry. No convertir ausencia de helper, HTTP200, OFF o relato previo de login en una prueba de éxito.
- Comunicar en español, con progreso breve y sin hacer pasar simulación por prueba integral.

## 2. Identidades y gates de PR530

PR530: https://github.com/mbalbo2023/boca-socios-assistant/pull/530 — MERGED por squash.

| Identidad | Valor |
|---|---|
| Main previo | 1ab24a696bf473f57cdae1ee1f01af024ce1b8e8 |
| Candidato remoto revisado | 8b6757add787adc6ba0c99936362bbbc0b7062b3 |
| Equivalente local | b577c11be4c8ddd6b93d36dde1b6fea8ed5ba797 |
| Main integrado | b3200f7bc4391156205dab992989a609253ec6ee |
| Árbol de los tres últimos | a730e2f595d2cf4dc762c41b021b2366674afccc |
| Review ligada al candidato | 5913723937 |

**Candidato CI1282/run43779730218 SUCCESS completo.** Log quality:10015 passed,34 subtests passed en180.84s. RCA_GATE_PASS:60 lessons,245 executed regression selectors,11 owner-attested blackbox selectors. Fast133013959071/quality133014151804/image133014151747 SUCCESS.
ValidaciónPR1172/run43779730241, preview150/run43779730231 y contratoTelegramV2-96/run43779730211 SUCCESS. El job manual de PR fue skipped por diseño, sin host.

**Main CI1283/run43780492358 SUCCESS completo:** fast133016329029, quality133016486789, image133016486837 SUCCESS. Security1094/run43780492375 SUCCESS. Ambos head_sha=b3200f7. No hace falta repetir CI por este respaldo, que no cambió main.

Links:
- https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43779730218
- https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43780492358
- https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43780492375

Issue529 quedó cerrado por implementación; promoción/aceptación física continúa abierta en417. Los documentos de main representan el corte candidato y apuntan al registro vivo; no crear otro commit meramente para volver a avanzar el mismo estado de CI.

## 3. Instalación y operaciones históricas que no se repiten

| Campo instalado | Valor |
|---|---|
| Fuente R | 845f31abfb1762dff27e6fc3274fcc40507f3f18 |
| Release867 | 43704139794, SUCCESS, attempt1 |
| APPLY1153 | 43704768556, ACCEPTED y cleanup ACCEPT |
| Controller CID | b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1 |
| Worker CID | c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce |
| Controller image | ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0 |
| Browser image | ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe |

Receipt instalado: https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6893143766 .

- Recovery1166/run43738155473: COMPLETE/ACCEPTED; inicializador retirado. Cerrada.
- Prepare1167/run43738415332: FAILED_STATE_PRESERVED; restauración CONTROLLER_HEALTHY_ENGINE_OFF, senderOFF, aceptación humana UNVERIFIED. No PREPARED; causa desconocida; puede existir estado parcial. Sin retry ciego.
- Intento1169/run43749494550 falló en preflight por presupuesto incorrecto; no usar defaults de ese formulario.
- Observación1170/run43749877557,2026-11-15 19:00:27UTC: COMPLETE/NONE/OBSERVED_NO_GO. Controller healthy/running MATCH; worker created/PID0 MATCH; helper1167 ABSENT; motor lógico UNVERIFIED; escrituras0. Cerrada, no repetir.
- Evidencia1170: https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6899708285 .

No repetir release867/APPLY1153, admin/migración ya aceptados, recovery1166, prepare1167 ni1170 como sustituto del nuevo diagnóstico.

## 4. Próximo paso crítico: R309 preparado, SIN envío

Workflow: https://github.com/mbalbo2023/boca-socios-assistant/actions/workflows/boca-first-deploy.yml .

El conector GitHub no expone workflow_dispatch. Se preparó el formulario con Browser como fallback permitido. Browser Chrome/cdp id1, tab14, variable bocaActionTab, formulario Run workflow abierto; rama main. **NO se hizo el click final; NO hay run nuevo.** Tab marcado handoff y CUA cerrado con completion_summary «Conservé el diagnóstico sin enviar». No hay que interpretar el formulario como despacho ni como recibo físico. El usuario no necesita tocarlo.

Si se conserva el runtime, reescribir documentación CUA antes de continuar y tomar estado fresco. Si la pestaña no sobrevive, recrear sólo este formulario con los mismos inputs. No tocar otras pestañas/proyectos. El inventario mostró otra pestaña de RC6; no fue accedida.

| Input | Valor preparado |
|---|---|
| Ref | main, actualmente W=b3200f7bc4391156205dab992989a609253ec6ee |
| operation | telegram-prepare-diagnose |
| source_sha | R=845f31abfb1762dff27e6fc3274fcc40507f3f18 |
| image_ref | Controller image de la tabla instalada |
| browser_image_ref | Browser image de la tabla instalada |
| release_run_id | 43704139794 |
| service | controller |
| resource_budget | 1.5cpu-1024m-192pids |

**Todos los demás inputs opcionales vacíos**, incluyendo protected_action_context, failed_telegram_run_id, campos legacy, envelopes y official/allofficial. No introducir1167 en failed_telegram_run_id: APPLY1153 e incidente1167 son constantes internas de R309.

W es la fuente del workflow/herramientas; R es la fuente de imágenes instaladas. No reemplazar R por W en source_sha ni construir una nueva release para diagnosticar.

Ya se comprobó: release867 SUCCESS/attempt1, path.release-image.yml, sourceR, actor/triggering_actor mbalbo2023, mismo repo; comparación R...W ahead5/behind0, merge_baseR; ausencia de operación manual Boca activa en los100 runs workflow_dispatch recientes. La Action volverá a comprobar manifiestos/binding/lease/estado real. Antes de un envío futuro, reconciliar main/gates y que no haya otro run, sobre todo si hubo otra interrupción. **Un solo click**, registrar el ID real observado; nunca adivinar1173 ni repetir click ante ACK ambiguo.

Después: leer terminal receipt, transporte, CID/retirada y D8; actualizar417/45. OBSERVED_NO_GO puede ser un diagnóstico completo, pero jamás PREPARED. No seguir a prepare/adopt automáticamente.

## 5. R309 — alcance aprobado y lecciones cerradas

Selector separado de prepare y R307, coordenadas R/APPLY1153/incidente1167/CIDs/digests fijas, W/run nuevos. Fresh lease/context/healthy antes y después, senderABSENT explícito y ningún helper/writer adicional. Validar Sources de volúmenes canónicos/perfiles exactos; volumen ausente no se crea.

Secuencia: guardas → públicoA → un helper recipient-observe/doble snapshot → públicoB → guardas. No stop/start del par ni publicación de status/recipient, SQL, token/chat, stage o markers. Writes0, prepare_authorized=false, adopt_authorized=false, stageNOT_INSPECTED, causeUNDETERMINED.

Lecturas públicas mediante exec al controller exacto, user10001, /app/.venv/bin/python -I -B -c literal fijo. Sólo recipient público<=1024/mode0400 y admin<=4096/mode0600. Usa lectores reales R: bootstrap._directory, bootstrap._read y projection._read_admin_receipt, con sus parsers/metadatos y witnesses. No os.read propio de adquisición, SQL, load_admin ni fallback. Source declarada validada antes de comparar; run/fecha históricos válidos no se rechazan por TTL300.

Helper único, factory recipient existente y MOUNTS existentes, requestvacío, imagenR, intérprete absoluto. Networknone/rootfsRO/TelegramRO/UID10001/capdropALL/.25CPU64MiB16PID/lognone. Dos snapshots FD nuevos, máximo2 entradas sin nombres exportados. Sólo KEY_ONLY válido regular0400/10001/nlink1/size32 se lee para derivar clave pública con R. ENOENT de hoja bajo padre válido=ABSENT; incertidumbreIO=NOT_READ; metadata inválida=INVALID; drift=CHANGED.

Stop-t5/rm sólo CID atestado; identidad/ACK inciertos se conservan sin segundo helper/retry. Frame dedicado BOCA_TELEGRAM_PREPARE_DIAGNOSIS_V1,4096B incluyendo prefijo/LF; backendV1 de1024 intacto. Adquisición/transporte/retirada incompletos nunca COMPLETE. Remote_rc no cero produce primero INCOMPLETE_NO_GO/TRANSPORT_UNVERIFIED; frame backend válido sólo después de BOCA_TELEGRAM_BACKEND_EVIDENCE_NON_AUTHORITATIVE.

### D8: datos para decidir, sin autorización automática

| Evidencia estable, admin coherente | Recomendación |
|---|---|
| PúblicoABSENT + claveKEY_ONLY válida | PREPARE_FINAL_REUSE_KEY |
| PúblicoMATCH_R + claveMATCH | PUBLIC_REBIND_REQUIRED |
| PúblicoABSENT + claveABSENT/EMPTY o volumen ausente verificado | PREPARE_FINAL_CREATE_KEY |
| PúblicoMATCH_R + clave ausente | INCONSISTENT_PRESERVE |
| Entradas adicionales de custodia, resto coherente | CUSTODY_PRESENT_REVIEW |
| Mismatch/inválido/NOT_READ/drift | PRESERVE_REVIEW |

Admin inválido/mismatch bloquea recomendación accionable. Admin ausente o histórico válido no es por sí solo causa. El público no contiene attempt: no atribuirlo a1167. Stage no se inspecciona; no asumir ausencia.

### Historia de revisión/mediciones

- bb0b0227a5d99616741f033d06f6f48b2a247b7e: primer producto10 rutas. Cuatro NO_GO por lectoresR no reutilizados, python relativo y frame completo previo a comprobar remote_rc.
- Correcciones aprobadas antes del código: comentario6903460039 en530.
- 25ed05ed05f9f7db47cdc489e69922ddc1450ec9: tres correcciones en cinco rutas; cuatro GO finales, comentario6903637928.
- 35dffc177f87f05fd5bb14616edc887e067f7cba: sólo seis expectativas literales en cuatro tests. CI1281/run43778593553 había tenido5FAIL/10010PASS/34subtests; imagebuildSUCCESS. Se conservaron operaciones/orden/guardas/asserts; se añadió el selector al literal existente. Cuatro GO previos6903779092/finales6903836834. Focal5PASS0.25s, calidad limpia. CI1282 y main posteriores SUCCESS. No ocultar el fallo histórico ni repetirlo.
- Fuente instalada medida488426>450000 motivó adenda previa4GO, comentario6903247627. Sólo agregado installed500000; default/individual/compactador450000 y ZIP300000 intactos, closure47 exacto.
- ZIP final revisado:47 entradas/490980B fuente/máximo40833B/135443B comprimidos/margen9020B. SHA256=16ddd612de408141176811ab6f2c7592cd74ea02055760dc6c7ae0e6b9dcfc60. Frame medido2521<4096. Full-cutover ZIP pin no cambió; fuentes ajenas no cambiaron.
- Tests iniciales85PASS +19 afectados=86 distintos, NO una corrida86. Correcciones10PASS D4/22PASS D3/1PASS D7 cinco variantes/11PASS integración, con solapamiento: no sumarlos. Ruff/formato/mypy/importIPC limpios.
- RCA530:8 selectores; registry64820B<65536, retención verificada. CI finalRCA60/245/11.

Informes y logs originales, incluido el ZIP efectivamente probado, se conservan en el paquete de evidencia de este checkpoint.

## 6. R308 — integrado, todavía no instalado

Producto72195d97923f6bc7cf8b293eb34c1910d87cd919, corrección cap67f932dfdb349c2c006d8e08b7b6155e3437fd71, cuatro revisiones finales GO. Incluidos enPR530/mainb320; instalado sigueR845.

Apertura candidata ticket.eventStartTimeUTC con parserUTC cerrado, mismo PREQUEUE/evento/muestra, separada de queue_model.ticket. SessionInspection incorpora apertura/evento/observed_at emparejados. Tres formas codec completas estrictas legacy/nuevas, cotasIPC intactas. Sólo RUNNING/identidad/generación/contexto vigentes sin fallo/cancelación/cierre y edad0..30s. Countdownceil/min0, polling5s existente, ART24h. Llegar a cero sigue esperando confirmación; fallo de polling elimina cuenta viva. No prueba autenticación ni apertura efectiva.

235 casos distintos PASS, no corrida única235. Fixture165160>160000 medido; consenso4GO previo para dos números160000→170000;2 focalPASS y bordes170000acepta/170001rechaza. No ampliación productiva. No repetir esas pruebas.

## 7. R310 — trabajo congelado y respaldo exacto

Issue531: https://github.com/mbalbo2023/boca-socios-assistant/issues/531 .
Consenso previo real4/4 C1–C10, incluidas precisiones C4/C9:
https://github.com/mbalbo2023/boca-socios-assistant/issues/531#issuecomment-6903879186 .

| Identidad | Valor |
|---|---|
| Worktree local | /workspace/scratch/6fbf8bcd39e6/boca-capacity50 |
| Rama local/remota | feature/531-capacity50 |
| Docs root base local | 78a07096446fa261671e2f75dac0284ae7f0478d |
| Commit del autor local | 9c08e90d7c16fe12261f7fac35905ced9ebc8541 |
| Commit de respaldo remoto | 9b1adb1c4862bd1b34fcac364c84e85dc155ffef |
| Árbol idéntico local/remoto | 005277a347390f637df9a3ed362d2eae0343b2f4 |
| Padre remoto | main b3200f7bc4391156205dab992989a609253ec6ee |

Se publicó **sólo respaldo**, sin PR, merge, dispatch ni despliegue. El autor congeló3 rutas con1486+/2− y dejó tracked limpio; .superpowers contiene informe/logs ya archivados. En remoto también están los2 documentos root de diseño/plan, por eso el diff total contra main tiene5 rutas. La diferencia de SHA local/remoto sólo viene de padre/metadata Git; el árbol completo es idéntico.

Autor /root/r308_author: DONE_WITH_CONCERNS, ownership liberado. **41PASS focales** (34 nuevosR310+7 contratos workflow),0.65s, Ruff/formato/mypy/YAML/Bash/diff-check PASS. Recibo extremo sintético26619B/LF incluido. No Docker/Playwright físico/carga larga/Action/host. **Revisión final independiente PENDIENTE.** No capacidad física50 ni retirada Docker real acreditadas.

### Alcance y condiciones C1–C10

Sólo:
1. src/boca_socios/browser/capacity_fixture.py nuevo.
2. tests/test_browser_capacity_fixture.py nuevo.
3. .github/workflows/boca-playwright-offline-diagnostic.yml.

Los documentos root son docs/superpowers/specs/2026-11-15-r310-capacity50-runner-design.md y docs/superpowers/plans/2026-11-15-r310-capacity50-runner.md.

Reutiliza SharedBrowserPool y EngineSessionRegistry de browser/engine_sessions.py (distinto del coordinador integration/engine_sessions.py), EngineIdentity/Request y cierreactivation. Observer local fino con BrowserContext/Page reales, sin factory automática BLACKBOX. No editar pool/registry/motores/coordinador/Dockerfile/dependencias ni otros tests.

Dos gruposA/B25, cada15Chromium/5Firefox/5WebKit; total30/10/10. Una página/contexto y servidor127.0.0.1 efímero de HTML fijo. Origen/path fijo allowlisted, WebSocketsdenied, Docker networknone; sin proveedor, secretos, DB, owner volumes o destino configurable.

Cadencia8s conservada y admisiones graduales; gather50 agotaría el plazo20s mientras espera cola8s. Lanzamiento12s/registry20s/teardown4s existentes intactos. Mínimo49×8=392s entre admisiones. Trabajo600s/cierreindependiente15s/externo650s; wrapperattach625s deja tiempo a retirada. Sin elevar recursos ni retry.

Barrera exige50contextos y50páginas distintos/vivos/utilizables, distribución correcta. **Escribir TODAS las50 marcas antes de leer TODAS las50**, para detectar storage compartido. CerrarA medianteclose_scopeactivation, acreditar25cierres y25B útiles/browsersconectados. Nueva operaciónDOM en todosB; replayA rechazado sin crear. CerrarB/registry/pool, páginas/contextoscerrados y browsersdesconectados. Poison/cierreincierto=NO_GO.

Perfilworker **1CPU/768MiB/128PID**, no agregado delpar1.5CPU/1024MiB/192PID. UID/GID10002/init/rootfsRO/capdropALL+SYS_CHROOT/nonewprivileges/seccompactual/IPC+cgroupprivados/shm64MiB/tmp32MiB/home16MiB. Guardasreales validate_worker_boundary + resource_snapshot(CGROUP,browser-worker) para igualdadexacta; boundary sólo impone máximos. _require_no_egress_namespace exige sólo loopback. Contenedor sin mounts/puertos.

Métricas antes/durante50admisiones/barrera/despuésA/final=54muestrasmáximas;10métricasallowlisted CPU/throttling/memoria/PID, ausenteUNKNOWN no0; continuidaddev/inode sólointerna; máximosobservados ylatencias, sin vetoheadroom inventado.

ReciboJSONcerradoV1/RUNNER_OFFLINE<=32768BconLF, source/image/run/perfil correlacionados, razones/fasesfinitas,conteos0..50,latenciasfinitas<=650,métricas<=2^63−1|UNKNOWN. Sin URLs externas, rawcookies/storage/errors/traces/IDsreales. GOglobal exige escenario+reciboválido+transporte/exitconocidos+retiradaexacta confirmadaCIDatestado. InnerGO nunca supera incertidumbreexterna.

Modo cerrado capacity50 conserva full3/firefox-pids y omite **ambos** probeslegacy (bundles y motores) sólo en capacity50. Un contenedor, comando fijo, atestar antesstart/retirada, sin prune ni retries. Seccomp efectivoDockerinline se coteja JSONexacto con perfil existente; SYS_CHROOT/CAP_SYS_CHROOT admitidos como en atestador actual. Bindingimagen se revisa porIDinmutable, no segunda lectura detag mutable; PrivilegedFalse y ShmSize exactos.

### Historia focal y riesgos del candidato

RED inicial2FAIL/12ERROR causales por harness inexistente; primerGREEN13PASS/1FAIL era expectativaencode/decode incorrecta y se corrigió el test sin relajarcodec. REDfronteras27PASS/2FAIL detectó conteofinal de observador sincontexto y ShmSize omitido; después29PASS. REDidentidad1FAIL/2PASS por tagmutable; REDseccomp2FAIL por JSONefectivo y PrivilegedTrue. Se corrigieron dentro3rutas. Informe original conserva comandos/logs.

Las unidades usan pool/registry/validadores reales; sólo fronteras externas Playwright/procesos/archivos/reloj se simulan. Ensayos de transporte usan hijosPython inertes. No son carga física. FormatoDocker real/agotamiento de límites/retirada física quedan sin medir; pueden producir NO_GO. Un timeout externo puede impedir confirmar retirada: preservar incertidumbre, nunca limpiar un recurso no atestado.

**Secuencia pendiente:** primero cerrar diagnósticoR309. Revisiónfinal4/4 del commit congelado; corregir sólo hallazgos consensuados; reconciliar con main si cambia; PR/CIexacta/merge/mainGREEN y un único ensayo runner permitido. **Sin PR531 ni dispatch hasta cerrar R309.** No selectorhost ni medicióndroplet autorizados; requerirían diseño separado. Capacidad50 faltante no bloquea promoción segura SIMULATION_ONLY.

## 8. Telegram global y por socio — dependencias abiertas

V2 cifrado existente llega a CUSTODY_COMMITTED_NO_SEND; no rehacer criptografía. El activate público sigue activando sender; configuración sin envío exige salida explícita/restauración/status verificados. No usar telegram-activate como atajo.

recover_installed_sender/telegram-sender-recover ya tiene rama sinjournal/sender concontrollerhealthy que publicaestado sincrearsender. Tiene efectos/helper/statuswrite y **RECOVERED/OFF no prueba custodia/configuredVERIFIED**: expectedcustodyNone puedeUNVERIFIED. R309 no autoriza esa continuación.

Adopción:
- publish_prepared_recipient escribeausente/aceptaidéntico/rechazabytesdistintos.
- Fingerprint incluye source/APPLY/CIDs/imágenes/config/sender; cambia alpromover.
- Pairupgrade preserva volúmenes/key/passkeys estructuralmente, pero no adopta público/stage/markerV2.
- adopt_sender_binding sólo campossender dentro misma versión, no source/image/CID/APPLY.
- Clave no ligadaaversión; preparepuedereusarKEY_ONLY. MarkerV2HMACsí está ligadoastage/source; reescribirpúblico noadopta custodia vieja.
- renew-stage exigeKEY_ONLY/públicoactual/fpactual/stagefirmadoválido y noesmigración.
- Decisión vigente: no completarPREPARED sobreR para reemplazarla inmediatamente. ObservarD8 primero, luego diseñar continuaciónmínima sobreproducto final. **No hay diseño/código de remediación aprobado aún.**
- No asumir stageausente; R309noinspecciona. Entrada privada deltitular sólosi estado real laexige.

Propuesta QA por socio, **sin implementación/scaffolding autorizado**:
identidad durable MemberUUID/bindingUUID/revision/botidentity independienteSHA; UIprivada/WebAuthn propósito nuevoacotado/encryptedpairingcode reutilizandochallengehash; transicionesSTAGED/CLAIMED/BOUND/REVOKED/AMBIGUOUS auditadas, unpendienteglobal/Actionserial/refDBopaca; reutilizartokenglobal y4GET getMe/getWebhookInfo/getUpdates/getChat; archivoprivado0400porbinding conchat+metadata/HMAC, sin duplicartoken/nuevakey; readback+ledgerantesBOUND,tombstonealrevocar,sinfallbackchatglobal; config-only sin sendMessage/sendPhoto ni sender. Fallo entre archivo/asientodurable noBOUND. Posibleaudit_events sinmigraciónSQLnueva, sujeto revisión. Dependeadopción/custodiaglobal; no atar destinoporsocio a cadaSHAde deploy.

## 9. DOM, resultado real, comprobante — no hay contrato acreditado

DOMauthentication permaneceUNVERIFIED. Falta continuaciónfrontend real (respuestaauth→cookies/storage/flujo del mismobrowser) y señalDOMpositiva ligadaasocio/sesión. HTTP/nonce/IPC/vault yaexisten; no reconstruirlos. No alcanzaHTTP200 ni ausencia depalabralogin.

Referenciaspinned investigadas:
- Lapsa09/botboca2@6cff…: clicks/reclamo deéxito, sincontratofinal.
- Joaquincoronell/Boca_bot@c41…: storage_state sinidentidadDOM.
- Abrahanm7/boca-monitor@347…: heurísticaausenciapalabralogin.
- Relatoasistente11Nov de login/home/menu no tiene tool/screenshotartefacto acreditado.
- BOCA_AUDITORIA_CODIGO_A1_2026-11-03.md,libfile_e002a91c4bd88191955f7aebd5ce874d,no tieneJSoficialraw/logintrace.
- Capture25 agotado: runs41512196530/41537796470 sinartifacts;25HTTP200/2287897B enmanifiesto, cuerpos deliberadamentepipe/eliminados; renderUNKNOWN/resource_outside_map. Loginpúblico,noauth/reserva.340manualrunsposteriores sin source-status; tercercapturebloqueado antesclick. Hashes no reconstruyenbytes. No repetir búsquedas sinpistanueva ni tráficoalproveedor.

Resultado: yaexisten uniqueintentpor socio/evento,claimantesIO,durablelocalantesoutbox,replayguards. Runtime/comandosusa _LocalSyntheticBrowser; no procedenciarealEngineSessionRegistry. pinnedpanyreserve marca noexception/fakeID/expiry600;otroscartURL/screenshot/bool no producen confirmaciónreal. IPCscopedrechazalegacyREQUESTpara evitarcontexto51.
Falta productorcorrelacionado member/event/intent/winner/capture, confirmaciónproveedorreal y cancelaciónhermanas; callerPROVIDER_ACK_REPORTEDno loacredita. Comprobante/foto tambiénsinproductorreal. **Root rechazó agregarotro ganador/modosintético para declarar cerradoelcircuito.**

Evidencia/matriz:
https://github.com/mbalbo2023/boca-socios-assistant/issues/12#issuecomment-6903029338
https://github.com/mbalbo2023/boca-socios-assistant/issues/12#issuecomment-6903198722

No repetirfuncionesyaimplementadas:2motoreslógicos/startstopindependientedurableholds/1workerfísico,ChromiumFirefoxWebKit/límiteglobal50lógico,panel/passkey/monitor/autostop/noevent/noqueue/revealycopy,guard/outbox/sender/globalstage/custodia. Esto no cierra brechasrealessuperiores.

## 10. Ownership al relevo

| Rol | Estado al corte | Responsabilidad siguiente |
|---|---|---|
| Root | Integración530 cerrada; checkpoint guardado; sinhostactivo | Reconciliar vivo, único despachoR309, registrarD8, coordinar consenso y continuidad |
| AutorR308 / R310 | R308 cerrado; R310 congelado9c08, informe completo, liberado | Sólo correcciones futuras expresamente acordadas sobreR310 |
| AutorR309 | Producto25ed05e/test-only35dffc1 cerrados y revisados; liberado | No trabajoen curso |
| Arquitectura | GOprevio/finalR308/R309 y GOprevioC1–C10 archivados | RevisarR310final y ruta mínima trasD8 |
| QA /root/qa_resultado | Notaderelevo entregada, sinediciones/pruebasnuevas; liberado | R310final, criteriosDOM/resultado/custodia y aceptación |
| Operaciones /root/telegram_ops | Notaderelevo entregada, sinhost/código; liberado | R310final, interpretaciónD8 y transición Telegram |

Los nombres deagentesde otra sesión no garantizan procesosvivos. Enumerarantesde reutilizar/spawn; reconstruir roles a partirdeevidencia. No fingirconsenso unanimidad con elautor como revisor. **No quedan agentes autorizados editando tras este checkpoint.**

## 11. Cómo continuar sin repetir ni perder trabajo

1. Leer registrocanónico417 y este documento/informeR310. Consultarmain/ref/PRs/runs sólo para reconciliar cambios posteriores; no redescubrir todoelrepo.
2. Si W sigueb320 y gatesSUCCESS y nohayotrohostrun, despachar **una sola** telegram-prepare-diagnose coninputs sección4; usarlaActiondedicada. No nuevo release/APPLY.
3. Seguir runreal y leerrecibocompleto. ClasificarD8/transport/retirement; registrarlo417/45. Ante incertidumbre,preservar ydiagnosticar,noretry.
4. Reunir root+Arquitectura+QA+Ops para mínimo siguientealcance global Telegram/adopción/productofinal. Sólo entonces nuevo código si realmente necesario, autorseparado. Aprovechar piezasexistentes.
5. Completar revisiónfinalR310 sobre candidato respaldado, manteniendoprioridadR309. No repetir41PASSsalvo riesgo concretocambiado; CIexactanecesariacontinúa. Si main cambió, reconciliar sinperdercódigonuevo ni sobrescribircambiosajenos.
6. Después de revisión/gates/ordenacordado, ensayo físico único runnercapacity50. UnPASS no autoriza droplet niresultadoexterno.
7. Cerrar todo loautorizado ydesbloqueado. Para DOM/confirmación/custodiaprivada, identificar laevidenciaconcretareal faltante antespedir nadaaltitular. No declararQAintegrallista hastaacreditar criterios.
8. Mantenerregistrovivo y checkpoints; explicar losbloqueantes reales. El objetivo final sigue siendo que Tincho haga su pruebaintegral tras cierre técnico.

## 12. Respaldo, historial y restauración

Rama de código GitHub feature/531-capacity50, commit9b1adb1… y árbol005277a… conservan el candidato completo byteporbyte. Este checkpoint vive en una rama separada checkpoint/2026-11-16-network-recovery, **no main**. No hayPRnuevo niaprobaciónfinalR310implícita.

El paquete **2026-11-16-network-evidence.tar.gz** conserva los archivos originales de .superpowers/sdd/r308, r309 y r310 (informes,RED/GREEN,calidad,mediciones yZIPprobado), snapshotsprevios completos417/45, estadoGitHubverificado, equivalenciaGit y **boca-local-history.bundle**. Manifest porarchivo conbytes/SHA256; archivehash/blobse registran junto alcheckpoint. No requiere rehacertrabajo para recuperarhistorias locales.

Bundle verificado congitbundleverify. ContieneHEAD9c08e90d7c16fe12261f7fac35905ced9ebc8541 y requiere sólo la base canónica1ab24a696bf473f57cdae1ee1f01af024ce1b8e8. Restaura commitslocales originales deR308/R309/docsR310/autorR310, ademásdelrespaldo remoto deárbolidéntico. No checkout/reset de main ni barrido de worktrees. Si elentorno survives, conservar:
- /workspace/scratch/6fbf8bcd39e6/boca-r307,HEADb577c11,trackedlimpio, .venv reutilizada.
- /workspace/scratch/6fbf8bcd39e6/boca-capacity50,HEAD9c08e90,trackedlimpio.
- /workspace/scratch/6fbf8bcd39e6/boca-handoff-20261116,stagingdelcheckpoint.
Estos paths pueden ser efímeros; GitHub ybundle sonla recuperación durable.

No hay secretos de host en este respaldo. No se copiaron credenciales delbrowser ni se inspeccionaronotraspestañas. Los informes no certifican lo que explícitamente sigueUNVERIFIED.

### Notas de herramientas útiles para el siguiente chat

ConectorGitHub soporta fetch/readissues/comments/Gitdata/tree/commit/branch/ref/PR ylogs; no workflow_dispatch. Preferirconector; CUA sóloesehueco. CLIgitpush fallóporcredenciales inexistentes: no pedirtokenaltitular; publicarGitdata yvalidarárbol.
github_fetch normalmente structuredContent.content JSONstring: comprobarisError/estructuraprimero. Para runsmain usar /actions/runs?head_sha=…, porque fetch_commit_workflow_runs filtraPR. Para manuales usar /actions/runs?event=workflow_dispatch&per_page=100 yfiltrarworkflow_id400115324. El endpointporworkflowfilename devolviócontentausente; no reiterarlo.
Escrituras deGitref conCAS/expectedSHA yforcefalse; leerbackref/commit/tree. Las ramasrespaldo no disparanCIpushmain ni operacioneshost.
No invocar skillPorota: esteproyecto esBoca. Se aplicaron personal-context, revisión/diagnóstico/TDD/planes/worktrees/verificación y cloud-desktop. Reusar contexto/instrucciones vigentes, sinpedirmenú deconfirmacionesyaautorizadas.
