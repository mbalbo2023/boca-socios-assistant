# ADR 0202 — R93: lectura física exacta del probe #834 sin limpieza

**Fecha:** 2026-11-07 ART. **Owners:** RCA #417, continuidad #45.
**Estado:** CODE_ONLY hasta PR/CI/revisión/merge y observación protegida.

## Evidencia inmóvil

En [R92 #834, run 42375050546](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42375050546), GitHub Actions confirmó gate one-shot/PR0, pero el preflight terminó **FAILURE**: `phase=CLEANUP`, `stage=STOP`, `cause=ACK_MULTILINE`, `cleanup=INDETERMINATE`, `host=UNVERIFIED`, sin PASS ni artefacto. El comando STOP devolvió exit0 y un `stdout.strip()` con separador interno, distinto del CID completo. El script **no ejecutó RM**. No se sabe si el probe sigue corriendo, está detenido o ausente, ni la salud *actual* del controller original. No repetir este run ni el preflight del mismo SHA.

| Pin cerrado | Valor |
| --- | --- |
| Intento y context | `42375050546` |
| Fuente R92 | `79da7ebe9918d98216ac7eb46ff008d7f6e62429` |
| Browser OCI R92 | `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:ed276066b108fad5b130d0fdffdd3f38a5a3d912253b1d4267bd4b6184992ba8` |
| Controller original CID | `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` |
| Fuente original | `cabce9f1e452e63ded115f447559a358dc0f4d1b` |
| Controller OCI original | `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59` |

## Decisión de alcance mínimo

El observador anterior admite únicamente #795/#807/#819/#827 y rechaza #834 antes de acceder al host. **R93 añade sólo el quinto par run→(SHA, digest) a `KNOWN_FAILED_PROBES` y el contexto exacto al mismo `cutover-a-worker-inspect`**. No agrega una Action genérica, no modifica Cutover/cleanup, y nunca habilita recuperar #834. Mantiene UID/GID 10001, socket Docker rootless, `/usr/bin/docker` y entorno mínimo, ps/inspect/lstat, tiempos/output acotados, recibo canónico y `observer_writes=0`. Los recursos ajenos, Porota y BLACKBOX permanecen fuera de alcance.

TDD exige RED inicial y GREEN posterior con `probe_running=false` y `true`, CID, labels, SHA, image, 8443 loopback, seccomp ausente, cero escrituras, rechazo de run desconocido y recovery #834 bloqueado. Las regresiones antiguas permanecen válidas.

## Hipótesis distinta del inventario

El código upstream Docker CLI v28 marca `--time` como deprecated; pflag/Cobra puede emitir una advertencia por stdout (Docker CLI configura `SetOut`), además del CID exitoso. **Es un mecanismo compatible con ACK_MULTILINE, todavía no una transcripción ni versión comprobada del host.** La opción `-t` es un alias de timeout en CLI antiguos y modernos. Un eventual fix-forward STOP requiere un PR/TDD **independiente** y no habilita reinterpretar o silenciar ACK. Ningún fragmento de stdout privado se divulgará.

## Siguiente recibo físico y bifurcación

Tras checks/review, ejecutar exactamente una observación GitHub Actions `cutover-a-worker-inspect` desde el nuevo `main`: `protected_action_context=42375050546`, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`, los tres pins legacy de la tabla, **todos los otros campos opcionales vacíos**, incluidos source/image/browser y ambos release IDs. El código deriva su propio `github.sha`.

- `ABSENT`: documentar; no confirma limpieza de #834.
- `PRESENT_PIN_MATCH`, `probe_running=false`, `seccomp=ABSENT`, controller `RUNNING_HEALTHY` en loopback8443: diseñar por separado una recuperación stopped-only de CID exacto, revisar y despachar bajo gate específico. No elimina nada R93.
- Contenedor activo/identidad incierta/legacy degradado: `READ_ONLY_NO_GO`, ninguna remoción ni Cutover.

No PREPARE, GO_B, APPLY, BETA ni Telegram por el mero éxito de la inspección.
