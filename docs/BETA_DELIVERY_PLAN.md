# Plan de entrega y aceptación de la BETA funcional

## Alcance y fuente de verdad

El dueño aprobó comenzar las recomendaciones del plan y mantener su avance en
GitHub. [ADR0056](ADR/0056-approved-simulation-beta-delivery.md) registra las
decisiones de esta etapa. La BETA objetivo es **privada y funcional en
simulación**, con **alta de socios obligatoria**; un controlador dormido sano
no basta. Este documento es un plan mantenido con las entregas, no evidencia
de funciones ya desplegadas ni un servicio automático de seguimiento.

El [plan inicial #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551577529)
fue una propuesta anterior. Su lenguaje de decisiones pendientes no revoca la
aprobación posterior de los frentes aquí registrados. El [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
registra autorización vigente, HEAD, decisiones y evidencia de cada cierre.
Revalidar esos hechos antes de actuar; no interpretar autorización del trabajo
como evidencia de éxito o permiso para operar datos reales.

[Autorización vigente ampliada](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
para completar la BETA sintética, Site conectado, Telegram y deploy validado
por Actions, sin reservas ni compras reales. El alcance anterior de preparación
queda como historial; ninguna autorización es evidencia de instalación.

**Decisión posterior 2026-11-01:** el panel Boca local en el droplet es la
interfaz principal de la BETA. Usa el puerto ya configurado
`127.0.0.1:8443` y forwarding privado desde la tablet; no se crea puerto
9000. El Site #113 deja de ser dependencia de aceptación de esta BETA;
permanece privado/sintético y su baja se posterga hasta validar el reemplazo.
Telegram conserva su gate propio, sin atribuir recepción a código integrado.
El [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6558572360)
registra la ejecución protegida 41310958281 sobre
`main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`: 8443 FREE
`reserved=no`, sin arrancar servicio ni instalar aplicación. PR #214/ADR0088
integró el origen exacto `https://localhost:8443` en
`main=8fdbec97262a525821eb87f3fbc27f1841a5d2ec`: CI 41312228362 y
scan 41312228548 SUCCESS. La [release protegida 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820),
intento 1 SUCCESS, publicó sólo la imagen
`ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
con manifiesto 13086161844 para ese SHA; no hubo pull ni instalación en el
droplet. Este cambio (#215/PR #216/ADR0089) incorpora en código un emisor
local de un solo uso, con pruebas sintéticas, no credencial física. La confianza TLS,
forwarding, WebAuthn Android/iOS y entrega privada del sobre siguen sin
prueba (#209). Una nueva HEAD tras este PR exige release propio antes del
host. Owner custody, instalación, aceptación y parada final requieren sus
recibos exactos por Actions.

**Corte de integración previo a esta actualización documental 2026-11-01:**
`main` `6d3007a3ca1dfdba428cb7595486b1166a1d02b6` incorpora loop persistente
#161, Telegram durable opt-in #162, stop-test #165, ciclo de vida local #164
y panel owner passkey #163, aceptación HTTP sintética #170 y entrypoint
TLS explícito #173, prueba de registro WebAuthn #174 y corrección
de lectura con schema Telegram0007 #176, paquete beta separado #171,
helper cifrado #178, cliente Site opt-in #179, custodia host #181 y RCA #196;
además RCA de comandos #187, preflight owner #189, worker Telegram #188,
probe sintético #190, `beta-install` #191, parada Telegram #194,
`beta-acceptance` #200, custodia cifrada Telegram #199 y fases protegidas
de migración/custodia posterior #203, prueba Bot API de un solo intento #204
y PR #205 de reconciliación documental, además del corte base descrito abajo.
La [publicación protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638) generó `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:ab0745a840e35a6d713fed14ec0761512fdc90284c133f2c321c9ffe2d3c9284`
para ese SHA y el manifiesto ID 13079654802; no instaló la aplicación.
Una modificación posterior de `main` necesita release propio antes de install.
[Estado actual y runs exactos](BETA_INTEGRATION_STATUS.md).
El Compose/primer install aún son dormidos y no hay aplicación en el droplet.
El stop-test protegido [#156/41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626)
emitió STOPPED, `containers=0` (ninguno detenido en esa invocación) y datos
preservados tras las pruebas de preparación. Verificó que no quedaran
contenedores Boca en ejecución; podría conservar contenedores ya detenidos.
No es evidencia de instalación BETA.
La custodia Site, `beta-install` y `beta-acceptance` están integrados en
código, sin dispatch al host; acceso privado y aceptación host requieren
pruebas propias. El Site privado v10 #113 publicó cola D1 sintética
desactivada y proxy/recibos fail-closed; existe release de imagen para el
SHA de corte; revalidar digest coincidente con la HEAD al operar. Faltan
bypass+HMAC host y E2E.
Telegram tiene worker, helper cifrado y fases host de custodia/prueba en código,
pero no tiene
bot/destino ni recepción
comprobada (#168). La [parada protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) observó
`ALREADY_STOPPED containers=not_queried data=preserved` sobre el SHA de corte.
Antes de otro uso se revalida el daemon y el main actual.

El [release protegido 41301618285](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41301618285)
publicó el digest `sha256:6f067e5078081760dec27f81d95792a4423ff9c1d9cb3bef19ef70dbfc8cf889`
para el corte #208 `58f57822e95da9574c0a9d5122607616da4a024a`,
con manifest 13082030761. Sigue siendo sólo una imagen: no se instaló BETA.
PR #208/ADR0086 integró la custodia cifrada de cinco archivos owner por
Actions, con 942 pruebas locales y smoke desechable del candidato
`465deba9456d9ace5a2cddbcdab25a5310f3d095`; no hubo efecto host.
Ese corte quedó histórico al avanzar `main`; cada HEAD final exige release
exacta antes de operar. Continúan pendientes
el alta física WebAuthn, origen/ruta HTTPS tablet, DNS/certificado y decisión
de acceso privado (#209); no inferirlos de la custodia.

## Base histórica comprobada de este plan

Punto de partida documentado: `4922e45b5e2e38242263b6ba10969a8190aa939a`,
después de #142. No se confunde ese baseline con una integración posterior.
[CI 41259139901](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139901)
y [scan 41259139886](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139886)
exitosos; 594 pruebas y RCA12/32 en ese corte. Los checks de una nueva entrega
se registran sobre su propio SHA; estas cifras no se trasladan a otro candidato.

El corte histórico de preparación fue `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`: incluye
#130/#128/#134, el análisis146, alta148, comandos149, preparación150 y pruebas
de composición152. [CI main41262581358](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262581358)
y [scan41262581422](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262581422)
verifican ese SHA; los cambios posteriores tienen checks propios.

En aquel corte, el runtime de `compose.yaml` validaba clave, inicializaba
esquema base y esperaba con engine=off; no servía panel ni conectaba
coordinador/avisos. Ese Compose conserva sólo el controlador sin puertos.
#128/#130/#134 eran candidatos separados en el corte inicial.
La primera integración incorporó #130 (coordinador durable opt-in), #128
(adaptador WSGI de lectura default-deny) y #134 (dispatcher sintético). Eran
componentes que entonces carecían de wiring runtime, listener, identidad real,
TLS y transporte externo. #148 agregó formulario/handler y sesiones de alta;
#149 integró el servicio de comandos durable. En ese corte ambos carecían de
servidor autenticado y wiring del runtime. El dispatcher conserva el límite de crash entre llamada sintética y
settlement: no prueba entrega exactamente una vez. La imagen y
smoke Chromium offline no prueban navegación Boca ni forman parte de ese Compose.
El Site #113 es una demo privada sintética; la versión v10 publicada incorpora
cola D1 desactivada y proxy/recibos fail-closed, aún sin conexión efectiva a
DB ni comandos.

La [preparación #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418) ejecutó
prepare-rootless sobre `6be606f83c5a6afe0ba7226abbca6a09276d1ca1`, attempt1, y terminó
SERVICE_READY: daemon propio creado/arrancado/habilitado, rootless/cgroupv2-
systemd/overlay2/data root privado y namespace Boca vacío verificados.
Application_database=not_accessed y application=not_installed: no se creó
SQLite, imagen/contenedor, volumen de app/clave ni clave. Capacidad informativa,
application_budget=not_checked; no prueba presupuesto del candidato BETA.
[Recibo y marcador DEPLOY en entorno protegido](https://github.com/mbalbo2023/boca-socios-assistant/issues/145#issuecomment-6551973756).
No reejecutar primera preparación: la configuración existente debe preservarse.

La inspección histórica98, sobre5c642b6d8bf5feac14aaf4a7c4df34ca2e91a97e,
había hallado DB/WAL/SHM candidate-absent sólo en tres rutas fijas; ubicación
global sigue UNVERIFIED. #120 resuelve el servicio ausente de aquel corte, no
prueba dónde existe o no existe toda DB previa. No hubo SQLite abierto/creado/
trasladado/migrado. El workflow de primera instalación todavía presupone
namespace vacío y controlador dormido: adaptarlo al candidato funcional antes
de usarlo. Preparar el daemon no instala ni acepta la aplicación.

## Decisiones aprobadas y fronteras

| Tema | Decisión de preparación/desarrollo | Límite |
| --- | --- | --- |
| Datos | Destino lógico futuro `/data/boca.sqlite3`, volumen `boca-socios_boca_data`, clave en volumen externo separado | Existencia global actual UNVERIFIED; no sobrescribir una DB hallada ni migrar datos reales por inferencia |
| Docker | Preparar servicio rootless dedicado Boca y comprobar recursos | No reinstalar Docker por inferirlo de una unidad ausente; único canal Actions protegido |
| Panel | Propia aplicación Boca sirve panel privado y accede localmente a SQLite | Elegir/probar identidad, sesión/TLS y acceso concreto; el navegador no recibe DB/clave/SSH/socket |
| Alta | `Socios > Agregar socio` obligatorio, sobre servicio cifrado existente | Sólo datos/credenciales sintéticos en esta BETA; alta local no verifica identidad ni elegibilidad Boca |
| Coordinación | Comandos y estado persistente; pausa visible en ambigüedad | No reejecución ciega ni éxito externo inventado |
| Avisos | Estado/avisos locales funcionales; ensayos del dispatcher sintético | Transporte #162, worker #188, helper #199, custodia #203 y prueba única #204 integrados opt-in; bot/destino, provisión host y recepción siguen pendientes |
| Site | Complemento #113 preservado | Versión privada v10 con D1 desactivado; no cuenta como panel operativo conectado |
| Operación final | Candidato concreto, imágenes/digests, preflight y aceptación verificables | Release/instalación final por decisión del candidato; no login/cola/reserva real ni backup |

Las decisiones ya aprobadas no se vuelven a preguntar para cada implementación,
prueba o reconciliación rutinaria. Desviaciones materiales fuera de este alcance
se presentan con opciones, recomendación e impacto. Backup/restore sigue
diferido; no se eliminan los requisitos de custodia/recuperación para alta real.

## Entregas y dependencias

| ID | Entrega y estado en el corte base | Criterio de cierre | Depende de |
| --- | --- | --- | --- |
| B1 | Plan/contratos y seguimiento: esta documentación | Matriz de alcance, alta obligatoria, decisiones, owners y evidencias registradas | Dirección del dueño |
| B2 | Servicio preparado #120; parada #156 y ALREADY_STOPPED en 41282301501; #191 preflight host beta integrado sin ejecución | Rootless propio sano; namespace candidato y procedencia de almacenamiento verificados; capacidad/cgroups/permisos de aplicación probados. No reemplazar una DB por inferencia | Destino delegado y propuesta concreta por Actions |
| B3 | Coordinador130, comandos149, loop161, ciclo164 y TLS173 integrados; RCA canónico187 | Comandos iniciar/detener/estado; guardia persistente, idempotencia, pausa ambigua y replay seguro probados | Contrato servido de B7 y panel B4 |
| B4 | Lectura128, formulario148, panel WSGI163, TLS173, preflight owner189, custodia #208 y origen exacto #214 integrados; este cambio #215 incorpora emisor local sólo en código, sin inscripción física ni forwarding #209 | Acceso privado tablet; Socios > Agregar socio cifrado/atómico; errores, duplicados, denegación y estado posterior visibles | B3 contrato; servicio de alta/clave/DB |
| B5 | Dispatcher134, Telegram162, `/avisos`163, worker188, custodia199/203 y prueba única204 integrados; recorrido host/recepción pendientes | Proyección fiel de estados persistidos, límites/restart/dedup; razón ambigua durable sin llamar entrega real a aceptación de API | Resultados persistidos de B3; UI B4 y provisión #168 |
| B6 | Chromium/medición | Una sesión aislada con recursos, parada y errores medidos en entorno candidato; alcance de egress explícito | Presupuesto separado; observación real no inferida de test offline |
| B7 | TLS173, Compose171 y operación protegida `beta-install`191 integrados; no ejecutados en host | Programa arrancado conecta B3/B4/B5; health funcional, acceso privado y manifiesto por componente; instalación desechable probada | B2–B6 según componentes del candidato |
| B8 | HTTP loopback170, probe TLS190 y smoke de contenedor limitado200; E2E host pendiente | Suite E2E, lint/types, RCA, seguridad e imágenes sobre mismo SHA; rapidez/recursos y revisión exacta | B7 consolidado |
| B9 | Release 41312460820 publicó imagen/manifiesto para `8fdbec97...` de #214; sólo GHCR, sin pull/install; código #191 sin dispatch | SHA→digest/manifiesto→proceso instalado trazables; nueva release para HEAD final y capacidad revalidada; sólo workflow y mutex Boca | B2 apto, B8 verde, decisión final del candidato |
| B10 | Aceptación/parada protegida200 integrada, sin dispatch | Recorrido desde interfaz real/tablet, persistencia/reinicio, límites, denegación y avisos; acta de versión/pendientes | B9 y matriz de aceptación |

Estos IDs no son estados de la aplicación. Cada cambio de estado de una entrega
se acompaña de issue/PR, SHA base/candidato/integrado, runs, resultado, límites,
siguiente dependencia y owner. Un merge de módulo no cierra B7/B10 por sí solo.
No es necesario fusionar todos los PR históricos; conservar su reconciliación
en [ROADMAP](ROADMAP.md) y rescatar únicamente aportes todavía pertinentes.

## Matriz completa de alcance UI: panel propio y Site complementario

El diseño y seguimiento deben contemplar desde el principio las funciones
conversadas, sin confundir cobertura del plan con funciones operativas. Esta
matriz conserva el alcance de [#113](https://github.com/mbalbo2023/boca-socios-assistant/issues/113),
[#9](https://github.com/mbalbo2023/boca-socios-assistant/issues/9) y
[#16](https://github.com/mbalbo2023/boca-socios-assistant/issues/16). No inventa
modalidades, permisos o productos que no se hayan definido.

**Panel propio** es la superficie operativa prevista de la BETA privada. El
**Site #113** sigue siendo demo privada sintética/complementaria: su proxy
read-only falla cerrado sin backend y la cola D1 está desactivada; no está
conectado a DB, comandos,
mensajería ni Actions. La intención de contemplar una
función en ambos diseños no decide duplicar todos sus controles ni demuestra
que el Site pueda ejecutarla. La navegación/estado planificado puede mostrar
«pendiente», «diferido» o «no habilitado» con motivo, sin botones que simulen
efectos reales. No afirmar «gestiona todo» ni «todo operativo desde el inicio».

Estados: **visible/planificado** significa incluido en el diseño o seguimiento,
no una pantalla ya publicada; **integrado** describe código; **operativo** exige
interfaz real, identidad/permiso, contrato conectado y prueba del candidato en
el entorno. Hoy ningún control del Site cumple esa última condición. La
aceptación BETA de simulación y la operación real contra Boca son hitos distintos.

| Función conversada | Cobertura UI prevista | Código/evidencia disponible | Estado de entrega y gate pendiente |
| --- | --- | --- | --- |
| Alta y consulta de socios | Socios > Agregar socio; lista/consulta con resultado explícito | Servicio cifrado31, formulario148, lectura128, panel163, TLS173 y preflight189 integrados | Alta sintética obligatoria; credencial física de dueño, instalación y recorrido tablet aún por probar |
| Baja/revocación y cambio de credencial | Acciones de ciclo de vida con confirmación y resultado | Servicio interno y UI owner #163 integrados | E2E servido/host pendiente; no borrar cuotas ni tratar revocación como borrado total de persona |
| Rotación de clave y eliminación completa | Mostrar alcance/estado y requisitos de custodia | Recifrador40 y migración0004 opt-in; no rotación real demostrada | Pendiente explícito: coordinación de escritores, DELETE/retención/recuperación; no se añade a la BETA por una pantalla |
| Eventos, categorías, horarios y fuentes | Selección/configuración definida, horarios ART, origen y fecha de avisos | Modelos/simulador y cuota local; backlog de categorías/ingesta/procedencia conservado | Gestión UI y datos oficiales no operativos; definir contratos concretos sin inventar categorías/modalidades |
| Simulación, iniciar/detener/estado y reinicio | Controles y resultado local, pausa visible en ambigüedad | Coordinador130, comandos149, loop161, ciclo164, controles163, TLS173 y RCA de UUID187 integrados | Objetivo obligatorio BETA; faltan instalación, sesión del dueño/acceso privado y E2E host; no es reserva Boca |
| Sesiones múltiples y límites | Configuración/estado de sesiones autorizadas y consumo | Simulador agrupa aliases por socio/evento; guardia una intención/cantidad1 | UI/BrowserContext/medición pendientes. Varias sesiones no prueban posiciones o tokens Queue-it independientes |
| Avisos locales y Telegram | Bandeja/estado de avisos, canal y fallos explícitos | Outbox durable, dispatcher134, adaptador162, UI163, worker188, parada194, helper cifrado199, custodia203 y prueba única204 | Bot/destino reales, dispatch de custodia/prueba host y recepción #168 pendientes, sin afirmar entrega por código integrado |
| Diagnóstico, fuente pública y recursos | Semáforo con procedencia/hora, salud y límites | Workflows fuente/host, inventario98, preparación120 y medición Chromium offline | Proyección UI real pendiente; un semáforo externo no habilita login ni prueba capacidad de host |
| RCA, calidad y trazabilidad | Versiones, SHA/digests, runs, decisiones y errores redactados | CI, reviews, ledger RCA y continuidad45; no editor automático de código | Integración UI/recibos por acción pendiente; nunca sustituir pruebas exactas por una insignia sintética |
| Release/deploy y operación host | Mostrar estado/recibos y alcance permitido | Workflow protegido; rootless #120, preflight #124, parada 41282301501, imagen release 41301618285 para corte #208, custodia owner208 y Site181/196, `beta-install`191 y aceptación/parada200 integrados | Revalidar release coincidente con HEAD; faltan BETA marker, identidad privada, dispatch de install y control Site→Actions; nada de SSH/Docker/secreto en Site |
| Backup/restore | Estado diferido y motivo visible/planificado | Biblioteca offline47; ningún ensayo operativo acredita recuperación | Diferido por el dueño hasta versión productiva fiable; sin botón operativo ni backup ahora |
| Login, cola, elegibilidad, reserva/compra real | Identificar hito separado y no habilitado | Modelos y observación pública histórica; sin flujo autenticado validado | No habilitado en esta BETA; requiere consentimiento/custodia, flujo legítimo y conciliación de resultados ambiguos |
| Administración multiusuario y modalidades no descritas | No inventar controles, roles o planes | El formulario de socios no crea administradores; no hay definición aprobada de otras modalidades | Sin definición: registrar la necesidad antes de diseñar/activar, sin presentar una suposición como función acordada |

El simulador sí documenta FIFO/lotería de precola y aliases locales; son
políticas sintéticas, no modalidades comerciales ni una descripción comprobada
de la fila de Boca. Su existencia en código no aprueba por sí sola un selector
nuevo de negocio. La interacción humana en una eventual reserva real conserva
su estado de decisión pendiente en ROADMAP.

Accesibilidad atraviesa todas las filas: tablet Samsung/Android e iOS, etiquetas
visibles, objetivos táctiles amplios, teclado/foco, estados comprensibles y
control por voz sin depender de hover. Las pruebas de HTML/handlers no acreditan
compatibilidad real de cada dispositivo. No publicar credenciales, cookies,
tokens de cola, enlaces que concedan acceso ni secretos en UI/logs/notificaciones.

Cada fila sólo se marca operativa al enlazar superficie concreta (panel/Site),
ruta/handler, permiso, pruebas, gate y recibo de ejecución. Un elemento que se
muestra únicamente como plan conserva ese rótulo y su pendiente; no se cierra
por haberlo dibujado ni se elimina por no entrar en el primer hito funcional.

## Recorrido obligatorio: Socios > Agregar socio

La persona autorizada abre el panel privado, entra a **Socios** y usa
**Agregar socio**. El formulario requiere los datos que ya valida el servicio
(email/identidad local, credencial sintética, registro de consentimiento y
nombre visible opcional). Usar labels explícitos, foco/teclado ordenados,
mensajes de error asociados y campos accesibles por voz; comprobar el recorrido
en tablet sin publicar secretos. La interfaz debe identificar el modo de simulación,
no sugerir que confirmó una cuenta Boca. La autenticación de quien administra
el panel es distinta del alta del socio; gestionar usuarios administradores
adicionales no se declara implementado por este formulario.

El backend autentica/autoriza la operación, valida límites y protección de
sesión/CSRF/replay y llama `MemberEnrollmentService.enroll()`. Ese servicio ya
normaliza email, crea UUID, cifra con AES-256-GCM vinculado al socio y persiste
miembro/credencial/auditoría en una transacción. El caller establece el contexto
de consentimiento; la biblioteca no verifica consentimiento externo ni
pertenencia/eligibilidad ante Boca. La clave no se guarda en DB, HTML, imagen,
repo o logs. La respuesta contiene estado/identificador opaco, jamás contraseña.

Después de éxito se muestra el socio local y puede seleccionarse para la
simulación. Doble envío/reintento no debe crear otro socio ni otra intención
indebida; diseñar el contrato de idempotencia sin sustituir datos existentes.
Validación fallida, email duplicado, clave inválida, DB incompatible o caída
transaccional deben dejar un estado visible y verificable sin filtraciones.
No mostrar de nuevo el secreto ni conservarlo en URL/logs/artefactos de prueba.
Las pruebas usan sólo fixtures sintéticos, incluso en la aceptación final.

## Evidencia de composición ya integrada

[PR152 / issue151](https://github.com/mbalbo2023/boca-socios-assistant/pull/152)
añade cuatro recorridos: alta/repetición/completado/reconstrucción; stop antes
de ejecutar; rechazo sin autenticación; y recuperación de aviso tras fallo de
persistencia sin repetir browser. Usa el WSGI y servicios reales de aplicación
sobre la misma DB temporal sintética, con identidad y browser dobles. Los
comandos se invocan en proceso, no por HTTP. No prueba servidor, passkey,
tablet/voz ni sitio Boca. Ver [aceptación en proceso](quality/BETA_JOURNEY_ACCEPTANCE.md).

## Integración de contratos pendiente antes de servir la aplicación

Los adaptadores #128/#148 por sí solos no constituyen un servidor privado.
El panel owner passkey #163 ya integrado en código unifica alta, estado y
comandos bajo la sesión de dueño. Su identidad no está provisionada ni servida
en el host; un puerto de pruebas no es acceso privado operativo.
[Las opciones concretas de acceso/bootstrap](https://github.com/mbalbo2023/boca-socios-assistant/issues/17#issuecomment-6551922108)
son antecedentes de diseño. Falta un contrato configurado y probando
identidad, origen TLS y rechazo de terceros. Incluir consulta de estado
después del alta desde la misma sesión autorizada y expiración/denegación
en la aceptación HTTP real.

El outbox persiste sólo pending/claimed/accepted/exhausted. Exhausted no guarda
la causa, y DispatchReport.ambiguous es transitorio; no se puede reconstruir un
motivo ambiguo durable a partir de esos cuatro estados. La proyección de avisos
con razón persistida queda pendiente si se necesita ese detalle tras reinicio;
la UI debe mostrar únicamente lo que la evidencia permite, separándolo de
needs_review del comando. La tabla de aceptación describe un objetivo, no un
motivo durable ya implementado.

El loop persistente #161 y el ciclo local #164 integraron recuperación
exclusiva al arranque en biblioteca; el panel #163 aporta lista, comandos y
avisos bajo un owner WSGI. Un stop de otra instancia no cancela por sí solo la
tarea que vive en un proceso diferente; el servidor debe respetar ese
contrato. Estas pruebas no demuestran listener, TLS, bootstrap, tablet o
navegador real. La composición servida y el despliegue conservan sus criterios
de cierre.

## Matriz de aceptación antes y después de desplegar

| Recorrido | Antes de desplegar | En droplet, después de instalación autorizada |
| --- | --- | --- |
| Acceso privado | Usuario no autorizado/permiso insuficiente/CSRF/replay rechazados; secretos ausentes de respuestas/logs | Acceso desde tablet autorizado y rechazo real de tercero; TLS/sesión del acceso concreto |
| Alta de socio | E2E formulario→servicio→cifrado/DB/auditoría→lista; error/duplicado/doble clic/reinicio; ninguna fila parcial | Alta sintética desde panel real; estado tras reinicio controlado; clave separada y permisos comprobados |
| Una entrada | Un socio/evento, cantidad1; concurrencia/alias/doble comando/replay sin nueva intención indebida | Repetición sintética desde interfaz sin multiplicar intención; no equivale a ticket Boca |
| Start/stop/status | Comandos idempotentes, parada repetible, reloj/expiración y fallos; UI refleja estado durable | Estado fechado consistente con proceso instalado; parada sin tocar otro proyecto |
| Reinicio/ambigüedad | Caídas antes/después de intención, resultado y aviso; pausa visible, sin éxito inventado ni reejecución ciega | Reinicio autorizado de Boca, datos/clave retenidos y estado coherente |
| Avisos | Estados persistidos y límites/backoff/fencing/replay; causa ambigua durable pendiente, no inferida de exhausted | Aviso local visible y trazable al resultado; no afirmar recepción Telegram |
| Recursos/errores | Clave inválida, DB incompatible, límites CPU/RAM/PID, red/mounts y capacidad post-pull | Pruebas efectivas de cgroups, salud funcional, espacio/inodos y aislamiento Boca |
| Rapidez | Medir tiempos y distribución de recorridos/checks con cantidad de muestras y SHA | Medir mismos recorridos sintéticos y consumo con versión/digests; comparar condiciones |

No aplicar migraciones automáticamente a una DB encontrada. El candidato debe
inventariar las estructuras necesarias de sus módulos y el diff concreto;
0004 de rotación no se transforma en requisito de esta BETA. First-install
no es un procedimiento de upgrade: datos/namespace existentes requieren
compatibilidad, procedencia y un procedimiento revisado antes de escribir.

## Rapidez y eficiencia sin perder integridad

La muestra del corte base [CI 41259139901](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41259139901)
(SHA `4922e45b5e2e38242263b6ba10969a8190aa939a`) registró calidad16s e
image-build41s: controlador8s, Chromium28s y smoke2s. La suite de 594 pruebas
ocupó 3,53s. Son duraciones de una ejecución de runner, no
capacidad del droplet ni latencia de despliegue; no bastan para atribuir una
mejora causal o prometer un ahorro. El análisis detallado de cola, builds
repetidos, opciones de caché y evidencia se mantiene en issue #143 y
[ADR0060](ADR/0060-measured-ci-budget.md), integrado por #146. No cambió
workflows ni implementó instrumentación nueva o un ahorro demostrado.

Prioridad de trabajo aprobada: consolidar cambios/formatos antes de publicar
cada candidato; ejecutar en paralelo pruebas/scan/build independientes; hacer
una reconciliación final en orden de integración. Conservar mutex único host,
revalidación inmediata de capacidad/identidad y checks exactos. No dividir por
principio una suite de pocos segundos ni anular los builds exigidos por policy
porque el cambio parezca documental. #136 ya separa concurrencia entre PRs.

Registrar cola vs ejecución, build por imagen, scan, suite/E2E, preflight,
release, transferencia/pull, arranque/health y postflight. Para panel/alta/estado
registrar muestras, mediana/p95, errores y CPU/RAM/IO del entorno. Separar
primera ejecución de ejecución con caché y distinguir sobrecarga del runner de
latencia de la app. Aún no hay cifras reales de despliegue ni SLA demostrado;
el candidato debe fijar criterios de aceptación medibles a partir del baseline
antes de presentarse para instalación, sin inventar umbrales cumplidos.

Caché acotada, builds separados o reutilización de imagen se evalúan como
cambios técnicos posteriores con medición y review: preservar lock/digests,
procedencia, aislamiento de confianza y escaneo actual. Nunca promover una
imagen no confiable de PR directamente a release privilegiada ni reutilizar
el resultado de scan de otro candidato como aprobación. Fallos de integridad
se corrigen; no se aceleran debilitando gates.

## Paralelización, documentación y cierre

El [recibo de inicio](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142)
registra los escritores asignados. Ownership operativo puede relevarse allí;
estas responsabilidades evitan editar rutas compartidas simultáneamente:

| Ámbito | Seguimiento | Responsabilidad de escritura/revisión |
| --- | --- | --- |
| Host/rootless | #145 | Helper/workflow y ADR0058; root es único operador del host |
| Coordinación | #127/#130 y #147 | Guardia/coordinador/comandos y ADR0057; contrato de estados primero |
| Panel/alta | #126/#128 y #17 | Adaptadores, formulario/consentimiento y ADR0061; sin docs centrales simultáneas |
| Avisos | #133/#134 | Dispatcher/ADR0051 integrados; ADR0059 sólo reservado para futuro alcance, no existe como contrato aceptado; sin envío real inferido |
| Eficiencia | #143 cerrado con146 | Baseline/análisis y ADR0060 integrados; instrumentación/optimización futura requiere evidencia propia, sin retirar gates |
| Plan/documentación | #144 | Este plan, docs centrales y ADR0056; reconciliar hechos de módulos |
| Integración/continuidad | #45/#113 | Root revisa, serializa merges y actualiza checkpoint/decisiones |

Un escritor por rutas: host/datos, coordinación, panel/alta, avisos, navegador y
calidad/documentación pueden avanzar en paralelo sobre contratos acordados.
Cada PR actualiza su ADR/contrato modular y evidencia en el mismo cambio. El
escritor documental central mantiene este plan y estado; el responsable de #45
actualiza el checkpoint al integrar. Evitar escritores simultáneos sobre docs
centrales y revalidaciones prematuras de todas las ramas tras cada merge.

Regla84 exige consistencia antes de cerrar la entrega; no obliga a duplicar
información idéntica en todos los documentos ni bloquea pruebas paralelas por
esperar un merge ajeno. Si cambia un hecho central, coordinar su actualización
con el mismo candidato o su integración controlada y dejar el pendiente
explícito hasta completar el recibo; no llamar actual a información conocida
como obsoleta. No hay robot ni calendario de mantenimiento separado.

El acta final enlaza versiones, digests, runs, acceso privado, matriz completa,
mediciones, limitaciones y pendientes. Sólo entonces se marca **BETA validada en
simulación**. Permanecen registrados el flujo real, Telegram externo pendiente,
observación pública autorizada, rotación/recuperación real, accesibilidad y
backlog histórico sin evidencia de cierre. Backup/restore diferido y
Porota/PPI Watch fuera de alcance.
