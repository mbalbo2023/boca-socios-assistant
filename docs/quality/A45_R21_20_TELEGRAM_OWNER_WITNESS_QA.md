# Boca A45-R21.20 — witness WebAuthn fresh de Telegram, sender OFF

Fecha: 2026-11-05 ART. CODE_ONLY; 0 SSH/GO/deploy/Bot API, no compras ni reservas reales.

## Fuentes exactas

- PR candidato DRAFT #319; main físico cabce9f1e452e63ded115f447559a358dc0f4d1b intacto.
- Padre R21.19 HEAD 9e3b77f4cb01487db956bd820766607d57e05d9a, TREE 7ab2636808ff1a1374e3465512422f3179fe6767: observer Cutover+Official del #375 integrado, nuevo QA 7/7 lanzado (no reclamar GREEN sin terminal).
- PR #374 origen exacto HEAD 8078d0881cc1f7a3dedf9b8005a752489a1b6dbc / TREE 9ddc58436f75e3d4c8cdeca3de0d7a907bcbebca, 14 rutas, **6/6 Actions COMPLETED SUCCESS**, 3668 PASS +34, revisión y ownership liberado.
- Primer commit CAS del overlay #374: 2f9c553ee1b05f471c1a6c5bca9ccf3916dd5926, TREE cc74e4ead3d2ef9b9b07f80f9ead2ac336226eb0. El SHA candidato definitivo R21.20 incluirá este documento agregado por Contents API para sincronizar PR y lanzar las 7 Actions sobre todo el árbol.

## Funcionalidad agregada y delimitada

1. En Chrome local por túnel SSH, el emparejamiento Telegram exige un desafío WebAuthn ES256 reciente con verificación de usuario (UV), vinculado al SHA256 del ciphertext y a un nonce único; cookie/CSRF por sí solos no autorizan.
2. El controlador persiste sobre cifrado y witness público conjuntamente en stage O_EXCL con TTL y comparación exacta; protege contra replay/cambio de operación/ciphertext, sin token en logs ni chat.
3. Lector posterior puede verificar witness; **no emite por sí mismo autorización para Bot API egress** ni reutiliza sesión persistente como passkey fresca.
4. Telegram sender sigue OFF; host same-PID/UID/flock lease, destinatario y GET/ACK real NO_GO hasta prueba separada después del deploy y GO independiente.
5. No se incorporó PR #365 HMAC-only aislado, no se tocó BLACKBOX, Porota, Docker ajeno, HTTPS ni otros puertos (solo localhost:8443).

## Próximo gate

- Certificar siete Actions exactas del HEAD final de este checkpoint y el smoke test del conjunto, sin inferir deploy físico.
- Integrar GO_B Cutover/import PR #376 cuando fuente 4/4 GREEN, sin borrar #372 postflight checker y #375 observer.
- Sincronizar docs PR #363 al último SHA final antes de single merge/release y predeploy en GH Actions.
- Revalidar recursos droplet compartidos, ACK físicos bot/Chromium, limpieza Boca exacta, Samsung Chrome + Termius y Telegram host activation postdeploy.

Regla84: issue #45, issue #362; seguridad extra P2 no priorizada. Sin backup ni compras/reservas reales.
