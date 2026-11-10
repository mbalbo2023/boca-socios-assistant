# ADR 0227 — Acuse de Docker durante el reinicio del panel

## Qué sucedió en el droplet

El [intento #921 con la release #799](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42755537951/job/129628946264) dejó un registro V7 que pudo leerse de nuevo después de la salida SSH. El panel candidato había respondido por HTTP. El instalador había comprobado su base, el motor detenido, el socket del activador y el controlador original estacionado. En la primera parada del candidato, Docker devolvió éxito y el texto leído en stdout difería del CID completo esperado. El registro conservó `PANEL_STOP_ACK / MISMATCH`. Después acreditó la restitución del original, la limpieza aceptada y la recuperación de la instalación anterior. El worker estaba creado y sin proceso durante esta prueba.

En [#899](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42730562010) sí se había iniciado el worker y se capturó `MODULE_NOT_FOUND_ERROR` antes de su retirada. El registro antiguo conserva la categoría de excepción. La identificación del módulo y el resultado de un arranque del worker de la nueva BETA requieren evidencia de ese proceso.

## Corrección

El cliente Docker anterior a la versión 28 usaba el nombre largo `--time`. Docker 28 pasó a `--timeout` y emite un aviso al usar el anterior. En el cliente examinado, pflag registra la deprecación y Cobra escribe el aviso en el canal que la CLI de Docker configuró como stdout. A continuación el comando exitoso imprime el identificador que recibió. Quitar el salto de línea final conserva el aviso y el CID en dos líneas. El recibo del droplet registra la discrepancia y omite los bytes de la salida y la versión del cliente. [Documentación de Docker](https://docs.docker.com/reference/cli/docker/container/stop/) · [Docker CLI 28.5.1](https://github.com/docker/cli/blob/v28.5.1/cli/command/container/stop.go) · [Cliente 27.5.1](https://github.com/docker/cli/blob/v27.5.1/cli/command/container/stop.go).

Se reutiliza `-t`, compatible con ambas variantes, en las paradas que consumen el CID de stdout. El argumento conserva los segundos de gracia de cada llamada. Se mantienen la comparación completa del CID y la confirmación posterior por inspect. El mismo criterio cubre el reinicio obligatorio del panel, la compensación y la detención pedida por su titular. [ADR 0204](0204-r95-portable-docker-stop-flag.md) ya lo había aplicado al preflight histórico del worker. R139 extiende esa decisión a los consumidores del resultado de STOP que quedaron fuera de su alcance.

Para la aceptación física del panel, el reinicio debe confirmar el mismo CID, acceso HTTP, identidad de la base, socket y worker en reposo. La prueba de funcionamiento del bot requiere por separado la operación autenticada del titular y la confirmación del proceso del navegador. [Contrato bajo demanda](0223-bot-bajo-demanda.md) · [Investigación de #921](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6759027570).

El laboratorio del runner usa un servidor HTTP descartable en loopback. Registra la forma de stdout y stderr de las opciones largas. Después recorre el método de reinicio del panel con la opción corta, verifica por separado el PID cero y el nuevo arranque sano del mismo CID y comprueba que un CID ausente se rechaza.

El ZIP completo tiene 47 entradas, 1.143.368 bytes de fuentes y 283.404 bytes comprimidos. Su SHA-256 es `bef701b7719e370790f9d6e6afe01a7e7e77dc490485e998ba77314c78c11aeb`. El ZIP de preflight pesa 109.588 bytes y el de recuperación pesa 44.922.
