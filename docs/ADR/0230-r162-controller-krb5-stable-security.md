# ADR0230 — Controlador Boca: parche `krb5-libs` desde Alpine 3.24 estable

Fecha: 2026-11-10 ART. Alcance: `Dockerfile` de controlador y security release. Owner: #417; continuidad #45. Estado inicial: CODE_ONLY; no se infiere instalación física.

## RCA y decisión

En `main=713fb9a08a3788189b8efa0e6fc44d0b2a415ca0`, `image-security` [42897140865](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42897140865) falló por `krb5-libs=1.22.2-r1` y HIGH `CVE-2026-107364` en la imagen controlador. El browser pasó su scan. [Release PR470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42896403373) no publicó imagen al fallar el gate. Esto **no** es un problema del socket IPC ni demuestra el motivo de `ExitCode=0` del worker.

El titular propuso fijar `krb5-libs=1.22.3-r0` desde el repositorio `edge`. Al verificar fuentes oficiales se observó que **Alpine v3.24/main publicó la misma versión parcheada el 10/11/2026**, por lo que se elige el backport estable y se descarta incorporar `edge`. Mezclar ramas está desaconsejado por Alpine. Fuente del paquete: <https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/krb5-libs>; aviso del mantenedor MIT: <https://web.mit.edu/kerberos/advisories/MITKRB5-SA-2026-001.txt>; manual de `apk`: <https://docs.alpinelinux.org/user-handbook/0.1a/Working/apk.html>.

## Implementación y verificación obligatoria

Se mantiene la imagen `python:3.12.15-alpine3.24` fijada por digest para ambas etapas. Solo la etapa final `runtime`, antes de `USER 10001`, ejecuta `apk add --no-cache 'krb5-libs=1.22.3-r0'`; si el espejo estable aún no tiene el pin, el build **falla cerrado**, sin fallback a `edge`. No reinstalar Python ni pip; el Dockerfile base ya los aporta. `Dockerfile.browser`, BLACKBOX, redes, volúmenes y los workflows quedan sin modificaciones.

La regresión de seguridad auténtica está en el scanner Trivy existente: exigir un build **nuevo** del candidato y scan de OS/bibliotecas HIGH/CRITICAL con estado SUCCESS exact-SHA, seguido de PR, merge, release dual por digest y un único Cutover V3 protegido. No desactivar ni silenciar vulnerabilidades, ni afirmar GREEN sobre la base de esta ADR. Docker no está disponible en el workspace actual, por lo que la validación de imagen real corresponde a Actions. No ejecutar worker BLACKBOX desde CI para este parche.

Validación local anterior al PR: `git diff --check` y `scripts/check_repo_policy.py` PASS; 23 tests focales de imagen/release PASS. `PYTHONPATH=src pytest -q` ejecutó 6.574 PASS +34 subtests PASS y **un FAIL ambiental**: `test_pytest_entrypoint_collects_observer_tests_without_pythonpath` exige un ejecutable `pytest` junto a `sys.executable`; en este workspace `pytest` está en `/home/agent/.local/bin` y el intérprete en `/opt/codex/.../bin`, fuera de ese supuesto. No se cambió el test ni se reinterpretó como GREEN; la suite de CI en runner preparado debe emitir su propio resultado. Revisión independiente: sin hallazgos críticos/importantes, GO condicionado a build/Trivy exact-SHA.

El despliegue de `main` actualizado y el arranque funcional del worker continúan como hitos distintos; el dueño se reserva la aceptación física del runtime. Porota, Docker rootful y recursos ajenos quedan fuera de alcance.
