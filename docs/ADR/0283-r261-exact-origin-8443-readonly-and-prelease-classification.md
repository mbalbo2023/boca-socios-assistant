# ADR0283 — R261: diagnóstico 8443 READ_ONLY y clasificación pre-lease

**13-NOV-2026 UTC · issue #417 · CODE_ONLY · DEPLOY NO_GO.**

## Decisión y procedencia

Sobre `main=32bb9546` (PR #503) se seleccionan dos cambios independientes
de la rama anterior PR #502 (`b9a816bb`), sin integrar el PR obsoleto:

1. Selector manual `boca-panel-exact-origin-observe` y módulo
   `host_boca_panel_exact_origin_readonly.py`, estrictamente de lectura.
2. En `host_boca_pair_upgrade_cli.py`, toda excepción durante el preflight
   anterior a crear una lease o cruzar el marcador debe informar
   `commit_started=false` y `failed_phase=ATTEST`; nunca inventar COMMIT.

Los ADR #0274, #0275 y #0277 del candidato histórico están ocupados por
evidencia vigente de R257/R255/R258; este ADR usa el único número #0283.
Se descarta expresamente el mecanismo alternativo de `SITE_URL` (sentinel
cadena `NOT_CONFIGURED`) porque el contrato técnico integrado usa ausencia
real representada por `None` y lectores físicos ya revisados. No se cambia
el journal, el actor protegido, el empaquetado memfd ni la política de APPLY.

## Contrato de lectura física, sin promoción

- La Action exige las variables Boca READ_ONLY/deploy en estado `ready`,
  presupuesto exacto `1.5cpu-1024m-192pids`, formulario sin pins adicionales,
  `github.sha == HEAD de main` auténtico, checkout de `main` sin credenciales
  persistidas y `git rev-parse HEAD == BOCA_SOURCE_SHA` **antes del SSH**.
- Ejecuta mediante SSH del usuario Boca sólo un script local, fijo,
  versionado bajo `main`, con intérprete absoluto
  `/usr/bin/python3 -I -B -` para aislar importaciones de directorios y
  `site-packages` del usuario y evitar caché de bytecode. El script no tiene input de URL, CID, PID, ruta,
  comando, destino remoto ni tipo de operación; el usuario aporta sólo
  `GITHUB_RUN_ID` y `main SHA` validados. Exige UID/GID **10001:10001**.
- Realiza dos GET acotados a `http://127.0.0.1:8443/healthz`, con el
  `Host: localhost:8443` exigido por el controlador, cuerpo y cabeceras
  exactos. No contacta Internet ni solicita rutas de login, formularios,
  passkeys, tokens o reservas.
- Inspecciona con `O_PATH|O_NOFOLLOW` sólo metadatos de dos archivos SITE_URL
  y de tres archivos Boca (SQLite, clave, sesión), atravesando directorios
  sin permisos de escritura para grupo/otros. Rechaza symlinks, inodes
  cambiantes, permisos ambiguos, rutas inaccesibles y observaciones
  discordantes. No lee bytes privados ni hace Docker/systemd/cleanup.
- Su recibo canónico es **siempre** `state=OBSERVED_NO_GO`,
  `observer_writes=0`, `deploy=NO_GO`, `namespace_map=UNVERIFIED` y
  `volume_provenance=UNVERIFIED`. Las categorías `UID_EQUALS_HOST` y
  `UID_DIFFERS_FROM_HOST` **no** demuestran remapeo UID/subuid ni custodia
  Docker. Incluso `HEALTH_HTTP_200` no demuestra que el par de imágenes
  instalado sea el candidato, ni passkey, worker, monitor o persistencia.

**Límite de confianza:** a diferencia del transporte protegido SHA/allowlist
memfd de R258, este diagnóstico de solo lectura transmite el archivo Python
directamente desde el checkout autenticado de `main` por stdin/SSH. Es una
vía de confianza menor, acotada al UID Boca y a operaciones sin efectos.
No sustituye el observador rootless R259, ni puede usarse para APPLY,
postflight final o aceptación BETA. Mantener este aislamiento al evolucionar.

## Verificaciones pendientes

Las pruebas offline cubren host de la petición, códigos de salud, metadatos
sin lectura privada, symlinks y drift, recibos de esquema cerrado, exclusión
de comandos destructivos en la Action y el error preflight antes de lease.
Un CI GREEN demuestra sólo la calidad del código. La Action todavía debe
ejecutarse físicamente bajo el SHA fusionado para informar un estado real.
No se ha instalado ni iniciado un nuevo controlador/worker; no se repite R186.
