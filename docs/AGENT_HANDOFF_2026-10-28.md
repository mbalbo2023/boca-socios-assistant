# Relevo para continuar Boca Socios Assistant hasta una BETA operativa

**Corte:** 2026-10-28, America/Argentina/Buenos_Aires. Esta es una foto
verificada de GitHub, no permiso para fusionar, usar cuentas reales ni
desplegar. Al retomar, comprobá de nuevo main, PRs, Issues, Actions y reglas
de protección; no tomes los SHA de este documento como estado eterno.

## Mandato y límites

El dueño autorizó **desarrollo y pruebas en ramas y PRs**. Una visita
anónima y directa a la página pública real ya se consumó en esta fase.
Para otra visita real con el script, un recorrido autenticado, una reserva,
una fusión o un despliegue, obtené la autorización que corresponda al alcance
concreto después de preparar un candidato revisable. No solicitar ni recibir
contraseñas en chat. La supervisión automática fue desactivada a pedido del
dueño; no la reactives.

Leé completos [AGENTS.md](../AGENTS.md), [README.md](../README.md),
[DEVELOPMENT_POLICY.md](DEVELOPMENT_POLICY.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [OPERATIONS.md](OPERATIONS.md) y los ADRs de cada
alcance. Una rama/PR por issue, pruebas y CI del candidato, revisión humana
antes de fusionar. Toda operación futura en el droplet se hace **sólo por
GitHub Actions dedicado a Boca**, con aprobación específica de imagen/digest,
SHA, recursos y aislamiento. No modificar Porota Trading ni PPI Watch. Una
sola entrada por socio y partido; no evadir Queue-it, CAPTCHA ni controles.
No presentar simulación o arranque offline como reserva real.

El usuario opera tablet Android y iPhone con control por voz. Las futuras
instrucciones y la interfaz deben ser accesibles y evitar secuencias largas
de comandos o uso repetido del portapapeles.

## Estado verificable en GitHub

- `main`: `09f390e483a9ad93caf460cb6e161fee22e6bd8d`, fundamento
  **SIMULATION_ONLY**. Ninguno de los cambios siguientes está fusionado.
- [Issue #10](https://github.com/mbalbo2023/boca-socios-assistant/issues/10)
  sigue abierto: el ruleset de protección de main no está verificado como
  activo. Los 25 PRs abiertos consultados, incluidos los cinco Dependabot,
  no tenían revisiones registradas al corte. Un revisor independiente del
  autor es necesario para el gate humano.
- Ningún despliegue ni operación en el droplet se ejecutó. No existe aún
  workflow de despliegue aprobado para Boca.

| Línea | PRs, base y evidencia | Estado real |
| --- | --- | --- |
| Fuentes de componentes | [#18](https://github.com/mbalbo2023/boca-socios-assistant/pull/18), [#19](https://github.com/mbalbo2023/boca-socios-assistant/pull/19), [#20](https://github.com/mbalbo2023/boca-socios-assistant/pull/20), [#21](https://github.com/mbalbo2023/boca-socios-assistant/pull/21), [#22](https://github.com/mbalbo2023/boca-socios-assistant/pull/22), [#23](https://github.com/mbalbo2023/boca-socios-assistant/pull/23), [#26](https://github.com/mbalbo2023/boca-socios-assistant/pull/26); [#15](https://github.com/mbalbo2023/boca-socios-assistant/pull/15) es protocolo aparte | Abiertos, sin revisión; el viaje sintético #26 no prueba Boca. #30 recupera el código fuente sin sustituir su revisión individual. |
| Integración interna | [#30](https://github.com/mbalbo2023/boca-socios-assistant/pull/30) desde main → [#34](https://github.com/mbalbo2023/boca-socios-assistant/pull/34) → [#36](https://github.com/mbalbo2023/boca-socios-assistant/pull/36) → [#38](https://github.com/mbalbo2023/boca-socios-assistant/pull/38) → [#40](https://github.com/mbalbo2023/boca-socios-assistant/pull/40) → [#42](https://github.com/mbalbo2023/boca-socios-assistant/pull/42) | Borradores apilados. #36: 144 tests; #38: 150; #40/#42: 157 tests locales. CI de #42 publicada antes de este relevo: [40779759406](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40779759406) verde. Sin runtime real. |
| Alta segura | [#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28) diseño → [#31](https://github.com/mbalbo2023/boca-socios-assistant/pull/31) servicio cifrado interno | #28 requiere revisión humana **antes de un endpoint expuesto**. #31 no es formulario, no autentica administrador ni valida identidad Boca. No cargar contraseñas. |
| Panel y avisos | [#29](https://github.com/mbalbo2023/boca-socios-assistant/pull/29) panel de estados simulados; #34 outbox SQLite | Panel no conectado a una API privada; outbox no entrega Telegram ni confirma Boca. |
| Observador público | [#33](https://github.com/mbalbo2023/boca-socios-assistant/pull/33) HEAD `577c52656cbd90d2f6f308340405c456b065a9ce`, CI [40777337319](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40777337319) verde, 42 tests locales | Una sola navegación opt-in a `/auth/login`, JavaScript deshabilitado, redirecciones y tráfico adicional bloqueados. **El script no fue ejecutado contra Boca**. |
| Worker Chromium | [#43](https://github.com/mbalbo2023/boca-socios-assistant/pull/43) apilado en #33, HEAD `9a6311d2be22de76d8f5cf609cba0f46c9e67eb2`, CI [40779396413](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40779396413) verde, 45 tests locales | Imagen separada con Playwright/Chromium 1.64.1, índice base `sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031`. CI arranca/cierra Chromium **sin red**; no despliegue ni visita a Boca. |
| Un solo navegador medido | [#44](https://github.com/mbalbo2023/boca-socios-assistant/pull/44) apilado en #43, HEAD `7106210be6c7d007af45ce547ee116b5c91bfd4a`, CI [40780641087](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40780641087) verde, 53 tests locales | En CI, un arranque offline: 185,2 MiB de memoria pico, 76 tareas pico, 714 ms CPU y 834 ms transcurridos, con límites 768 MiB/128 PIDs/1 CPU. No estima Boca ni el droplet. |

Los cinco PRs Dependabot [#1–#5](https://github.com/mbalbo2023/boca-socios-assistant/pulls)
también están abiertos; evaluarlos por separado, sin merge automático.
Las ramas de integración y de navegador forman **dos líneas apiladas
distintas**: no afirmar que #42 ya contiene #33/#43/#44. Ver
[BETA_COMPONENT_GATE.md](BETA_COMPONENT_GATE.md) y [ROADMAP.md](ROADMAP.md).

## Qué se vio en Boca

Una visita anónima desde la raíz terminó en
`https://bocasocios.bocajuniors.com.ar/auth/login`. Una visita directa
posterior a esa ruta mostró correo, contraseña, recuperación, activación
y el botón «INICIAR SESIÓN» deshabilitado sin datos. Fueron vistas en
navegador normal con JavaScript: no se completó ningún campo ni se hizo
login. No se observó cola, elegibilidad, sector, disponibilidad, pase ni
reserva. **No se ejecutó el script #33** con red real; puede devolver
`unknown` si la página requiere JavaScript. La visita directa autorizada
en la fase anterior ya se hizo; una nueva ejecución real debe aprobarse
por separado con entorno y egress revisados.

## Pendientes en orden de dependencia

1. **Gobernanza.** Obtener revisión humana independiente del diseño #28 y
   de cada PR fuente; activar y comprobar protección efectiva de main (#10).
   Revalidar checks en el merge candidate actualizado. No fusionar borradores
   ni usar #30/#36 como sustituto de la revisión de origen.
2. **Privacidad y alta.** Tras aprobar el diseño #28, construir formulario
   privado accesible desde tablet/voz con TLS, autenticación/autorización de
   administrador, CSRF, vencimiento de sesión, consentimiento, borrado y
   auditoría mínima sin datos sensibles. Vincular un identificador de socio
   externo verificado a la identidad interna, con unicidad. Probar backup
   cifrado, restauración, permisos y custodia/rotación de clave fuera de
   repositorio, Actions, logs y conversación. Avisar al dueño **sólo cuando
   el canal seguro completo esté revisado** para que ingrese las credenciales
   una vez directamente allí.
3. **Navegador público.** Revisar #33 → #43 → #44, mantener el sandbox efectivo
   y egress de sistema limitado al host HTTPS público. La próxima prueba
   opt-in del script contra Boca requiere autorización nueva y entorno no
   productivo; detener en redirect, JS indispensable, cola, CAPTCHA,
   bloqueo o estado desconocido. No usar CI recurrente para visitar Boca.
4. **Flujo de reserva.** Diseñar y revisar un recorrido autenticado con una
   cuenta consentida, sin credenciales en chat, y una conciliación humana de
   resultados ambiguos. Conectar el guard #38 al único intento externo por
   socio/partido y verificar identidad/eligibilidad real; el guard local no
   demuestra idempotencia del proveedor. La simulación no confirma compra.
   Cualquier reserva real es una autorización separada; no evadir controles.
5. **Operación de usuario.** Conectar panel accesible y estados reales
   revisados, notificaciones con entrega y deduplicación verificables,
   horarios de Argentina y trazas redactadas. Probar reinicios, fallos,
   accesos indebidos y una sesión real autorizada sin carga sobre Boca.
6. **Docker y despliegue.** Revisar imagen/scan, presupuesto de recursos del
   host aislado, backups/restauración, health/rollback y un **único** workflow
   manual de Actions exclusivo Boca. Preparar candidato SHA + digest + plan de
   recursos para aprobación específica del dueño antes de cualquier preflight
   u operación en droplet. No tocar otros contenedores, volúmenes ni redes.

## Definición de evidencia y primera tarea útil

Los comandos locales de calidad son `uv sync --frozen`,
`uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy src`, `uv run pytest -q` y
`uv run python scripts/check_repo_policy.py`. Actions sólo construyó el
controlador y, en #43/#44, el worker aislado; ningún test visitó Boca desde
CI. No hay Docker local en este entorno. Todos los PRs siguen sin revisión
humana y main no recibió los cambios.

Al retomar, verificá primero si algún PR/issue/check cambió; recuperá el
trabajo existente, no abras duplicados. La **primera decisión bloqueante** es
la revisión independiente de #28 y la activación de #10. Mientras tanto,
pueden prepararse PRs pequeños de diseño/backup, borrado y tests de
notificaciones o escaneo de imagen que no expongan endpoints ni activen
operaciones externas. Informá cada etapa con prueba, limitaciones y NO-GO/GO.

**Instrucción breve para el siguiente agente:** «Continuá Boca Socios
Assistant desde este handoff de GitHub. Reauditá main, PRs, Issues y Actions;
retomá los pendientes por prioridad sin duplicar trabajo. Desarrollo sólo
en ramas/PRs y pruebas; no credenciales, fusión, reserva real ni droplet sin
las revisiones y autorizaciones específicas indicadas aquí».
