# ADR0177 — Telegram R31: enlace de lectura protegido con atestación de helper por fase

**Fecha:** 2026-11-05 ART · Issues #315/#357/#45 · Rama apilada sobre
PR #388, HEAD base `3e35bedcdec1d170d724ca8c8336e1a5fa9e5b1d`.
**Estado:** DRAFT / CODE_ONLY / NO HOST / NO GO / SENDER OFF.

## RCA de integración

El `four_gets_under_existing_lease` de ADR0173 obliga a revalidar el host
antes de cada GET, pero recibe el `session_factory` y `recheck_host` por
separado. El helper rootless exact-ID de ADR0175 verifica su identidad
dentro de cada GET, sin exponer una atestación por fase a un caller superior.
No se podía construir un enlace comprobable que demostrara que el recibo de
fase correspondía al **mismo helper efímero y lease**, sin aceptar un callback
sintético como evidencia de Docker real.

Además, los cuatro GET de ADR0173 terminan explícitamente en
`custody=UNCOMMITTED`. Su salida redacted contiene `bot_id` pero no el plan
secreto necesario para `install_v2_plan`; por ello encadenar una supuesta
custodia con ese recibo sería falso. El adaptador
`execute_staged_pairing_under_lease` de ADR0151 sí tiene commit y nonce O_EXCL,
pero requiere host rechecks auténticos, GO separado y una ruta de ejecución
con criptografía/volúmenes bajo el mismo lock. Nada de eso puede deducirse de
una prueba con fake Docker ni activarse sólo agregando una función Python.

## Cambio seguro de R31

1. `host_telegram_egress_helper.ProtectedEphemeralGet` sigue siendo callable
   para compatibilidad de #388, pero agrega `attest_phase(phase)` con ocho
   fases cerradas. Cada fase revalida el `BocaJobLease` real y el **ID exacto
   del helper recién creado**: imagen/labels/source, UID10001, env simulación,
   red exclusiva, mounts vacíos, puerto ausente, recursos acotados y Docker
   rootless Boca, sin ampliar el allowlist global de limpieza.
2. El objeto se invalida antes del cierre/cleanup del contexto. Una fase no
   contemplada, lease perdida, helper diferente o retorno después del cierre
   da NO_GO. `TelegramHelperPhaseProof` sólo contiene fase, intento, source,
   `sender=OFF`, `host_go=false`; nunca ID helper, token, chat ni provider.
3. `host_telegram_protected_readonly_caller.run_bound_telegram_four_gets`
   combina la sesión efímera única con el contrato exacto de owner stage y
   cuatro GET. Antes de delegar cada `HostRecheckReceipt`, verifica que la
   prueba del helper corresponda a las mismas coordenadas y fase. La futura
   Action debe proveer un `phase_host_attestor` **físico** que certifique
   también el controller/worker detenidos, sender OFF, cutover previo,
   owner y red; un mock no da autoridad.
4. El resultado de éxito de biblioteca es sólo
   `READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED`, cuatro GET, un helper,
   `sender=OFF`, `custody=UNCOMMITTED`, `human_receipt=UNVERIFIED` y
   `host_go=false`. No se genera nonce, no se escribe custodia, no se hace
   envío ni se toca un contenedor en un run real desde este branch.

## Qué falta para un único release definitivo

- Resolver Cutover A físico y cleanup INDETERMINATE sin reutilizar PREPARE/GO
  antiguos, y atestar source/image/digest/controller reales.
- Implementar en el **mismo workflow Boca protegido** un GO_B de Telegram
  independiente con evidencia PREPARE/ACK y lectura exacta de manifests.
  No usar un flag, un input público ni un test falso como autorización.
- Construir el `phase_host_attestor` real compatible con el helper activo,
  que valide la topología completa bajo la misma lease en cada fase. El
  observador actual `observe_telegram_host` rechaza por diseño cualquier
  peer en egress y exige controller detenido; no se puede invocar sin cambios
  durante los GET ni falsificarle un inventario sin helper.
- Conectar la recepción de owner WebAuthn UV y la credencial X25519 del
  volumen real al adaptador de custodia de ADR0151 sin segundo GET, rechecks
  y nonce O_EXCL durable. Verificar UID/subuid, librería `cryptography` y
  formato del stage en el host; mantener sender apagado y ACK humano aparte.
- Recalcular CI/seguridad/release sobre el **SHA final**. Integrar R31 ahora
  es material CODE_ONLY; no garantiza evitar un segundo release hasta que
  exista la implementación protegida completa. Congelar la release antes de
  ese wiring obligaría otro SHA y potencialmente nuevas imágenes.

## TDD, evidencias y límites

Test-first RED: dos casos fallaron con `AttributeError` al faltar
`attest_phase`; otro archivo de tests falló en import por módulo inexistente.
Después PASS focal de R31 y regresiones de R30/R29: sesión única, fases
exactas, cierre, drift de estado Docker, rechazo de fase extra, host erróneo,
ausencia de GET tras rechazo, nonce/custodia no escritos. Ningún test abre
red, navega Boca o ejecuta Docker/Telegram real.

No se modificó `.github/workflows/boca-first-deploy.yml`, BLACKBOX,
Compose, SQLite legacy, Porota, otros servicios, puertos, HTTPS, backups,
reservas ni compras. Este diseño preserva Regla84: sólo el PR y su SHA/Actions
exactos acreditarán código; un release o ACK físico requiere su propio run.
