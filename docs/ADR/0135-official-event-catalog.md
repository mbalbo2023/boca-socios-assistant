# ADR 0135 — Eventos y ventanas de socios: procedencia oficial, sin ejecución

**2026-11-04 ART · Issue #314 · Estado: DRAFT (código/QA, no integración operativa).**

## Decisión autorizada y límites

Tincho aprobó la opción #3: consultar eventos, categorías de socios y horarios
publicados por fuentes oficiales para informar la BETA. Rechazó opciones #4
(múltiples sesiones), #5 (rotación de clave maestra/eliminación completa),
#6 (login/fila/elegibilidad/reserva/compra reales) y backups. Este scope no
autoriza ningún botón real de compra, acceso a Boca Socios autenticado,
peticiones a Queue-it, ni una segunda sesión de navegador. Los módulos
`synthetic.py` y `ipc_worker.py` siguen siendo BLACKBOX exclusivos del owner.

## Fuentes y observación auténtica

- **Club Atlético Boca Juniors** —
  [Boca-Defensa: Información al socio](https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio),
  publicación 2026-11-03. El aviso enumera el encuentro local del sábado
  2026-11-07 a las 17:30 y **ventanas diferenciadas**, no una hora única de
  disponibilidad: generales activos/interior desde 03/11 13:00, adherentes
  desde 04/11 17:00; confirmación de abonados 03/11 14:00 a 06/11 23:59;
  abono solidario desde 03/11 14:00 hasta apertura del estadio (hora exacta
  no publicada); vitalicios desde 04/11 14:00. Son observaciones indexadas
  del aviso público, **no** recibo del backend de Boca Socios, evidencia de
  disponibilidad o regla de elegibilidad validada.
- **Liga Profesional AFA** —
  [fixture 2026](https://www.ligaprofesional.ar/notas/primera/2025/12/11/fixtures-de-la-temporada-2026/)
  es fuente secundaria oficial para emparejamientos del torneo; **no informa**
  apertura de categorías/sectores de Boca Socios. No debe completarse una
  ventana con estimaciones basadas solo en el fixture.
- **Control histórico del mismo canal** —
  [Boca-River: información para socias y socios](https://www.bocajuniors.com.ar/noticias/boca-river-informacion-para-socias-y-socios)
  publicó para el clásico del 01/11/2026 ventanas de generales 26/10 para
  activos/interior y 27/10 para adherentes, plateas abonadas 26/10 a 31/10,
  y vitalicios desde 28/10. Confirma la necesidad de conservar la **fecha
  propia por categoría y encuentro**; es un aviso ya histórico, no datos vivos.
- **Contraejemplo de canal** —
  [Final a la vista, 02/11/2026](https://www.bocajuniors.com.ar/noticias/final-a-la-vista)
  expresa que la venta prioritaria de la final sudamericana se realiza en
  **la plataforma externa de CONMEBOL**, no necesariamente en Boca Socios.
  Por lo tanto, **"publicado por Boca" no significa "operable en Boca Socios"**.
  No hay aceptación de rutas de venta, endpoints ni automatización del tercero.
- En búsquedas de fuente oficial no se pudo verificar un feed/API documentado,
  estable y autorizado para obtener automáticamente las ventanas por categoría.
  El hecho de que haya artículos indexados no acredita una API, cuota, cambio
  de esquema o persistencia actual. No se automatizó navegación ni HTTP GET
  contra Boca; el futuro origen de capturas requiere su propia aprobación y
  evidencia read-only separada.

La página no declara explícitamente el huso en cada franja; el uso de
`-03:00`/ART para una transcripción revisada es una normalización contextual
que debe validarse con la fuente exacta antes de dar un aviso por confirmado.

## Contrato de código de esta etapa

`src/boca_socios/events/official_catalog.py` importa únicamente una estructura
JSON **previamente observada** fuera de esta librería. Requiere URL HTTPS
exacta del dominio y ruta de noticia pública oficial, fecha de publicación,
instante de observación, SHA-256 declarado de la captura, clave opaca del
evento, título, inicio del encuentro y las ventanas por categoría/sector.
Los horarios requieren minutos y offset ART explícito. Un cierre `stadium_open`
se registra como una condición sin hora: **nunca** inventa una hora de cierre.
El importador rechaza claves duplicadas o extra, UTF-8 demasiado grande,
timestamps ambiguos, sectores desconocidos, categorías duplicadas, horarios
contradictorios y URL falsa/otro host. No contacta un proveedor, Chrome,
Docker, Telegram, SQLite ni el sitio de Boca.

La salida es invariablemente `SOURCE_OBSERVED_UNVERIFIED` con
`actionable=False`, incluso cuando la noticia dice que la ventana ya abrió.
`build_observed_catalog` ordena hasta 20 observaciones sin duplicados y sin
activarlas. El importador consume **como máximo 21 elementos** de un iterable
externo: el 21.º provoca rechazo antes de materializar un generador sin fin o
realizar trabajo no acotado. `assess_official_notice` distingue evento todavía futuro de histórico,
pero **no** consulta precios, disponibilidad, elegibilidad ni cola. El hash y
URL del JSON son afirmaciones del observador externo, no pruebas
criptográficas de autenticidad del sitio; sólo un futuro recibo de fuente
puede promover el grado de confianza. No se establece caducidad de código ni
se convierte un dato antiguo en rechazo de instalación del controller.

Las pruebas (`tests/test_official_event_catalog.py`) emplean una noticia
**enteramente sintética, no publicada**, evitando atribuir calendarios
inventados a Boca. Probar una importación con esa fixture nunca acredita la
fecha de un partido real.

Regresión 04/11: la conversión anterior `tuple(notices)` consumía por completo
el iterable **antes** del límite de 20 y podía agotar tiempo/memoria ante un
productor no acotado. La versión corregida corta en el elemento 21 y rechaza
de forma determinista; no cambia los datos ni aumenta la confianza en su origen.

## Bloqueo de integración consciente

La UI actual sólo admite `events: Mapping[UUID, label]` sintéticos y el
puente de comandos restringe `SIMULATION_EVENT_ID` a un único valor.
Inyectar directamente noticias oficiales como IDs de comando alteraría la
lógica de negocio y daría una falsa impresión de operador real; el owner
descartó expresamente #6. **Este PR NO conecta las fuentes a `/comandos`**.
Una futura integración de lectura en el panel deberá separar eventos
informativos del único evento sintético permitido, documentar el estado
`NO_VERIFICADO` y obtener evidencia de fuente oficial en un Action READ_ONLY
antes de afirmar disponibilidad. El próximo deploy no puede declararse listo
para operar entradas en Boca con este módulo.

## Extensión de proyección informativa para la tablet (04/11)

`src/boca_socios/events/official_presentation.py` provee **dos funciones
offline, sin I/O ni persistencia**:

- `export_observed_catalog_json` genera un manifiesto JSON con esquema `v1`,
  `source_mode=OFFLINE_PREOBSERVED_ONLY`, `live_feed=false`,
  `availability_verified=false`, `admission_channel_verified=false`,
  `actionable=false`, URL, día publicado,
  timestamp de observación, digest declarado, horarios, fase y
  `observation_age_minutes`. El cálculo sólo mide antigüedad de una
  transcripción respecto del corte suministrado: **no define FRESH ni promete
  actualidad, cupos o elegibilidad**. Los instantes del corte se expresan en ART.
- `render_observed_catalog_html` entrega un fragmento de HTML accesible para
  Chrome/Android: jerarquía de encabezados H2/H3/H4, fechas con `<time>`,
  vínculo explícito a la noticia de origen, aviso visible de NO VERIFICADO y
  ventanas por categoría en una lista. Escapa títulos y atributos antes de
  dibujarlos y **no incluye formularios, scripts ni controles de compra**.
  Advierte expresamente que el canal de admisión no está verificado.
  La fuente podría ser abierta manualmente por el usuario; **el agente no
  automatiza navegación**.

Ambas proyecciones requieren una observación previamente validada, mantienen
el estado no operable incluso para horarios recientes y fallan ante relojes
sin zona horaria o anteriores a la observación. Sus fixtures son sintéticas.
No están todavía conectadas a la UI servida: `private_http.py` y los comandos
siguen fuera del ownership de este frente. Conectarlas requerirá un PR de UI
independiente, con una sección de lectura y sin derivación a TicketIntent.

### Contrato v2 del canal *declarado*, sin promoción de confianza

En la evidencia de `Final a la vista` el club anunció una plataforma externa
CONMEBOL; en avisos de partidos locales anunció Boca Socios. El importador
acepta ahora `official-notice-observation-v2`, manteniendo las mismas
restricciones de URL oficial, sello temporal, digest **declarado** y ventanas,
más dos campos **obligatorios**:

- `admission_channel_claim`: `BOCA_SOCIOS`, `CONMEBOL` o `UNKNOWN`.
- `admission_channel_excerpt`: texto corto observado en el mismo artículo,
  sin datos personales y acotado a 20–320 caracteres cuando hay canal.
  Para `BOCA_SOCIOS` debe contener «Boca Socios»; para `CONMEBOL`,
  «Conmebol» y «plataforma». Extractos que mencionan ambos canales se
  rechazan como ambiguos. `UNKNOWN` exige `null`.

Este extracto y su relación con la URL son **afirmaciones del operador**,
no una validación de la fuente ni un derecho de acceso. En JSON se conserva
`admission_channel_verified=false` a nivel catálogo **y evento**; en HTML
se indica «según transcripción no verificada» y que no habilita navegar ni
operar. La observación v1 preexistente sigue admitida sin alteraciones pero
su canal es **obligatoriamente `UNKNOWN`**, nunca Boca Socios por defecto.
No se agregan URL externas a la lista permitida, descargas automáticas ni
endpoints de CONMEBOL o Queue-it.

## Evidencia / Regla 84

Base `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`, propiedad de #314
en una rama aislada; no toca otros repos, contenedores, servicios ni puertos.
Hasta integrar, registrar SHA de candidato, Ruff, Mypy, suite completa y
resultado remoto del PR DRAFT. El estado del controller instalado sigue el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
Sin merge, workflow protegido ni deploy autorizado por este ADR.

## Extensión R6 — lectura segura de snapshot offline (código DRAFT, no host)

La auditoría de [#314](https://github.com/mbalbo2023/boca-socios-assistant/issues/314#issuecomment-6648149945)
detectó un faltante funcional concreto: la única construcción del servidor en
`runtime.build_beta_server` no suministra `observed_official_notices`, de modo
que las rutas de eventos del candidato #319 muestran el catálogo vacío. Los
checks de PR certifican la ruta y sus restricciones, no la presencia de avisos
en un panel físico. Por decisión de integración se agrega en este PR **sólo un
lector**, sin cablear el servidor ni modificar la fuente oficial.

`events.official_snapshot.load_official_snapshot(path)` devuelve una tupla de
`OfficialNotice` no accionables. El nombre fijo del archivo es
`boca_official_notices.jsonl`, propuesto como archivo **dentro del volumen Boca
existente** junto a `/data/boca.sqlite3` (ruta lógica
`/data/boca_official_notices.jsonl`). **No crea volumen, archivo, subdirectorio,
tabla, migración ni puerto.** El futuro servidor debe construir esta ruta
solamente a partir de su directorio de datos Boca confiable: el lector no
autentica por sí mismo un montaje Docker, una captura del club ni una fuente
de escritura. No lee URLs ni otras bases de datos.

Contrato fail-closed:

1. Sólo el archivo opcional ausente, con el directorio de datos existente y
   válido, se interpreta como catálogo vacío; un directorio ausente, enlace
   simbólico, ruta relativa u otro nombre son errores explícitos. Nunca se
   interpreta una lectura fallida como «no hay eventos».
2. Recorre los componentes del directorio con `openat`/`O_NOFOLLOW`, exige
   directorio final dueño UID del proceso, no escribible por grupo/otros, y
   archivo regular dueño UID del proceso, con modo exactamente `0400` o `0600`
   y un único enlace físico. Se rechazan enlaces simbólicos/duros, FIFO,
   identidad mutable, tamaño alterado entre lectura y postflight, o escritura
   concurrente detectada. No usa un `read()` ilimitado: máximo **327.700 bytes**
   y 20 líneas de hasta **16.384 bytes** cada una.
3. Cada línea UTF-8 es exactamente una observación JSON v1/v2 del importador
   preexistente, con URL pública oficial declarada, horarios ART y
   `source_sha256` **declarado, no cotejado contra HTML real**. Rechaza líneas
   vacías, CRLF ambiguo, bytes NUL, JSON inválido, duplicados y exceso.
4. Un archivo presente corrupto o inseguro levanta `OfficialSnapshotError`
   (subclase de `OfficialCatalogError`) con texto redactado y sin contenido ni
   rutas privadas. No realiza fallback silencioso, uso de datos anteriores ni
   promoción de confianza. En la futura integración, los errores deberán
   degradar **sólo** las rutas informativas de eventos con un estado 503, sin
   impedir los controles/simulaciones locales seguros.
5. La eventual escritura del snapshot **no** está implementada ni autorizada
   aquí. Un escritor futuro debe generar fuera de este lector observaciones
   revisadas por el dueño, publicar por reemplazo atómico con permisos exactos
   y conservar recibo de fuente. Nunca editar el archivo in-place ni crear un
   cron/Actions que navegue Boca Socios o Queue-it. La primera versión no
   tiene feed automático ni TTL de código; la antigüedad de observación es
   un dato mostrado, no disponibilidad.

La implementación no abre los módulos BLACKBOX ni llama Telegram, el sitio
de socios, SQLite, Docker o el host. Sus pruebas crean sólo archivos
**sintéticos** en directorios temporales del runner. Falta el wiring separado
de `runtime`/panel (propiedad del integrador #319), QA combinada, validación
real de fuente/procedencia, y recepción física del owner. Esta extensión no
autoriza merge, release o cutover y no convierte noticias en `TicketIntent`.

## Extensión R7 — vínculo criptográfico de captura pública preexistente

La búsqueda de fuente oficial 04/11 constató artículos públicos del club:

- [Boca-Defensa del 03/11](https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio):
  fecha del encuentro, horas diferenciadas por categoría, abreviaturas
  «hs.» y condición de cierre «apertura del estadio». Esta última **no**
  constituye un horario de cierre fijo.
- [Final a la vista del 02/11](https://www.bocajuniors.com.ar/noticias/final-a-la-vista):
  confirma que una noticia oficial puede informar venta en plataforma de
  CONMEBOL, no en Boca Socios. Su condición externa **no** habilita ningún
  integrador de ese proveedor.

Los enlaces y extractos públicos son evidencia **de contenido indexado**, no
un recibo propio de adquisición HTTPS/TLS ni los bytes HTML que se usarán en
una transcripción. Tampoco se verificó API/feed estable autorizado ni un
esquema de avisos versionado. Por eso el estado de producción de eventos
permanece **NO_VERIFICADO**: no se entregan observaciones reales, no se
inventa un `source_sha256`, no se encola captura del sitio de socios, no se
activa ninguna escritura en host y el lector opcional devuelve catálogo vacío
cuando el snapshot no existe.

Para cerrar parcialmente la brecha probatoria sin declarar origen auténtico,
`events.official_capture_binding` implementa exclusivamente una función pura:

`build_official_snapshot_jsonl(captures: Iterable[OfflineCapture]) -> str`

Cada `OfflineCapture` debe recibirse **ya preparado**, con los bytes de una
página pública, el aviso JSON v1/v2 revisado y fragmentos **literales** para
título, fecha de publicación, inicio del partido y **cada** ventana, más el
extracto de canal v2. La función:

1. Limita a 20 capturas, hasta 1 MiB de HTML UTF-8 por captura y 16.384 bytes
   por aviso; consume como máximo el elemento 21 de cualquier generador.
2. Recalcula SHA-256 de los bytes efectivamente proporcionados y rechaza si
   difiere del `source_sha256` de la observación; comprueba que los extractos
   aparezcan en texto del cuerpo HTML, excluyendo scripts, estilos y algunos
   elementos ocultos, y que el título declarado esté cubierto por el extracto.
3. Reutiliza `load_observed_notice` y `build_observed_catalog` para el
   contrato estricto de URL pública, categorías, horarios ART, canales,
   duplicados y estado invariablemente **`SOURCE_OBSERVED_UNVERIFIED`**.
4. Devuelve sólo JSONL canónico acotado, adecuado para el lector R6 **sin
   guardar ni publicar ningún archivo**. `actionable=False` permanece
   inalterable. La función nunca abre URL, socket, navegador, ruta de host,
   sesión de socios, base SQLite, token o fichero local.

Esta prueba vincula **bytes entregados por un tercero** con texto y hash, no
autentica que los bytes hayan venido de la URL indicada; tampoco demuestra
que una fecha se haya interpretado correctamente, que el horario ART figure
explícitamente en la noticia, ni que se pueda comprar una entrada. La
verificación semántica y la cadena de custodia son tareas separadas.

### Cadena de procedencia pendiente (NO_GO de datos reales)

1. **Origen:** un futuro productor read-only específico y autorizado para
   páginas **públicas** deberá adjuntar evidencia verificable de URL final,
   respuesta HTTP, TLS, fecha/hora de captura, bytes íntegros, SHA-256,
   run/SHA de Action y ausencia de credenciales o redirecciones a login.
   No se implementa tal productor en este PR.
2. **Revisión:** un responsable deberá revisar contra el artículo exacto
   fecha/hora local, sector, categorías, vigencia y canal; marcar toda
   ambigüedad como no verificada. Las ventanas no publicadas no se deducen
   del fixture. No puede transformar un aviso informativo en orden.
3. **Generación:** con la captura íntegra y la revisión, el helper offline
   vinculará hash/extractos y generará un candidato JSONL. QA repetirá
   mismas pruebas contra ese artefacto **antes** de considerarlo publicable.
4. **Distribución:** sólo el dueño del cutover posterior, con GO independiente,
   podrá definir cómo entregar de forma atómica y con permisos exactos ese
   snapshot **al volumen Boca ya existente**; esta rama no modifica host,
   archivo real, `runtime`, UI, Docker ni workflows de despliegue.

Las 22 pruebas nuevas son deliberadamente sintéticas (incluyen digest
alterado, supuesta fuente privada, extractos ausentes, scripts/HTML oculto,
duplicados, generador acotado y compatibilidad con el lector R6). Una batería verde prueba la seguridad
**del transformador**, no certifica que existan datos reales frescos en la
tablet. Documentar HEAD/tree exactos y resultados de GitHub Actions en #314
antes de solicitar integración por el owner.

## Extensión R17 — recibo HTTPS para una noticia pública, PR-only READ_ONLY

La investigación nocturna identificó como **índice público del club**
[Noticias buscador](https://www.bocajuniors.com.ar/noticias-buscador), que
enlaza artículos ordinarios y de socios, incluido
[Boca-Defensa del 03/11](https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio).
Este índice no acredita un **feed/API oficial publicado, versionado y estable**
que entregue por contrato todas las categorías, ventanas, fechas de cambio,
zonas horarias y canales. Tampoco acredita admisión/eligibilidad/cupos en
Boca Socios. Un resultado de buscador no es una captura cruda autenticada.

Se incorpora un diagnóstico aislado, de **único GET anónimo por ejecución**,
específico para un artículo público **fijo**:

- `src/boca_socios/events/official_news_receipt.py` usa biblioteca estándar
  de Python, contexto TLS predeterminado con verificación de CA/hostname,
  origen exacto `https://www.bocajuniors.com.ar/noticias/boca-defensa-informacion-al-socio`,
  método GET sin cookie, token ni autorización, sin proxies de ambiente, sin
  redirects ni retries. No recibe URLs ni parámetros de usuario. Timeout de
  8 segundos y máximo 1.000.000 bytes, validando status 200, ubicación final,
  `Content-Type`, `Content-Length` y UTF-8.
- La respuesta queda **sólo en memoria efímera del runner**. Se emite un
  recibo JSON pequeño con URL fija, hora observada UTC, código HTTP,
  longitud, SHA-256 de los bytes efectivamente recibidos, Date HTTP
  normalizado si existe y presencia booleana de 11 marcadores textuales del
  artículo (título, fecha, inicio, canal y categorías). Excluye datos ocultos
  como scripts de la comprobación de texto. No emite HTML, cookies, cabeceras
  privadas, contenido integral, sesión ni un JSONL de eventos.
- El workflow nuevo `.github/workflows/boca-official-news-receipt.yml` es
  **sólo `pull_request`**, limita origen a la rama del repositorio propio,
  usa runner GitHub efímero, token con `contents: read`, acciones fijas por
  SHA, sin credenciales persistidas y con rechazo de rerun. Deja en el run un
  artifact efímero de **recibo redactado**, no una descarga de la página.
  Ningún job llega a droplet, Docker, Boca Socios, Queue-it, controlador,
  volumen, archivos de usuarios, Telegram o puerto.
- Los errores de sitio/HTTP/TLS/HTML devuelven estado `SOURCE_DEGRADED` o
  `CONTENT_UNVERIFIED` y un **código de causa**, sin excepción ni datos de
  red en los logs. Por política, es **alerta externa**, no un gate de
  simulación ni una excusa para reintentar tráfico; fallos del contrato del
  script/Actions sí requieren fix-forward propio. Una señal
  `PUBLIC_PAGE_OBSERVED_UNVERIFIED` verifica **sólo** que esa página pública
  fue servida al runner en ese momento, con bytes y marcadores; jamás
  equivale a «venta abierta», fuente universal o canal autentificado.

La prueba local incluye fixtures HTML totalmente sintéticas, red falsa,
rechazo de redirects, digest real de bytes de fixture, presupuestos, HTML
oculto, salida redactada y no accionabilidad. No ejecuta GET real. Sólo el
futuro run exact-SHA del PR puede completar evidencia de ese único artículo;
antes del recibo real y revisión semántica sigue **NO_VERIFICADO**. Incluso
con HTTP 200 y todos los marcadores presentes, no se crea ni publica un
snapshot real ni se fusiona automáticamente un candidato. La cadena de
procedencia general de múltiples eventos permanece pendiente de una fuente
confiable o un proceso de observación individual gobernado.

## Extensión R21.3 — extracción de ventanas de una noticia pública, offline

La auditoría del candidato integral #319 comprobó que
`runtime.build_beta_server` **ya conecta** el snapshot opcional al panel
`/avisos-oficiales` y `/avisos-oficiales.json`: no faltan rutas de presentación.
El faltante funcional es un **productor verificable** del archivo JSONL.
El workflow público R17 demuestra sólo un GET/TLS/HTTP y 11 marcadores; descarta
el HTML después de producir un digest. No puede construir por sí solo las
franjas horarias del evento ni publicar automáticamente su lectura en el
volumen Boca. Continuar mostrando `NO_EVENTOS_VERIFICADOS` cuando no hay
snapshot es correcto: **no implica que no exista un partido**.

`events.official_article_observation.build_boca_defensa_offline_jsonl`
introduce un eslabón **puro**, para la **única** noticia pública del
03/11/2026 sobre Boca–Defensa: toma bytes HTML *previamente capturados* y un
reloj de observación con zona horaria, sin red ni filesystem, y extrae las
cinco ventanas de activos/interior, adherentes, abonados, abono solidario y
vitalicios. Los cierres por apertura del estadio continúan sin hora exacta.
Reutiliza el vínculo `OfflineCapture` y el importador v2 existente para
verificar el hash de los **bytes suministrados**, cada fragmento textual,
el canal declarado y el contrato no accionable. Exige coincidencia de título,
fecha de publicación, encuentro, hora, títulos de secciones, orden y fechas
coherentes. Cambio de plantilla, texto duplicado, fecha contradictoria,
fuente oculta, dato faltante o documento demasiado grande causan rechazo;
no hay fallback, horario por defecto ni inferencia desde otra noticia.

La fuente web indexada del club muestra el partido de 07/11 a las 17:30, con
cinco ventanas distintas y canal **declarado** Boca Socios, pero la noticia
no certifica expresamente huso para cada franja. El extractor asume ART
(`-03:00`) para representarlas de acuerdo con el contrato del catálogo;
esa interpretación requiere **revisión semántica humana** contra la captura
exacta antes de avisos confirmados. La prueba sintética y el SHA calculado
no atestiguan origen TLS, disponibilidad, elegibilidad, cupos ni entrega
real del JSONL. El método se limita deliberadamente a la noticia fija, no
pretende descubrir todas las noticias ni una API no documentada.

**Continuidad operativa:** todavía no hay productor Action que entregue
simultáneamente bytes autenticados y el extractor en memoria, ni artefacto
JSONL real revisado, ni escritura/replace atómico en el volumen existente,
ni validación física Samsung. No ampliar el diagnóstico de un GET ni instalar
ese archivo en producción por inferencia. El próximo paso de #314 es
proponer esa unión READ_ONLY específica y una distribución protegida tras
revisión de fuente, separada de los comandos sintéticos y de reservas.

**Regla 84:** R21.3 parte del candidato #319 `129f789a62f80ea350e55f700a7d6f64ee238ce1`
con sus siete workflows GREEN en runner y host operativo sin cambios; el PR
de extracción debe registrar su propio HEAD/árbol, suite completa y Actions
exact-SHA antes de integrar. Seguridad externa queda en seguimiento P2 por
decisión de Tincho 05/11; no se modifican `synthetic.py` ni `ipc_worker.py`,
bot, Telegram, datos de socios, puertos, GitHub host workflows u otras apps.

## Extensión R22 — una GET pública, recibo + JSONL acotado en el mismo runner

El R21.3 comprobó con 19 fixtures que cinco franjas pueden expresarse como
observación no accionable, pero el artículo sólo existía como entrada de
bytes sintéticos y la fuente R17 producía exclusivamente un recibo con
digest. En esta extensión, sin ampliar URLs ni métodos, el **mismo GET**
anónimo ya autorizado sobre la noticia pública fija puede pasar sus bytes
recibidos en memoria al extractor puro *antes* de descartarlos.

### Cadena nueva de código, sin despliegue

1. `official_news_receipt.observe_public_news(with_offline_snapshot=True)`
   conserva el único GET HTTPS/TLS verificado, con cero cookies, redirecciones,
   proxies, credenciales, reintentos y segundo fetch. Después de HTTP 200,
   digest del cuerpo y marcadores públicos, llama **una sola vez** al extractor
   R21.3 sobre el **mismo buffer** y mismo reloj de observación.
2. El modo fijo CLI `--emit-offline-observation` produce sólo un sobre JSON
   temporal dentro del runner efímero. Si el texto semántico cambió,
   desapareció un sector, la fecha/ventana es ambigua o el cuerpo no coincide,
   devuelve recibo de la noticia con
   `offline_snapshot_state=NO_EVENTOS_VERIFICADOS` y **sin JSONL**. Esto es una
   degradación de datos externos, no un permiso para inventar horarios.
3. `split_public_observation_envelope` verifica en la misma tarea URL final
   exacta, SHA-256 de observación vs JSONL, hora UTC vs ART redondeada a
   minuto, 5 ventanas, canal **declarado** y `actionable=false`; exige un
   JSONL único de hasta 16.384 bytes. Rechaza recibos corruptos o campos
   contradictorios, y separa el JSONL de la salida redactada.
4. El workflow PR-only `.github/workflows/boca-official-news-receipt.yml`
   sube por **7 días** sólo un recibo JSON redactado y, si fue extraído, un
   `boca-official-news-catalog.jsonl` delimitado, cada uno con permisos 0600
   dentro del runner. No sube HTML, sobre intermedio, cookies ni secretos.
   No tiene dispatch manual, schedule, otro puerto, SSH, Docker, credencial,
   escritura de volumen Boca ni navegación por Boca Socios/Queue-it.

**Interpretación:** este JSONL es un artefacto de *noticia pública observada*,
no una API o feed universal, una confirmación de eventos del sistema de socios,
un inventario de cupos ni una autorización para operar tickets. Incluso con
HTTP 200 y cinco ventanas, `verification_state=SOURCE_OBSERVED_UNVERIFIED` y
`actionable=false` se mantienen. La noticia no certifica zona horaria de
cada tramo; la aplicación de ART requiere revisión semántica adicional.
Se desconoce si el HTML real del nuevo run cumplirá exactamente la gramática
R21.3; si falla, sólo se conserva el recibo y el diagnóstico de incompatibilidad.
El módulo no genera snapshots de otros partidos ni hace descubrimiento de API.

**Falta para la BETA física:** inspeccionar el recibo real de esta Action,
revisar las cinco franjas/canal contra el artículo auténtico y, sólo con un
GO de Cutover posterior y custodia de volumen, publicar ese JSONL mediante
reemplazo atómico en `/data/boca_official_notices.jsonl`. Hasta entonces las
rutas del panel pueden legítimamente estar vacías sin que ello diga que no
existen partidos. Esta extensión es **CODE-ONLY / PR-DRAFT / SIN HOST**;
las pruebas locales son sintéticas y cada HEAD requiere Actions nuevas.

### RCA R22.1 — separador invisible del artículo real (fix-forward acotado)

La primera Action exact-SHA de la unión GET→extractor
[42028314553](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42028314553)
observó HTTP 200/TLS, **76.355 bytes**, SHA-256
`db3b4cb424d5b6282dd7a562960be834705b8274637710b477d4154c26f14889`,
11/11 marcadores públicos y un único GET, pero **no generó JSONL**:
`offline_snapshot_state=NO_EVENTOS_VERIFICADOS`,
`offline_snapshot_reason=article_semantics_unverified`. El job y la subida
del recibo fueron verdes; ello no convierte la fuente en catálogo de eventos.

Una inspección posterior de la página pública identificó literalmente un
separador de formato invisible **U+200D (ZERO WIDTH JOINER)** entre la frase
del cronograma y el encabezado GENERALES. El extractor R21.3 exigía que la
sección intermedia fuese exactamente `generales` tras quitar sólo puntos y
espacios; `_VisiblePublicText` conservaba el U+200D. Se reprodujo con una
fixture sintética basada exclusivamente en esa diferencia: el nuevo test
falló por `official category heading absent or ambiguous` antes del fix.

Corrección mínima: **sólo en la proyección semántica**
`official_article_observation._visible`, eliminar U+200D, sin eliminar otras
letras, palabras, símbolos visibles o encabezados. El SHA se sigue calculando
sobre los **bytes originales intactos** y `OfflineCapture` valida todos los
fragmentos sobre la captura original. La posición/orden de las cinco
categorías, horas, cierres y canal no se relajan. El test de U+200D y las
pruebas anteriores deben pasar antes de una nueva Action: **aún no afirmar
que el próximo recibo tendrá JSONL**. Si persiste otra diferencia, conservar
NO_EVENTOS_VERIFICADOS y diagnosticar con recibos sin exportar HTML.
