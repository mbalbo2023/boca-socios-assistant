# ADR 0101: SO_PEERCRED entre namespaces PID separados

**Estado:** corrección candidata de [issue #257](https://github.com/mbalbo2023/boca-socios-assistant/issues/257)
para [PR #253](https://github.com/mbalbo2023/boca-socios-assistant/pull/253).
Reemplaza exclusivamente la exigencia de PID positivo de
[ADR0094](0094-local-synthetic-browser-ipc.md). No acredita instalación,
disponibilidad del droplet ni una corrida satisfactoria del candidato corregido.

## Causa observada

El smoke Docker descartable de
[run 41486701176](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41486701176)
superó inspect y la comprobación de aislamiento del kernel, pero falló en
`verify_peer` con `ipc_peer_unverified`. La ejecución posterior de diagnóstico
[41489306391, job 125427800778](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41489306391/job/125427800778),
sobre `0006aa8951da4e442d014a36359cc61c8a65a8a4`, obtuvo desde UID10001:

```text
2026-11-02T17:17:19.9790858Z
BOCA_CI_IPC_PEER {"gid":10002,"pid":0,"uid":10002}
```

La conexión diagnóstica no envió ningún comando de simulación; después falló
la guarda original durante el recorrido IPC. Inspect y aislamiento del kernel
pasaron y las dos etapas de limpieza selectiva del runner finalizaron PASS.
Estos recibos pertenecen al runner descartable, no al droplet.

La causa es una suposición del protocolo: `pid <= 0` rechazaba credenciales
válidas cuando los dos contenedores conservaban namespaces PID separados.
Las pruebas AF_UNIX anteriores en un único proceso no ejercían esa topología.
No se trata de un error de UID/GID ni de una necesidad de compartir procesos.

## Semántica del kernel y decisión

Linux entrega `SO_PEERCRED` desde las credenciales del peer: `cred_to_ucred`
usa `pid_vnr()` para el PID y transforma UID/GID efectivos al user namespace
del receptor. `pid_nr_ns()` devuelve cero si el PID no es visible allí.
Entre namespaces PID hermanos, ese cero no invalida el UID/GID mapeado.
Fuentes primarias:

- [Linux SO_PEERCRED y cred_to_ucred](https://cos.googlesource.com/third_party/kernel/+/91b75001d548f8c92798185831048162ef092fa5/net/core/sock.c).
- [Linux 6.18 pid_nr_ns y pid_vnr](https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/linux.git/+/refs/heads/linux-6.18.y/kernel/pid.c).
- [unix(7), SO_PEERCRED](https://man7.org/linux/man-pages/man7/unix.7.html)
  y [pid_namespaces(7), visibilidad](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html).

`verify_peer` rechaza PID negativo y mantiene la igualdad exacta de UID **y**
GID: 10001 al recibir un controlador, 10002 al recibir un worker. PID cero
no se utiliza como credencial ni como prueba de aislamiento. Ningún PID,
positivo o cero, establece por sí solo la identidad de un contenedor.
Credenciales ausentes, sin mapear, de otro usuario/grupo, truncadas o ilegibles
siguen siendo NO_GO; no se agrega fallback ni campo declarado por el cliente.

La identidad del contenedor continúa dependiendo de las comprobaciones
existentes de imagen, labels, usuario, montajes y aislamiento del host.
El protocolo conserva directorio UID/GID10002 modo0711, socket UID/GID10002
modo0622 y un solo enlace, inode comprobado antes y después de conectar,
volumen IPC exclusivo y controlador con montaje de sólo lectura. El worker
autoriza antes de leer una trama y el cliente antes de enviar `REQUEST`.
Se conservan namespaces PID/IPC/cgroup separados, seccomp, capacidades
descartadas, límites, STOP, timeout, single-flight, protocolo fijo y cero
egress del navegador. No cambian puertos, red, permisos ni recursos ajenos.

## Regresiones y límites de evidencia

Los casos deterministas de `tests/test_browser_ipc.py` inyectan respuestas
de `getsockopt`, sin sustituir la comprobación real del protocolo:

- PID cero y positivo con UID/GID exactos en ambas direcciones.
- PID negativo, UID/GID ajenos, root, ausentes y overflow rechazados.
- Tamaños incompletos/excesivos, error de lectura, socket ausente o plataforma
  sin `SO_PEERCRED` rechazados.
- Cliente sin envío de `REQUEST` y worker sin lectura de trama ni ejecución
  del navegador ante una identidad inválida con PID cero.

Antes de corregir producción, esos casos dieron 2 FAIL (las dos identidades
válidas con PID cero) y 35 PASS. Después de la corrección, los mismos 37
casos pasaron; lint, formato, tipado del protocolo y política de aislamiento
local también pasaron. Se conservan íntegramente los tests AF_UNIX,
STOP, cancelación, inode, idempotencia y simulación existentes, sin skips.
La prueba de la topología sigue requiriendo el smoke Docker real del SHA
corregido y sus checks CI/seguridad completos. Sus recibos, revisión y SHA
final se registran en PR #253 y el checkpoint #45; un mock verde no los
reemplaza ni autoriza una operación protegida del droplet.
