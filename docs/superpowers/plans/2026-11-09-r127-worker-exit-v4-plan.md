# R127 — Plan de implementación y verificación

Estado: en curso, rama `fix/417-worker-exit-telemetry-v4`.

1. **Contrato y tests RED.** Reutilizar fixtures de
   `tests/test_host_cutover_adapter.py` para metadatos `docker inspect`
   sintéticos: ausencia, tipos falsos, timestamp cruzado, health logs con
   canary privado. Probar que los cuatro enums exactos sobreviven a ambas
   compensaciones y nunca filtran cadenas libres.
2. **Captura GREEN.** Derivar cuatro campos dentro de la observación de
   `_browser_wait_healthy` sin nuevas llamadas Docker; transitar por
   `WorkerHealthPhaseError`, `CutoverWorkerPhaseError` y el contrato del
   `run_cutover_a`, con defaults que preservan V3.
3. **Recibo V4 y consumidores.** Añadir roundtrip estricto al recibo durable
   O_EXCL/fsync; salida CLI tipada y parser runner de claims NO_GO; adaptar
   reconciliador de solo lectura para el esquema explícito. TDD por capa.
4. **QA de frontera.** Ejecutar suite completa, Ruff, format, MyPy, policy,
   transporte ZIP y pin/limites; prohibir lectura/ejecución del BLACKBOX.
5. **Integración.** Revisión Arquitectura/IPC externo/DevOps/QA; actualizar
   ADR y procedimientos; PR pequeña hacia main; CI exact SHA y release dual
   antes de considerar el único dispatch protegido y documentar #417/#45.

Todo error conserva NO_GO sin reintento automático, no modifica otros
Docker y no produce efectos host durante el desarrollo de código.
