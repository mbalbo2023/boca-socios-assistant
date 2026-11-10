# R150 — Resolver el nombre `synthetic` en la imagen del worker

## Motivo y evidencia

El único W1 físico [#934](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42841239384)
registró `MISSING_BARE_SYNTHETIC`, `missing_module=synthetic`, `exit_code=1`,
`oom=false`, `controller=HEALTHY` y `cleanup=VERIFIED`. La instrucción
actual de `Dockerfile.browser` agrega `/app/src` al `PYTHONPATH`, pero no
`/app/src/boca_socios/browser`, aunque esa carpeta sí se copia a la imagen.
Un `importlib.util.find_spec("synthetic")`, que no ejecuta el módulo,
no encuentra el nombre bare con la primera ruta y sí lo encuentra con ambas.

## Alternativas consideradas

- **Elegida:** añadir sólo el directorio del navegador al `PYTHONPATH` de
  `Dockerfile.browser`, manteniendo el entrypoint y la ubicación de los bytes.
- Crear `src/synthetic.py` como puente: exige un archivo nuevo y podría
  alterar la identidad de importación; no ofrece una ventaja comprobada.
- Editar `ipc_worker.py` o `synthetic.py`: prohibido, ambos son BLACKBOX del
  propietario y no existe autorización específica para abrir sus contenidos.

## Alcance, prueba y límites

Cambiar exclusivamente el empaquetado de la imagen navegador, probar la
resolución bare mediante `find_spec` en un intérprete descartable sin cargar
ninguno de los dos módulos protegidos, y actualizar la explicación operacional.
No iniciar contenedores en el droplet, no probar navegación real, no alterar
Cutover, controlador, puertos, UID, socket, daemon Docker o servicios ajenos.
El resultado del build/CI probará empaquetado; sólo una nueva prueba física
autorizada podrá acreditar posteriormente un worker funcional. La posibilidad
de un doble import bare/canónico sigue siendo un riesgo no demostrado sin
observar los archivos protegidos; no se les atribuye comportamiento interno.
