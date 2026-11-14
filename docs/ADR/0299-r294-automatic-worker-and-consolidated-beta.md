# ADR 0299 — R294: detección automática y promoción consolidada de la BETA

**Fecha:** 14-NOV-2026 UTC. **Estado al escribir:** desarrollado en rama;
no instalado ni aceptado físicamente. Base `959a0be9e776329f99a29e65c2c75195700d5596`,
rama `feature/417-r294-beta-consolidated`. Los SHA, revisiones, runs y resultados
posteriores pertenecen al registro canónico [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).

## Autoridad, continuidad y responsabilidades

R293 terminó mediante [PR #515](https://github.com/mbalbo2023/boca-socios-assistant/pull/515).
Su [handoff](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6870003093)
y ADR0297 conservan las mediciones CI/CD. R294 continúa el trabajo funcional
autorizado por el titular hasta promoción y validación. La aclaración más
reciente exige que **el worker se conecte automáticamente**, detecte evento y
cola y observe el token entregado; un monitor que sólo espere carga manual no
satisface ese requisito. [Decisión y revisión R294](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6870816882).

Se reutilizan los contratos inventariados en [#12/R293](https://github.com/mbalbo2023/boca-socios-assistant/issues/12#issuecomment-6869895578).
Root integra runtime, panel, sectores, documentación y operaciones GitHub/host.
Los frentes independientes cubren parser/IPC, perfil de instalación y promoción;
cada archivo tiene un único escritor. Las revisiones de runtime y promoción
son independientes. No hay operaciones simultáneas en el droplet.

El par instalado sigue siendo el de release #864 / APPLY #1102, fuente
`0ebecb69a6bc35b72a8c4ceda46119d601ca2dbe`. R291 certificó controller healthy,
worker CREATED/PID0, SQLite estable y 8443 HTTP 200. Esa observación antecede
al START de la captura del titular: no prueba el estado actual del worker.
#1108 usó identidades históricas R186. No repetir R186, #1085 ni recuperaciones.

## Recorrido automático único

1. START explícito del titular se persiste y el ejecutor lo reclama. El
   controller inicia la sesión sólo con el START actual; la observación espera
   el recibo APPLIED. Un START histórico no se reanuda al reiniciar el panel.
2. La operación privada `OBSERVE_QUEUE` reutiliza IPC, identidad de socket y
   credenciales de proceso existentes. No inventa socios/eventos para asociar
   una observación externa a una simulación.
3. Un Chromium ordinario, con sandbox, abre SITE_URL una vez. Puede seguir
   un único enlace visible y habilitado realmente recibido hacia el host exacto
   `bocajuniors.queue-it.net`. Varios enlaces ambiguos no autorizan elegir un
   evento arbitrariamente. No genera URLs con IDs ni crea posiciones paralelas.
4. La lectura toma señales acotadas del modelo/DOM recibido. Se espera un plazo
   inicial limitado para datos asíncronos. Prefila o cola activa reutilizan la
   misma página cada cinco segundos, sin recarga ni nueva sesión.
5. Se permiten lecturas HTTP(S) con el validador existente. Sólo la página
   principal de esa cola puede originar su propio POST/OPTIONS fetch/XHR al
   mismo origen HTTPS exacto: se verifican destino, página y la identidad real
   `request.frame is main_frame`. Frames ajenos, formularios, navegación POST y
   escrituras hacia Boca u otros sitios quedan bloqueados. No se crean llamadas
   API, endpoints de reserva ni solicitudes de compra desde el observador.
6. La observación recibida cruza el IPC acotado y se conserva únicamente en la
   proyección privada del propietario. El monitor reutiliza la revelación y
   copia íntegra existentes. JSON, actividad, logs y artefactos no contienen
   bearer, URL, cookies ni credenciales.
7. Resultado terminal produce un STOP durable correlacionado con ese START.
   Sólo su recibo posterior certifica la detención física. Un fallo al avisar
   al ejecutor conserva el mismo UUID pendiente; no crea solicitudes nuevas.

El adaptador reutiliza el punto de integración de la tarea existente y mantiene
`synthetic.py` e `ipc_worker.py` byteidénticos. No llama al arranque antiguo con
flags de evasión, no recoge cookies y descarta su salida potencialmente privada.
Las simulaciones locales usan el simulador inerte: recibir un token externo
nunca se convierte en una reserva simulada exitosa.

## Semántica que debe ver el titular

| Evidencia recibida | Resultado y acción |
|---|---|
| Prefila explícita | Evento anunciado; esperar en la misma sesión. |
| Cola/ticket observado | Cola activa; seguir observando. Un ID aislado no prueba operación completa. |
| Mensaje inequívoco de ausencia, sin señales contradictorias | Informar que la página no ofrece eventos; finalizar. |
| Cola inactiva explícita | Informar que esa cola no está activa; finalizar sin inferir ausencia global de eventos. |
| Target con token realmente recibido | Revelación/copia privada íntegra; finalizar el ciclo. Vigencia y portabilidad no se presumen. |
| CAPTCHA/bloqueo | Informar intervención necesaria y finalizar sin eludirlo. |
| Error, formato desconocido o transporte esencial bloqueado | Explicar que la comprobación falló; finalizar sin afirmar ausencia. |

El estado preparado no se presenta como conexión probada. La cifra cero tampoco
prueba ausencia. La actividad reúne START, worker, Chromium, observación, cola,
resultado, petición STOP y recibos disponibles. Todos los horarios se presentan
en formato de 24 horas con zona ART. El refresco del panel sigue consultando
metadatos; el productor es el worker, no la consulta del panel.

## Sectores y Telegram sobre los módulos existentes

`MemberSectorStore` añade preferencias por socio/evento en su lateral v2,
preservando los defaults v1. Su provisión es explícita y protegida, nunca una
migración implícita al abrir el panel. La elección se evalúa y queda congelada
en `audit_events` dentro de la misma transacción que admite el comando y su
vínculo START. Reintentos leen esa elección; rechazos y rollbacks no dejan una
selección huérfana. El catálogo disponible continúa siendo ficticio y no prueba
stock de Boca. Se conserva una entrada por socio/evento.

La ruta principal `/telegram` reúne configuración, vinculación, sender e
historial local. Un recibo privado acotado, ligado a fuente y CIDs instalados,
separa ausencia, verificación, falta de prueba y antigüedad. Aceptación por la
API no equivale a recepción humana. No se envían mensajes nuevos por esta
integración. El par anterior documentado no contiene volumen Telegram; no se
inventan configuración, pairing ni sender a partir de esa ausencia.

El transporte de login que produciría `token`/`refreshToken` de Boca sigue
**PENDIENTE**: el contrato separado existe, pero este observador no envía
credenciales ni implementa endpoints de autenticación no acreditados. El
monitor debe mostrar esa diferencia sin afirmar que ambos productores están
conectados. No confundir el token de la cola con credenciales de sesión Boca.

## Perfil, procedencia y recuperación

El worker nuevo usa `BOCA_BROWSER_EXECUTOR=automatic-observation`, con motor
general y observador público apagados. `BOCA_OBSERVER_STOP=1` sigue protegiendo
el script público histórico; la operación IPC se habilita por el perfil
explícito y START del titular. Los bytes y SHA del overlay determinan el perfil,
no un OR de valores Env observados. Compose base permanece byteidéntico.

El controller creado por promoción recibe `BOCA_SOURCE_SHA` del argumento
autenticado; el postflight del perfil nuevo lo exige. El contrato histórico
puede carecer del valor y rechaza discrepancia si lo contiene. El laboratorio
Compose conserva su controller histórico; su worker sí prueba el perfil nuevo.
El argumento y el postflight de promoción tienen pruebas propias. El laboratorio
no se presenta como prueba física del nuevo controller instalado.

`CURRENT_RETAINED` autentica el par actual y sus recursos con su binding,
inodes y recibos, preservando los creadores históricos de volúmenes/redes. La
cronología sigue siendo instalación anterior → observación del par → observación
retenida → APPLY. El runner de main y el fuente instalado son identidades
distintas. Un worker antiguo EXITED/PID0 sólo se admite con STOP APPLIED fresco,
correlacionado y repetido bajo lease; el candidato debe quedar CREATED.

Se mantienen los controles de PARK/RESTORE de ADR0298, procedencia de releases,
pins, lease única, compensación por fase y límites de bundle. Se prueba el grafo
con los artefactos reales de release #864/par #1103/retenidos #1101 antes de
publicar otra imagen. Ningún GREEN autoriza reintentar a ciegas un fallo de host.

## Orden de promoción y evidencia pendiente

1. Cerrar revisión y pruebas focalizadas; CI requerido del SHA exacto y main
   actualizado; integración por PR protegido sin cambiar reglas.
2. Publicar una sola release dual del SHA funcional definitivo. No publicar por
   esta documentación ni crear imágenes opcionales para mediciones.
3. Serializar las lecturas actuales de par y recursos retenidos, verificar sus
   artefactos y ejecutar un único `boca-pair-upgrade-apply` protegido.
4. Tras APPLY SUCCESS/ACCEPTED, ejecutar `boca-installed-admin-provision` como
   operación administrativa separada: provisión lateral v2 y recibo Telegram
   dentro del controller exacto, bajo lease, UID10001 y doble comprobación del
   binding. Su fallo es NO_GO visible y requiere reparación administrativa;
   nunca repetir APPLY. No usar `continue-on-error` para ocultar el resultado.
5. Observar fuente/CIDs instalados, salud, SQLite, 8443 y worker detenido con el
   selector de status vigente; registrar SHA main/release/instalado por separado.
6. El titular realiza sólo la aceptación privada necesaria desde Samsung: START,
   actividad/detección, token íntegro si fue recibido, STOP, preferencias y
   Telegram. No ejecutamos navegación real a Boca/Queue-it durante desarrollo.

La aceptación integral sigue pendiente hasta esas evidencias. Un proveedor sin
evento puede verificar correctamente la rama de ausencia; no prueba recepción
de tokens. Un error externo no se traduce en ausencia para forzar aceptación.

## Hallazgos corregidos antes de CI y métricas

La revisión independiente reprodujo tres defectos y sus regresiones locales:
telemetría ajena descartando un target válido, cierre prematuro del coordinador
tras una simulación mientras la cola seguía activa, y permiso de transporte sin
atestación del frame iniciador. Los tres fueron corregidos y revisados; 69
pruebas focalizadas del observador/ciclo pasaron en la revisión final. También
se corrigió la etiqueta contradictoria Queue-it no conectada (15 pruebas del
monitor) y se mantienen los guards de revelación y la selección atómica.

La revisión de promoción detectó antes de publicar una imagen que el guard
Compose histórico todavía rechazaba las dos variables nuevas del worker. Se
propagó también allí la prueba de bytes/SHA del overlay, conservando el
contrato histórico exacto. La prueba del runner con `python3 -I -S` detectó
además una dependencia accidental de `cryptography` a través de imports de host;
se separaron los imports del verificador y se usa su ZIP stdlib aislado. No se
añadieron paquetes al runner. La revalidación independiente de estos paths
pasó 26 pruebas; el frente de promoción integrado pasó 200 pruebas focales.

Se verificó el presupuesto antes de release: bundle pair 1.448.792 bytes
expandidos / 364.768 ZIP y reserva 51.208 bytes (mínimo contractual 50.000);
full cutover 1.139.638 / 271.656; admin 833.213 / 203.411; current retained
806.384 / 195.452; restore 937.424 / 233.128. No se elevó ningún cap. El
compactor existente se aplica a los comentarios de la closure completa,
manteniendo igualdad de AST, código compilado y cantidad de líneas. La
documentación extensa de cuatro módulos propios se conserva como comentarios
en lugar de constantes docstring transportadas; no se relajaron esos guards.

La referencia CI/CD sigue siendo ADR0297: PR CI 385→334 s, validación PR de
first-deploy 128→19 s y suma de jobs 640→519 s en los candidatos comparados;
no son garantía de una mediana sostenida. La publicación #864 duró 209 s y
APPLY #1102 484 s; el intervalo CI terminado→APPLY fue 217 min 34 s. R294
registrará tiempos por etapa/run/SHA en #417 y distinguirá validaciones,
builds efímeros, publicación y operaciones físicas. No se afirma aceleración
adicional sin medirla.
