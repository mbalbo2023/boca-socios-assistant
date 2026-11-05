# ADR0178 — Telegram R32: observador read-only con helper efímero activo

**Fecha:** 2026-11-05 ART · Issues #315/#45 · Stack DRAFT #388 → #393 → R32.
**Estado:** CODE_ONLY / NO HOST / NO GO_B / NO CUSTODIA / SENDER OFF.

## RCA comprobado

`host_telegram_postcutover.observe_telegram_host` (ADR0160) verifica el
estado inactivo instalado exigiendo exactamente controller + browser-worker,
opcional sender STOPPED y **red Telegram egress vacía**. Durante los cuatro
GET de la fase protegida, el único peer autorizado es el helper efímero
UID10001 de ADR0175. Por lo tanto ese observer rechazaba legítimamente el
estado real de una sesión activa: no era correcto cambiar la exigencia general
de egress vacío ni marcar a mano todos los campos de `HostRecheckReceipt`.

## Decisión

1. `ProtectedEphemeralGet.attest_topology(phase)` sólo está disponible dentro
   del context manager del **mismo helper exact-ID y BocaJobLease** que lo
   creó. Mantiene fases cerradas, revalidación de lease e identidad real del
   helper; no expone ID, token, chat ni paths en el recibo público.
2. El nuevo módulo `host_telegram_active_helper_topology` obtiene el
   inventario físico Boca rootless, vuelve a atestar por sí mismo el ID,
   env sin secretos, mounts y límites del helper, y comprueba **exactamente** los 2/3 servicios
   previstos más ese único helper, y confirma que egress tiene exactamente
   ese ID, sin peers adicionales. Rechaza IDs duplicados, contenedores
   inesperados, coordenadas o fase ajena.
3. Sólo después de esa prueba, crea una proyección interna limitada que
   excluye **ese ID** y su conexión egress para reutilizar intactas las
   verificaciones del observer de estado inactivo: controller/worker STOPPED,
   labels, imágenes, config hashes, ports localhost:8443, redes, mounts,
   sender OFF, volúmenes, UID/GID y provenance. La proyección nunca se
   expone como evidencia de host a un workflow.
4. Vuelve a inventariar tras las lecturas para rechazar drift de objetos;
   revalida la lease antes de devolver **sólo**
   `ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO`. Sigue sin permitir
   acciones de Docker, egress nuevo, emisión ni custodia.
5. El caller R31 requiere esta prueba antes de entregar cada fase a su
   `phase_host_attestor`. El callback sigue siendo obligatorio y debe
   aportar *evidencia física real* de owner/WebAuthn, schema, recipient
   custody, GO_B, cutover ACK y ausencia de impacto a otros servicios.
   Esta nueva observación **NO** emite ni autoriza `HostRecheckReceipt`.

## Qué todavía impide prometer un único despliegue

- Falta wiring del backend y Environment protegido `telegram-activate`;
  hoy `NO_GO` pre-SSH. No se toca workflow por ownership cleanup.
- Falta custodia real `execute_staged_pairing_under_lease` con owner WebAuthn,
  HMAC privada, volúmenes/UID/subuid/`cryptography` comprobados, nonce O_EXCL
  y exactamente **una** serie de 4 GET de Bot API. El R31 de lectura deja
  `custody=UNCOMMITTED`, por lo que no se puede agregar commit por inferencia.
- Sender real y acuse humano necesitan su propio GO protegido posterior,
  distinto del ACK de código y del ACK físico de Cutover A.

Un **único release de imagen** sigue siendo posible si estos componentes y
evidencias pasan a main antes del SHA freeze; la activación Telegram podría
ser otra Action protegida sin otro pull/deploy de imagen. No hay garantía
hasta pruebas físicas: si el host gating falla o el SHA ya se congeló, hay
que priorizar BETA core y planear release incremental Telegram.

## Verificación

TDD RED: import de observer inexistente y luego dos negativos en caller
(`TOPOLOGY` ausente y drift no rechazado). GREEN focal: topología nominal
sin efectos, extra/foreign container, segundo poller, controller que arranca,
inventario que muta, invocación directa con helper falso/env con token,
sesión cerrada y fase fuera de allowlist; caller no
invoca host si falló helper o topología. Se registrarán en PR exact-SHA las
pruebas integrales, lint, mypy, política y Actions reales.

No hay lanzamiento Docker ni invocación Bot API en pruebas, modificación de
BLACKBOX, otros servicios, Porota, puertos, backups, reservas o compras.
