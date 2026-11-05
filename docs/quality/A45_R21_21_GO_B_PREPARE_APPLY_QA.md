# Boca A45-R21.21 — GO_B PREPARE/APPLY integrado, QA final pendiente

Fecha: 2026-11-05 ART. CODE_ONLY. Aún NO hubo GO físico, merge, release publicable ni deploy sobre droplet.

## Corte exacto y proveniencia

- PR único DRAFT #319; main físico legacy cabce9f1e452e63ded115f447559a358dc0f4d1b no modificado.
- Padre R21.20 HEAD 7679ebf21549fca84b8092415c0bb631ae18fd20 TREE 8730efdeb7dcc2af5a34cc4c67003c68f283dcab: integra cleanup #372, observer #375 y Telegram fresh owner witness #374; cada satélite tiene QA terminal green, pero R21.20 propio se verificaba con siete Actions al siguiente overlay.
- #376 GO_B fuente exacta HEAD a60c9d4280cf653435ea1e1eefd2dcd4b0c35345, 11 rutas, 4/4 Actions SUCCESS, CI 3702 PASS+34, FirstDeploy PR runtime smoke GREEN y host manual SKIPPED; review 5788330958, Rule84 issue #371.
- Primer commit CAS de la integración #376: 8d85124dea5e5131a1faaf9cdfd27bcb1102b829 TREE 52491e89d8b13619979980f2939e195c21e29f8c. El SHA R21.21 definitivo incluirá este checkpoint por GitHub Contents API para sincronizar PR y disparar Actions. No transferir GREEN de la fuente #376 al nuevo HEAD.

## Contrato de operación (ningún efecto físico en PR)

1. Operaciones existentes cutover-a-apply y official-notice-import, sin añadir inputs (>25) ni nuevos puertos; PREPARE usa protected_action_context vacío, consulta READ_ONLY inventorios Boca y GH artifacts verificables, emite receipt 15 campos/GO digest independiente. Si una evidencia es ambigua, NO_GO.
2. APPLY consume sólo decimal corto del run PREPARE; GitHub API revalida SHA/main/actor/attempt1/recibo/TTL, Go variable independiente del Environment por operación, O_EXCL/0600 y host replay tombstone/ACK exacto.
3. Cutover legacy usa CID/image/source labels reales del observador #375, cruzados con manifest de release histórico GH Actions. Importación usa CID oficial observado y un único official_news_run_id corto si hay varios runs revisables, no heurística latest.
4. Checker GO_B #372 conserva postflight limpieza selectiva Boca por IDs exactos y disco/inodos; parser de dos líneas GO_B y ACK legacy v1 permanecen compatibles. Seis install legacy continúan NO_GO antes de SSH.
5. Telegram fresh passkey owner witness #374 protege el stage, pero bot sender OFF y egress host mismo UID/PID/flock/GO sin atestación, por lo que la BETA integral Telegram todavía no es física.

## Próximo gate

- Registrar 7/7 Actions y conteo real del SHA definitivo R21.21, comprobar blackbox protected, diff sin owners solapados, artifacts PR no publicar.
- Sincronizar docs DRAFT #363 a R21.21 y completar predeploy gobernado (recursos, releases, puerto 127.0.0.1:8443, acceso Samsung Chrome/Termius, Docker selectivo).
- No fusionar main/crear release/ejecutar GO protegido sin evidencia correspondiente. El conector actual no habilita workflow_dispatch protegido, por lo que la ejecución real dependerá del botón manual GitHub autorizado al final, sin terminal ni PIN en chat.

Restricciones: 0 órdenes reales de compra/reserva, 0 backups, no manipular BLACKBOX synthetic.py/ipc_worker.py, Porota ni otros Docker, sin HTTPS ni puertos nuevos. Documentación continua en issue #45.
