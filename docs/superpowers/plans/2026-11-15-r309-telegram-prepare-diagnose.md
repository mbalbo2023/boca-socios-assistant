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

La adenda D9 posterior a la medición amplía exactamente dos rutas:
scripts/build_protected_telegram_bundle.py y la aserción agregada en
tests/test_r296_telegram_installed_bundle.py. El agregado installed pasa a500000;
default, umbral del compactador, fuente/entrada individual permanecen450000.
Separar la guarda individual de memfd. No modificar R307, código de imagen,
BLACKBOX, MOUNTS, transformaciones ni otros límites históricos.

- [ ] Inspeccionar las interfaces existentes y validar que los parsers instaladosR requeridos existen sin suponer API nueva.
- [ ] Escribir RED causal de los datos/selector faltantes; mockear sólo I/O externo, no los validadores que se pretende probar.
- [ ] Implementar D3: programa público fijo, ausencia/invalid/mismatch/not-read/drift, metadata y resultados cerrados.
- [ ] Implementar D4–D5: recipient-observe con factory recipient, literal exacto atestado, dos snapshots, metadatos, máximas2entradas, lectura privada sólo KEY_ONLY válido.
- [ ] Implementar D1–D2/D6–D8: contexto fijo, comprobaciones explícitas, un helper, públicoA/B, codec y recomendaciones no ejecutables.
- [ ] Cablear selector y verificación en CLI/memfd/Action; excluir de todos los pasos legacy. Distinguir remote/verification errors de recibo completo.
- [ ] Probar fronteras D10 y modos legacy representativos sólo donde el delta toca el contrato.
- [ ] Medir receipt/frame y ZIP/closure exactos,47entradas, default y installed. Si exceeds450000, detener aumento y enviar medida para adenda; no compactar ajenos.
- [ ] Adenda D9 aprobada4/4: corregir el rechazo real488426>450000 sólo mediante agregado installed500000; probar500000/500001 y entrada450001 con suma<=500000, preservando default/individual450000 y ZIP300000. Revalidar el test R296 afectado, sin repetir baseline.
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

## Despacho preparado por Operaciones — no ejecutado

El SHA de herramientas W será el main final revisado; `source_sha` sigue
siendo el producto instalado R, no W. Root verificará main, PRs, gates,
manifiestos/linaje y ausencia de otra operación antes del único despacho.

| Input | Valor |
|---|---|
| Workflow/ref | boca-first-deploy.yml / main final W |
| operation | telegram-prepare-diagnose |
| source_sha | 845f31abfb1762dff27e6fc3274fcc40507f3f18 |
| image_ref | ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0 |
| browser_image_ref | ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe |
| release_run_id | 43704139794 (release867) |
| service | controller |
| resource_budget | 1.5cpu-1024m-192pids |

Los demás campos opcionales quedan vacíos, incluidos
`failed_telegram_run_id`, `legacy_release_run_id` y `protected_action_context`.
El incidente1167/run43738415332 y APPLY1153/run43704768556 son coordenadas
fijas internas del diagnóstico; no enviarlos como inputs legacy. El run nuevo
lo asignará GitHub. No copiar secretos a formularios ni pedir comandos al titular.

## Reutilización posterior, condicionada a D8

La revisión estática de Arquitectura confirmó que el protocolo V2 ya termina
en `CUSTODY_COMMITTED_NO_SEND`; no hace falta inventar otra criptografía para
la custodia global. El selector activate continúa hacia el sender y requiere
una salida explícita si se necesita primera configuración sin envío.

Para custodia ya válida del source actual existe la rama sin journal/sender
de `recover_installed_sender`, que publica estado sin crear sender. Su recibo
RECOVERED/OFF no garantiza configured=VERIFIED: debe acreditarse la custodia
derivada. La operación tiene efectos y no queda autorizada por el diagnóstico.

`adopt_sender_binding` sólo incorpora campos del sender en la misma versión.
La actualización conserva volúmenes, pero no adopta documento público, stage
ni marcador V2 de otro source. KEY_ONLY con público antiguo necesita una
transición acotada del documento; custodia confirmada de otra versión exige
conocer marcador/pruebas antes de diseñar la transición. No usar renew-stage
como atajo ni asumir stage ausente. Ninguna remediación tiene voto previo aún.

