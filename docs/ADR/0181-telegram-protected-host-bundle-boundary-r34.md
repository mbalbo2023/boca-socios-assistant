# ADR0181 — Telegram R34: bundle host independiente y GO_B pendiente

**Fecha:** 2026-11-05 ART. **Owner:** issue #315 (Telegram). **Estado:**
DRAFT #398, CODE_ONLY, NO RELEASE / NO HOST / NO ENV GO_B / SENDER OFF.

## Decisión arquitectónica

La primera imagen BETA puede incluir todos los módulos Telegram del candidato
consolidado #398, sin introducir un segundo servicio, puerto, HTTPS ni envíos.
Sin embargo, el workflow `telegram-activate` sigue rechazando antes de SSH:
`host_same_lease_backend_unverified`. La presencia de Python en una imagen
no crea un caller físico ni autoriza consumir un nonce o escribir custodia.

El bundle protegido de Cutover A `scripts/build_protected_boca_bundle.py`
estaba al corte en **765.019 bytes** de fuentes bajo un límite de 768.000.
La clausura Telegram supone más de 180 KB; mezclarla con ese artefacto cambia
su integridad y la superficie del despliegue P0. Se adopta **un artefacto
Telegram distinto**: `scripts/build_protected_telegram_bundle.py`, con 31
fuentes explícitamente incluidas, inicializadores host mínimos, ZIP
determinístico fechado 1980, tamaño sin comprimir máximo 450 KB y comprimido
máximo 300 KB. El builder rechaza fuentes simbólicas, ausentes, sobredimensionadas
y destinos existentes. Excluye BLACKBOX y cualquier Compose/Port/Workload ajeno.

Su **único comando disponible** es `selftest`: importa el cierre del
stage/custodia/lease/helper y devuelve comprobante de código `sender=OFF`.
El selector `activate`, un argumento desconocido o invocación sin argumento
devuelven `NO_GO`, código de salida 2, sin importar secretos ni Docker.
**No** se ha unido el ZIP a la acción protegida ni se ha ejecutado en el host.

## Comparativa de runtime físico

| Opción | Beneficio | Requisito / riesgo | Estado real |
|---|---|---|---|
| A: Python host UID10001 | Reutilizar `run_bound_telegram_staged_custody` y un único `BocaJobLease` | Host debe importar `cryptography` y **acceder correctamente** a directorios y llave del volumen Boca bajo mapa rootless; PASS de import no implica PASS de lectura | Host import `AVAILABLE 41.0.7` en [READ_ONLY #42125071037](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42125071037); UID/subuid y custodia NO_GO hasta próximo recibo |
| A2: `docker exec` controller | Reutiliza Python crypto de imagen | El contrato exige controller/worker **STOPPED** durante los cuatro GET; `docker exec` necesita controller RUNNING | Incompatible con el contrato actual, NO_GO |
| B: contenedor efímero crypto de **misma imagen** sin red | Evita dependencias crypto en host, sin segunda imagen | Debe transferir callbacks/rechecks al proceso host con una sola lease, secretos sólo por IPC, uno solo helper egress sin mounts, custodia volumen UID10001 y postflight | No implementado ni probado; requiere ADR/QA específica |

## Puertas de operación y no-segundo-deploy

Para que el dueño configure el bot posteriormente vía
`http://localhost:8443/telegram/emparejar` **sin ningún cambio de código
posterior**, la primera release debe incluir (a) módulos Telegram y bundle,
(b) backend físico **efectivamente conectado** a `telegram-activate`, (c) protocolo
GO_B independiente PREPARE/APPLY con exact SHA/digest y Environment protegido,
(d) autenticación WebAuthn UV fresca y HMAC sin exponer token, (e) una sola
lease con 4 GET, nonce durable y commit V2, y (f) finalizador Boca-only en
SUCCESS y FAILURE con ACK. Si cualquiera falta al freeze, **no** es honesto
prometer «sólo configuración» posterior ni GREEN de Telegram. La vía de
fuente dual, detallada abajo, podría permitir **un merge adicional de workflow
sin otra imagen OCI**, pero tampoco sería una configuración sin desarrollo.

El stage cifrado existe en el volumen de datos y se completa desde Chrome
por el dueño. El propietario ya dispone del token; **nunca** se pide pegarlo
en chat, Issue, Actions input o log. El commit V2 deja `sender=OFF` y
`human_receipt=UNVERIFIED`; START real y aviso humano son operaciones y
aceptaciones separadas. No hay compras ni reservas reales.

### Fuente dual acotada a Telegram — opción para no repetir la imagen

El gate heredado exige `BOCA_SOURCE_SHA == GITHUB_SHA`. Es correcto para
Cutover A y operaciones legacy, pero impediría usar **la imagen ya publicada**
si un arreglo posterior afecta sólo al workflow. La alternativa propuesta
divide dos identidades, ambas verificadas por separado:

1. `workflow_sha = GITHUB_SHA`: commit exacto actual de `main`, verificado
   con el GitHub ref antes de cualquier SSH.
2. `image_source_sha = inputs.source_sha`: provenance exacta de ambas imágenes
   inmutables, verificadas contra release run/manifests y contenedores
   instalados; no se acepta otra imagen implícitamente.
3. GitHub Compare `image_source_sha...workflow_sha` debe ser `identical` o
   `ahead` sin commits `behind`, con `merge_base_sha == image_source_sha`.
   El script nuevo `scripts/check_telegram_release_lineage.py` valida sólo
   una proyección JSON mínima del compare real, sin acceso a red ni host.
4. El eventual artefacto PREPARE y GO_B deben firmar **ambos SHAs**, los dos
   digests de imágenes, IDs exactos y nonce; la operación debe retener la
   lease hasta postflight. Una respuesta JSON fabricada en CI **no** es GO.

El decodificador público existente `check_protected_action_context.py` ya
exige `workflow_sha` adicional **sólo para kind=telegram** y lo compara con
`GITHUB_SHA`, mientras conserva `source_sha == BOCA_SOURCE_SHA` para la
imagen. `_environment(..., operation="telegram-activate")` acepta esa
distinción, pero su llamada sin Telegram sigue requiriendo igualdad exacta.
No se ha conectado un PREPARE de Telegram ni un GO_B firmante: el contexto
por sí solo nunca autoriza nada y la Action termina antes de SSH.

**Estado:** contrato de parser **CODE_ONLY conectado sólo al preflight de
`telegram-activate`**. El workflow valida primero main HEAD (`GITHUB_SHA`),
release exacto (`BOCA_SOURCE_SHA`) y ambas imágenes, obtiene proyección de
GitHub Compare y construye el ZIP Telegram en runner; luego ejecuta
**incondicionalmente `exit 1` antes de cualquier SSH**, con resumen redacted
`host_same_lease_backend_unverified`. Falla cerrado incluso si ancestry PASS.
Las operaciones no-Telegram siguen ancladas al mismo SHA de
workflow e imagen; no se modifica Cutover A ni se concede rollback de imagen.
El resultado `ANCESTRY_OBSERVED_NO_GO` demuestra únicamente posibilidad
estructural de reutilizar OCI, **no** que el host haya sido autorizado, que
el backend ya funcione o que una segunda imagen sea innecesaria en todos
los casos.

## Evidencia (únicamente local / no desplegada)

- `tests/test_protected_telegram_host_bundle_r34.py`: 5 pruebas PASS,
  ZIP reproducible, allowlist sin BLACKBOX/Compose, import autocontenido
  con Python aislado, NO_GO en `activate`, symlink/oversize y no overwrite.
- `tests/test_telegram_release_lineage_r34.py`: 23 pruebas PASS,
  fuente original vs. workflow descendiente, misma fuente inicial,
  divergencia, SHA erróneo, JSON extra/duplicado/no canónico, CLI offline
  y orden de `NO_GO` antes del primer SSH protegido.
- `tests/test_protected_action_context_r26.py`: regresión adicional en la
  matriz Telegram: fuente de imagen antigua + workflow nuevo válido sólo
  si el contexto declara ambos SHA; lifecycle con esa diferencia rechazada.
- Fuentes revisadas: 362.281 bytes bajo máximo 450.000, calculado localmente
  al corte previo a nueva integración; no implica compatibilidad física.
- Verificación física parcial: observación Boca READ_ONLY
  `#42125071037` confirmó **sólo** host Python `cryptography 41.0.7`
  importable como UID10001, sin escrituras. No atestigua mapeo rootless,
  permisos de volumen, llave ni posibilidad de ejecutar el caller.
- Verificación host UID/subuid, volumen, fuente final,
  GO_B y receipts de custodia reales: **PENDIENTE**. Cualquier fallo es NO_GO; no ejecutar
  preparación con efectos ni sender automáticamente.

## Alcance inmutable

Se preservan BLACKBOX, Porota, todos los demás servicios Docker y sus datos,
el único `127.0.0.1:8443`, sin HTTPS/puertos nuevos, ni backups, ni limpieza
global. Este ADR no cambia el bundle de Cutover A y no representa autorización
para saltar el gate GitHub ni un ACK físico.
