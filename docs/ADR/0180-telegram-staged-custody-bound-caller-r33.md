# ADR0180 — Telegram R33: un único helper y un único commit V2 bajo lease

**Fecha:** 2026-11-05 ART · Issue #315 / #45 · R33 integrado como fuente
CODE_ONLY en [DRAFT #398](https://github.com/mbalbo2023/boca-socios-assistant/pull/398).
**Estado:** NO HOST / NO GO_B / SENDER OFF. El preflight de fuente dual
posterior R34 [ADR0181](0181-telegram-protected-host-bundle-boundary-r34.md)
sigue rechazando antes de SSH; no conecta este caller a producción.

## RCA

El caller R31 entrega sólo un comprobante de cuatro GET con
`custody=UNCOMMITTED`. Es intencional: no posee el plan confidencial
descifrado, de modo que intentar convertir ese comprobante en instalación
V2 requeriría **otra** serie de GET o inventar tokens/chat. El adapter
`telegram_same_lease_stage.execute_staged_pairing_under_lease` ya implementa
exactamente una serie de cuatro GET, revalidaciones entre fases, consumo
durable de nonce con `O_EXCL` e instalación/verificación V2; faltaba enlazarlo
al helper efímero exact-ID y al observador de topología activa R32.

## Diseño y guardias

1. Nuevo `run_bound_telegram_staged_custody` recibe la lease **ya adquirida**
   por el backend Boca protegido; no crea su propio `flock`, job, CLI,
   credencial, ruta, red ni puerto.
2. Antes de crear el helper verifica coordenadas exactas, misma lease,
   stage cifrado del volumen, ventana de descubrimiento firmada y HMAC
   del owner. La ausencia de owner/passkey no se reemplaza por flag.
3. Abre **un solo** `protected_ephemeral_get_session`: usuario UID10001,
   red Telegram exclusiva, mounts/puertos vacíos, cuatro GET permitidos.
   En cada fase (antes de API; antes de cada GET; antes/después de commit)
   exige prueba exact-ID del helper y observación R32 de controller/worker
   STOPPED sin poller competidor.
4. Exige además `phase_host_attestor` **externo y físicamente verdadero**.
   Sus 9 atributos de `HostRecheckReceipt` (owner, estado de servicios,
   schema, lease, egress, recipient, servicios ajenos) no se derivan de
   un mock ni del witness de helper.
5. Delega el plan secreto, nonce `O_EXCL`, cuatro GET y commit a los módulos
   existentes. Comprueba `CUSTODY_COMMITTED_NO_SEND`, mismo SHA/fingerprint,
   sender OFF, recibo humano UNVERIFIED. Fallo en cualquier fase es NO_GO
   estático; si el efecto fue incierto, **no se elimina ni reintenta nonce**.

## Dependencias físicas todavía no satisfechas

| Bloqueo | Requisito para GO_B real |
|---|---|
| Workflow | Gate independiente `telegram-activate` con Environment protegido, PREPARE/ACK exact SHA y rootless host action; hoy NO_GO pre-SSH. R34 agregó sólo revisión lineage en runner. |
| Host y owner | Cutover A ACK físico, WebAuthn UV fresco y HMAC privada, credenciales sólo en UI Chrome privada, no Secrets/argv/logs. |
| Volúmenes/UID | Atar `stage_directory` y `custody_directory` a volúmenes Boca inmutables y demostrar mapeo UID/subuid 10001. |
| Dependencias | Observador host READ_ONLY [#42125071037](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42125071037) comprobó `cryptography` Python UID10001 `AVAILABLE 41.0.7`, **pero** acceso/mapeo UID a volúmenes y lectura/escritura de custodia siguen sin verificar mientras controller STOPPED. |
| Envíos | El commit **no** activa sender ni prueba entrega. Sender real y ACK humano requieren GO separado; sin un mensaje autorizado, siguen OFF/UNVERIFIED. |

## Integración y riesgo de release

Estos módulos quedan inertes hasta que un backend físico protegido los
importe expresamente. Es posible incluirlos en **una sola imagen** de BETA
si se integran antes del freeze; no significa que Telegram esté configurado
ni que el workflow sepa usarlos. Si el host/owner gate no llega a QA físico,
desplegar core Cutover A P0 primero, sin retrasarlo. Una posterior operación
`telegram-activate` podrá ser **otra Action** con la misma imagen sólo si el
backend, los volúmenes y el runtime ya fueron resueltos; de otro modo hará
falta nuevo release, no prometer «sólo configurar».

## QA (source-only)

TDD RED: import inexistente; luego GREEN 7 pruebas con filesystem sintético
en tmp, API ficticia y Docker helper ficticio: un helper, siete fases,
cuatro GET una sola vez, nonce que sobrevive a replay, drift de helper,
topología o host, owner HMAC inválido, stage ausente y callback faltante
antes de abrir helper. Nunca se contactó al proveedor ni al host.

Este R33 no cambió workflow, BLACKBOX, Porota, servicios ajenos, puertos,
HTTPS, backups, reservas ni compras. Su consolidación en #398 es DRAFT;
R34 agrega un preflight separado de fuentes sin host, detallado en ADR0181.
Ningún test sintético o resultado de import demuestra activación ni ACK físico.
