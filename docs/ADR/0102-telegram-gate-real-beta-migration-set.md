# ADR 0102: gate Telegram sobre el esquema real de la BETA

**Estado:** candidato de issue #258 para revisión e integración en PR #253.
Fecha: 2026-11-02. La evidencia del smoke y del SHA final se registra en #45.

## Causa

El smoke Docker real llegó al sender después de comprobar IPC y reinicio del
par, pero la migración Telegram falló con `schema_ledger`. La reproducción
independiente con `runtime.initialize_beta` creó el ledger
`[1,2,3,5,6]`, exactamente el requerido por `LocalBetaRuntime`; el gate
Telegram exigía una secuencia contigua. Las pruebas anteriores construían
artificialmente 0001–0006 y no ejercitaban el inicializador real.

0004 pertenece exclusivamente al procedimiento opt-in `CredentialKeyRewrapper`.
Instala una política y triggers para la versión activa de claves; no forma
parte de init-beta y no debe activarse como efecto de habilitar notificaciones.
No se modifica el inicializador ni se agrega 0004 al fixture del smoke para
ocultar el desacuerdo entre contratos.

## Decisión

Este ADR sustituye solamente la suposición de ledger contiguo de ADR0084.
El gate acepta exactamente `{1,2,3,5,6}` o `{1,2,3,4,5,6}` antes de migrar y
los mismos conjuntos más `7` después. Cada versión observada conserva el
checksum SHA-256 de su archivo revisado, buscado por su número real. No se
admiten versiones desconocidas, duplicadas o faltantes de la base. Si 0004
está presente su checksum también debe ser exacto.

La operación conserva los controles de UID10001, archivo 0600/nlink1,
identidad dev/inode, SQLite sólo lectura para preflight, tablas requeridas,
integridad y foreign keys. Después de ese gate reutiliza el coordinador
existente para agregar únicamente 0007, sin enviar notificaciones ni borrar
el outbox o el ledger de entrega. Una DB ya migrada sólo se verifica.
Un checksum inválido de 0007 nunca habilita una reparación o reenvío implícito.

## Regresión y límites

Las nuevas pruebas parten de `runtime.initialize_beta` real y cubren ambas
formas válidas del ledger, preservación de credenciales cifradas, clave,
intenciones y outbox, idempotencia y un fence Telegram ya aceptado. También
exigen rechazo antes del DDL para cada migración base faltante, checksum
alterado de cada versión 1–7, versión desconocida, duplicada o de tipo inválido.
La UID del executor local se sustituye sólo en el wrapper de custodia de las
pruebas; el esquema, inicializador y SQLite son reales. El gate de producción
no cambia esa custodia. El smoke Docker debe repetirse sobre el candidato
revisado; ninguna prueba local demuestra instalación o entrega Telegram real.
