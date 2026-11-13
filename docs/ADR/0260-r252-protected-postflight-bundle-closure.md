# ADR 0260 — R252: cierre exacto del ZIP postflight V2 sin ampliar autoridad

**Fecha:** 12-NOV-2026 ART. **Issue:** #417. **Base comprobada:**
`87df6dca6622b02b16e6ec643da6b3e726bf418a` (R251 en main).
**Estado:** candidato CODE_ONLY; ningún efecto físico ni aprobación de APPLY.

## RCA reproducido

El productor real `host_boca_postflight_sources_v2.py` estaba incorporado al
repositorio y probado por separado, pero faltaba del `PAIR_UPGRADE_SOURCES` del
builder y del `PAIR_UPGRADE_ENTRIES` del verificador memfd del host. Un ZIP
autenticado de R251 contenía 73 entradas, **322.196 bytes comprimidos** y
**1.285.698 bytes descomprimidos** tras compacción comentarial, sin aquel
productor. Esta diferencia de cierre de imports impediría importarlo en la
ejecución física protegida: la presencia en el árbol Git no implica
presencia en el artefacto del host.

El límite previo de 1.300.000 bytes descomprimidos era insuficiente como
presupuesto de los actores R252 más su postflight. El builder ya eliminaba
**únicamente tokens COMMENT** cuando el contenido excedía ese límite,
comprobando igualdad de AST, bytecode y saltos de línea. No corresponde
eliminar código importado, suprimir pruebas de procedencia ni aumentar el
ZIP general de Cutover para resolverlo.

## Decisión acotada

1. Añadir exclusivamente `src/boca_socios/host_boca_postflight_sources_v2.py`
   al cierre del **par sucesor** en el builder y el verificador memfd. Sin
   nuevos imports de navegación, módulos BLACKBOX, scripts externos o
   capacidades de host. El perfil SQLite READ_ONLY, Cutover histórico y los
   demás ZIP conservan exactamente sus listas anteriores.
2. Ajustar **sólo** el límite descomprimido de ese perfil a **1.400.000 bytes**
   en ambos lados. Mantener el máximo de ZIP comprimido en **480.000 bytes**,
   la lista de entradas exacta, el SHA256 del paquete, el modo regular,
   prohibición de symlinks y la ejecución desde memfd autenticado.
3. Mantener compacción de comentario únicamente **si el total sin modificar
   excede el límite real**. Si el conjunto cabe, transportar bytes fuente
   originales; si requiere compacción, verificar igualdad exacta de
   bytecode/AST/líneas. Rechazar cualquier tamaño superior al nuevo límite,
   incluso con SHA256 recalculado por un atacante de pruebas.

## Verificación y límites

- TDD inicialmente ROJO: no aparecía el módulo V2 en el ZIP y ambos límites
  seguían en 1.300.000. Tras la reparación: **3 pruebas R252 PASS**,
  incluyendo importación aislada `python -I -B` desde el ZIP, rechazo de
  miembro descomprimido sobredimensionado y compacción sin cambio de
  bytecode. Los **24** tests R179/R247/R252/workflow relevantes pasaron
  localmente en esta rama antes de la integración completa. El SHA final de
  integración y sus Actions deberán revalidarse por separado.
- La suite completa sobre esta rama base R251 cerró con **7900 PASS,
  34 subtests PASS y 1 SKIP AF_UNIX/EPERM exclusivo del sandbox**; Ruff,
  formato, mypy de ambos scripts y `POLICY_PASS` sin errores.
- Medición independiente del paquete R252 en esta rama: **74 entradas**,
  **346.242 bytes comprimidos**, **1.343.642 descomprimidos**. Ese segundo
  total incluye los comentarios originales y queda dentro de 1.400.000,
  sin transformación de código en la ruta común. La diferencia frente al
  ZIP previo no es una ampliación de privilegios, sino un módulo importable
  agregado y comentarios originales preservados. El integrador podrá sumar
  código en archivos ya permitidos sólo mientras conserve ambos límites.
- No hay dispatch, release, Docker, SQLite, puerto ni modificación del
  droplet. La funcionalidad `build_protected_postflight_sources` requiere
  *volume attestor* real bajo una única lease; aquí sólo se transporta el
  código, no se fabrican los datos. Salud `/healthz` no demuestra passkey
  del propietario ni sesiones del monitor.
- El flag `requires_persistent_receipt=False`, el CLI de APPLY NO_GO y los
  interlocks R251 **no se alteran**. Los bridges SUCCESS/FAILURE, la decisión
  física y el postflight siguen en manos del integrador R252. R186 no se
  repite; las imágenes y recursos R108 se preservan.

### Seguimiento R252: cierre del bridge SUCCESS

Al incorporar el actor de código `host_boca_success_bridge_v2.py`, la misma
revisión detectó que no alcanzaba con tenerlo en `main`: debía entrar **en
ambas** listas exactas del ZIP sucesor. Se añadió sólo ese módulo al par,
sin cambiar los límites, los perfiles de observación o los mecanismos de
instalación. Una prueba primero ROJA por ausencia del miembro y después
VERDE comprueba la importación aislada de `prepare_success_cleanup` y el
productor postflight, manteniendo rechazo de entradas extra.

Con el commit de SUCCESS `06b9174` incluido **sólo en este worktree de
pruebas**, el ZIP medido contiene **75 entradas**, **349.255 bytes**
comprimidos y **1.353.333 bytes** descomprimidos, dentro de los presupuestos
1.400.000/480.000. Los números no sustituyen las mediciones del SHA
integrador final ni autorizan un postflight físico.

**Reversibilidad:** un nuevo PR puede revisar de forma aislada el presupuesto
medido tras el integrador, manteniendo builder/bootstrap vinculados y sin
modificar los límites generales. La cifra 1.400.000 es un techo de seguridad
para contenido explícitamente allowlisted, no autorización de importar
arbitrariamente más fuentes.
