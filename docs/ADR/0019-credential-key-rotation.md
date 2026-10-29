# ADR 0019: recifrado atómico y versión activa de credenciales

**Estado:** Propuesto, 2026-10-28. Issue #39, PR apilado sobre #38. Implementación
interna sin endpoint, comando de operación ni despliegue.

La migración 0004 guarda únicamente la **etiqueta no secreta** de la versión
activa en SQLite. Dos triggers rechazan `INSERT` o `UPDATE` de credenciales con
una versión distinta, incluso si un proceso anterior conserva su clave en
memoria. El servicio exige dos versiones y materiales distintos, comprueba que
las filas existentes pertenecen a la versión anterior y procesa hasta 1000
filas cifradas en `BEGIN IMMEDIATE`. Cambia la etiqueta, descifra cada fila
con la clave vieja, vuelve a cifrar con AES-GCM y nonce nuevo, comprueba que
puede abrirla con la nueva clave y confirma **una sola transacción**. Un fallo
de descifrado, escritura, integridad o límite revierte etiqueta y filas.

Después del commit, una llamada **separada y de sólo lectura**
`verify_active_credentials` carga la clave nueva desde un archivo externo y
verifica todas las filas, también tras reiniciar el proceso. La clave anterior
se conserva fuera del repositorio junto con respaldos históricos hasta una
política de recuperación aprobada; este módulo no la elimina ni publica.
Nunca expone claves, contraseñas, ciphertext o registros personales en salida.

## Riesgos que impiden uso operativo

- La transacción es adecuada sólo para un lote pequeño y revisado. Se necesita
  parada coordinada de escritores, backup cifrado y restauración probada antes
  de usar datos reales. Los triggers impiden la **versión vieja**, pero no
  prueban que un proceso conozca realmente el material de la clave nueva.
- Un respaldo anterior requiere su clave anterior. La verificación posterior
  al commit detecta errores, pero no revierte una transacción ya confirmada;
  ambas claves deben seguir disponibles para recuperación de emergencia.
- No hay borrado completo, identidad externa única, autenticación de panel,
  canal seguro de secretos, observación autenticada ni reserva con Boca. El
  runtime no importa este módulo ni ejecuta la migración automáticamente. Hoy
  el runtime abre la clave con etiqueta `v1`; antes de cualquier rotación real
  debe existir configuración revisada para arrancar con la nueva versión.
- La base y las claves siguen dentro de la misma zona de confianza del futuro
  proceso; custodiar y probar la separación y el montaje sólo en un despliegue
  autorizado vía Actions, con revisión humana previa.

Pruebas exclusivamente con credenciales sintéticas: reinicio, escritor viejo,
dos filas, corrupción de la última y rollback de la primera, versiones
mezcladas, material/etiquetas iguales, lote excesivo y checksum alterado.
