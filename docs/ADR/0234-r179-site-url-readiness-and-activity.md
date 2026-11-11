# ADR 0234 — R179: SITE_URL visible y actividad sin falso estado actual

**Estado:** CODE_ONLY, sin recepción física. Rama aislada
`feature/417-r179-site-activity`, base exacta
`527ecdadff72fcba4fa2126e37ea3aa75b2058b3`. Continúa la frontera
R172/R177 y el diagnóstico R178; no cambia Docker, Cutover, workflow, IPC,
red, secretos ni código de navegación.

## Inventario de las variables relacionadas con URL

| Nombre / fuente | Uso | Edición desde `8443` |
| --- | --- | --- |
| `SITE_URL` | Único destino del ensayo de navegador, leído desde el volumen URL-only por IPC | **Sí**, en `Configuración`, con passkey, `simulation:write`, CSRF y operación de un uso |
| `BOCA_PANEL_ORIGIN` / `SSH_LOOPBACK_ORIGIN` | Origen exacto de la sesión local y RP de la passkey | **No**; cambiarlo rompería la identidad de la passkey y la atestación del host |
| `BOCA_SITE_ORIGIN` | Puente Site legado y su contrato de firma | **No**; no es destino de Chromium ni pertenece al formulario del bot |
| Telegram Bot API y su token | Transporte de mensajería protegido, separado del destino de prueba | **No**; una URL con token nunca debe entrar al editor del navegador |
| `source_url` de avisos oficiales | Metadatos informativos importados, sin acción de reserva | **No**; sólo vista de observaciones, no destino configurable del bot |
| Rutas relativas `/socios`, `/control`, `/estado` y similares | Navegación del propio panel privado | **No**; no son endpoints externos |

`SITE_URL` ya admitía HTTP(S) público o privado, rechazaba material de
credenciales, query, fragmentos y metadata IP, se guardaba en el volumen de
datos de Boca y se publicaba atómicamente en `boca_site_config`, visible al
worker únicamente como montaje de lectura. No se añade un segundo editor,
una tabla de URLs ni un fallback codificado. Guardar una cadena no verifica
su resolución DNS, el egreso de Chromium ni una navegación.

## Cambio mínimo al control bajo demanda

Antes de R179, el botón **Iniciar bot** aparecía habilitado aunque `SITE_URL`
faltara o su copia de worker difiriera. El POST devolvía correctamente 503,
pero el usuario no conocía ese estado hasta pulsarlo.

Se reutiliza una **única comprobación** de que la URL guardada existe y
coincide exactamente con el mirror de solo lectura. La misma función rige la
precondición del POST y el estado de `GET /` y `GET /control`, sin duplicar
la política:

- `matched`: mensaje accesible «SITE_URL lista para solicitar un inicio»;
  habilita el botón pero **no** afirma actividad del worker, conectividad o
  reserva.
- `missing`, `diverged`, directorio inseguro o lectura corrupta: mensaje
  «SITE_URL no verificable para iniciar», enlace directo a Configuración y
  botón START deshabilitado. **STOP permanece accesible**, sujeto sólo a las
  reglas ya existentes de la operación en curso.
- El POST conserva la comprobación fresca independiente de la pantalla;
  una página vieja o un POST fabricado no puede sortear el rechazo 503.
- Ninguna lectura de estado visita `SITE_URL`, invoca Docker, inicia el bot,
  expone la URL en la pantalla Control ni hace escrituras en SQLite.

La pantalla **Actividad del worker** ya presentaba exclusivamente eventos
locales de categorías fijas y telemetría acotada a cinco minutos. Se corrige
el error visual cuando falla una actualización de cinco segundos: el resumen
indica que los eventos mostrados son históricos y el estado actual no está
verificado. Se invalida la firma de render para que la siguiente lectura
exitosa restaure el resumen aunque los eventos no hayan cambiado. No se
presenta la vista como monitor de salud de Docker o evidencia de una reserva.

## Pruebas y aceptación restante

La regresión nueva recorre inicio y Control con URL ausente, divergente y
coincidente; comprueba mensajes visibles, botón START, botón STOP, ausencia
de wake, y la protección del POST ya existente. Otra regresión prueba el
texto del manejo de error de actualización y la recuperación de su firma.
Ambas se observaron **RED** antes de los ajustes y **GREEN** después.

**Evidencia local R179:** `pytest -q -n 2` produjo **6865 PASS**, **34
subtests PASS**, **1 SKIP** en 94,32 s. El único SKIP es
`tests/test_r177_fixture_probe_transport.py:72` porque este sandbox deniega
el socket AF_UNIX (`EPERM`); su recepción exige runner Linux de GitHub
Actions con recibo positivo. La suite focal de panel/URL/actividad reportó
**84 PASS**. `ruff check .`, `ruff format --check .` (846 archivos),
`mypy src` (155 fuentes) y `git diff --check` dieron PASS. Esto no reemplaza
las Actions exact-SHA ni la recepción del droplet.

La recepción física requiere nueva imagen instalada por la Action protegida,
passkey del dueño en Chrome, `SITE_URL` guardada y reflejada por su volumen,
recibo de START/STOP exacto, socket/UID y telemetría real. El worker de
producción mantiene el ejecutor `OfflineNoGoExecutor`; ni una URL coincidente
ni los tests de panel habilitan navegación o reservas reales. Telegram queda
separado y OFF hasta su aceptación/rotación independiente.
