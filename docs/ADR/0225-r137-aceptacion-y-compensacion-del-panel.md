# ADR 0225 — Aceptación física del panel y compensación por CID

## Evidencia que debe sobrevivir a una instalación fallida

En [#904](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42742150879) se conoció la fase `ACCEPT_CANDIDATE` tras el primer HTTP sano. Esa fase abarcaba la consulta del motor, la base de datos, la identidad Compose, la instalación del socket, un reinicio del candidato y la evaluación de las imágenes antes de retirar el original. El registro histórico de ese intento conserva los CIDs y el resultado de compensación. [Investigación y laboratorios](https://github.com/mbalbo2023/boca-socios-assistant/issues/328#issuecomment-6757461327).

El registro V7 conserva qué comprobación estaba ejecutándose y una categoría finita del resultado. El proceso protegido preserva el dato durante la compensación y escribe el terminal en el directorio privado ya reservado para el intento. Una segunda lectura puede verificar el mismo registro si se pierde la primera respuesta SSH. El lector de errores previos del navegador sigue disponible para las fases que sí arrancan el worker. El protocolo mantiene fuera de la salida el entorno, texto de excepciones y stderr del proceso. El campo `original_restored` y el resultado de limpieza se analizan por separado.

## Comportamiento demostrado en laboratorio

* Un candidato de CID completo e imagen esperada con un reinicio anterior podía impedir su retirada incluso después de detenerse. La aceptación del candidato comprueba que no hubo reinicios. La compensación puede retirar el CID que se registró al crearlo después de verificar su identidad y su estado estable. Si se pierde la identificación, los recursos se conservan para inspección.
* Una conexión HTTP recién cerrada puede dejar `127.0.0.1:8443` en `TIME_WAIT`. El laboratorio con red privada recuperó el bind exclusivo tras 61 segundos. Cuando ya se verificó la retirada del CID conocido, la compensación admite una espera máxima de 65 segundos y exige el bind exclusivo antes de restituir el original. Los controles iniciales del puerto continúan siendo inmediatos. Un listener que conserva el puerto impide la restitución. [Semántica de direcciones TCP en Linux](https://man7.org/linux/man-pages/man7/ip.7.html).
* El marcador privado `removing` identifica una retirada interrumpida. El verificador rechaza esa instalación mientras la compensación puede retomarse con la identidad registrada. El laboratorio de CI usa un gestor systemd de usuario en una máquina Ubuntu descartable, los fragmentos reales de la unidad y una trama local inválida para comprobar la activación y la limpieza.

La prueba física del START requiere que la sesión del titular genere un UUID y que el lector independiente confirme el resultado del proceso, del motor y del panel. [Criterio de aceptación](0223-bot-bajo-demanda.md).

## Paquetes reproducibles

Con estos cambios, el paquete completo tiene 46 entradas, 1.075.475 bytes de fuentes y 266.886 bytes comprimidos. El paquete reducido de preflight tiene 7 entradas, 501.302 bytes de fuentes y 109.102 bytes comprimidos. El constructor y el receptor aplican el mismo límite de 520.000 bytes de fuentes al preflight y de 128.000 al ZIP. El paquete reducido de recuperación conserva su digest. Las pruebas de frontera verifican que exceder el límite por un byte produce rechazo.
