# ADR 0226 — Finalizar la limpieza con el panel original activo

## Estado que cambió en el droplet

| Comprobante | Controlador | Worker y candidato | Resultado |
| --- | --- | --- | --- |
| [Observación #915](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42750716605/job/129613417052) | Original detenido bajo su nombre temporal. PID 0 y 8443 sin publicar. | Worker creado con PID 0. Candidato ausente por dos búsquedas de su CID. | Subfase de recuperación autorizada por identidad. |
| [Rescate #916](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42750940352/job/129614147059) | El original recuperó su nombre, política y salud HTTP en loopback. | La comprobación de limpieza confirmó sólo el CID original y la ausencia del volumen IPC temporal. | Falló en IMAGES antes de liberar el staging. |
| [Observación #917](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42751222045/job/129615059001) | Mismo CID original, en ejecución y sano en 127.0.0.1:8443. | Se confirmó por separado la ausencia de ambos CIDs. | Perfil OLD_ACTIVE y staging vinculado al mismo intento. |

El recibo de #916 identifica la etapa de imágenes, pero carece del digest y de la operación que falló. El estado del panel ya recuperado puede comprobarse independientemente. [Antecedentes en #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6758017802).

## Decisión

Terminar el staging de #904 con el panel histórico activo. Se usan los dos digests de GHCR registrados en la release original, el CID del controlador y los inodos acreditados en #908. Una lectura previa prepara el plan. La finalización protegida contrasta en vivo las mismas identidades y conserva el proceso que atiende al titular. La evidencia incluye la disposición de cada imagen, el estado del staging y la salud del panel. Después de esa confirmación puede comenzar la instalación en reposo de la BETA desde la release del commit vigente.

## Semántica de Docker que debe cubrir la prueba

El cliente de Docker 28.5.1 imprime un único salto de línea al cerrar una plantilla de inspect sin elementos. Exigir stdout de longitud cero puede clasificar como fallo una imagen ya ausente. Se verifica el código de salida, el diagnóstico exacto para la referencia solicitada y la forma completa de stdout. Un error de acceso al daemon queda indeterminado. El digest de la referencia de repositorio y el identificador que devuelve el motor se verifican por sus respectivos campos. El almacén clásico y el de containerd pueden representarlos de manera distinta. [Inspector de Docker CLI](https://github.com/docker/cli/blob/v28.5.1/cli/command/inspect/inspector.go#L147-L152) · [Tipo ImageInspect](https://github.com/moby/moby/blob/v28.5.1/api/types/image/image_inspect.go#L18-L47) · [Implementación de containerd en Moby](https://github.com/moby/moby/blob/v28.5.1/daemon/containerd/image_inspect.go#L86-L101).

Las trazas públicas de compilación y publicación de la release #788 permiten buscar los identificadores de las dos imágenes incluso si Docker ya retiró el nombre. Un identificador residual impide declarar que la imagen desapareció. El comprobante público sólo informa sobre estas dos imágenes. [Build y push de #788](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42741500632/job/129583391462).

| Imagen de #904 | ID de compilación SHA-256 | Digest publicado SHA-256 |
| --- | --- | --- |
| Controlador | `a191fe19d4837225f066aaeeb68ed459f668b55c20e3cb29e86a48c74ab86fb6` | `40ceea681a8568e93bb2d22decb294e712e70de32b68156d998a0bf612b7569b` |
| Worker | `81753c847715010eadfb410747753c95745cf3080cc55b7bbc7f0c8562e57c34` | `8fb79002e937de1ca014db502af053a37046fa4361c44a7719f24e813faf185c` |

## Verificación de la operación protegida

El runner verifica los jobs de #915, #916 y #917 y la CI del mismo commit de main. La lectura devuelve dos filas y una huella del proceso original. Sólo un plan con las dos imágenes ausentes o retirables permite la finalización. La operación bajo bloqueo vuelve a comprobar las filas y la huella antes de cualquier retirada. El runner contrasta el recibo final del host con el plan descargado. Una imagen previamente ausente debe seguir ausente y una retirada debe acreditar el ID registrado y su desaparición. Si se pierde la respuesta SSH, una lectura posterior puede identificar qué quedó en el droplet.

El paquete completo contiene 47 entradas y 1.143.350 bytes de fuentes. Su ZIP ocupa 283.376 bytes y su SHA-256 es `f8513a879e2530f6f51dea256f4b3e1502eba11048360d193d5f26a02bf3583b`. El constructor y el receptor admiten 1.147.000 bytes de fuentes y 512.000 comprimidos. El preflight reducido ocupa 109.606 bytes comprimidos y la recuperación histórica 44.922. Las pruebas verifican sus listas de entradas y límites independientes.
