# R162 — Parche de seguridad Kerberos del controlador Boca

Fecha: 2026-11-10 ART. RCA: issue #417. Estado: propuesta de código; no implica release ni Cutover.

## Objetivo y límites

Cerrar el hallazgo de Trivy HIGH `CVE-2026-107364` sobre `krb5-libs=1.22.2-r1` en la imagen **controlador** sin modificar el navegador BLACKBOX, el host o las reglas de publicación. El titular propuso instalar `1.22.3-r0` desde Alpine `edge` manteniendo el resto estable.

## Opciones consideradas

1. **Elegida: versión 1.22.3-r0 de Alpine 3.24 `main`, fijada en `Dockerfile` runtime.** El mismo paquete ya figura publicado en la rama estable desde el 10/11/2026, por lo que evita mezclar repositorios. No volver a instalar Python ni `pip`: la imagen `python:3.12.15-alpine3.24` ya los incluye.
2. Versión 1.22.3-r0 de `edge` mediante `--repository`: equivalía al objetivo de parche pero introduce riesgo por cruce de ramas, innecesario ahora que existe backport estable.
3. Permitir la vulnerabilidad HIGH en Trivy: no corrige el problema y debilita un control distinto de los módulos BLACKBOX.

Fuentes: [paquete estable](https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/krb5-libs), [paquete edge](https://pkgs.alpinelinux.org/package/edge/main/x86_64/krb5-libs), [gestión de repositorios Alpine](https://docs.alpinelinux.org/user-handbook/0.1a/Working/apk.html), [MITKRB5-SA-2026-001](https://web.mit.edu/kerberos/advisories/MITKRB5-SA-2026-001.txt).

## Verificación y no objetivos

La regresión real existente es el escaneo Trivy de la imagen exacta: rojo en `42897140865`. Construir una imagen nueva y exigir Trivy sin HIGH/CRITICAL; no se considerará corregido hasta ver el run exact-SHA. El pin `apk add --no-cache` debe fallar si el espejo estable aún no tiene la versión, sin recurrir automáticamente a `edge`. No tocar `Dockerfile.browser`, `synthetic.py`, `ipc_worker.py`, credenciales, puertos, datos ni otros Docker. Publicación y Cutover protegidos son pasos posteriores e independientes.
