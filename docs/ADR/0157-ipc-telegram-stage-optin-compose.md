# ADR 0157 — Telegram V2: opt-in cifrado sólo en el controller IPC del Cutover A

**Fecha:** 2026-11-05 ART. **Estado:** DRAFT / CODE-ONLY / NO HOST / NO GO.
**Ownership:** issue #315, subfrente de Compose y contrato de despliegue. Candidato
integral [#319](https://github.com/mbalbo2023/boca-socios-assistant/pull/319).

## RCA funcional P0

[ADR0149](0149-runtime-telegram-v2-staging-optin.md) implementó el callback
`telegram_pairing_stage_mode=encrypted-only` en el runtime, pero dejó el
opt-in fuera de Compose y Actions. La única composición aprobada para el
controller posterior a Cutover A es la combinación
`compose.beta.yaml` + `compose.beta.browser.yaml`. El overlay activaba
`BOCA_BROWSER_BACKEND=ipc` sin
`BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only`. Por eso, incluso
después del Cutover A, el panel autenticado podía mostrar la ruta
`/telegram/emparejar`, pero POST no tenía el callback de escritura;
la fase protegida de activación Telegram no tendría un stage cifrado real
que consumir. El controller físico legacy sigue sin este opt-in.

La corrección no puede hacerse agregando la variable sólo en un workflow:
el controller contenedorizado debe recibir una configuración de entorno
propia de su modelo Compose aprobado. Tampoco puede agregarse a
`compose.beta.yaml`, porque habilitaría staging en el controlador
legacy/backend `off` y debilitaría el aislamiento entre fases.

## Decisión aprobada dentro de BETA de simulación

1. **Base intacta:** `compose.beta.yaml` conserva motor `off`,
   `boca_data:/data`, puerto exclusivo de host
   `127.0.0.1:8443`, tres volúmenes y controller legacy sin opt-in.
2. **Overlay IPC exclusivamente:** `compose.beta.browser.yaml` agrega
   al servicio `controller`, y sólo allí, el valor literal
   `BOCA_TELEGRAM_PAIRING_STAGE_MODE: "encrypted-only"` junto a
   `BOCA_BROWSER_BACKEND: ipc`. El navegador worker no recibe
   token, stage, claves privadas ni volumen `/data`; no se crea
   servicio Telegram ni se habilita sender. Los límites, redes, puertos,
   healthchecks y modos de simulación existentes no cambian.
3. **Contrato de Compose estricto:** el validador
   `validate_beta_browser_contract` exige ambos valores fijos
   (`ipc` y `encrypted-only`), los retira exclusivamente de la copia
   del modelo V2 antes de verificar el contrato legacy original.
   Ausencia, `off`, valores distintos, env extra, staging en worker o
   alteración de backend producen `NO_GO`; la validación de Compose legacy
   permanece sin modificaciones y sigue rechazando staging.
4. **Habilitación temporal:** Cutover A aún debe autenticar el nuevo SHA
   de overlay dentro de su ZIP/GO y atestar controller, imagen y
   volumen Boca existentes. Sólo después de completar realmente Cutover A
   podrá Tincho entrar en Samsung Chrome vía Termius
   `http://localhost:8443` y guardar **un sobre V2 ya cifrado**;
   el recibo honesto permanece `STAGED_PENDING_PROTECTED_CUTOVER`.
   La segunda operación `telegram-activate` con lease nueva y GO
   independiente pertenece al frente #315/ADR0156; staging jamás implica
   Telegram conectado ni autoriza acceso del controller al Bot API.
5. **Seguridad adicional P2, invariantes intactos:** no se modifica
   `synthetic.py` ni `ipc_worker.py` (BLACKBOX), no hay navegación
   Boca/Queue-it, compras, reservas, backup, esquema SQLite 0008,
   otros puertos, HTTPS, host, Porota ni cargas ajenas. No se guarda ni
   solicita token/PIN en GitHub o chat.

## Regresiones y alcance de la evidencia

Prueba test-first
`tests/test_telegram_stage_compose_optin_r27.py`: overlay sin opt-in
(Red esperado antes de implementación), activación IPC exacta, siete
valores no autorizados, prohibición de staging en worker y legacy,
controller con backend `off`, ausencia de sender/puerto nuevo.
`tests/test_beta_browser_deploy_contract.py` actualiza sólo el modelo
sintético del overlay para exigir la variable revisada. La CI existente
también resuelve el Compose real a JSON con Docker Compose sobre runner
efímero y ejecuta el validador exacto.

Los tests son **code-only**; incluso todos GREEN no acreditan que el
nuevo overlay haya sido instalado, que la ruta POST funcione en el
Samsung, que exista un stage real, ni que Telegram haya recibido o enviado
un mensaje. El integrador debe incorporar los cinco paths verificados al
único PR #319, ejecutar QA y predeploy exact nuevo SHA, obtener GO específico
para merge/release/Cutover A y luego validar físicamente mediante el
workflow protegido existente.

**Regla84:** documentar SHA, árbol, Actions exactos y limitaciones en el PR
de este frente y en issue propio. El dueño de #319 conserva la escritura del
checkpoint canónico #45. No repetir los pasos de passkey o
`beta-install` legacy ya completados.
