# ADR 0210 — R112: evidencia acotada de eventos del worker V3

Fecha: 2026-11-07 ART. Owner: RCA #417 / continuidad #45.
Estado: CODE_ONLY, sin despliegue ni evidencia nueva del host.

## Incidente y criterio

El intento físico Cutover V3
[#42422235097](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42422235097)
(source `c8bea3eb13695722ae294f454c7811395c159c26`) terminó
`PREPARE_WORKER/HEALTH_EXITED`; la compensación dejó el controlador legacy
activo y removió el worker temporal. La fase identifica salida anticipada,
**no** la causa de esa salida. El preflight previo no ejecutó el proceso real
protegido del worker. Ni una nueva construcción ni un Cutover ciego aportan
evidencia que ya no existe en el contenedor compensado.

## Operación autorizada sólo para diagnóstico

Una opción `cutover-a-worker-events-r112` del único
`boca-first-deploy.yml` consulta **exclusivamente** el ring histórico de
Docker para el intento documentado. El formulario exige `controller`,
presupuesto `1.5cpu-1024m-192pids` y todos los demás campos vacíos. El job
es manual, `main`, actor/triggering actor propietario, Environment Boca,
GitHub `GITHUB_RUN_ATTEMPT=1`, y valida el run histórico con GitHub API
antes de conectar al host. No requiere nuevos builds, manifests ni releases.

El host recibe por el canal SSH existente el propio script revisado,
sin input shell libre. El proceso Python de UID10001 verifica el socket
rootless `/run/user/10001/docker.sock` y reutiliza el ejecutor Docker
bounded de `host_cutover_worker_inspect.py`, con **un único comando**:

```
docker events --since=2026-11-07T22:47:15Z --until=2026-11-07T22:48:30Z \
  --filter=type=container --filter=event=die --filter=event=oom \
  --filter=label=boca.socios.browser-ipc-attempt=42422235097 --format='{{json .}}'
```

No `docker ps/inspect/exec`, pull/start/stop/remove, host filesystem write,
cleanup, credenciales de API, navegación, tickets, puertos o cambios a Porota.
Límites: 12 s de comando, 45 s de SSH, 8 KiB de stdout Docker, 2 KiB de
stderr, 512 bytes de recibo canónico, sin publicar el evento crudo. El
parser verifica identidad exacta `browser-worker` / `boca-socios` / etiqueta
del intento, tiempo en ventana, ID de contenedor y `exitCode` numérico 0–255;
solamente imprime `state`, `exit_code` y `oom` junto con constantes
`observer_writes=0`, `foreign_resources_touched=0`, `retry=NO_GO`.

## Interpretación y límites

- `OBSERVED` con `exit_code` confirma el código de salida del proceso,
  no su motivo. `137` **no** prueba OOM por sí solo: `oom=YES` requiere
  evento `oom` independiente y autenticado.
- Ring sin evento relevante = `UNKNOWN`; Docker retiene sólo los últimos
  **256 eventos** de daemon, por lo que la ausencia no prueba normalidad.
- Socket no verificado, error Docker, timeout, payload alterado o transporte
  incompleto = `INDETERMINATE`; varios `die` = `AMBIGUOUS`.
- Cualquiera de estos resultados mantiene `Cutover=NO_GO` y no autoriza
  reintentos. Si el ring ya caducó, la siguiente propuesta debe ser una
  instrumentación mínima de exit-code **antes de compensación**, revisada
  como operación distinta; no inferir causas de configuración especulativas.

## QA y documentación

Tests `tests/test_r112_worker_events.py` cubren parsing estricto,
identidad Boca, redacción, combinación die/oom, ausencia, ring ambigüo,
timeout, socket, recibo canónico, identidad GitHub y wiring exacto del
workflow. No se inspeccionaron ni ejecutaron `synthetic.py` o
`ipc_worker.py`. El RCA #417 sólo podrá atribuir causa física cuando exista
un recibo real nuevo de GitHub Actions; este ADR es diseño CODE_ONLY.

## Extensión R113 — clasificación de observador INDETERMINATE

El primer diagnóstico físico READ_ONLY [#42424149186](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42424149186)
autenticó el incidente y completó el SSH sin error, pero el host emitió un
recibo canónico `INDETERMINATE` y el verificador devolvió el error intencional
3. **No fue** un fallo de canon/parseo del recibo en el runner ni un ring vacío
(`UNKNOWN`); no hay evidencia aún de cuál condición de host falló. Su
duración acotada hace el timeout menos probable, sin descartarlo como hecho.

Para evitar otra investigación sin datos, el mismo observador añade un campo
`reason` de enumeración cerrada: `UID_UNVERIFIED`, `SOCKET_UNVERIFIED`,
`DOCKER_COMMAND_FAILED`, `DOCKER_OUTPUT_INVALID`, `TIMEOUT`. Sólo
`INDETERMINATE` puede llevar uno; los demás estados exigen `reason=null`.
El runner verifica esa combinación, publica únicamente el enum sanitizado,
y mantiene exit 3/no GO en cualquier `INDETERMINATE`. Nunca publica stderr,
evento Docker crudo, labels, IDs, información de otros proyectos ni cambia
comandos, socket, ventana, permisos o efectos. Ningún nuevo dispatch se
ejecutó al desarrollar esta extensión; el uso físico requerirá revisión
independiente y el flujo GitHub ya aprobado, sin reintento ciego de Cutover.
