# R305 Telegram initializer recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recuperar y retirar una vez el helper exacto1156, preservando el par Docker ya instalado.
**Architecture:** Adaptador host específico y acotado que reutiliza el observador R304 y el inicializador inmutable de R. No crea otro helper ni adopta genéricamente volúmenes. Corrección mínima del spelling CapAdd en el atestador ordinario.
**Tech Stack:** Python3.12 stdlib, pytest, Ruff, mypy; Docker rootless; GitHub Actions/SSH/memfd.
**Spec:** docs/superpowers/specs/2026-11-15-r305-telegram-initializer-recovery-design.md

## Global Constraints

- SIMULATION_ONLY; BLACKBOX synthetic.py/ipc_worker.py unread/unmodified; Porota/PPI fuera de alcance.
- Único workflow boca-first-deploy; main exacto; lease canónica; UID/GID10001.
- Imagen R/APPLY1153 y helper1156 fijos; caller sólo run/W.
- Sin permisos nuevos, creación de helper, stop/start del par, SQL, eliminación de volumen, prune ni force.
- R304 bytes/semántica/pin intactos. No modificar guard _created_volume.
- Autor separado; raíz owns docs/RCA/GitHub/host; cuatro votos previos y finales.
- Árbol base W0 be788a7dc602f4fce63da1d2a4ce859da73c5b08; worktree recuperado limpio, no duplicarlo.

## Review Focus

- CAP_CHOWN físico: probar _attest y call reales, no sustituir validadores.
- Otro mount/Entrypoint/helper o drift: ningún start/rm antes de guardas completas.
- Volumen no vacío/UID incorrecto: inicializador existente falla antes de fchmod/fchown; no asumir datos actuales.
- Timeout/respuesta/ACK perdido: distinguir posible init/retire; jamás segundo start o force/stop.
- ZIP/workflow: mismo verificador aislado, límites y rc/estado; no falsa aceptación ni cambio de ramas previas.

## Propiedad de archivos

Autor puede modificar sólo:
1. src/boca_socios/host_telegram_initializer_recovery.py (nuevo)
2. src/boca_socios/host_telegram_maintenance.py (sólo expresión CapAdd)
3. scripts/build_protected_boca_bundle.py
4. scripts/boca_protected_memfd_bootstrap.py
5. .github/workflows/boca-first-deploy.yml
6. tests/test_r305_telegram_initializer_recovery.py (nuevo)
7. tests/test_r305_telegram_initializer_transport.py (nuevo)
8. tests/test_r296_telegram_maintenance.py (regresión CapAdd)

Raíz posee spec/plan, AGENTS, README, docs/DEVELOPMENT_POLICY, OPERATIONS,
ROADMAP, BETA_DELIVERY_PLAN, BETA_INTEGRATION_STATUS y quality/rca-lessons.json.
No editar otros tests/gates para acomodar el resultado. Si otro pin realmente
cambia, informar antes de editar; no ampliar scope unilateralmente.

### Task 1: frontera real CapAdd y recuperador exacto

**Interfaces:** nuevo módulo exporta recover(run_id: str, workflow_sha: str) -> bytes,
verify(raw: bytes, run_id: str, workflow_sha: str) -> bytes y main(argv=None)->int.
Recibo/state/coords según spec. Importa sólo stdlib, cleanup y observador R304;
usar dependencias de la clausura existente para validación de mounts, sin
agregar imports que excedan la allowlist. Helper/run/imagen son constantes.

- [ ] Escribir test_r305_cap_chown_reaches_real_initialize_and_cleanup en test_r296_telegram_maintenance: builder/_inspect/_attest/call reales, sólo frontera Docker/subprocess simulada; CAP_CHOWN llega a start y rm, CHOWN sigue admitido. Negativos listas dobles/extra/ausente/operación noinit quedan rechazados. Ejecutar y conservar RED causal antes del parche.
- [ ] Escribir tests del nuevo recuperador con transporte externo sintético: flujo exacto lease→dos snapshots→start único→validar→rm→postflight; efecto exacto sin factory ni recreación. Rechazos de preflight/mounts/Entrypoint/start previo/imagen/censo/drift; incertidumbre de start/rm; codec que acepta sólo la tabla cerrada de spec, incluidos resultados parciales, y rechaza ACCEPTED fuera de COMPLETE, retiro sin init aceptada, senderOFF no observado y métricas fabricadas. Conservar RED por ausencia del módulo.
- [ ] Aplicar sólo whitelist exacta [CHOWN]/[CAP_CHOWN] al atestador y crear recuperador según spec. No modificar inicializador R ni R304.
- [ ] Ejecutar los tests focales nuevos y las regresiones existentes estrictamente afectadas de mantenimiento. Probar inicializador real execute con I/O filesystem externo simulado: vacío/UID0 hace secuencia prevista; no vacío/otroUID no llega fchmod/fchown.
- [ ] Ruff check/format y mypy sólo archivos productivos tocados. Capturar comandos/resultados en evidencia. Preparar diff para revisión de Task1; ningún host/GitHub.

### Task 2: ZIP/memfd y Action aislados

**Interfaces:** builder.build(..., telegram_initializer_recover: bool=False)->str
y CLI --telegram-initializer-recover. Bootstrap verify(...,
telegram_initializer_recover: bool=False); operación
boca-telegram-initializer-recover run_id W, luego módulo main host.
Allowlist30 entradas, límites900000/320000, módulo<=24000.
Mismo patrón R304, sin agrupar casos previos ni cambiar la semántica anterior.

- [ ] Añadir tests RED de exclusividad/allowlist/cotas; ZIP real aislado CLI host+verify sinrepo/PYTHONPATH; denegación UID antes de efectos, wronghash/wrongmode/caller inválido.
- [ ] Añadir regresión ejecutando el tail shell real con fixtures de recibo/rc:
  ACCEPTED+0, NO_GO+3, rc255, mismatch, malformed, wrongW. Únicamente el primero verde; NO_GO3 canónico en summary y job rojo; otros no reflejan input libre.
- [ ] Implementar modo de builder/memfd, selector/caso separado y paso protegido con22blanks, actor/trigger/main/attempt gates, BOCA_DEPLOY_ENV_READY/BOCA_TELEGRAM_ENV_READY/BOCA_HOST_READONLY_ENV_READY exactamente ready, mainrecheck y unaSSH. No introducir otraworkflow ni markers BETA/BROWSER/OWNER nuevos para esta ruta.
- [ ] Ejecutar pruebas focales Task2 y casos existentes de binding/R304workflow que protegen la admisión separada. Bash-n de pasos alterados.
- [ ] Construir una vez paquete de recuperación, verificar/bootstrap/listar30entradas/hash/tamaño y probar CLI0/3 desdeZIP. Construir paqueteTelegram, medir bajo450000/300000 y registrar hashactual; no existe pinliteral Telegram que editar. R304/fullcutover hashes intactos.
- [ ] Registrar diff/filehashes/package manifests/resultados para revisión final de árbol congelado.

### Task 3: integración y única operación, raíz

- [ ] Consumir revisión de spec y QA de cada unidad sin duplicar suites certificadas. Reconciliar base/main y registrar cuatro revisiones finales sobre árbol/hash.
- [ ] Docs/RCA526: causa reproducida, prevención, selectores realmente ejecutados; conservar lecciones anteriores. No afirmar init/cleanup física antes del recibo.
- [ ] Publicar rama fix/526-r305-telegram-initializer-recovery como conversión de issue526 a PR; un candidato coherente. CI completa obligatoria de SHA; merge esperado y gates del nuevo main.
- [ ] Reconciliar runs/PRs; preparar un único dispatch por browser fallback documentado. Operación nueva/controller/budget fijo/22blanks. No release/APPLY.
- [ ] Validar recibo físico con mismoZIP, guardar hash y checkpoint GitHub inmediato. Ante NO_GO detener efectos y analizar fase; nunca retry ciego.
- [ ] Sólo tras init+retire ACCEPTED, ejecutar prepare canónico instalado R/release867 con guardas y recibo propio; no activate/mensajes. Registrar PREPARED/restoration/sender literal o bloqueo real.

## Evidencia y no repetición

Reutilizar recibo1161/R304, revisión base y CI1273/1090. No suite local total,
relectura masiva de logs, nuevos diagnósticos por curiosidad, ni release duplicada.
Verificar sólo riesgo concreto del delta y gates exigidos del candidato/main.
