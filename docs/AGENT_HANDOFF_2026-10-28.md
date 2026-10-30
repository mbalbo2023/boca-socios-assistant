# Relevo histórico de Boca Socios Assistant hacia una BETA operativa

**Corte:** 2026-10-28, America/Argentina/Buenos_Aires. Esta es una foto
verificada de GitHub. Los SHA, conteos y estados de PR de abajo son evidencia
de ese corte, no instrucciones vigentes ni prueba de gates actuales. Al
retomar, comprobá de nuevo main, PRs, Issues, Actions y protección. La
integración de #30 y sus límites se documentan en
[BETA_INTEGRATION_STATUS.md](BETA_INTEGRATION_STATUS.md).

**Continuidad desde 2026-10-29:** [ADR 0038](ADR/0038-agent-review-and-operations.md)
reemplazó el requisito de aprobación humana por revisión técnica registrada
del agente y checks de la HEAD exacta. La dirección permanente del dueño
permite operar la simulación mediante el único Actions manual de Boca cuando
esté integrado y sus gates objetivos estén probados; un merge no despliega.
El diseño de alta [#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28)
fue revisado técnicamente y fusionado el 2026-10-29 en horario de Argentina;
no habilita credenciales reales ni un endpoint. Revalidá el resto del estado
antes de actuar.

## Mandato y límites

Una visita anónima y directa a la página pública real se consumó en esta fase.
El diagnóstico acotado y de sólo lectura de una fuente pública se hace primero
por Actions cuando se necesite verificarla antes de un nuevo despliegue. Una
observación interactiva, un recorrido autenticado o una reserva real son hitos
distintos y no están habilitados por la simulación. No solicitar ni recibir
contraseñas en chat. La supervisión automática fue desactivada a pedido del
dueño; no la reactives.

Leé completos [AGENTS.md](../AGENTS.md), [README.md](../README.md),
[DEVELOPMENT_POLICY.md](DEVELOPMENT_POLICY.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [OPERATIONS.md](OPERATIONS.md) y los ADRs de cada
alcance. Una rama/PR por issue, revisión técnica registrada y CI exacta antes
de fusionar. Toda operación en el droplet se hace **sólo por GitHub Actions
dedicado a Boca**, con SHA, digest inmutable para instalar, SSH fijado,
entorno protegido, aislamiento rootless y recursos comprobados. No modificar
Porota Trading ni PPI Watch. Una sola entrada por socio y partido; no evadir
Queue-it, CAPTCHA ni controles.
No presentar simulación o arranque offline como reserva real.

El usuario opera tablet Android y iPhone con control por voz. Las futuras
instrucciones y la interfaz deben ser accesibles y evitar secuencias largas
de comandos o uso repetido del portapapeles.

## Estado verificable en GitHub

- `main` **al corte**: `09f390e483a9ad93caf460cb6e161fee22e6bd8d`,
  fundamento **SIMULATION_ONLY**. Ninguno de los cambios siguientes estaba
  fusionado entonces; varios llegaron posteriormente a main.
- [Issue #10](https://github.com/mbalbo2023/boca-socios-assistant/issues/10)
  estaba abierto: el ruleset de protección de main no estaba verificado como
  activo. Los 25 PRs abiertos consultados, incluidos los cinco Dependabot,
  no tenían revisiones registradas al corte. ADR 0038 sustituyó el gate de
  aprobación humana por revisión técnica del agente. El ruleset `protect-main`
  se verificó activo posteriormente, con cero aprobaciones exigidas; ver
  [GITHUB_SETUP.md](GITHUB_SETUP.md).
- Al corte, ningún despliegue ni operación en el droplet se había ejecutado.
  No existía aún workflow de despliegue aprobado para Boca.

| Línea | PRs, base y evidencia | Estado al corte, salvo actualización indicada |
| --- | --- | --- |
| Fuentes de componentes | [#18](https://github.com/mbalbo2023/boca-socios-assistant/pull/18), [#19](https://github.com/mbalbo2023/boca-socios-assistant/pull/19), [#20](https://github.com/mbalbo2023/boca-socios-assistant/pull/20), [#21](https://github.com/mbalbo2023/boca-socios-assistant/pull/21), [#22](https://github.com/mbalbo2023/boca-socios-assistant/pull/22), [#23](https://github.com/mbalbo2023/boca-socios-assistant/pull/23), [#26](https://github.com/mbalbo2023/boca-socios-assistant/pull/26); [#15](https://github.com/mbalbo2023/boca-socios-assistant/pull/15) es protocolo aparte | Al corte estaban abiertos y sin revisión; el viaje sintético #26 no prueba Boca. Después se revisaron e integraron individualmente. |
| Integración interna | [#30](https://github.com/mbalbo2023/boca-socios-assistant/pull/30) desde main → [#34](https://github.com/mbalbo2023/boca-socios-assistant/pull/34) → [#36](https://github.com/mbalbo2023/boca-socios-assistant/pull/36) → [#38](https://github.com/mbalbo2023/boca-socios-assistant/pull/38) → [#40](https://github.com/mbalbo2023/boca-socios-assistant/pull/40) → [#42](https://github.com/mbalbo2023/boca-socios-assistant/pull/42) | Al corte eran borradores apilados. #36: 144 tests; #38: 150; #40/#42: 157 tests locales. CI histórica de #42 [40779759406](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40779759406) verde; no acredita su HEAD actual. Sin runtime real. |
| Alta segura | [#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28) diseño → [#31](https://github.com/mbalbo2023/boca-socios-assistant/pull/31) servicio cifrado interno | El diseño #28 se revisó y fusionó después del corte. #31 no es formulario, no autentica administrador ni valida identidad Boca. No cargar contraseñas. |
| Panel y avisos | [#29](https://github.com/mbalbo2023/boca-socios-assistant/pull/29) panel de estados simulados; #34 outbox SQLite | Panel no conectado a una API privada; outbox no entrega Telegram ni confirma Boca. |
| Observador público | [#33](https://github.com/mbalbo2023/boca-socios-assistant/pull/33) HEAD `577c52656cbd90d2f6f308340405c456b065a9ce`, CI [40777337319](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40777337319) verde, 42 tests locales | Una sola navegación opt-in a `/auth/login`, JavaScript deshabilitado, redirecciones y tráfico adicional bloqueados. **El script no fue ejecutado contra Boca**. |
| Worker Chromium | [#43](https://github.com/mbalbo2023/boca-socios-assistant/pull/43) apilado en #33, HEAD `9a6311d2be22de76d8f5cf609cba0f46c9e67eb2`, CI [40779396413](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40779396413) verde, 45 tests locales | Imagen separada con Playwright/Chromium 1.64.1, índice base `sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031`. CI arranca/cierra Chromium **sin red**; no despliegue ni visita a Boca. |
| Un solo navegador medido | [#44](https://github.com/mbalbo2023/boca-socios-assistant/pull/44) apilado en #43, HEAD `7106210be6c7d007af45ce547ee116b5c91bfd4a`, CI [40780641087](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40780641087) verde, 53 tests locales | En CI, un arranque offline: 185,2 MiB de memoria pico, 76 tareas pico, 714 ms CPU y 834 ms transcurridos, con límites 768 MiB/128 PIDs/1 CPU. No estima Boca ni el droplet. |

Los cinco PRs Dependabot [#1–#5](https://github.com/mbalbo2023/boca-socios-assistant/pulls)
estaban abiertos al corte; evaluarlos por separado, sin merge automático.
Las ramas de integración y de navegador formaban **dos líneas apiladas
distintas**; el antiguo árbol de #42 no contenía #33/#43/#44. Ver
[BETA_COMPONENT_GATE.md](BETA_COMPONENT_GATE.md) y [ROADMAP.md](ROADMAP.md).

**Revalidación del 2026-10-30 (UTC):** `main` en
`acea211b9346a521a5568dcdc9cfd181088ae506` integra las fuentes #18–#23,
#26, #28–#31, #33, #34 y el worker offline #43; también el semáforo manual
#96 y la actualización Node 24 #104. El ruleset `protect-main` está activo
con PR, checks y conversaciones resueltas; no exige aprobación humana.
#36, #38, #40 y #44 siguen abiertos como borradores, cada uno con revisión
técnica y CI actual pendientes de su integración. El PR #42 actual se limita
a documentación y ya no arrastra la pila de código de aquel corte. Ninguna
de estas integraciones habilita credenciales reales, reserva ni despliegue.

## Qué se vio en Boca

Una visita anónima desde la raíz terminó en
`https://bocasocios.bocajuniors.com.ar/auth/login`. Una visita directa
posterior a esa ruta mostró correo, contraseña, recuperación, activación
y el botón «INICIAR SESIÓN» deshabilitado sin datos. Fueron vistas en
navegador normal con JavaScript: no se completó ningún campo ni se hizo
login. No se observó cola, elegibilidad, sector, disponibilidad, pase ni
reserva. **No se ejecutó el script #33** con red real; puede devolver
`unknown` si la página requiere JavaScript. La visita directa anterior ya se
hizo. Para incidentes de fuente pública, usá primero el diagnóstico acotado
de Actions; una nueva visita interactiva exige entorno y egress revisados.

## Pendientes en orden de dependencia

1. **Gobernanza.** El diseño #28 y las fuentes #18–#23/#26 ya obtuvieron
   revisión técnica y se fusionaron. Para los PRs pendientes, registrar
   revisión técnica, revalidar la protección activa de main (#10), resolver
   conversaciones y comprobar checks exactos de la HEAD. No fusionar
   borradores ni usar la CI histórica de la pila como sustituto.
2. **Privacidad y alta.** Con el diseño #28 fusionado, construir formulario
   privado accesible desde tablet/voz con TLS, autenticación/autorización de
   administrador, CSRF, vencimiento de sesión, consentimiento, borrado y
   auditoría mínima sin datos sensibles. Vincular un identificador de socio
   externo verificado a la identidad interna, con unicidad. Probar backup
   cifrado, restauración, permisos y custodia/rotación de clave fuera de
   repositorio, Actions, logs y conversación. Avisar al dueño **sólo cuando
   el canal seguro completo esté revisado** para que ingrese las credenciales
   una vez directamente allí.
3. **Navegador público.** #33 y #43 están integrados; revisar #44 y mantener
   el sandbox efectivo y egress de sistema limitado al host HTTPS público. La
   próxima prueba opt-in del script contra Boca es un hito distinto del diagnóstico de fuente
   pública por Actions; requiere entorno y egress revisados y detenerse en
   redirect, JS indispensable, cola, CAPTCHA, bloqueo o estado desconocido.
   No usar CI recurrente para visitar Boca.
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
   manual de Actions exclusivo Boca. Para la simulación, comprobar SHA y
   digest inmutable, SSH fijado, entorno protegido, aislamiento rootless y
   capacidad antes de instalar. Serializar operaciones y registrar decisión
   separada de release e instalación. Ante un fallo, inventariar disco e
   inodos; retirar por Actions sólo remanentes Boca identificados como
   descartables y sin uso. No tocar otros contenedores, volúmenes ni redes.

## Definición de evidencia y primera tarea útil

Los comandos locales de calidad son `uv sync --frozen`,
`uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy src`, `uv run pytest -q` y
`uv run python scripts/check_repo_policy.py`. Actions construyó el
controlador y, en #43/#44, el worker aislado; ningún test visitó Boca desde
CI. No había Docker local en aquel entorno. Esas cifras pertenecen al corte;
el diseño #28 y la política ADR 0038 llegaron después a main. El diagnóstico
público manual por Actions #96 también se integró; no es visita recurrente de
CI. Una fuente
externa fallida se informa con hora y semáforo verde/amarillo/rojo/desconocido;
no bloquea por sí misma un despliegue seguro de simulación ni justifica otro.

Al retomar, verificá primero si algún PR/issue/check cambió; recuperá el
trabajo existente, no abras duplicados. La siguiente decisión de merge exige
revisión técnica y CI exacta; revalidar la protección efectiva de #10.
Mientras tanto, pueden prepararse PRs pequeños de diseño/backup, borrado y
tests de notificaciones o escaneo de imagen que no expongan endpoints ni activen
operaciones externas. Informá cada etapa con prueba, limitaciones y NO-GO/GO.

**Instrucción breve para el siguiente agente:** «Continuá Boca Socios
Assistant desde este handoff histórico de GitHub y ADR 0038. Reauditá main,
PRs, Issues y Actions; retomá pendientes sin duplicar trabajo. Revisión
técnica registrada y CI exacta para merge; operación autónoma de simulación
sólo por Actions con gates objetivos. Sin credenciales ni reserva real».
