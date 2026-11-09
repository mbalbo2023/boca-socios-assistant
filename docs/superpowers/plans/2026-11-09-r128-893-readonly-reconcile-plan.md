# R128 — Reconciliación READ_ONLY del Cutover #893

Fecha ART: 2026-11-09. Issue canónico: #417; continuidad: #45.

## Evidencia y límite

- Cutover #893 (`42658939650`), `main=759a1dbadd6e50ab8c331daefc4e39608025a66f`, terminó FAILURE en PREPARE_WORKER. La Action informó `ExitCode=1`, `OOMKilled=NO`, firma V4 `EMPTY.EXITED.EARLY_LT_5S.NOT_RUN`, compensación declarada VERIFIED y aceptación host/terminal UNVERIFIED.
- No existe un PREPARE independiente para este único workflow_dispatch V3. Los selectores de reconciliación V3 existentes sólo admiten #853 y #878. Ni la causa interna ni el recibo durable están verificados en forma independiente.
- No reintentar Cutover. No tocar ROOT, Porota, Docker ajeno, servicios, puertos, datos ni módulos BLACKBOX.

## Alcance implementable

1. Extender exclusivamente el selector existente `cutover-a-reconcile` para aceptar **un solo** incidente nuevo `42658939650`, con SHA fijo `759a1dbadd6e50ab8c331daefc4e39608025a66f`, sin PREPARE ni IDs suministrados para el host.
2. Conservar la autenticación GitHub exacta (repo, workflow, actor, triggering actor cuando conste, intento 1, rama main, estado completed/failure, SHA), la lectura bajo UID Boca y el contrato de `host-v3/verify-v3` que ya reconoce terminal V4.
3. Omitir sólo para #893 el planner histórico de cleanup aun READ_ONLY: el resultado será únicamente inventario y observación, con `runtime_attested=false`, `go_for_retry=false`; ninguna nueva vía de recuperación.
4. Añadir pruebas RED→GREEN para whitelisting exacto, SHA incorrecto, PREPARE ficticio, contrato V4, e invariantes de cero efectos/crecimiento de permisos.
5. Revisar seguridad, calidad y arquitectura; publicar PR breve, merge con CI y documentar Go/No-Go en #417/#45. La lectura física podrá ejecutarse **una sola vez después del merge**, con controles completos. Su GREEN no será GO físico.
   El formulario protegido exige `operation=cutover-a-reconcile`, `service=controller`,
   `resource_budget=1.5cpu-1024m-192pids`, `protected_action_context=42658939650`;
   SHA/imagen/release/legacy/PREPARE y otros pines deben quedar vacíos.

## Fuera de alcance deliberadamente

- Recapturar el `docker logs` del worker ya eliminado es imposible sin otro arranque, y no se inventarán excepciones internas.
- La captura confidencial prospectiva de stdout/stderr requiere diseño independiente, límites reales de bytes/tiempo y custodia del titular; no se implementa ni habilita aquí.
- No se crea un nuevo workflow, contenedor, usuario, credencial, script de limpieza ni ruta de retry.
