# Relevo de Operaciones — Boca Socios Assistant — 2026-11-16

## Punto de continuidad

Main remoto es `b3200f7bc4391156205dab992989a609253ec6ee`. Root informó CI1283 y Security1094 SUCCESS. Eso acredita el candidato de código y herramientas; no cambia la instalación del host.

El formulario de `telegram-prepare-diagnose` está preparado en la pestaña 14, marcada como handoff. **No se hizo el click final ni existe un nuevo run del diagnóstico.** Antes de cualquier despacho, root debe cotejar nuevamente el main revisado, sus gates y la ausencia de otra operación concurrente. Sólo root opera Actions/host.

R310 mantiene tres rutas congeladas por el autor y tiene pendiente la revisión final independiente. La revisión y el cierre del diagnóstico Telegram siguen siendo pasos distintos.

## Instalación real y evidencia cerrada

| Campo | Valor vigente |
|---|---|
| Source instalado R | `845f31abfb1762dff27e6fc3274fcc40507f3f18` |
| Release | 867 / run `43704139794` |
| APPLY | 1153 / run `43704768556`, ACCEPTED; cleanup ACCEPT |
| Controller image | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0` |
| Worker image | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe` |
| Controller CID | `b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1` |
| Worker CID | `c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce` |

Recovery1166 terminó ACCEPTED y retiró el initializer: está cerrado. Prepare1167, run `43738415332`, terminó `FAILED_STATE_PRESERVED` y restauró `CONTROLLER_HEALTHY_ENGINE_OFF`, sender OFF. No acreditó PREPARED; su causa histórica sigue desconocida.

Observación1170, run `43749877557`, terminó `COMPLETE/OBSERVED_NO_GO`: controller healthy, worker creado con PID 0, helper1167 ausente, engine lógico UNVERIFIED y cero escrituras. Esa observación histórica no sustituye las guardas actuales del diagnóstico.

**No repetir release867, APPLY1153, recovery1166, prepare1167, observación1170, admin ni migración.** No preparar otra vez a ciegas.

Fuentes canónicas de continuidad:

- [Checkpoint de issue417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6899119716).
- [Recovery1166](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6898002351).
- [Prepare1167](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6898066194).
- [Observación1170](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6899708285).
- [R309 / issue530](https://github.com/mbalbo2023/boca-socios-assistant/issues/530).

## Inputs exactos de la futura Action R309

Workflow `.github/workflows/boca-first-deploy.yml`, ref `main` correspondiente al W revisado. El workflow toma W de `GITHUB_SHA`; `source_sha` conserva el R instalado.

| Input | Valor |
|---|---|
| `operation` | `telegram-prepare-diagnose` |
| `source_sha` | `845f31abfb1762dff27e6fc3274fcc40507f3f18` |
| `image_ref` | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0` |
| `browser_image_ref` | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe` |
| `release_run_id` | `43704139794` |
| `service` | `controller` |
| `resource_budget` | `1.5cpu-1024m-192pids` |

Todos los demás inputs opcionales deben quedar vacíos, incluidos `protected_action_context`, `failed_telegram_run_id`, `legacy_release_run_id`, envelopes, pins legacy y campos oficiales. APPLY1153 e incidente1167 son constantes internas del diagnóstico; no deben introducirse en campos legacy.

Las guardas previas a SSH verifican main, release y manifests de ambas imágenes, linaje R→W, primer intento, owner/repo/ref y entorno protegido. El backend vuelve a comprobar lease exclusiva, binding, controller healthy, engine STOPPED, worker detenido, sender ausente y ausencia de otros helpers/escritores. No inferir esos estados de1170.

## Alcance y lectura del resultado R309

R309 es un diagnóstico nuevo con efectos Docker explícitos y acotados. No prepara, publica status, provisiona, adopta, migra ni detiene/inicia controller, worker o sender.

Lee público A, ejecuta como máximo un helper `recipient-observe` con perfil existente de recipient RO, lee público B y comprueba guardas finales. Usa `/app/.venv/bin/python -I -B -c` literal y parsers/lectores instalados en R. Los programas son fijos; no se admite un intérprete o programa arbitrario. Si el volumen Telegram está ausente de forma verificada, no se crea por montarlo.

La inspección de custodia usa dos snapshots con fd nuevo, no-follow y metadata acotada. Sólo `KEY_ONLY`, archivo regular, modo 0400, UID/GID10001, nlink1 y tamaño32 habilitan derivar el público dentro del helper. INVALID/EXTRA no habilitan lectura de bytes privados. Ningún byte secreto sale del helper. ENOENT sólo acredita ABSENT en la hoja bajo un padre ya válido; acceso/IO son NOT_READ; drift es CHANGED. No se exportan nombres de entradas, tokens, chats, markers, contenido privado ni excepciones crudas.

Sólo el CID exacto y atestado admite compensación `stop -t 5` seguida de `rm`. Si ACK, identidad o retiro quedan inciertos, se conserva la incertidumbre, sin retry automático. El recibo mantiene el CID alcanzado y los efectos conocidos.

El frame cerrado es `BOCA_TELEGRAM_PREPARE_DIAGNOSIS_V1 `, con máximo4096 bytes incluyendo LF. `OBSERVED_NO_GO` completo sigue siendo diagnóstico, con `prepare_authorized=0` y `adopt_authorized=0`; no significa PREPARED. Las escrituras de datos, custodia y status son cero. Stage queda `NOT_INSPECTED`. No se atribuye una causa histórica a1167.

Si el transporte remoto falla, la primera línea debe ser `INCOMPLETE_NO_GO/TRANSPORT_UNVERIFIED`. El frame backend puede conservarse sólo como evidencia **NO AUTORITATIVA**, con su CID/retiro; no debe quedar como afirmación principal completa.

### D8: interpretación útil para el siguiente diseño

Estas ramas son recomendaciones para una operación posterior sobre el producto final, no autorizaciones ni acciones del diagnóstico. Requieren observaciones estables y admin compatible.

| Estado observado | Recomendación posterior |
|---|---|
| Público ABSENT + clave válida / KEY_ONLY | `PREPARE_FINAL_REUSE_KEY` |
| Público MATCH de R/binding actual + fingerprint de clave igual | `PUBLIC_REBIND_REQUIRED` |
| Público ABSENT + clave ABSENT/EMPTY, o volumen ausente verificado | `PREPARE_FINAL_CREATE_KEY` |
| Público presente coherente + clave ABSENT | `INCONSISTENT_PRESERVE` |
| Custodia con extras | `CUSTODY_PRESENT_REVIEW` |
| Invalid, mismatch, NOT_READ o drift | `PRESERVE_REVIEW` |

Un admin ausente o histórico válido puede admitirse. Antigüedad mayor a300 segundos no invalida un recibo histórico: la frescura procede de las lecturas actuales. Admin inválido, incompatible o ilegible impide recomendar una continuación. Debe informarse su `observation_run_id` real. El público no tiene attempt; su presencia no demuestra que lo creó1167.

## Adopción, custodia y orden de promoción

La decisión acordada es **no completar PREPARED sobre R para reemplazarlo inmediatamente**. Primero se adquiere el estado D8; después se diseña y revisa la preparación/adopción para la imagen final del producto.

La brecha es real: `publish_prepared_recipient` admite archivo nuevo o bytes idénticos; un cambio de source o installation fingerprint entra en conflicto aunque la clave sea la misma. No existe una ruta acreditada de rebind público. `renew-stage` archiva stage con binding actual y no migra ese público. `adopt_sender_binding` sólo permite cambiar los campos de sender conservando el resto del binding. Marker y fence V2 también están ligados al source; la migración de custodia entre versiones no está resuelta.

`recover_installed_sender` puede omitir creación/arranque cuando no hay journal ni sender y el controller ya está healthy, y publicar status mediante la ruta existente. Sin embargo, `RECOVERED/OFF` no prueba custodia configurada VERIFIED cuando `expected_custody=None`; tampoco resuelve la adopción entre versiones. No usar recovery ni activate como atajo de configuración o como consecuencia automática de D8.

La configuración por socio queda en diseño pendiente de conocer custodia/adopción global. No se autorizó implementación de ese frente ni activación de sender o envío de mensajes.

## Evidencia de revisión y cotas R309

Operaciones dio GO final al arreglo `25ed05ed05f9f7db47cdc489e69922ddc1450ec9`, que corrigió lectores R reales, intérprete absoluto y degradación del resumen ante transporte incierto. También dio GO final al delta test-only `35dffc177f87f05fd5bb14616edc887e067f7cba`: cuatro archivos, seis literales, cinco tests afectados PASS según evidencia del autor. No cambió producto ni workflow con ese delta.

La última medición revisada del bundle fue47 entradas,490980 bytes agregados, entrada máxima40833 y ZIP135443 bytes; SHA256 `16ddd612de408141176811ab6f2c7592cd74ea02055760dc6c7ae0e6b9dcfc60`.

La adenda aprobada amplió únicamente el agregado installed a500000. Permanecen450000 para default, fuente individual, entrada individual memfd y umbral del compactador; ZIP300000. No aumentaron CPU, RAM, PID, entradas ni recursos del helper:0.25CPU,64MiB,16PID. La evidencia CI no acredita una ejecución física del diagnóstico.

Las especificaciones están en `docs/superpowers/specs/2026-11-15-r309-telegram-prepare-diagnose-design.md` y `docs/superpowers/plans/2026-11-15-r309-telegram-prepare-diagnose.md`.

## R310: guardas que deben sobrevivir al relevo

[Issue531](https://github.com/mbalbo2023/boca-socios-assistant/issues/531) recibió GO previo de Operaciones al alcance runner offline. La revisión final independiente del código congelado sigue pendiente.

El presupuesto efectivo del worker es **1CPU,768MiB,128PID**, no el agregado1.5CPU/1024MiB/192PID. El controller consume la otra partición:0.5CPU,256MiB,64PID. No elevar límites por el ensayo.

El escenario aprobado usa pool/registry reales,50 contextos y50 páginas distintos,30Chromium/10Firefox/10WebKit, dos activaciones de25, fixture local y namespace sin egress. Se escriben primero las50 marcas sintéticas y después se leen/verifican las50 para detectar almacenamiento compartido. Se conserva la cadencia8 segundos;600 segundos de trabajo,15 de cierre y650 de límite exterior. Recibo cerrado32768 bytes, un único CID atestado y retirado. GO global requiere escenario completo, recibo válido, exit/transporte conocidos y retiro verificado; cualquier incertidumbre es NO_GO y vuelve no autoritativo el recibo interno.

Sólo tres rutas, full3/firefox-pids intactos y sin host. El modo capacity debe excluir también los probes comunes que crearían CIDs adicionales. Deben usarse los validadores reales, incluido `_require_no_egress_namespace`; `validate_worker_boundary` comprueba cotas superiores y `resource_snapshot` la igualdad del perfil. Runner PASS no acredita capacidad del droplet. No reutilizar `worker-physical-once`: fija otro linaje y ejecuta BLACKBOX, sin entrada para este harness.

## Cierre de ownership

Ownership de Operaciones liberado. No dejé cambios propios pendientes ni ejecuté host, código o pruebas adicionales en este cierre.
