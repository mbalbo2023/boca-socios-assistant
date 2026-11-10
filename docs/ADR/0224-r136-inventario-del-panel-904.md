# ADR 0224 — Inventario del panel tras el intento #904

## Incidente

La [release #788](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42741500632) publicó las imágenes del commit `b6a53c3348ce39c4d8536487e2baed559c2ca42f`. La [instalación #904](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42742150879/job/129585575534) se detuvo en `ACCEPT_CANDIDATE`. El contrato de `ACTIVATE_CANDIDATE` ya había verificado el contenedor del navegador en reposo, la salud del controlador candidato y la respuesta HTTP de loopback. La última causa observada dentro de un proceso de navegador procede del intento anterior #899, con `MODULE_NOT_FOUND_ERROR` sin nombre de módulo. El intento #904 no arrancó el navegador.

El código que registra el terminal de #904 conserva el ID del candidato y del worker, el resultado de la transacción, la restauración del original y el resultado de la limpieza. La salida de fallo del runner agrupa los terminales `RECOVERED` y `NO_GO`. El lector automático que seguía a esa salida requería una captura de salida del worker. El [observador #905](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42742672722) devolvió `LEGACY_COMPOSE` antes de identificar los contenedores. Esa categoría abarca varias condiciones del directorio y su archivo Compose. El archivo Compose de ambas versiones tiene el mismo SHA-256.

## Decisión

Ampliar la operación protegida de reconciliación para que el operador pueda leer el terminal exacto de #904 y contrastarlo con los objetos identificados por Docker rootless, el staging y el activador local de Boca. En el workflow esos datos se vinculan al intento original `42742150879`, a la release y al controlador histórico. Sólo se publican estados y metadatos de identidad acotados. El resultado se registra antes de decidir una recuperación o un nuevo despliegue.

Una lectura válida puede confirmar que el host quedó en un estado que requiere reparación. La prueba de arranque bajo demanda requiere el UUID de una solicitud real de la sesión con passkey y una observación del motor y del worker. [Seguimiento de la investigación](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6757241696) · [Operación bajo demanda](0223-bot-bajo-demanda.md).

## Validación del transporte

El paquete completo incorpora el lector histórico y suma 1.059.785 bytes de fuentes en 46 entradas. El ZIP verificado ocupa 263.164 bytes y su SHA-256 es `0bc394e88b9837cd92ef5fdb5db7e277f93522e1c19ca962a9c458b764ee421f`. El constructor y el receptor admiten hasta 1.100.000 bytes de fuentes y 512.000 bytes comprimidos. La proyección pública de esta observación tiene un límite separado de 16 KiB.
