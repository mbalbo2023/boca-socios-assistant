# ADR 0168 — Recibo postdeploy Boca exacto y verificable (#323)

**05/11/2026 ART · CODE_ONLY / DRAFT / host NO_GO.**

## RCA

La política permanente exige que el mismo deploy protegido, en PASS y FAIL,
publique evidencia selectiva de limpieza (bytes e inodos de área de staging y
Docker rootless, identidades exactas retiradas y residuos inciertos). En la
candidata integral #319 R21.17, la planificación y eliminación exact-ID ya
calculan `CleanupReceipt`, pero Cutover A convertía el resultado en el solo
texto `cleanup=ACCEPT`. Los datos de antes/después y recursos eliminados se
perdían antes del ACK de Actions. Sin ellos no se puede auditar la higiene.

## Decisión y límites

- Mantener Docker **exclusivamente** rootless Boca UID/GID10001 y proyecto
  `boca-socios`; conservar aplicación activa, imágenes referenciadas por
  cualquier contenedor, cuatro volúmenes persistentes, recursos inciertos.
- Reutilizar el inventario/readback y el límite `MAX_DELETIONS=32` de #323;
  nunca `docker system prune`, `image prune -a`, `-f`, glob ni Compose down.
- Añadir un recibo público ASCII canónico y acotado sólo con estado, attempt,
  conteos bytes/inodos antes/después (área Boca+Docker), lista de exact-ID
  positivamente eliminados y razones estrictamente enumeradas de retención.
  Información personal, contenido de volumen, credenciales y etiquetas
  arbitrarias de contenedores nunca se publican.
- Cutover A sólo puede confirmar `cleanup=ACCEPT` con un `CleanupReceipt`
  auténtico y completo de su mismo backend/lease; un resultado ausente,
  parcialmente escrito, ambiguo o mismatch produce NO_GO. Probar PASS y FAIL
  recuperado, drift/cancelación, imagen activa y otra aplicación protegidas.
- GO B Cutover mantiene la autorización independiente, PREPARE/APPLY, una
  llamada SSH y marcador O_EXCL, sin introducir nuevos workflow/puertos/host
  acciones. La publicación de dos líneas en stdout requiere ajuste estricto
  del verificador de host en la única Actions. Preservar compatibilidad de
  token histórico v1 sin privilegiar un ACK sin evidencia para la ruta v2.

## QA y estado

Tests primero en rama feature/323-postdeploy-receipt-exact-r31, procedencia
candidata única #319 R21.17 `82c7c3edf75911805218149d4907ecb37b374a66`.
Los recibos físicos en droplet y la limpieza real **NO se ejecutaron**;
el workflow owner #371 conserva edición exclusiva YAML y debe integrar sólo
ABI validado con QA exacto. El futuro PR satélite no fusiona por sí solo
y no implica nuevo GO, backup, tickets reales ni cambio BLACKBOX/Porota.

RCA y evidencia Rule84: issue #323 y checkpoint #45 (root documental).
