# ADR 0292 — R273: reconciliar versión instalada, código y BETA; no falsificar efectos

**Fecha:** 13-NOV-2026 ART. **Proyecto:** Boca Socios Assistant. **Issue:** #417.
**Estado:** candidato CODE_ONLY; ninguna nueva release o instalación aprobada por este documento.

## RCA de continuidad y despliegue

El 13-NOV se respondió ambiguamente a «¿Boca ya está desplegado?»: se confundió
la instalación física del **par histórico** con el despliegue de la **última
versión `main`**. La posterior sobreverificación repitió controles que ya
tenían recibos auténticos, retrasando identificar el bloqueo real del sucesor.
Un `SUCCESS` de un observador READ_ONLY nunca prueba que se haya promovido
un SHA nuevo. Una Action de CI o de release tampoco prueba instalación.

Evidencia reconciliada antes del cambio:

| Plano | Fuente independiente | Resultado válido |
| --- | --- | --- |
| Instalado | Action [43455761226](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43455761226), binding de systemd exacto | `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`, `VERIFIED_LISTENING`, `MATCHED_EXACT` |
| Par/worker en reposo | Action [43455012469](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43455012469) | `pair=PASS`; worker `CREATED`, EXIT0, estado previsto bajo demanda |
| Commit original R186 | Action [43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287) | Histórico `NO_GO/RETIRE_OLD/INDETERMINATE`, irreversible e inmutable |
| Finalizador R186 | Action [43237528968](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43237528968) | `ACCEPTED`, `ARCHIVED_BINDING_ONLY`, cero Docker mutado; **consumido, no repetir** |
| Código en GitHub | `main e1b35fc9c78d2f2b3534300bda3ea4da571127d0`; [CI](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43444686315) y [seguridad](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43444686103) | Fuente revisada; **NO instalada** según la última evidencia física |

Otro RCA ya implementado: los lectores de sesión SQLite buscaban el archivo
en `boca_owner`; el productor y el almacenamiento atestado lo ubican en
`boca_data`. PR #508 corrigió ese contrato sin migrar volúmenes ni cambiar
permisos. El directorio protegido `boca_owner` y su remapeo rootless no son
por sí solos un error de permisos. No reabrir ese defecto por observaciones
de una rama antigua.

## Bloqueo técnico independiente

La única ruta de actualización permitida es el selector existente
`boca-pair-upgrade-apply`. El `main apply` de la revisión anterior hacía un
preflight auténtico pero lanzaba luego `SuccessorPreflightIneligible` de
forma incondicional: no existía una ruta operativa al backend sucesor y
despachar Actions habría dado `NO_GO` antes de tocar Docker.

La activación ingenua del helper era además peligrosa: al capturar todas
las excepciones en el mismo `try`, podía afirmar `commit_started=false` y
`failed_phase=ATTEST` después de un PARK, COMMIT, retiro o fallo del
terminal/salida del lease. Tal declaración sería materialmente falsa.

La regla R273 separa estrictamente dos fronteras:

1. **ANTES de entrar al actor:** si fracasa el memfd preflight, emitir recibo
   canónico `NO_GO/ATTEST/commit_started=false`; no se adquirió lease.
2. **DESPUÉS de entrar al actor:** conservar íntegramente el `PairUpgradeReceipt`
   auténtico, incluyendo `commit_started`, CIDs y fase fallida. Si un fallo
   impide obtener o verificar un recibo terminal, emitir únicamente un mensaje
   acotado `POST_ENTRY_UNVERIFIED/INDETERMINATE`, código no cero. Ese texto
   no es recibo canónico; el runner lo rechaza, inmoviliza el despliegue y
   exige RCA READ_ONLY sin reintento ni rollback automático.

El `ACCEPTED` técnico exige la limpieza SUCCESS V2 y el postflight persistido
genuinos bajo una sola lease, **no** una cookie ni una passkey simulada. Aun
si se consigue `TECHNICAL_ACCEPTED_OWNER_PENDING`, `BETA_DEPLOY=NO_GO` hasta
la aceptación independiente del titular prevista por ADR0285.

## Reglas permanentes y lecciones aprendidas

1. **Siempre publicar tres estados por separado:** `INSTALLED_SHA`,
   `MAIN_SHA` y `BETA_OWNER_ACCEPTED`, cada uno con fecha, run y fuente.
2. **No ejecutar observadores duplicados** cuando el mismo alcance tiene un
   recibo físico vigente; sólo una duda nueva, concreta y crítica justifica
   otra observación, sin alterar el host.
3. **No repetir ni reescribir una operación irreversible histórica.**
   `43217075287` y el finalizador `43237528968` quedan excluidos.
4. **No interpretar worker `CREATED/PID0/Health ausente` como avería** si
   su contrato es reposo bajo demanda; comprobar su par exacto.
5. **No despachar un deploy que el código rechazará determinísticamente.**
   Primero TDD RED→GREEN, revisión, CI/seguridad, PR0, release única y
   preflight actual de recursos Boca.
6. **No fabricar recibos de pre-efecto tras iniciar host operations.**
   La indeterminación obliga a detener y preservar el journal físico.
7. **`SITE_URL=NOT_CONFIGURED` es admisible sólo en postflight técnico frío,**
   nunca implica un START, actividad real de tokens o BETA aceptada.
8. **Todo efecto por la Action protegida, nunca por terminal del usuario;**
   no tocar Porota, Docker global, claves, otros puertos ni reservas reales.

## Camino de aceptación, sin repetir trabajo

`SOURCE_VERIFIED` → `RELEASE_VERIFIED` → `HOST_INSTALLED` →
`TECHNICAL_ACCEPTED_OWNER_PENDING` → `BETA_OWNER_ACCEPTED`.

No se salta una transición por tener un check verde de otra capa. Para
R273: tests y PR de la ruta actualizada; luego release dual de SHA final
**una sola vez**, observación de identidad actual necesaria para APPLY y
una sola transacción protegida si sus puertas están realmente positivas.
Si el intento es `NO_GO` o `INDETERMINATE`, parar y documentar RCA; nada
de reintentos ciegos. Último paso independiente: Chrome/passkey real,
SITE_URL editable, worker START/STOP, monitor, IPC y SQLite por el titular.

Este documento es una regla de continuidad, no un certificado de producción.
