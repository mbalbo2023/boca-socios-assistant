# ADR0144 — Contrato host de CLAIM/ACK de bot y Chromium, sin ejecución física

Fecha: 2026-11-04 ART
Estado: **DRAFT / CODE_ONLY / NO_GO host**. Issue #328, PR #329 (panel).

## Decisión y ownership

El panel de PR DRAFT #329 registra cuatro solicitudes autenticadas en la
tabla `audit_events` existente. **Una solicitud REQUESTED nunca es una
operación ejecutada.** Esta propuesta implementa únicamente el lado del
contrato que un futuro workflow Boca protegido podrá usar para reconocer
CLAIMED, UNCERTAIN, APPLIED y REFUSED. Pertenece a
`src/boca_socios/host_boca_lifecycle.py`, con tests independientes y sin
alterar el módulo de intentos del panel, sus rutas, esquema ni migraciones.

El helper **no tiene CLI, main, transporte SSH, socket Docker, llamada de
inicio/parada, puerto, cron, supervisor ni acceso Telegram**. No está en el
bundle ZIP/memfd, no existe workflow effectful que lo llame y ningún cambio
se ha desplegado. Su `HostProbe` es una interfaz de pruebas/revisión, **no**
un comprobante de host: un objeto Python o JSON puede falsificarse. El futuro
adapter deberá realizar atestación real desde el rootless Docker exclusivo
de Boca, bajo la misma lease, con respuesta fresca e IDs observados; no
alcanza con inyectar un test fake, un flag o una afirmación del runner.

## Protocolo condicionado

1. El workflow protegido fija SHA exacto del código, imágenes controller y
   browser con digest inmutable, run/attempt, request UUID y los IDs de
   contenedores **observados**, no deducidos por nombres. Exige el flock
   canónico de Boca de manera ininterrumpida mediante
   `verify_protected_boca_job_lease`.
2. Un **attestor host independiente todavía no implementado** demuestra
   proyecto/servicios Boca singleton, UID rootless, origen únicamente
   `127.0.0.1:8443`, imagen y SHA exactos, volumen exclusivo
   `boca-socios_boca_data` con punto de montaje correspondiente a la SQLite,
   worker sin IP (`network_mode=none`), controlador healthy/running y estado
   real del componente.
   Para `bot`, un bit de **motor sintético real** debe ser observado; una
   pausa de admisión NO equivale a un motor detenido. Para `chromium`, se
   exige el ID exacto del worker y su estado observado. Si el bit de motor
   es desconocido, falla cerrado.
3. Reabre únicamente la SQLite legacy ya existente por URI `mode=rw`;
   exige UID/GID del proceso, archivo privado 0600, `nlink=1`, inode estable,
   integridad básica y ausencia de versión/tabla owner 0008. **No crea la
   base, no ejecuta DDL, no toca la SQLite lateral de sesión Chrome**. Bajo
   `BEGIN IMMEDIATE`, comprueba que la última solicitud global sea el UUID,
   componente y destino exactos con estado REQUESTED, y añade el `CLAIMED`
   calculado por el contrato de PR #329.
4. Sólo después de eso un **futuro** ejecutor de host podrá intentar el
   efecto físico (este módulo no tiene método que lo haga). Luego debe
   comprobar de nuevo identidad, aislamiento, controller healthy y
   postestado. `APPLIED` sólo se admite si hubo intento verificable y un
   cambio real al estado pedido; `REFUSED` sólo si **no** hubo efecto y el
   estado no cambió. Resultado parcial/desconocido se registra UNCERTAIN;
   ninguna nueva orden se acepta hasta reconocimiento protegido.
5. ACK se escribe append-only con el UUIDv5 del panel. APPLIED y REFUSED
   comparten la misma clave: nunca pueden coexistir. Una transición
   UNCERTAIN puede recibir luego un único ACK bajo una nueva evidencia
   física válida; el helper no borra, reemplaza ni reintenta operaciones.
   Si se pierde lease, identidad, SQLite o host ACK, se mantiene NO_GO.

## Límites críticos que impiden activación

- No existe aún la implementación de `HostProbe` que lea y valide Docker,
  el estado real del motor bot, el manifiesto de contenedor y el recibo de
  efecto. El parámetro `effect_attempted` por sí solo es una declaración del
  futuro ejecutor, **no** un testigo criptográfico independiente.
- No existe un host executor protegido que pueda START/STOP motor y worker
  sin detener el panel HTTP; tampoco `beta-browser-stop` ni una forma de
  reconciliar un ACK perdido de una ejecución anterior con nueva autorización.
- La política de cleanup Boca-only después de cada operación (PASS/FAIL),
  los checks de seguridad #326, único GO exacto, integración #320, Option B
  y validación Samsung Chrome/Termius permanecen gates independientes.
- El lector normal de `LifecycleIntentStore` es reutilizado para evitar
  discrepancias de protocolo. Antes de introducir este helper en un memfd
  privilegiado se deben revisar y empaquetar explícitamente sus dependencias
  (sin BLACKBOX) o extraer un core stdlib-only equivalente; **no** debe
  copiarse automáticamente un árbol de paquetes al host.

## Evidencia de alcance

Pruebas sintéticas del host contract: claim y ACK persistentes visibles al
panel tras reinicio, inicio/detención, motor desconocido, worker/digest/port/
source SHA ajenos, rootless/lease inexistentes, refusals sin efecto,
incertidumbre que bloquea otras solicitudes, replay, SQLite insegura o
ausente y esquema 0008 prohibido. Ejecutan `FakeBocaAttestor` explícito,
**sin Docker, SSH, Telegram, navegación Boca ni efectos físicos**.

Regla84: publicar SHA y tree reales del PR DRAFT, checks CI/Actions con
estado confirmado, alcance y P0 restante en #328/#45. **Nunca** llamar
`APPLIED` físico a un test unitario. El backend y las vistas protegidas de
`synthetic.py` e `ipc_worker.py` se mantienen intocables y sin inspección.
