# ADR0241 — R189: root JSON exacto y NO_GO diagnosticable

Fecha: 2026-11-12 ART. Issue #417. Estado: **CODE_ONLY; sin nueva observación host**.

## Evidencia y alcance del RCA

R188 se ejecutó una vez desde main
`95591d33134cf055f73f8739d51f9bb742064ee9` en run
[`43274319171`](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43274319171),
job `131378566255`. El log muestra `BOCA_MAIN_REF_PASS` y después exit 1.
El stderr SSH estaba descartado; un RC remoto no cero descartaba también
el recibo de fallo stdout. No es posible reconstruir la primera condición
fallida del host a partir de ese log. Su resultado sigue siendo NO_GO.

Se reprodujo un defecto determinista de fuente: `_identity` comparaba
`cleanup._docker(info --format {{.DockerRootDir}})` con la ruta sin LF.
Ese wrapper devuelve stdout crudo. Docker entrega una línea terminada en LF,
por lo que aun la raíz correcta falla antes de abrir un directorio. Los
fixtures R188 omitían LF. En contraste, `host_first_deploy._run` recorta stdout
y su verificador de storage interpreta JSON; no son contratos equivalentes.
La reproducción local no prueba que el host llegara hasta ese predicado.

El transporte SHA/ZIP/memfd/import se probó localmente sin Docker ni host.
Eso descarta un defecto reproducido del bundle, no certifica transporte SSH
ni runtime del droplet en el run fallido.

## Decisión

1. Pedir **solo** `{{json .DockerRootDir}}`, decodificar el escalar JSON y
   exigir la misma ruta fija exacta. LF de framing no es parte del valor;
   espacios dentro del string, otra raíz, JSON múltiple o malformado fallan.
   No adoptar otra ruta, hacer resolve, ni cambiar permisos para continuar.
2. Conservar rootless/UID, mountpoint exacto, O_PATH/O_NOFOLLOW en cada
   componente, labels, dos CIDs/digests, worker CREATED y egress sin peers.
   Un worker configurado para una red no prueba un endpoint activo. Alias
   no admitidos, aun sin referencias de contenedores, siguen siendo NO_GO.
3. `ResourceNoGo` conserva una fase del enum cerrado: inventario, par,
   identidad IPC/SITE/control, egress, provenance de imágenes, validación
   del snapshot y drift. El error solo lleva la categoría fija; nunca texto
   de la excepción, nombres arbitrarios, valores de labels o contenido.
4. El host emite un frame canónico `BOCA_RETAINED_RESOURCES_FAILURE`, limitado
   a 512 bytes, con run ID, estado NO_GO, fase, cero escrituras y sucesor no
   autorizado. El runner rechaza keys extra/duplicadas, otro run, fase ajena,
   framing no canónico y cualquier contenido agregado.
5. El mismo paso de la misma Action conserva stdout/stderr en archivos
   privados efímeros del runner, con límite físico por archivo y lecturas
   acotadas. **No publica stderr crudo**. Solo reconoce el frame host bajo
   RC3 y stderr vacío, o el marcador exacto ya existente del bootstrap bajo
   RC1 y stdout vacío. Otros casos son `TRANSPORT_UNVERIFIED`.
6. RC remoto no cero siempre termina en fallo, incluso con recibo READ_ONLY
   perfectamente válido. RC0 con recibo inválido o stderr inesperado es
   `RECEIPT_UNVERIFIED`. No retries, cambio de destino, bypass o efectos.

El bootstrap/builder, R186 y su journal, backend effectful y política de
propiedad de recursos permanecen intactos. Las categorías no convierten un
estado desconocido en aceptación ni autorizan instalar el sucesor.

## Verificación y siguiente frontera

TDD: los nuevos tests fallaron primero por framing Docker incorrecto,
ausencia de fases y descarte del fallo host. Cubren JSON+LF con filesystem
temporal real, raíces falsas, symlinks, labels/aliases, fallos inyectados,
drift, parser estricto y ejecución del paso Bash real con SSH simulado.
Los señuelos sensibles no deben aparecer en stdout, stderr o summary.

Focales, suite completa, formato/lint, tipos, política y revisión independiente
son obligatorios antes de PR/merge. El entorno local puede impedir el test
AF_UNIX requerido; ese skip no equivale a aceptación física y debe resolverse
en Actions. Un nuevo observador protegido solo puede ejecutarse después del
Fix-Forward revisado y checks exact-SHA. No reintentar el run R188 histórico.
