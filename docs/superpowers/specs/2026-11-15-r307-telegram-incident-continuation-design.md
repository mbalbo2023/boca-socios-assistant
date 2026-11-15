# R307 — Continuar observación Telegram1167

## Necesidad y decisión previa

El fallo prepare1167/run43738415332 conserva un recibo válido de restauración
saludable, pero no la excepción causal. El lector R304 sólo admite1156 y no
puede caracterizar un auxiliar1167. No hay corrección productiva demostrada.
El consenso previo 4/4 está registrado en issue528: Arquitectura/continuidad,
QA/funcionalidad, Operaciones/RCA y root. El titular delegó continuar el chat
interrumpido, sin repetir código ni operaciones aceptadas.

Se consideraron dos opciones: transportar otro argumento por workflow,
builder y bootstrap, o seleccionar el incidente actual dentro del CLI del
lector existente. Se elige la segunda por necesitar un solo módulo productivo.
No se crea otro observador ni se cambia el transporte.

## Contrato

- Base W2: e16bfb78bc16b9f7554c76191c50f354e61fcbbc.
- `INCIDENT=43705714873` y APIs por defecto conservan1156 para R305.
- `CURRENT_INCIDENT=43738415332`; `main` selecciona1167 tanto para host
  como para verify, sin cambiar sus tres argumentos ni inferir del payload.
- Parámetro opcional finito propagado por inventario, snapshot, perfil,
  base del recibo, observe, helper-verifier y verify. Sólo esos dos IDs;
  inválidos se rechazan antes de Docker. Sin globals mutables.
- Perfil1156 intacto. Perfil1167 acepta CHOWN/CAP_CHOWN en initialize-volume
  y reconoce publish-status/publish-status-absent del publicador existente.
- Se preserva V1: observación completa usa reason=NONE, incluso si el helper
  está ausente. ABSENT sólo prueba ausencia actual; no determina causa pasada.
- Factorizar únicamente la tabla fija `_TEMPLATES` para eliminar redundancia:
  mismos items/orden/strings y órdenes derivados. Ningún campo del caller.
- Módulo <=24000 bytes;29 entradas; fuentes900000/ZIP320000; recibo4096;
  campo8192; mismo binding, doble snapshot, inventario y campos permitidos.
- `observer_writes=0`, engine UNVERIFIED y autorizaciones false. Sin lease,
  SQL, secretos, HTTP, Docker mutante, Telegram ni otras aplicaciones.

## Ownership, pruebas y salida

Autor separado: sólo módulo y dos archivos de tests indicados en el plan.
Root: documentación, RCA, GitHub, integración y único despacho eventual.
Pruebas causales RED/GREEN, selección y recibos cruzados con igual run/SHA,
perfiles separados, CLI/ZIP/tail reales, consumidor R305 real, ausencia/drift,
redacción y tabla exacta. No repetir suite local histórica ni imágenes.

Cuatro revisiones finales y checks exactos preceden merge/mainGREEN. Sólo
entonces una observación protegida puede examinar1167; no autoriza prepare,
recovery, cleanup, restore, release, APPLY, admin o migración. Instalado
R845f31abfb1762dff27e6fc3274fcc40507f3f18/release867/APPLY1153 y recovery1166
ACCEPTED permanecen preservados. Si no queda auxiliar, la causa puede seguir
indeterminada: documentar ese resultado y su límite, sin inventar diagnóstico.
