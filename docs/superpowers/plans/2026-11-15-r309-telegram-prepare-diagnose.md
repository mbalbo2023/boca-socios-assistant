# R309 — Telegram prepare diagnosis implementation plan

> **For agentic workers:** use subagent-driven-development with one separate author and independent reviewers.

**Goal:** obtener evidencia actual de clave y recibos para decidir preparación/adopción final sin publicar ni reparar a ciegas.

**Spec:** [contrato D1–D10](../specs/2026-11-15-r309-telegram-prepare-diagnose-design.md); issue530 registra cuatro GO previos.

## Global constraints

- Reutilizar worktree aislado actual y toolchain; no repetir baseline local ni pruebas de R308.
- Root posee documentación, GitHub, integración y única Action. Autor sólo rutas indicadas.
- SIMULATION_ONLY; senderOFF, BLACKBOX unread/unmodified, datos/passkeys y otros proyectos intactos.
- Sin helper nuevo en imagenR, cambio de MOUNTS, servicios, release/APPLY, prepare, publicación o adopción.
- Cotas actuales intactas. Medir el cierre y pedir revisión de adenda si installed450000 no alcanza; ningún aumento implícito.

## Preflight and ownership

| Contrato | Productor y consumidor | Comprobación |
|---|---|---|
| Público A/B | Programa literal en controllerR → lector host | Parsers existentesR, no SQL ni fallback, forma estricta y estados diferenciados. |
| Clave observada | Programa literal en helperR → InstalledMaintenance | Sólo request vacío, Cmd atestado, perfil recipientRO, metadata y dos snapshots antes de derivación. |
| Diagnóstico | Coordinador → CLI/Action | Codec nuevo <=4096, V1 intacto; no interpretación de éxito como PREPARED. |
| Transporte | Action existente → memfd/ZIP instalado | Selector en todas las rutas instaladas y excluido de todos los pasos legacy. |
| Integración | Autor → root/revisores | Un único escritor productivo; revisión independiente y gates exactos. |

## Task1 — Circuito completo mínimo (autor separado)

**Modify only these product paths:**

- src/boca_socios/host_telegram_status.py
- src/boca_socios/host_telegram_maintenance.py
- src/boca_socios/host_telegram_backend.py
- src/boca_socios/host_telegram_cli.py
- scripts/boca_protected_memfd_bootstrap.py
- .github/workflows/boca-first-deploy.yml

**Tests, new focal files:**

- tests/test_r309_telegram_prepare_diagnose.py
- tests/test_r309_telegram_prepare_transport.py

El builder y tests históricos quedan fuera de escritura inicial. Si una frontera
existente exige cambio, informar evidencia antes de ampliar rutas. No modificar
R307 ni código de imagen, BLACKBOX, MOUNTS o límites históricos.

- [ ] Inspeccionar las interfaces existentes y validar que los parsers instaladosR requeridos existen sin suponer API nueva.
- [ ] Escribir RED causal de los datos/selector faltantes; mockear sólo I/O externo, no los validadores que se pretende probar.
- [ ] Implementar D3: programa público fijo, ausencia/invalid/mismatch/not-read/drift, metadata y resultados cerrados.
- [ ] Implementar D4–D5: recipient-observe con factory recipient, literal exacto atestado, dos snapshots, metadatos, máximas2entradas, lectura privada sólo KEY_ONLY válido.
- [ ] Implementar D1–D2/D6–D8: contexto fijo, comprobaciones explícitas, un helper, públicoA/B, codec y recomendaciones no ejecutables.
- [ ] Cablear selector y verificación en CLI/memfd/Action; excluir de todos los pasos legacy. Distinguir remote/verification errors de recibo completo.
- [ ] Probar fronteras D10 y modos legacy representativos sólo donde el delta toca el contrato.
- [ ] Medir receipt/frame y ZIP/closure exactos,47entradas, default y installed. Si exceeds450000, detener aumento y enviar medida para adenda; no compactar ajenos.
- [ ] Ejecutar focales una vez tras implementación; repetir sólo fallos corregidos. Ruff/formato/mypy afectados; no suite completa local.
- [ ] Commit de las seis rutas y dos tests; informe con RED/GREEN, medidas, hash, riesgos y límites. No voto independiente del autor.

## Task2 — Revisión, evidencia y diagnóstico (root)

- [ ] Arquitectura, QA, Operaciones y root revisan diff/contrato y resultados, sin repetir suites.
- [ ] Cualquier adenda de límites o rutas se registra y aprueba antes del cambio correspondiente.
- [ ] Actualizar RCA y documentos vigentes; publicar candidato revisable y gates exactos.
- [ ] Reconciliar main/PRs e instalado; una única Action con parámetros exactos y recibo real en417.
- [ ] Decidir continuación específica a partir del resultado; nunca retry, prepare o adopción por inferencia.
- [ ] Mantener pendientes DOM/resultado y configuración por socio como desarrollo o contrato faltante, sin presentarlos como QA concluido.

## Self review

D1–D10 cubren necesidad, alternativa, límites, operaciones, codec, matriz,
rutas y verificación. Los dos programas ejecutan únicamente parsers deR y
publican datos acotados; author no toca esos módulos instalados. El inventario
explícito evita atribuir a healthy comprobaciones que no realiza. La incertidumbre
preserva el estado. Ninguna operación histórica se repite para probar este código.

