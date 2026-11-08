# R119 — plan verificable: RECOVERED/ACCEPT en planner READ_ONLY

1. Conciliar #883 y semántica terminal V3 del productor. Acreditar 3 votos
   independientes y crear acta en #45 **antes de editar** (cumplido).
2. TDD RED: caso exacto #878 `RECOVERED/ACCEPT`, rechazo de cualquier otra
   pareja, SHA/incidente, evidencia de worker y topología. Conservar #853.
3. Cambio pequeño en el observador y su derivador de CID; proyectar enums
   y tipos externos, nunca bytes protegidos ni autoridad de retry.
4. Ejecutar focales, suite completa, Ruff, MyPy, policy y ZIP pin; revisión
   de QA/Arquitectura y DevOps independiente sin tocar host.
5. Publicar PR único CODE_ONLY, esperar checks, hacer merge si GREEN y
   verificar CI/Security postmerge y cero PR abiertos. Documentar hashes,
   run IDs y bloqueantes en #45/#417/#386.
6. Solo entonces revisar un **nuevo consenso separado** para una posible
   observación READ_ONLY por Actions, sin asumir GO físico de BETA/Telegram.

No repetir Cutover #878, no eliminar Docker ni inspeccionar/importar/ejecutar
`synthetic.py` o `ipc_worker.py`. Sólo GitHub contiene las decisiones durables.
