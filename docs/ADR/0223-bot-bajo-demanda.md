# ADR 0223 — Panel disponible y bot Boca bajo demanda

## Decisión del titular

La sesión privada autenticada con passkey puede iniciar y detener únicamente el bot Boca con un toque. GitHub Actions conserva la instalación y actualización de la BETA de simulación. El panel sigue atendiendo en el puerto local 8443 cuando el bot está detenido. El worker ejecuta la parte de navegador que recibe las órdenes del controlador por un socket Unix. Docker puede conservar su contenedor creado o detenido con cero procesos entre usos.

El último arranque observado terminó con código 1 en menos de cinco segundos. La captura armada antes de arrancar conservó la categoría `MODULE_NOT_FOUND_ERROR`. El nombre del módulo sigue sin identificarse. La comprobación externa de los trece imports públicos del artefacto pasó. La cadena anterior exigía un worker sano para sustituir el controlador y después para abrir el panel HTTP. Una excepción en el proceso impedía las dos cosas.

## Instalación y operación

1. La Action dedicada verifica la release dual, la identidad Docker rootless de Boca y los volúmenes. Prepara el contenedor aislado con la imagen por digest. La aceptación de la instalación exige el panel sano con motor parado, el canal local de control disponible y el worker sin proceso. El retorno del panel tras un reinicio debe conservar el estado seguro del motor.
2. El panel registra la operación del titular en SQLite y entrega sólo su UUID a un socket Unix dedicado. Una unidad de usuario de systemd se activa por conexión. El servicio compara la identidad del par con el controlador instalado, valida la operación persistida y obtiene el mismo bloqueo exclusivo que usa el despliegue. Las únicas operaciones sobre Docker se limitan al worker identificado por CID e imagen de esa instalación. El socket del daemon Docker queda fuera del contenedor.
3. Para iniciar, el ejecutor prepara la captura del intento antes de arrancar el CID exacto. Comprueba el estado y el socket del worker antes de habilitar el motor. Una salida temprana conserva un resultado acotado sin stderr crudo ni credenciales. El panel sigue disponible. Para detener, cierra la admisión y el motor antes de apagar y verificar el worker. La terminación de una tarea puede originar una parada correlacionada con la solicitud original.
4. Una repetición del mismo UUID consulta la misma operación. Pérdida de ACK, actualización concurrente, reinicio o estado incierto exigen conciliación por identidad antes de informar el resultado. Los recibos distinguen una orden aceptada de un efecto físico confirmado.

Se conserva la frontera de los dos módulos de navegación a cargo del titular. La ruta de operación conserva simulación, aislamiento de red del worker, límites de recursos, perfiles y montajes vigentes. Los laboratorios de CI usan procesos ajenos a la navegación y datos descartables.

## Fallos encontrados en la ruta de control anterior

El adaptador de producción pedía campos de inspect que su propio lector rechazaba. El doble de pruebas le devolvía los campos directamente. Además, el arranque por CLI comparaba la salida con un CID de 64 caracteres sin contemplar el terminador de línea. Las regresiones deben atravesar el adaptador de producción y usar la forma real de la respuesta.

La UID 10001 de un proceso dentro del controlador también puede diferir de la UID 10001 de la cuenta que ejecuta Docker en el host. Se comprueba la identidad del cliente del socket con las credenciales del kernel y los mapeos del proceso de la instalación. El acceso a SQLite debe ocurrir en el espacio de usuario autorizado o con una identidad efectivamente verificada. [Docker rootless y UID/GID](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/).

El panel puede usar la política Docker `unless-stopped`; el worker conserva `no`. La unidad de usuario activa un servicio por conexión con `Accept=yes`. [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/) · [systemd.socket](https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html).

## Aceptación y trazabilidad

La instalación en reposo, un inicio desde la sesión real, el efecto del motor, la detención con cero procesos y la continuidad del panel son verificaciones distintas. Una ruta HTTP sana o un recibo de solicitud sólo acreditan su propio paso. Chrome y Telegram requieren la evidencia correspondiente a cada función.

[Dictámenes y decisión](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6756141182) · [Autorización de R135](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6756261211) · [Captura física](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42730562010) · [Inventario posterior](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42731842989).
