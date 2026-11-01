# Resiliencia de comandos de la BETA — evidencia sintética de #228

**Alcance:** simulación aprobada, SQLite temporal, panel privado local y
puerto de navegador sintético. Este documento vincula pruebas que ya existían
con las fronteras de reinicio y fallo agregadas en #228. No habilita acciones
reales sobre Boca, Telegram ni el droplet.

## Invariantes y trazabilidad

| Riesgo de primera BETA | Prueba de regresión | Criterio seguro |
| --- | --- | --- |
| Browser detenido en ejecución y parada por el usuario | `test_beta_served_acceptance.py::test_loopback_http_stop_cancels_worker_and_survives_restart`; `test_beta_commands.py::BetaCommandTests::test_stop_running_cancels_without_rearming_guard` | Cancelación, estado `stopped`, ningún aviso ni segunda ejecución tras reinicio |
| Excepción del adaptador y reintento después de reinicio | `test_beta_served_acceptance.py::test_loopback_http_failed_browser_is_redacted_and_not_retried_after_restart` | HTTP expone `failed`, no filtra texto privado, no publica aviso y el nuevo UUID reutiliza el comando original |
| Timeout del navegador | `test_beta_commands.py::BetaCommandTests::test_timeout_is_terminal_and_never_retried`; `test_timeout_survives_restart_and_new_alias_without_retry_or_notice` | `failed` terminal, sin retry aun con nuevo UUID en una instancia posterior |
| Proceso interrumpido entre claim y resultado | `test_beta_served_acceptance.py::test_loopback_http_interrupted_command_recovery_does_not_replay_browser[ambiguous-running]` | Guard sin resolución lleva a `needs_review` visible sólo tras autenticación, browser cero veces |
| Proceso interrumpido después del resultado y antes del aviso | `test_beta_served_acceptance.py::test_loopback_http_interrupted_command_recovery_does_not_replay_browser[completed-before-notice]` | Un aviso local durable, estado `completed` y browser cero veces, incluso tras dos reinicios |
| Un único ticket sintético por socio y evento | Los tres casos nuevos de HTTP; `test_beta_commands.py::BetaCommandTests::test_repeated_keys_and_member_event_aliases_never_repeat_browser` | UUID alternativo apunta al comando canónico; `ticket_requests.quantity=1` y una fila para el par socio/evento |
| Restricción de sesiones y permisos de panel | Los casos HTTP de reinicio; `test_private_beta_panel.py` | Cookie antigua no válida, rutas privadas requieren nueva passkey; CSRF y origen ajeno denegados |
| Outbox offline persistente, sin duplicados ni envíos reales | `test_beta_commands.py::BetaCommandTests::test_notice_failure_is_recovered_without_repeating_browser`; `test_notification_outbox.py`; `test_sqlite_outbox.py` | Notice-id deduplicado, lease y reintentos controlados; cero o un aviso conforme al guard |
| Exclusividad y límite del worker | `test_beta_commands.py::BetaCommandTests::test_two_service_instances_share_global_one_browser_claim`; `test_pending_capacity_rolls_back_new_intent` | Una única ejecución simultánea y rollback seguro ante límite |

Los tests nuevos **siembran estados SQLite de interrupción**, no matan un
proceso real ni ejercen Docker. Cada `LocalBetaRuntime.start(...,
initialize_new=False)` vuelve a abrir el mismo esquema sin migración
implícita. El HTTP servido usa exclusivamente `127.0.0.1` con puerto efímero
de pruebas y un gateway WebAuthn sintético: **no es TLS ni aceptación Chrome**.
La implementación real mantiene para la futura BETA sólo
`127.0.0.1:8443` por túnel SSH, sin modificar servidor web, otros puertos,
contenedores o apps del droplet.

## Ejecución local y gate requerido

```bash
uv sync --frozen --no-group browser
uv run pytest -q tests/test_beta_served_acceptance.py tests/test_private_beta_panel.py tests/test_beta_commands.py tests/test_notification_outbox.py tests/test_sqlite_outbox.py tests/test_local_beta_runtime.py tests/test_beta_command_host.py tests/test_beta_enrollment_journey.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python scripts/check_repo_policy.py
```

En el ambiente local del 2026-11-01, el subconjunto de ocho módulos terminó
con **70 pruebas y 10 subtests aprobados en 9,14 s** cuando se permitió la
comunicación local entre los threads del host y el socket loopback. El sandbox
que prohíbe red bloquea estos mismos recorridos; **no** se debilitó ningún
timeout ni aserción para tolerarlo. Esa ejecución local no reemplaza el CI
requerido sobre el **SHA exacto del PR**, la revisión técnica independiente
ni la aceptación protegida antes de operar en el droplet.

La prueba sólo demuestra regresiones de lógica sintética y persistencia. No
comprueba disponibilidad real de Chrome/passkey, enlace de un solo uso,
Telegram remoto, condiciones de instalación protegida, accesibilidad móvil,
rendimiento en el host ni interacción con el sitio Boca. Esos recibos deben
adjuntarse al [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
en sus etapas respectivas; no se permite afirmar una beta operativa a partir
de estas suites solamente.
