# ADR 0055: Regla 84 y aprobación de decisiones acotadas

**Estado:** Accepted on merge. Registra la instrucción explícita del dueño
y la Regla 84; alcance documentado en issue #138.
No cambia arquitectura, infraestructura, lógica de negocio ni estado del host.

## Contexto

Las inspecciones de Actions probaron hechos que documentos anteriores aún
negaban o dejaban sin distinguir. Además, una delegación general histórica se
mantuvo escrita después de que el dueño exigiera opciones, recomendación y
aprobación antes de decidir infraestructura o lógica de negocio. Un workflow
configurado, un test sintético o una función `Database.migrate()` tampoco
prueban que exista una instancia de base en el droplet.

## Instrucción vigente

El agente presenta opciones concretas, recomendación, efectos y evidencia
antes de nuevas decisiones de infraestructura o lógica de negocio; espera la
aprobación del alcance. Una vez aprobado, completa implementación y pruebas
sin pedir repetidamente el mismo permiso. Un diagnóstico de lectura o un fix
no autoriza instalación, release, migración real ni otra función. La revisión
técnica del agente y los checks exactos siguen siendo requisitos; que GitHub
no exija un aprobador humano adicional no sustituye la decisión del dueño.

Esta instrucción reemplaza exclusivamente la delegación general de autonomía
operativa de ADR0038 y el lenguaje equivalente heredado de ADR0014, ADR0026,
ADR0029, ADR0031 y ADR0035. Esos textos conservan su contexto histórico y sus
gates técnicos; no confieren autorización nueva. El checkpoint #45 registra
los alcances concretos y la evidencia, sin ampliar esa autorización.

## Regla 84: documentación factual y al día

- Mantener en el mismo PR los documentos afectados por el comportamiento final.
- Distinguir código integrado, candidato abierto, configuración, propuesta y
  observación real. Desarrollo de storage no equivale a creación de una DB
  operativa; corregir una función no ejecuta una migración sobre datos reales.
- Vincular SHA, PR y run exactos con lo comprobado y sus límites. Etiquetar
  cortes anteriores como históricos, sin convertir sus fechas en actualidad.
- Reconciliar README, operación, backlog, integración y checkpoint afectados
  antes de cerrar el trabajo, con pendientes y decisiones todavía necesarias.
- Asignar un escritor por ámbito. Justificar expresamente cuando un PR no
  afecte documentación, en lugar de declarar una actualización inexistente.

La plantilla PR incorpora estos puntos como obligaciones de revisión. No se
implementa ni promete un robot que revise todo GitHub, un nuevo gate automático
o una frecuencia arbitraria de actualización. El ledger RCA conserva su gate
existente de regresiones realmente ejecutadas; no prueba actualidad de prose.

## Límites

La instrucción no habilita datos/credenciales reales, login, cola, reserva,
Telegram, instalación ni release. Backup/restore operativo sigue diferido
hasta una versión productiva fiable. Porota/PPI Watch quedan fuera de alcance.
