# ADR 0223 — Panel disponible y bot Boca bajo demanda

## Decisión del titular

La sesión privada autenticada con passkey puede iniciar y detener únicamente el bot Boca con un toque. GitHub Actions conserva la instalación y actualización de la BETA de simulación. El panel sigue atendiendo en el puerto local 8443 cuando el bot está detenido. El worker ejecuta la parte de navegador que recibe las órdenes del controlador por un socket Unix. Docker puede conservar su contenedor creado o detenido con cero procesos entre usos.

El último arranque observado terminó con código 1 en menos de cinco segundos. La captura armada antes de arrancar conservó la categoría `MODULE_NOT_FOUND_ERROR`. El nombre del módulo sigue sin identificarse. La comprobación externa de los trece imports públicos del artefacto pasó. La cadena anterior exigía un worker sano para sustituir el controlador y después para abrir el panel HTTP. Una excepción en el proceso impedía las dos cosas.

## Instalación y operación

1. La Action dedicada verifica la release dual, la identidad Docker rootless de Boca y los volúmenes. Prepara el contenedor aislado con la imagen por digest. La aceptación de la instalación exige el panel sano con motor parado, el canal local de control disponible y el worker sin proceso. Antes de retirar el controlador anterior, la Action detiene e inicia una sola vez el candidato por CID. Revalida el puerto del panel, la identidad de su almacenamiento, el socket de control, el motor parado y el mismo worker sin procesos. El reinicio se limita al controlador Boca.
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

## Evidencia reproducible

El laboratorio del runner usó software de prueba e identificó el mismo CID en los dos arranques. El primer proceso, iniciado desde `created`, emitió la categoría `PERMISSION_ERROR`. El segundo, iniciado desde `exited`, emitió `RUNTIME_ERROR`. Se verificaron el nuevo instante de inicio, el código 1 en cada salida y la eliminación del CID exacto. La matriz de integración reproduce el botón autenticado con credenciales descartables, la transacción SQLite, la comunicación Unix, la pérdida de un ACK, la competencia entre START y STOP y el fallo de arranque con el panel disponible. [Laboratorio Docker](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42738868312/job/129574708353) · [RCA-328](https://github.com/mbalbo2023/boca-socios-assistant/issues/328#issuecomment-6756838061).

Para comprobar el efecto de un toque, la operación `beta-browser-status` de la Action protegida toma una lectura breve de la instalación. El recibo muestra la salud del panel, estado del motor, estado y PID del worker y el último pedido de este perfil con su resultado. La coincidencia del UUID con el de Chrome permite distinguir esa operación de un resultado previo. Un recibo de lectura puede registrar el fallo de un START. El código de salida de esa lectura sólo acredita que pudo realizarse y verificarse.

La instalación conserva el ejecutor mínimo por digest y valida el binding del controlador. Un pedido anterior a este perfil necesita un nuevo toque autenticado; una operación previa reclamada o incierta mantiene su cuarentena. Al completarse un trabajo simulado, el STOP derivado queda ligado al START original. Si se solicita iniciar sin enviar un trabajo, el bot queda disponible hasta que el titular pulse Detener. La categoría nominal de módulos sólo se amplía para nombres públicos de paquetes y archivos ya declarados. Los demás siguen produciendo la categoría genérica.

El paquete completo de esta revisión reúne 46 entradas con 1.036.397 bytes de fuentes y 257.845 bytes comprimidos. Su SHA-256 es `2a91c7efd38e2d67b32c56838543c043b1d1f576d7da2e6b6784af7f794291eb`. Las variantes reducidas de preflight y recuperación tienen 7 entradas cada una y ocupan 108.367 y 44.922 bytes, respectivamente. La verificación del runner contrasta índice, tipo de archivo, tamaño y digest antes de la ejecución. Los límites comprimidos siguen en 512.000 y 128.000 bytes.

## Enmienda R143 — `Origin` de formularios nativos (CODE_ONLY)

Base de la revisión: `main=03df9a14bdd78cf768386a865876fed9d5656911` (2026-11-10 ART); no equivale a una instalación. El panel respondía `Referrer-Policy: no-referrer` también en Inicio (`/`) y Control (`/control`) con el bot bajo demanda, aunque esos documentos presentan formularios HTML POST nativos. En ese caso, el navegador puede enviar `Origin: null`; la verificación exacta de `_handle` rechaza correctamente ese valor con 403. La política de respuesta y la expectativa de Origin eran incompatibles entre sí.

Se selecciona **`Referrer-Policy: same-origin` únicamente para esos dos documentos del perfil bajo demanda**: permite referer al mismo origen para la navegación del formulario y lo suprime hacia cualquier otro origen. No se sustituye el botón por JavaScript/fetch, evitando añadir una dependencia de script al control accesible por voz. Las páginas restantes, incluido ingreso con passkey y configuración/emparejamiento Telegram, conservan `no-referrer`. También permanecen exactos el origen autorizado, el CSRF, los permisos de sesión, `form-action 'self'` y el transporte privado `http://localhost:8443` por túnel SSH. [Semántica del encabezado y efecto en Origin](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header).

La regresión local verifica el encabezado en ambas páginas, los dos formularios del bot, un POST legítimo, rechazo de `Origin: null`/vacío/externo y CSRF inválido, y la política anterior en otras rutas. No prueba un toque real desde Samsung Chrome: para acreditar la reparación hacen falta PR, gates de CI, instalación autenticada por Actions y observación física de inicio/detención; no se autorizan esas operaciones por esta enmienda. Los dos módulos BLACKBOX y el worker no se inspeccionaron ni cambiaron.
