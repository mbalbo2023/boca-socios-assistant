# A45-R179 — QA funcional independiente del panel y del motor Boca

Fecha: 2026-11-11 (ART). Alcance: `boca-socios-assistant` exclusivamente.
Se excluyen sitio real de socios, reservas y cualquier operación sobre Docker,
Porota o servicios externos. Las pruebas nuevas sólo usan WSGI, SQLite y
autenticación artificiales, sin listener ni red.

## Base y pruebas reproducibles

- `origin/main` actualizado y observado: `ce77979` (PR #480 R178). El árbol
  del candidato R178 `252007e` contra este `main` es idéntico (`git diff
  origin/main HEAD` vacío), aunque sus ancestrías de commits son distintas.
- Suite completa configurada por `pyproject.toml`:
  `uv run --frozen pytest -q -n 4 --tb=line` → **6933 passed, 1 skipped,
  34 subtests passed, 0 failed (52,00 s)**. Único SKIP: prueba AF_UNIX real
  R177 por `EPERM` de sandbox; requiere Linux/CI para prueba física.
- Suite focal de panel/socios/SITE_URL/actividad, lifecycle, IPC, Telegram y
  egress: **162 passed, 5 subtests passed (39,30 s)**.
- `tests/test_r179_functional_journey.py`: **2 passed**. Integra login
  passkey local → formulario → persistencia cifrada → listado/actividad y
  pantalla Telegram; comprueba que no nacen `ticket_requests`, outbox, wake,
  llamadas del host, ni datos sensibles en proyecciones. POST de origen ajeno
  devuelve 403 sin escribir el socio. No supone real accesibilidad ni servicio.
- Los módulos históricos `browser.synthetic` y `browser.ipc_worker` siguen
  expresamente excluidos por `pyproject.toml` y `tests/conftest.py`. Ejecutar
  manualmente `tests/test_browser_ipc.py` fuerza un error de importación por
  ese guard; **no es fallo del runner normal ni certificación del blackbox**.

## Mapa de trazabilidad (no confundir CODE_ONLY con físico)

| Frente | Código y resultado local | Estado físico aún requerido |
| --- | --- | --- |
| Socios/formulario | `panel.enrollment_http` valida sesión, Origin exacto, CSRF, operación, consentimiento; `security.enrollment` cifra credencial y escribe `members`/`credentials`; la prueba R179 confirma alta sin ticket ni aviso | En `8443` release exacto, login Chrome con passkey real, alta sintética consentida, lectura persistida/reinicio y aislamiento del volumen SQLite; no importar datos reales en smoke |
| Panel privado/8443 | `panel.private_http`, `owner_sessions`, `owner_session_store` y aceptación WSGI cubren 401, permisos, revocación, cookie persistente y Origin | Túnel privado a `localhost:8443`, passkey real, `GET /healthz`, sesión tras restart del controller y 401 después de logout, en la revisión instalada |
| SITE_URL | `panel.site_url_settings` almacena URL HTTP(S) pública o privada; `browser.site_url_runtime` publica espejo sólo-URL para UID worker; START rehúsa origen/espejo divergentes | Guardar URL no transaccional controlada, comprobar ambos inodes/digest/lectura por UID10002 y que el START consume esa revisión en el par nuevo; último inode de SQLite sigue sin certificación física por el frente infra |
| Bot bajo demanda e IPC | `panel.bot_control` despierta host tras intención durable; `integration.beta.OnDemandBotSession` requiere START/CLAIMED/APPLIED; `browser.ipc_client` usa SO_PEERCRED, STOP y timeout. `PROBE_FIXTURE` es opt-in y no reserva | Control owner START → worker `running/healthy` → socket AF_UNIX real y UID/gid, lectura de recibo host → owner STOP → worker detenido y sin IPC huérfano; repetir en release exacto |
| Simulador/navegación | `browser.ipc_server.OfflineNoGoExecutor` sigue predeterminado. RUN transaccional = NO_GO; fixture inventado opt-in = FIXTURE_OBSERVED. Los estados `ObservationStatus` nunca son reserva | No hay adaptador probado de navegación HTTP(S) de sandbox bajo este START: **pendiente funcional específico**. No simular tokens, acceso real, reservas ni `SUCCESS` del motor sin evidencia |
| Actividad | `panel.worker_activity` combina audit host, comandos y telemetría Chromium sólo con etiquetas permitidas y vistas owner-only; nueva prueba confirma ausencia de email/clave | En el nuevo par comprobar orden y marcas temporales START → IPC/fixture → STOP en `/control/actividad(.json)` y diferenciar timestamps antiguos de proceso activo |
| Telegram | `telegram_setup_ui` cifra localmente y `telegram_pairing_staging` requiere WebAuthn/operación; `notify.telegram_worker` es opt-in separado; `TelegramDeliveryCoordinator` usa pre-send fence y se detiene ante ack incierto | Emparejamiento real cifrado autorizado, custodia y pin de bot/chat, one-shot API `api_accepted` **más confirmación humana** de recepción. OFF por defecto y sin envío durante QA R179 |
| Internet worker | `compose.beta.browser.yaml` define sólo bridge Boca egress `internal:false`; `browser.egress_probe` tiene diagnóstico a example.com con IPv4 pinneada, TLS y HEAD sin SITE_URL | Worker corriente `running/healthy` y recibo de Action `beta-browser-egress-readonly` DNS+TLS+HTTPS; smoke offline `--network none` no prueba salida normal |

## Stoppers físicos y orden de aceptación

1. **Par instalado histórico vs nuevo:** un `controller` sano no certifica
   worker. Captura anterior R177 describía worker viejo `network_name=none`,
   `exited/exit=1`; obtener evidencia del pair nuevo tras upgrade selectivo.
2. **Identidad/inode SQLite y montajes:** revalidar volumen Boca de datos,
   sesión passkey, configuración SITE_URL y socket IPC en la misma versión
   antes de cualquier START o migración. Estado físico previo: UNVERIFIED;
   no convertir `verify_schema()` de pruebas locales en GO de droplet.
3. **Arranque y STOP reales:** solicitar desde owner autenticado; atestar
   CID/UID/red rootless, recibo host `APPLIED` y sockets, luego STOP y
   proceso detenido. Confirmar rutas no autorizadas y accesibilidad privada.
4. **Egress:** ejecutar diagnóstico neutro sólo sobre worker que está RUNNING,
   con Action protegida y sin visitar SITE_URL ni sitio de socios.
5. **Telegram:** procedimiento protegido opt-in separado y, si el dueño lo
   solicita, recepción de heartbeat sintético; no emitir tokens/IDs en logs.
6. **Alcance funcional real:** formulario local y fixture NO equivalen a
   navegación sandbox ni reservas. Hace falta un adaptador observador HTTP(S)
   opt-in con contratos y tests propios; no está certificado ni se autoriza
   el sitio real dentro de este QA.

**Criterio de cierre:** para cada fila dejar recibo del SHA instalado, Action
con hora/CID/digest cuando aplique y resultado observado en UI; de lo
contrario etiqueta `FISICO_PENDIENTE` o `NO_GO`, jamás `GREEN` por CI local.
