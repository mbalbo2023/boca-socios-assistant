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

## Evidencia / Regla 84

Base `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`, propiedad de #314
en una rama aislada; no toca otros repos, contenedores, servicios ni puertos.
Hasta integrar, registrar SHA de candidato, Ruff, Mypy, suite completa y
resultado remoto del PR DRAFT. El estado del controller instalado sigue el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
Sin merge, workflow protegido ni deploy autorizado por este ADR.
