# R310 — Plan del ensayo físico de50 en runner

> Ejecución por autor separado; root integra y opera. Cuatro votos previos en issue531/comment6903879186.

## Objetivo y alcance

Implementar el contrato C1–C10 del [diseño](../specs/2026-11-15-r310-capacity50-runner-design.md). Reutilizar pool/registry, fixturelocal y métricas existentes para medir50 contextos reales en un runner. No alterar producto, límites o BLACKBOX. No hay selector/operación host en este alcance.

Base de autoría: b577c11, árbol a730e2f595d2cf4dc762c41b021b2366674afccc, idéntico al candidato publicado8b6757add787adc6ba0c99936362bbbc0b7062b3 de PR530. Root reconciliará main antes de publicar. PR530/diagnósticoTelegram mantienen prioridad; no abrir PR531 ni despachar antes de cerrarlos.

## Ownership

Autor único:
- src/boca_socios/browser/capacity_fixture.py (nuevo).
- tests/test_browser_capacity_fixture.py (nuevo).
- .github/workflows/boca-playwright-offline-diagnostic.yml.

Root: este plan, diseño, progreso, GitHub, CI y cualquier despacho. Ningún otro escritor productivo. Worktree aislado feature/531-capacity50. Usar toolchain existente de boca-r307 con PYTHONPATH del nuevo worktree; no cambiar lock ni instalar nuevas dependencias.

## Preflight de interfaces

| Frontera | Productor/consumidor | Evidencia requerida |
|---|---|---|
| Browser real | SharedBrowserPool → observador local | Tres tipos, préstamos reales, cadencia8s, sin factory BLACKBOX. |
| Activaciones | EngineSessionRegistry.execute → handles | Dos grupos25, identidades únicas, cierreA/replay sin recreación, B utilizable. |
| Aislamiento |50 escrituras →50 lecturas posteriores | Contextos/páginas distintos, mismo origen, cookies y storage aislados. |
| Recursos | Guardas reales y resource_snapshot → recibo | Perfil worker exacto, loopback sólo, métricas UNKNOWN explícitas, continuidad interna cgroup. |
| Resultado | Harness → Action → retiradaCID | Recibo<=32768B, trabajo600/cierre15/envolvente650; GO global sólo con evidencia completa y retiro atestado. |

## Task1 — Autoría completa mínima

- [ ] Verificar APIs exactas y usos existentes antes de escribir.
- [ ] Escribir regresiones causales focales para falsos éxitos y efectos/timeout; usar sólo dobles de I/O externo, sin reemplazar pool/registry/validadores que se prueban.
- [ ] Implementar el observador/harness local,50 contextos reales, barrera, todas las escrituras antes de todas las lecturas, cierreA y B/replay.
- [ ] Implementar métricas allowlisted y codec cerrado, fases/razones finitas, resultados parciales y cierre independiente.
- [ ] Agregar capacity50 al workflow existente y excluir en ese modo ambos probes legacy; un único contenedor atestado, output acotado, resultado externo/retirada verificados. Sin nueva operación host.
- [ ] Validar únicamente tests afectados, Ruff/formato/mypy del módulo, contrato de shell/workflow y medición del recibo real máximo. No repetir suitespool50/baseline ni correr localmente la carga física larga.
- [ ] Informe RED/GREEN, rutas/medidas/limitaciones y commit sólo tres rutas. No push/PR/Actions/host; no voto independiente del autor.

## Task2 — Root y revisores

- [ ] Cuatro revisiones finales independientes, sin volver a ejecutar suites aceptadas.
- [ ] Reconciliar base/main y PR530/diagnósticoTelegram; publicar sólo delta pertinente.
- [ ] CI exacta, merge y mainGREEN; registrar estado factual y un único despacho capacity50 offline.
- [ ] Conservar recibo/retirada/entorno medidos. NO_GO no es capacidad acreditada ni habilita aumentar recursos o retry.
- [ ] Decidir el siguiente paso físico del droplet sólo con evidencia y contrato protegido separado.

## Verificación y límites

La unidad debe detectar handles repetidos, storage compartido, apertura parcial, B inutilizable, replay que recrea, cierre incierto y transporte/retiro externo fallido. No duplicar la suite lógica de50 ya existente ni presentar mocks como capacidad física. La evidencia positiva sólo llegará de la Action.

Registry/pool mantienen plazos internos. Deben existir50 contextos simultáneos; no sumar contextos ya cerrados. No medir cuota agregada del par como worker. Sin headroom preventivo nuevo. Cualquier necesidad de otra ruta, cota o modificación productiva se detiene para evidencia y nuevos votos previos.

