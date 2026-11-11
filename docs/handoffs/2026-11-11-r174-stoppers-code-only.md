# A45-R174 — stoppers DNS/IPC/Telegram y continuidad (11/11/2026 ART)

**Estado:** consolidación local CODE_ONLY, revisión y Actions exactas
pendientes. **NO_GO para merge, release, Cutover y validación física.**
Issue canónico [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417),
ledger [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45),
candidato único [PR #478 DRAFT](https://github.com/mbalbo2023/boca-socios-assistant/pull/478).
Esta hoja no convierte una observación en autorización de host.

## Reconciliación anterior a R174

- `main=361e3ff42c44e1b8699d7a3e2d158c9a367b2f86`,
  PR publicado `HEAD=0ae6bf04ca0ec016916f236b6326792a51d3a6e8`,
  `TREE=05cc15eee528dc192a8b7a0e12044e3ec2039810`;
  el árbol remoto R173 coincidía con el local probado antes de nuevos commits.
- Un PR abierto (#478); #474–#477 cerrados individualmente sin merge ni borrar
  ramas. No atribuir esa observación a un SHA futuro sin releer GitHub.
- Cinco workflows exactos del remoto R173: panel preview
  [#43039017276](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43039017276)
  SUCCESS; CI [#43039016920](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43039016920),
  FirstDeploy [#43039017135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43039017135),
  seguridad [#43039016884](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43039016884)
  y release [#43039016969](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43039016969)
  FAILURE. Todos los trabajos browser fallaron resolviendo los mirrors
  Ubuntu en `apt-get`, **antes de ejecutar Chromium/Trivy browser**.

## Tres correcciones paralelas sin pisar ownership

1. **CI/DNS:** branch aislada `feature/417-r174-ci-apt-diagnostics`,
   commit `78ed1156779c7a9a7676e6a695b1a531dda63f42`. Un
   `apt-get update --error-on=any` impide éxito falso con listas obsoletas.
   Un helper build-only en bind read-only admite solo las fuentes firmadas
   Noble conocidas y cambia exclusivamente los URIs archive/security a
   `https://mirrors.edge.kernel.org/ubuntu/` si falla el mirror original.
   Se preservan `Signed-By`, pins de apt/libapt 2.8.4ubuntu0.1,
   brotli 1.1.0-2ubuntu0.1 y Trivy HIGH/CRITICAL bloqueante.
   Las [fuentes públicas del espejo](https://mirrors.edge.kernel.org/ubuntu/dists/noble-security/)
   prueban que existen `InRelease` y paquetes, **no que el runner pueda
   resolverlos**. [ADR0231](../ADR/0231-r174-browser-apt-signed-mirror-fallback.md).
   La coincidencia con el [incidente runner-images #15296](https://github.com/actions/runner-images/issues/15296)
   es corroboración, no prueba causal de infraestructura específica.
2. **IPC Linux:** branch `feature/417-r174-worker-ipc-smoke`,
   commit `e10248a052aadaa3ad86bc88b6c269e014578e84`. Suma
   `scripts/check_worker_ipc_linux.py`, tests de harness y un paso en
   `CI / quality-and-tests`: socket real con worker UID10002, cliente
   extraño UID10003 denegado, UID10001 recibe exclusivamente NO_GO,
   SIGTERM y eliminación de socket. Sin Docker, Internet, SITE_URL,
   credenciales ni navegación. El sandbox local rechaza AF_UNIX con EPERM:
   el **test real está sin ejecutar** hasta GitHub-hosted runner.
   Revisión independiente: GO CODE_ONLY, sin P0/P1.
   [ADR0223](../ADR/0223-bot-bajo-demanda.md).
3. **Telegram/QA:** branch `feature/315-telegram-json-duplicate-r174`,
   commit `8e62a87ef9c7e4a3262763e0add6d104e064c44b`, integrado
   localmente como `cad6009`: el verificador `getMe/getChat` rechaza
   claves JSON duplicadas con el parser estricto ya usado por el transporte.
   Regresiones TDD RED→GREEN y tres casos adicionales para `getChat`.
   Revisión independiente GO CODE_ONLY. El sender permanece **OFF**;
   token anterior comprometido y rotación/entrega reales aún pendientes.

Las tres ramas fueron escritas en worktrees independientes, luego
reconciliadas por un único integrador. No se importó código externo del
frente de investigación posterior a BETA; no se tocaron algoritmos de
navegación protegidos ni se añadieron reservas.

## Evidencia integrada LOCAL (no física)

- `uv run --frozen pytest -q -n 4 --tb=line`: **6807 PASS,
  34 subtests PASS, 0 FAIL, 46,81s** en la integración R174.
- `uv run --frozen ruff check .`: PASS;
  `uv run --frozen ruff format --check .`: **834 archivos PASS**;
  `uv run --frozen mypy src`: **154 módulos PASS**;
  `uv run --frozen python scripts/check_repo_policy.py`: **POLICY_PASS**;
  `git diff --check`: PASS.
- Se añadió una prueba en GitHub runner Linux **aún no ejecutada**;
  la evidencia local valida el harness, no el socket físico.
- La corrección de mirror **aún no está validada con BuildKit real ni
  por Trivy**. No reducir seguridad de paquetes para forzar el verde.

## Puertas físicas y siguiente orden

1. Cerrar revisión independiente del mirror APT y actualizar documentación
   del PR #478 con rutas/SHA; publicar **un solo nuevo HEAD exacto**.
2. Revisar cinco Actions y jobs del nuevo HEAD. Si falla algún mirror,
   Chromium, socket UID o escáner, hacer RCA y fix-forward: **NO_GO**.
3. Solo con PR review y checks GREEN reales, merge seguro a main,
   PR0 y checks postmerge; publicación dual por digests exactos.
4. Ejecutar **únicamente** `cutover-a-census` protegido y READ_ONLY
   para distinguir cero/uno/varios controladores: el último host run
   [#42912586832](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42912586832)
   terminó `LEGACY_SINGLETON` por `len(inventory.containers)!=1`
   antes de cualquier Cutover. El censo debe identificar el caso actual,
   no habilitar borrado ni APPLY automáticamente.
5. Reconciliar por identidad bajo lease si el censo difiere; solo después
   `cutover-a-apply` una vez, demostrar 8443/passkey/socios/SQLite,
   SITE_URL montado, IPC/STOP, egreso exclusivo Boca, actividad, limpieza
   propia y aceptación física. Telegram sender ON queda en fase separada,
   después de rotación privada y prueba de mensaje; no usar token viejo.

**Restricciones intactas:** solo Boca simulation, cero reservas reales;
no inspección, limpieza, reinicio, Docker, puerto o servicios Porota/ajenos;
ninguna ejecución manual SSH/Docker al droplet; no declarar GREEN,
RECOVERED o INSTALL aceptada sin recibo físico exacto.
