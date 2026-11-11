# A45-R176 — IPC cross-UID: fixture aislada y byte-idéntica en Actions

**Fecha:** 2026-11-11 (ART). **Ámbito:** solo Boca Socios Assistant.
**Estado:** fix-forward CODE_ONLY, **NO_GO físico** hasta nueva ejecución
real de GitHub Actions y censo protegido.

## Referencias canónicas

- [PR único #478](https://github.com/mbalbo2023/boca-socios-assistant/pull/478),
  base protegida `main=361e3ff42c44e1b8699d7a3e2d158c9a367b2f86`.
- [Issue #417 R175.2](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6800844404)
  con RCA físico, seis Actions y cinco resultados SUCCESS.
- [Handoff R175](2026-11-11-r175-ci-two-stoppers.md) que documenta
  soluciones APT/runner y los cuatro frentes de producto.
- [ADR 0223](../ADR/0223-bot-bajo-demanda.md) sobre worker bajo demanda.

## Evidencia R175 que no debe confundirse con R176

**SHA GitHub R175:** `a829b0022e4c51d175a4dfd6af2c9be46c595705`,
árbol idéntico al código local auditado.

| Workflow | Resultado real |
| --- | --- |
| [Panel preview #43054437405](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054437405) | SUCCESS |
| [Telegram V2 contract #43054437632](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054437632) | SUCCESS, sender OFF |
| [Image security #43054437476](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054437476) | SUCCESS, Chromium + controller |
| [Image release #43054437759](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054437759) | SUCCESS PR validation, publicación SKIPPED |
| [First deploy #43054437558](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054437558) | SUCCESS PR/runtime, host SKIPPED |
| [CI #43054438126](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43054438126) | FAILURE solo smoke IPC cross-UID |

**APT/Docker solucionado físicamente en el runner:** el job de seguridad
Chromium `130639997161` registró DNS fallido de ambos hosts Ubuntu,
`BOCA_APT_FALLBACK state=READY mirror=kernel_archives`, descarga efectiva
de cuatro `InRelease` Noble vía HTTPS, compilación de imagen y Trivy
aprobados. El job `image-build` de CI también fue SUCCESS. Firmas,
versiones CVE fijadas, Trivy, UID/cgroups/seccomp originales intactos.
Esto certifica la **imagen en GitHub**, no la instalación en droplet.

**Último error IPC concreto:** job `quality-and-tests` `130639998900`
aprobó 6819 pruebas +34 subpruebas, lint, formato, tipos y smoke AF_UNIX
anterior, pero el nuevo script bajo UID separados y Python del sistema
terminó en 0,2s:

```
BOCA_WORKER_IPC_LINUX state=NO_GO stage=WORKER_BIND
```

Por el recibo R175 no se sabe si el hijo terminó por error de lectura
del workspace, si falló una importación o si hubo error de inode. La
explicación más sólida, **todavía hipótesis**, es que UID10002 no puede
atravesar `/home/runner/work` que pertenece al usuario `runner` distinto:
[runner-images #6930](https://github.com/actions/runner-images/issues/6930) y
[GitHub community #26811](https://github.com/orgs/community/discussions/26811).
No alterar chmod global de runner ni convertir ese fallo en bug probado
del contenedor productivo.

## Fix-forward R176 estrictamente desechable

En `scripts/check_worker_ipc_linux.py` se prepara antes del START una
fixture bajo `/tmp` que debe ser root:root/sticky `01777`; el directorio
raíz individual es propio y su nombre Boca impredecible. Se copian
**byte a byte** solo 11 archivos de código público necesarios:

- propio script IPC de laboratorio;
- `boca_socios`/`browser`/`domain` inicializadores;
- `ipc_client.py`, `ipc_protocol.py`, `ipc_server.py`, `activity_events.py`,
  `contracts.py`, `worker_health.py` y `domain/policy.py`.

La fixture aplica directorios de código 0555 y archivos 0444, preserva
los bytes y permite importación a los tres UID; nunca incorpora credenciales,
SITE_URL, módulos `synthetic.py`/`ipc_worker.py` ni datos de socios. El
intérprete es `/usr/bin/python3` **solo en CI** y el `PYTHONPATH` de los
hijos apunta únicamente a esta copia. No se habilitan red IP ni Docker.

El worker de prueba aún exige socket UID10002, directorio0711,
permisos0622, SO_PEERCRED, rechazo de UID10003, acuse NO_GO de UID10001,
STOP por PID propio y desaparición del socket. Si falla, subetapas fijas
identifican `WORKER_BIND_CHILD_EXIT`, `WORKER_BIND_INODE` o
`WORKER_BIND_TIMEOUT`. Nunca mostrar stderr privado ni una excepción que
pueda contener ruta, token, sitio o dato de socio.

**Verificación del branch aislado:** 6826 tests PASS +34 subtests,
0 FAIL (54,95s), Ruff/format (836 archivos), mypy (154 módulos),
política, diff-check PASS; nuevos tests TDD RED→GREEN.
**Lote integrado exacto:** 6826 PASS +34 subtests, 0 FAIL (46,97s),
Ruff/format, mypy 154 y política PASS. Revisión independiente de 16
pruebas focales PASS, 0 P0/P1, GO_CODE_ONLY.
La prueba AF_UNIX entre UID distintos **no puede correrse localmente**
en el sandbox restringido: requiere la Action exacta GitHub.

## Próximos gates de cuatro frentes

1. IPC: consolidar R176 con revisión independiente, publicar una sola
   actualización del PR #478 por CAS y obtener en Actions exact-SHA
   `BOCA_WORKER_IPC_LINUX state=PASS peer=UID10001_10002
   stranger=DENIED result=NO_GO stop=VERIFIED` junto a CI verde.
2. SITE_URL/dashboard/actividad: 85 pruebas focales PASS de código;
   falta acuse del panel 8443/passkey/volumen URL-only en el droplet.
3. Docker/volúmenes/Cutover/bundle: 29 pruebas focales PASS y builds
   Chromium+Trivy de R175 verdaderos; último host
   [#42912586832](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42912586832)
   `LEGACY_SINGLETON` sin cardinalidad 0/2+. Tras CI y merge a `main`,
   despachar **solo** censo protegido READ_ONLY desde Actions con
   `operation=cutover-a-census`, `service=controller`,
   `resource_budget=1.5cpu-1024m-192pids`, resto de pins en blanco;
   no elimina/rearranca nada ni autoriza APPLY.
4. Socios/Telegram/QA: suite integral local y focal Telegram/UI 40 PASS;
   sender OFF hasta rotación del token expuesto; ninguna reserva real,
   ninguna operación en un sitio externo. Validar con pruebas físicas
   separadas luego de resolver la infraestructura.

Sin seis workflows de Actions GREEN, PR protegido y censo físico atestado,
**NO_GO de merge, release instalado, Cutover y GREEN del droplet**.
Porota, PPI Watch, Docker ajeno y otros puertos intocables. No hay
autorización para bypass de confianza APT/Trivy o permisos del host.
