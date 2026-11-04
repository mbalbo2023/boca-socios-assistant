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
activarlas. `assess_official_notice` distingue evento todavía futuro de histórico,
pero **no** consulta precios, disponibilidad, elegibilidad ni cola. El hash y
URL del JSON son afirmaciones del observador externo, no pruebas
criptográficas de autenticidad del sitio; sólo un futuro recibo de fuente
puede promover el grado de confianza. No se establece caducidad de código ni
se convierte un dato antiguo en rechazo de instalación del controller.

Las pruebas (`tests/test_official_event_catalog.py`) emplean una noticia
**enteramente sintética, no publicada**, evitando atribuir calendarios
inventados a Boca. Probar una importación con esa fixture nunca acredita la
fecha de un partido real.

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
