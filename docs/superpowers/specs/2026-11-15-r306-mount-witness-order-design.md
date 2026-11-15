# R306 — orden canónico de testigos Mounts

## Objetivo y evidencia

Corregir exclusivamente la sensibilidad al orden de las listas de mounts en
el recuperador R305. Base W1 b96db3a13ad50e663ae3eb8cde82345a72792aaf,
árbol1393132c6ec8bf1eeed16c5f11e60e9697751618, PR526, CI1276/Security1091 verdes.
R845f31abfb1762dff27e6fc3274fcc40507f3f18 ya está instalada por release867/APPLY1153.

El único intento1164/run43734148189 produjo NO_GO/PREFLIGHT, inicialización y
retiro NOT_ATTEMPTED. Recibo verificado con el ZIP exacto, SHA256
b2ddc07299e9f986b963e81076e3a845f2f95150679d42791a9788b523310edb. No prueba cuál
subguarda falló: no atribuir retrospectivamente ese run al orden ni a permisos.

El defecto independiente está en _mount_witnesses: _mounts prueba composición
como frozenset, pero raw e identities se conservan como listas en el orden de
adquisición. first==second, _unchanged y retiring!=initialized pueden confundir
una permutación con deriva, incluso después de inicializar. El fixture previo
siempre suministraba un orden fijo.

Fuentes primarias consultadas, sin afirmar la versión del host:
- https://github.com/moby/moby/blob/v28.3.1/daemon/inspect.go
- https://github.com/moby/moby/blob/v28.3.1/container/container_unix.go
- https://go.dev/ref/spec#For_statements
Inspect utiliza GetMountPoints; esa implementación recorre un mapa y agrega
registros sin ordenar. Go no garantiza orden estable entre iteraciones.

## Decisión

Después de que _mounts valide la lista y su igualdad con el contrato exacto,
crear una lista nueva ordenada por Destination. Los destinos ya son únicos y
válidos en ese punto. Construir identities recorriendo esa misma lista.
Conservar cada diccionario íntegro, todos sus campos y la cardinalidad. No
ordenar identidades por separado ni convertir registros en sets/dicts que
eliminen datos. Mantener las validaciones de Source y la adquisición dev/inode.

La única equivalencia admitida es la permutación de registros idénticos.
Cambios de Source, Destination, Type, Name, Driver, RW, Propagation, Mode,
campos adicionales o identidad física deben seguir visibles/rechazados según
las guardas actuales. Duplicados, mounts adicionales y alias Telegram siguen
siendo NO_GO. No modificar _snapshot, _unchanged, recover, el codec, tiempos,
permisos, auxiliares, censo, initializador R, capas o política de cleanup.

## Alcance

Autor separado sólo puede cambiar:
1. src/boca_socios/host_telegram_initializer_recovery.py: normalización local.
2. tests/test_r306_mount_witness_order.py: nuevo, reutiliza fixtures anteriores.

Raíz posee AGENTS, README, documentación de continuidad, RCA527 y este diseño
con su plan. No cambiar tests existentes, builder, bootstrap, workflow,
allowlists ni cotas. El ZIP R305 cambia de hash por el módulo; se atribuye al
nuevo árbol y se mide dentro de30entradas/900000fuente/320000ZIP/módulo24000.
Los paquetes R304, Telegram y full-cutover se reutilizan: sus fuentes no cambian.

## Verificación concreta

Regresión RED antes del parche: recover real con el transporte Docker externo
que devuelve los mismos registros en órdenes diferentes. Cubrir las dos
lecturas previas, verificación posterior a init, anterior a rm y postflight;
probar también orden que cambia sólo después de init para revelar el falso
rechazo tardío. No sustituir _mount_witnesses/_snapshot/_unchanged/_mounts ni
recover. El resto de I/O externa puede reutilizar el fixture R305 aprobado.

GREEN debe llegar a un start y un rm exactos y recibo ACCEPTED con la misma
identidad lógica/física. Negativos con permutación conservan NO_GO para Source,
RW, duplicados/extra, alias/inode y drift de Mode/campo no proyectado; verificar
que no se produce un rm sin prueba y que los hechos parciales no se falsifican.
Probar que se mantienen campos completos y que no se modifica la lista fuente.

Ejecutar sólo test nuevo + suite R305 runtime afectada y los controles de
transporte que consumen ZIP real (closure, verify0/3, memfd UID y shell rc).
Una sola construcción del ZIP por esa fixture, copiada como evidencia; no
reconstruir paquetes ajenos ni repetir65 pruebas ordinarias de mantenimiento.
Ruff/format sobre los2archivos y mypy del módulo; diff-check. Raíz ejecuta los
2controles del registro RCA al añadir la lección, respetando20..300 caracteres,
1..8selectores y65536B, para no repetir el defecto documental anterior.

## Promoción y decisión física

Cuatro GO previos y finales sobre hashes; CI candidato, merge esperado y gates
exactos de main. Reconciliar PRs/runs. Un único despacho nuevo de la operación
existente boca-telegram-initializer-recover, main/controller/budget fijo/22blanks.
No rerun1164. Es admisible porque1164 acredita NOT_ATTEMPTED y el nuevo código
recorre nuevamente lease fresca, created/timestamps cero, perfil/volumen/mounts,
doble lectura y recheck íntegros antes de START. El inicializador R sigue
exigiendo vacío/UID0. No se supone que no haya otro bloqueo físico.

Si vuelve a NO_GO de causa desconocida, no repetir recuperación: obtener
subfase/razón finita con diagnóstico sin efectos antes de otra operación.
Sólo init ACCEPTED + retiro RETIRED + COMPLETE/ACCEPTED habilitan prepare
canónico separado sobre R/release867. Sin release/APPLY/admin/migración nuevas.
SIMULATION_ONLY; datos/passkeys/volúmenes y BLACKBOX unread/unmodified; sender
sin activar, sin mensajes/proveedor; Porota/PPI fuera de alcance.
