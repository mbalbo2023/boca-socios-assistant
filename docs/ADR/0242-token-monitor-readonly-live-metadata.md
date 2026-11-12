# ADR 0242 — Lectura privada periódica del estado de observaciones (R241)

**Fecha:** 2026-11-12 ART. **Estado:** candidato CODE_ONLY, no instalado.

## Problema confirmado

El monitor privado `/monitor/tokens` mostraba una foto HTML de dos monitores
opcionales en memoria, sin actualización automática. El ejecutable BETA en
`runtime.build_beta_server` **no conecta ningún productor** al constructor del
panel (`queue_monitor` y `auth_monitor` permanecen ausentes). Por eso un
usuario que ya puede ingresar a `8443` no ve obtener tokens en tiempo real;
la presencia de un panel o de una ruta de copia no demuestra observaciones.

Por separado, el formulario `SITE_URL` ya guarda en el volumen privado,
publica el espejo URL-only y redirige a `/configuracion` para mostrar el valor
guardado. La discrepancia con el host requiere instalar y comprobar la versión
correcta; este ADR **no altera** ese formulario, controles ni navegación.

## Decisión del alcance mínimo

- `GET /monitor/tokens.json` es exclusivamente privado: sesión passkey,
  `local-status:read`, origen del panel para todas las peticiones, sin query,
  `Cache-Control: no-store`. Sólo publica estado **del monitor en memoria**,
  cantidades y horas UTC, nunca tokens, `refreshToken`, URLs o credenciales.
- Una vista accessible de estado hace una lectura al abrir, cada cinco
  segundos mientras la pestaña está visible, y al pulsar **Actualizar ahora**.
  El enlace **Actualizar listado de observaciones** vuelve a cargar el HTML
  seguro que ofrece revelar individualmente por POST con CSRF y nonce único.
- `IN_MEMORY` indica que una proyección in-process fue inyectada; **no afirma**
  conexión real con Boca/Queue-it. `NOT_CONNECTED` muestra explícitamente que
  no hay origen de observaciones asociado al controlador. Sin fuentes, el
  contador permanece cero; no se fabrican resultados ni tráfico a terceros.
- No se toca el worker, socket, Docker, SITE_URL, scripts de login, Queue-it,
  autenticación, compra ni políticas de host. La visualización es metadata
  pasiva y no proporciona atajos o validación de pases.

## Pruebas y aceptación

La suite de `tests/test_private_token_monitor.py` primero reprodujo los
faltantes (404 en snapshot, controles de refresco ausentes) en RED. El candidato
debe comprobar 401 sin sesión, valores JSON acotados sin secretos ni URLs,
estado sin productor transparente y cero llamadas al motor. La aceptación
de la vista requiere el SHA final, controles CI y posterior instalación
protegida con comprobación física aparte; **CODE_ONLY no es deploy**.
