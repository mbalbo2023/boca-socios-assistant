# ADR 0185 — Preflight reversible de GHCR/rootless previo a Cutover A

**07/11/2026, ART · CODE_ONLY, sin operación en droplet.** Continuidad #45;
incidentes Cutover #763/#770/#778, diagnóstico #414, Stage #788 y
observación física #789. Este ADR no declara resuelto el RCA original.

## Causa y decisión

El APPLY #778 (run `42317092809`) pasó el GO_B protegido del PREPARE #776
pero terminó con código remoto 3, sin ACK final. Los observadores posteriores
demostraron el controlador original sano, sin nuevo worker o candidato; no
identifican si el fallo estuvo en descarga GHCR, cgroups/rootless o creación
del worker. `failed_phase=PREPARE_WORKER` aún agrupa descarga, creación y
salud. Repetir APPLY consumiendo GO sin separar esas condiciones es evitable.

Se añade al **único** `boca-first-deploy.yml` una operación manual distinta,
`cutover-a-worker-preflight`, que requiere el mismo `main` exacto, release
dual publicado, ambos manifiestos del mismo run, imagen anterior firmemente
atestada y actor/Environment/SSH restringidos. No acepta un PREPARE run ID,
`GO_B` ni contexto de APPLY. Usa el ZIP determinista con allowlist y bootstrap
memfd existentes, nunca copia scripts permanentes al host.

## Transacción limitada a Boca

1. Bajo lease exclusivo de Boca UID10001, atestar por ID exacto el único
   controlador legacy RUNNING con `127.0.0.1:8443`, data/key/owner originales
   y rootless socket y store propios. Cualquier residuo de un probe anterior
   devuelve NO_GO sin efectuar otra escritura.
2. Descargar exactamente las dos imágenes GHCR por digest y revisión OCI,
   reutilizando `_storage_snapshot`, `_browser_validate_image` y
   `_validate_storage_continuity`: observar capacidad real y continuidad de
   filesystem, Docker root y socket sin introducir otro margen numérico
   arbitrario. El gate del APPLY real sigue siendo un contrato separado.
   **El pull sí modifica la cache de imágenes del Docker rootless
   Boca**; no es READ_ONLY y puede consumir disco. No borra otras imágenes.
3. Crear un archivo temporal `0600` de seccomp revisado en el runtime privado
   `/run/user/10001` y **un único contenedor descartable** con nombre/label
   derivados del GitHub Run ID, imagen Browser exacta, UID/GID10002,
   `--network none`, CPU1, RAM768MiB, 128PIDs, seccomp y `no-new-privileges`.
   No se monta owner/key/data ni ningún volumen IPC; no se publica puerto,
   crea red, configura Telegram, ejecuta Playwright ni abre navegador.
   Se lanza solo Python dormido y se verifica identidad Docker y kernel de
   cgroup/UID/seccomp/no-egress por `docker exec` de lectura.
4. En success/failure, inspeccionar el label/imagen/nombre/ID exactos antes de
   detener y eliminar **solo** ese contenedor. Elimina únicamente su archivo
   seccomp temporal identificado por inode, conserva las imágenes GHCR
   descargadas para no desperdiciar una futura instalación y reatesta el
   original. No realiza `prune`, operación de Docker rootful, backup, ni
   toca Porota u otros proyectos.
5. El runner acepta `PASS` exclusivamente con SSH exit0 y recibo único
   byte-a-byte exacto (`images=VERIFIED worker_boundary=VERIFIED
   cleanup=VERIFIED original=RUNNING prepared_go=UNCONSUMED`). Fallo/ACK
   ausente queda rojo y exige inventario Boca READ_ONLY nuevo; sin reintento
   ciego ni nuevo GO.

## Cobertura y limitación crítica

Esta prueba **separa GHCR y capacidad kernel de un intento Cutover**, pero
no hace arrancar `boca_socios.browser.ipc_worker`, no crea volumen/socket
IPC, no valida su handshake/salud final ni certifica que Cutover APPLY
funcione. El contrato de `ipc_worker.py` es BLACKBOX: no se inspecciona,
refactoriza ni prueba con Chromium. El pass de este preflight no autoriza
`PARK_ORIGINAL`, no demuestra BETA en el droplet y no convierte el GO en
automático. Un fallo de SSH puede dejar residuos inciertos; entonces el
operador debe reconciliarlos con una lectura independiente, sin tocar el
controller legacy o completar limpieza por suposición.

Los controles preventivos que siguen obligatorios son SHA/digest, lease,
identidad original, memoria/cgroups/seccomp, ownership de volúmenes,
GO_B independiente **en un APPLY nuevo**, cleanup Boca-only y ACK físico.
El costo adicional normal es una sola descarga exacta (aprovecha cache), un
proceso efímero y su eliminación; no encadena miles de pruebas ni duplica
el release. Se mide su tiempo por Actions cuando exista un run físico real.

**QA antes de ejecutar:** tests de argumentos inválidos, comando sin
montajes/puertos, release exacto, limpieza por ID y rechazo de un label
ajeno. No presentar estos tests offline como evidencia física. Regla 84:
al integrarse registrar SHA, checks, Run ID real y resultado en #45.
