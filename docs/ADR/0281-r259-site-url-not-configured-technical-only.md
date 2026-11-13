# ADR 0281 — R259: ausencia real de SITE_URL en postflight técnico

**Fecha:** 2026-11-13 UTC (2026-11-12 ART). **Issue:** #417.
**Estado:** CODE_ONLY; `DEPLOY NO_GO`. Ningún host/Actions APPLY ejecutado.

## RCA

R255 distinguía antes de `PARK` una configuración `SITE_URL` ausente de
un error de lectura mediante dos probes físicos: `site_url_state=NOT_CONFIGURED`
y fingerprint `None`. Sin embargo, `PreParkExpectedSeed.expected_after_cleanup`
rechazaba ese estado y `PostflightExpected` exigía 64 caracteres hexadecimales.
El verificador post-cleanup también exigía huellas de la URL guardada y del
espejo del worker. Si la URL sigue legítimamente vacía, un futuro backend
podría cruzar `COMMIT_MARKER`/`RETIRE_OLD` y después fracasar de manera
determinística, sin rollback permitido. ADR0271 es antecedente histórico;
se reemplaza sólo su veto a construir el `PostflightExpected` técnico.

## Decisión

1. Se conserva intacto el camino **configurado**: una huella hexadecimal real
   de `SITE_URL` debe coincidir entre controlador viejo, controlador nuevo y
   volumen espejo; no se inventa ninguna URL o digest. `NOT_CONFIGURED` sólo
   admite `site_url_fingerprint=None`, y ambas lecturas anteriores a `PARK`
   deben concordar bajo la misma lease de Boca.
2. Después del SUCCESS oficial de limpieza V2, `expected_after_cleanup`
   puede construir las coordenadas nuevas reales con fingerprint `None`.
   No usa IDs previstos, de formulario ni de un artefacto distinto: exige
   dos observaciones físicas del nuevo par y su binding con lease retenida.
3. Antes del marcador irreversible, el backend puede llamar
   `attest_precommit_candidate_site_state(plan, new_controller_id,
   new_worker_id, lease, seed)` **después** de su `replace_binding`. Ese veto
   vuelve a leer dos veces el binding autenticado al nuevo source/ambos
   CIDs, exige que el inventario de CIDs del daemon Boca rootless tenga
   exactamente los cuatro contenedores viejo+nuevo y ejecuta en el nuevo
   controlador únicamente dos probes fijos de la URL guardada y su espejo,
   ambos antes/después de revisar la lease y el binding. Un resultado ausente
   se acepta sólo si **ambos** probes confirman la ausencia; cualquier
   mezcla, cambio, CID ajeno, binding incorrecto o error deniega el marker.
   Esto complementa los controles de composición, montajes y worker frio del
   backend; no los reemplaza y no otorga una capacidad APPLY por sí mismo.
4. **Sólo el perfil técnico `schema=2`** permite esa ausencia. El snapshot
   debe confirmar **en cada una de dos observaciones post-cleanup** que
   el archivo de configuración guardada en el controlador nuevo y el archivo
   espejo del worker están verdaderamente ausentes; el worker sigue
   `CREATED/PID0/Exit0`, no se lo inicia ni se visita ninguna URL. El
   productor guardado mantiene la lectura con `SiteUrlSettingsStore.read()`;
   el espejo usa `_directory` y `_read_from` del transporte URL-only, que
   devuelven ausencia únicamente por `FileNotFoundError` de su hijo fijo y
   rechazan directorios, propietarios, modos, enlaces o contenido inválidos.
   Ningún fallo de importación/Docker/archivo se convierte en ausencia.
5. El recibo canónico `BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2` conserva `schema=2`,
   añade en este único caso `site_url.state=NOT_CONFIGURED` y emite
   `fingerprint=null`, `mirror=null`; jamás un falso SHA. `beta_deploy=NO_GO`,
   `passkey_chrome=NOT_ATTESTED`, sin sesión owner ni monitor autenticado.
   `capture_postflight`/`verify_postflight` de esquema 1 rechazan
   explícitamente el fingerprint ausente **antes de llamar al lector**.
6. La lectura del comando fijo del worker sólo demuestra que al próximo
   inicio leerá el archivo; la ausencia del archivo debe seguir bloqueando
   START efectivo. La BETA completa necesita luego que el propietario
   configure SITE_URL desde el panel corregido, se pruebe persistencia,
   espejo y consumo, y se atestigüen passkey Chrome y monitor por separado.

## Límites y admisión antes de efectos

Esta decisión elimina un rechazo lógico predecible, **no garantiza que los
probes físicos vayan a funcionar**. El backend de upgrade todavía debe
enlazar estos lectores exactos, demostrar ausencia/volúmenes rootless en el
host, completar el terminal durable y asegurar la barrera previa a
`COMMIT_MARKER`. Ante un fallo de cualquiera de esos requisitos, incluso de
permisos `subuid` de los inodos, el resultado sigue `NO_GO`; está prohibido
repetir R186 o interpretar un HTTP `/healthz` como passkey del titular.

No se toca Porota, Docker/sistema del host, SQLite/keys/sesiones, red
externa, TLS, navegación Boca/Queue-it, reservas ni worker activo. No se
agregan archivos a la allowlist ni se eleva el límite de ZIP desde este
scope. Integración en Actions, release exacta y aceptación física pendientes.

## Pruebas de regresión

TDD RED reprodujo los tres rechazos independientes: constructor de
expectativa post-cleanup, captura técnica de ausencia y productor real de
los dos probes. GREEN: ausencia doble exacta en snapshot técnico con recibo
canónico `NOT_CONFIGURED`, esquema 1 y BETA GO denegados, mezcla de presente/
ausente rechazada, comandos fijos Docker sin URL/Internet, sentinel malformado
o resultado real distinto rechazado, y equivalencia del flujo `ATTESTED`
existente. Fixtures son sintéticos, no prueba del droplet. Ejecutar también
la suite completa, Ruff, mypy, política del repositorio y ZIP protegido
en el árbol de integración antes de PR/merge.
