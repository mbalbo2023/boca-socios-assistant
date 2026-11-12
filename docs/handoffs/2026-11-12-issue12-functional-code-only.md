# Issue #12 — handoff funcional aislado al responsable de #417

**Corte:** 12/11/2026 (ART). **Alcance:** CODE_ONLY, simulación y pruebas
locales offline. **Estado externo/físico:** NO_GO. Ni tokens ni URLs externas
fueron comprobados. **No desplegar este parche aisladamente**: el propietario
de #417 decide integración en un **único despliegue** tras revisión, merge,
CI exact-SHA y validaciones físicas pertinentes.

## Origen, recuperación y trazabilidad

- Main reconciliado al iniciar: `b8f9a8c8daa246ea39fd206397ec27fd6bcf652b`.
- Predecesor de preferencias de sector:
  `c86059ef91c65446f4e0999c370124affd43b595`.
- Rama `feature/12-member-profile-sectors-20261111`:
  `d56235c4260ab0db33eae7d37ef5fd2ca7e39328`.
- Rama `feature/12-private-token-view-contract-20261111`:
  `c1b25cb07807c586b7c218fc49efb7ea14070e3d`.
- `051b9a2` no se encontró en refs recuperables: reconstruimos solo las
  interfaces faltantes y las pruebas nuevas; no afirmamos recuperar su
  contenido ni su SHA.
- Rama nueva exclusiva: `feature/12-functional-token-flows-20261112`.
  El HEAD remoto exacto y sus checks deben tomarse del PR, no de este corte
  prepublicación.

La recuperación se hizo por delta exacto de los tres commits de #12 sobre
main, sin incorporar los ancestros de infraestructura del issue #417 ni
archivos de otros scopes. Se conservaron los contratos del lateral SQLite
para sectores, su formulario en la ficha existente y el objeto de estado
Queue-it original. No hay migración silenciosa de `0008`.

## Contenido funcional

| Circuito | Fuente real exigida | Entrega disponible hoy | Ausencias deliberadas |
| --- | --- | --- | --- |
| Queue-it | URL completa previamente observada por un adaptador autorizado, con `queueittoken` en query | Parser puro, estado in-memory por socio/evento/sesión, URL exacta y token para copia bajo passkey | Sin adaptador real, validación de URL/token, fila, salto ni navegación |
| Boca | Socio ya enrolado en SQLite; vault AES-GCM; bytes de respuesta de transporte inyectado | Lectura y descifrado reales de fixtures SQLite; parser estricto de `token` + `refreshToken`; canal privado independiente | Sin endpoint inventado, sin transporte activo, sin autenticación online y sin refresh automático |
| Sectores | Socio de SQLite y fichero lateral provisionado explícitamente | Preferencias `ALL`/lista ordenada en pantalla preexistente; pruebas de persistencia local | No instalación del lateral ni cambios de Docker/migración de base legacy |

El nuevo panel `/monitor/tokens` usa el autenticador de llave de acceso ya
existente; `local-status:read` para ver estados y `simulation:write`, Origin
exacto, CSRF y nonce de un solo uso para `Mostrar completo`. Los valores
completos solo aparecen en una respuesta privada `no-store`, con copia
deliberada desde controles accesibles. Los resúmenes y `repr` no contienen
secretos. No se persisten tokens. Los monitores son procesos volátiles y no
arrancan el bot, Chromium, la cola o la navegación legacy.

## Evidencia y alcance de TDD

- **RED previo reproducido:** módulos de Queue-it, autenticación y rutas del
  monitor inexistentes antes de implementación; caso sin URL devolvía 404,
  corregido a copia de token + indicación de URL no observada.
- **GREEN focalizado, solo offline:** sector/perfil recuperado, contrato de
  cola, SQLite-vault con transporte fake inyectado, dos vistas de tokens,
  acceso/CSRF/Origin/replay, ausencia de tráfico y protección de valor
  completo. Fixtures `.invalid` y contraseñas inventadas de laboratorio,
  nunca se han obtenido credenciales reales del sitio.
- **Auditoría negativa:** `tests/test_issue12_no_shortcuts.py`, más
  `test_host_chrome_public_smoke.py`: prohíbe atajos de TLS/Chromium en
  módulos nuevos, prueba que `queueId`/`skipQueue` sin `queueittoken` no
  generan pase y verifica que las rutas offline no abren sockets.
- **Revisión independiente:** no detectó hallazgos P0/P1. Observó que las
  aperturas sucesivas podrían consumir el límite de 16 nonces; se añadió
  primero un test RED, luego `form_scope` reutilizable para GETs del monitor
  y finalmente se verificaron 40 refrescos continuos sin 429. El limitador
  protector compartido conserva **1 segundo entre revelaciones** incluso si
  se alterna de Queue-it a Boca: es una restricción de experiencia de uso,
  no una mezcla de los canales. Si una segunda copia inmediata responde 429,
  el titular debe volver a abrir el monitor pasado ese intervalo.
- La suite integral, Ruff, Mypy, política de repositorio y Actions deben
  registrarse **en sus resultados finales**. Una suite local no certifica
  exact-SHA remoto, autenticación real, TLS del host ni Queue-it activo.

**Resultado local observado en este corte (no es certificación de Actions):**

| Control | Evidencia local | Límite |
| --- | --- | --- |
| `uv sync --frozen` | EXIT 0 | Dependencias instaladas en workspace temporal |
| `uv run pytest -q` | **7135 PASS, 1 SKIP, 34 subtests PASS**, 142.40 s | `tests/test_r177_fixture_probe_transport.py:72` SKIP por AF_UNIX `EPERM` del sandbox |
| `uv run ruff check .` | PASS | Sin errores de lint |
| `uv run ruff format --check .` | PASS, 903 archivos conformes | Los 3 archivos de sector recuperados se normalizaron sin cambiar lógica |
| `uv run mypy src` | PASS, 171 archivos | Tipado estático local, no runtime externo |
| `uv run python scripts/check_repo_policy.py` | `POLICY_PASS` | No acredita instalación física |
| GitHub Actions exact-SHA | **PENDIENTE** hasta publicar PR | No heredar workflows GREEN de `main` |

## Stoppers abiertos (no ocultar con GREEN)

1. **OBSERVADOR_QUEUEIT_NO_CONECTADO:** falta procedencia/adapter autorizado
   desde una navegación futura. El sitio no está disponible; orden expresa
   del titular de **no validar todavía** URL con token.
2. **BOCA_LOGIN_TRANSPORT_NO_CONECTADO:** falta endpoint, contrato de payload
   y respuesta auténtica; está prohibido inventarlos. Las contraseñas
   guardadas en SQLite no prueban que Boca acepte login.
3. **SECTORES_SIDECAR_NO_PROVISIONADO:** el propietario de instalación debe
   pactar y ejecutar la migración explícita del nuevo fichero lateral en
   el volumen Boca, preservando la base legacy.
4. **CI_EXACT_SHA_Y_HOST_PENDIENTES:** el candidato de este PR precisa sus
   propias Actions y revisión; #417 conserva exclusividad de merge/deploy
   y no existe prueba física nueva del monitor ni de los proveedores.

## Custodia y acciones requeridas

- Issue funcional: [#12](https://github.com/mbalbo2023/boca-socios-assistant/issues/12).
- Propietario de la instalación y RCA físico:
  [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).
- Revisar el PR **solo de #12**, verificar diff y la ausencia de cambios en
  Docker/Compose, workflows, `synthetic.py`, `ipc_worker.py`, `SITE_URL`,
  operaciones de limpieza o infraestructura Porota.
- No ejecutar Actions de despliegue por este handoff. Si #417 acepta la
  integración, manejarla en su lote consolidado y después acreditar
  observadores/proveedor cuando el sitio esté operativo y el titular lo
  autorice.
