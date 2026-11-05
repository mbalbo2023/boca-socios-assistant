# ADR 0159 — Único Actions protegido para ACK bot/Chromium y Telegram post-Cutover (#352)

**Fecha:** 2026-11-05 ART. **Estado:** DRAFT / CODE_ONLY / HOST NO_GO.
**Ownership:** solo workflow boca-first-deploy.yml, runner gate check_protected_action_context.py,
pruebas test_protected_*_r26.py y este ADR. Interfaces host son propiedad
de #351 (bot/Chromium) y #315 (Telegram). Integración canónica solo por #319.

## RCA y alcance funcional

- El panel localhost:8443 registra REQUESTED; no despacha automáticamente
  GitHub Actions. El adaptador rootless #348 ya implementa exact-ID, CLAIM y ACK,
  pero falta ejecutor protegido. **Botón no significa APPLIED inmediato.**
  La fase aprobada es una operación manual lifecycle-apply después del botón
  que produce recibo host APPLIED/REFUSED/UNCERTAIN. Una futura solución
  con efecto en un clic requiere arquitectura distinta: este PR no crea broker,
  token GitHub en panel ni socket Docker en controlador.
- El controller legacy cabce9f no admite Telegram stage V2. Tras Cutover A
  IPC y sender OFF, Tincho puede cargar token en Samsung Chrome y enviar /start.
  La interacción humana no debe ocurrir con la antigua lease/SSH abierta.
  La segunda operación telegram-activate requiere **nueva lease** en el
  mismo workflow y excluye los pasos telegram-* legacy de start/stop daemon.
- El workflow R24 ya utiliza **24 de 25** inputs workflow_dispatch, máximo
  confirmado en documentación oficial de GitHub. Ambas operaciones
  comparten un solo campo adicional, protected_action_context, apto para
  copiar/pegar como bloque único sin docenas de coordenadas en Android.

## Contrato de autorización

El único input nuevo es base64url **sin padding** sobre JSON ASCII
canónico (claves ordenadas, sin espacios ni duplicados). Payload decodificado
de 1–2048 bytes, tipos string y lista de claves exacta por
kind=lifecycle|telegram. Claves/valores secretos, comando shell, token,
nonce o tiempo humano inventado son NO_GO antes SSH.

Campos comunes públicos: version, kind, attempt_id de Actions, source main,
digest GHCR controller/browser, IDs exactos, browser attempt, hashes
Compose y data_mountpoint. El host no confía en input: reatesta Docker
rootless Boca UID10001, manifests release, configuración, IDs y almacenamiento.
No adivinar host data-root a partir de pruebas sintéticas; lifecycle exige
ruta absoluta normalizada y comparación exacta con Docker volume inspect
del volumen boca-socios_boca_data. Telegram monta /data exclusivamente.

- Lifecycle incluye expected_component=bot|chromium y
  expected_target=start|stop. Deben corresponder a la única REQUESTED
  vigente en el ledger legacy antes de CLAIM/effect/ACK. El UUID no es
  autorización por sí mismo.
- Telegram incluye recibo Cutover A previo, pins de propietario y destinatario,
  y sender inactivo. La hora stage auténtica nace del archivo server-side 0600
  y de la firma HMAC owner, no del input Actions; la ventana /start se ata
  a ese timestamp y nonce O_EXCL/antirreplay.
- Cada operación tiene variable distinta en Environment protegido:
  BOCA_LIFECYCLE_GO_BINDING_SHA256 o
  BOCA_TELEGRAM_ACTIVATE_GO_BINDING_SHA256. El SHA esperado liga repo,
  actor, ref main, source SHA, release, run/attempt, operación y SHA
  del contexto canónico. Ausente o diferente: NO_GO pre-SSH.
  Los GO cutover/import no autorizan lifecycle/Telegram.

## Secuencia

1. PR ejecuta solo CI offline, host_calls=0. Host exige dispatch manual
   main SHA exacto, propietario original, intento 1 y Environment protegido.
2. Runner autentica release/manifests, contexto estricto, GO y revalida main.
   No material privado en argv, artifacts ni resumen.
3. Un único SSH Boca recibe bundle verificado por stdin. Host adquiere una
   flock nueva y reatesta UID, config/ID, ledger/nonce, salud y sender OFF.
   Bot START/STOP usa AF_UNIX interno y worker solo Docker ID exacto.
4. Recibo host terminal es obligatorio; ausencia, timeout o incertidumbre
   implican NO_GO sin reintento, prune ni borrados por inferencia. Cutover A
   conserva su postflight Docker selectivo success/failure; los seis
   instaladores legacy permanecen bloqueados pre-SSH.
5. Cutover, stage Chrome, segunda activación y observación Samsung/Termius
   se prueban físicamente en etapas separadas. Ningún GREEN PR instala
   o comprueba Telegram por sí solo.

## Fronteras, evidencias y límites

No tocar BLACKBOX synthetic.py/ipc_worker.py, Porota, otros workloads,
kernel/servicios/puertos/volúmenes, backups, ni legacy SQLite 0008. Sin
login/fila/reserva/compra reales ni nueva navegación externa por agentes;
origen privado exclusivo 127.0.0.1:8443 por Termius. Seguridad adicional P2,
sin relajar identidad, source, autorización ni limpieza.

Baseline del PR #319: SHA 3c4880df6453a766fb8869f44913fdc1dccf539f,
TREE df560555c3b1949e2bd4e730344676fc024ea6b9, 7/7 Actions SUCCESS
sobre el mismo SHA (antes de este R26), ningún host. Referencias: issue #45
A45-R12/R12.1, #315, #328, #351, #352; ADR0151/0152/0154.
Los resultados de QA R26 y cualquier recibo real son PENDIENTES y deben
documentarse por SHA/run exactos (Regla84).
