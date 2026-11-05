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
