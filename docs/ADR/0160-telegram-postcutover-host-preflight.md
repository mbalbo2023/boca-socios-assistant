# ADR 0160 — Telegram post-Cutover host: atestación parcial, NO_GO físico

Fecha: 2026-11-05 ART. Issue #357; seguimiento canónico #45 y Telegram #315.
**Estado: DRAFT / CODE-ONLY / HOST NO_GO / SIN BOT API.** Owner exclusivo:
Telegram HOST R27. Base candidato #319 `6daffeecb0c6a33afca750ab19d9f5c7e69e1583`.

## RCA observado en código existente

La ejecución física del paso 2 **después** de Cutover A no tiene backend listo,
aunque el panel pueda guardar un sobre Telegram V2 cifrado y aunque el parser
de Telegram permita cuatro lecturas GET-only:

1. `host_first_deploy._telegram_container` monta solo `boca_telegram` **o**
   `boca_data`, siempre `--network none`. Sirve para preparar claves o migrar
   schema 0007, no para leer stage y custodia simultáneamente.
2. `host_first_deploy._telegram_test_container` ya usa ambos volúmenes Boca y
   `boca-socios_telegram_egress` en un contenedor efímero, pero **no** importa
   `BocaJobLease`, no comparte el inode canónico
   `/run/user/10001/boca-socios-protected-job.lock`, no tiene revalidación
   física host por cada GET ni firma owner/passkey.
3. `telegram_same_lease_stage.execute_staged_pairing_under_lease` verifica
   un único flock en el proceso, firma HMAC independiente de `stage_id`,
   nonce durable O_EXCL, `staged_at` firmado y ≤3600s, cuatro consultas
   Telegram controladas y custodia privada. Un runner que le pasa `true` a
   `owner_authenticated`, `sender_off` o `recipient_custody_verified` no
   produce pruebas físicas. El panel HTTP tampoco posee la clave HMAC host
   ni autoridad para operar Docker.
4. En 05-Nov el release nuevo no está físicamente instalado. Main sigue
   BETA legacy, por lo que no existe recibo real de stage V2 postcutover.
   Mantener abierta la lease de Cutover A para esperar Chrome/Telegram no
   es aceptable. La ventana de mensajes `/start` entre stage y Actions se
   resuelve en PR #353 con `discovery_not_before=staged_at`.

## Decisión aprobada sin nuevos permisos

Se agrega `host_telegram_postcutover.py`, con **una sola operación read-only**
`observe_telegram_host(pins, lease, io=None)`, sin CLI ni acciones:

- Exige la lease existente de UID10001 y verifica su identidad antes/después.
- Los pins públicos del workflow son datos NO CONFIABLES. Exige SHA/release
  exactos, ID controlador/worker, digest GHCR, Hash Config Compose, intento
  Browser previo, recibo Cutover y fingerprint recipient sintácticamente
  válidos, `sender_expected_state=absent|stopped` y `/data` fijo.
- Consulta exclusivamente el Docker rootless **Boca** mediante el adaptador
  existente: inventario exacto de dos servicios (o tres si sender instalado),
  ambos detenidos, sender OFF, imágenes/source, mounts, red, loopback 8443,
  5 volúmenes del proyecto, Telegram egress aislada con 0 conexiones, sin
  procesos de polling competidores. Reusa `_service_boundary` para comprobar
  las propiedades exactas del servicio, evitando un segundo contrato
  parcialmente divergente.
- El resultado, aun con inventario observado, es
  `TOPOLOGY_OBSERVED_NOT_AUTHORIZED`, `authorized=False`,
  `host_effects=False`, `human_receipt=UNVERIFIED`. No guarda ruta absoluta
  del host, token, nonce, claves ni chat ID. Un fake IO testable no es una
  credencial; para producción hay que usar `ProductionRootlessDockerIO`
  dentro de un despacho protegido ya aprobado.
- No lee el contenido del stage ni secretos, no cifra/descifra y no crea,
  para, elimina o toca contenedores/volúmenes/redes. Un topology pass jamás
  se interpreta como `CUSTODY_COMMITTED_NO_SEND` ni como GO de sender.

**Limitación explícita**: no se incorpora todavía un host caller de
`execute_staged_pairing_under_lease`; el módulo no puede reportar READY.
El operador de workflow #352 debe mantener el job Telegram físicamente
NO_GO hasta disponer de prueba no simulada de owner passkey y del bridge
de lease/egress/custodia autorizado, además del GO protegido.

## Dos opciones para terminar el P0 (requieren decisión y GO específico)

| Opción | Arquitectura | Beneficio | Riesgo/costo |
|---|---|---|---|
| A (recomendada condicional) | Extender el patrón efímero `telegram-test` del **mismo** daemon rootless Boca, con ambos volúmenes existentes, red Telegram dedicada, lease canónica revalidada y canal host de atestación antes de cada GET. | Dependencias `cryptography` ya están en la imagen fijada; ningún puerto, volumen ni servicio permanente adicional. | Nuevo contrato de bind/IPC y contenedor efímero; hay que probar identidad del flock/PID y limpieza selectiva post-éxito/fallo antes del GO. |
| B | Resolver en proceso host UID10001 bajo lease existente y cuatro HTTPS GETs, con custodia del volumen montado y biblioteca criptográfica host. | Evita un segundo proceso/contenedor Docker. | No hay evidencia de biblioteca criptográfica ni ruta de egress Telegram dedicada desde host, y no debe relajarse aislamiento sólo por conveniencia. Requiere demostración read-only. |

En ambas: primero dueño autenticado realmente, HMAC fuera del código/SQLite y
revisión de `staged_at`/recipient, no tomar credenciales por argv, logs o
Actions; después GO de activación específico, exact main/release y ACK redacted.
Un GO posterior **distinto** para sender y una recepción humana separada.
Si stage O_EXCL vence >3600s, hace falta recuperación explícita a través
de la UI privada del owner, sin sobreescribir/borrar unilateralmente.

## Evidencia CI y alcance

`tests/test_host_telegram_postcutover.py` usa inventario falso sin comandos
Docker, red, archivos de secretos ni bot real. Comprueba ausencia o parada del
sender, drift en ConfigHash/imagen/volúmenes/red/puerto, lease incorrecta,
contenedor extranjero, ausencia de egress exclusiva y que un resultado
perfecto **siempre** sea no autorizante.

No se tocan BLACKBOX, GitHub workflow, Compose, host lifecycle, SQLite
legacy 0008, Porota, puertos externos, HTTPS, backups, notificaciones,
reservas ni compras. Los resultados exactos SHA/TREE y Actions PR-only se
anotan en PR #357 y issues #315/#45 según Regla84.
