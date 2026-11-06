# ADR0172 — Telegram: prueba cruzada de stage owner, lease y cuatro GET

Fecha: 2026-11-05 ART · #315 / #357 · DRAFT / CODE_ONLY.

## Decisión de alcance

Se porta byte-for-byte el satélite #377 (tres archivos verificados) a una nueva
rama basada en el main posterior al merge de #319 y se agrega una suite de
regresión que enlaza el stage V2 cifrado, la firma WebAuthn ES256 UV, la
observación del owner/controller/volúmenes bajo la misma lease simulada, un
recibo HMAC inventado, cuatro consultas sintéticas y el estado final OFF.

El test *no* usa el host ni Telegram. Inyecta una implementación fake de Docker,
un emisor ficticio de Bot API y una custodia modelada; revalida la firma del
dueño y stage antes de cada uno de los cuatro métodos. Verifica orden exacto
getMe, getWebhookInfo, getUpdates, getChat; nonce O_EXCL y respuesta final
CUSTODY_COMMITTED_NO_SEND, human_notification_receipt=UNVERIFIED. Dos caminos
negativos (webhook no vacío y revocación del dueño) deben fallar antes de
instalar: nunca se activa emisor ni se finge un ACK humano.

## Lo que queda físicamente NO_GO

La lectura del código en main demuestra que
`.github/workflows/boca-first-deploy.yml` corta `telegram-activate`
antes de SSH. El helper de #377 no está en el ZIP host stdlib-only y depende
de criptografía/FS metadata; un test sintético exitoso no arregla esto.

La implementación posterior requiere inspección física READ_ONLY de
rootless UID/subuid, controller/image/owner/pairing stage, comprobación de
recibo del Cutover A, elección explícita del caller efímero Boca-only bajo la
misma lease PID/UID/flock, host recheck de cada GET, verificación de GO
GitHub Environment y receipt físico de custodia. Un GO para sender y una
recepción humana verificada son pasos *distintos*. Preservar OFF hasta
observar esos resultados; no aceptar flags de entorno como GO.

## Límites y Regla84

Sin changes a BLACKBOX `synthetic.py`/`ipc_worker.py`, Porota, otros
contenedores, puertos, HTTPS, backups, compras reales ni reintentos ciegos.
El PR es CODE_ONLY: no release, no deploy, no credenciales, no Bot API.
Se adjuntará SHA/TREE exactos y resultados Actions de esta rama, sin
heredar checks anteriores. Documentación general del candidato core
es propiedad del integrador principal; #315 conserva el seguimiento Telegram.
