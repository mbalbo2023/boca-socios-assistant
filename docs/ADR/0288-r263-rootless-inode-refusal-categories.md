# ADR0288 — R263: evidencia física del rechazo de inodos rootless

**13-NOV-2026 UTC · #417 · CODE_ONLY · DEPLOY NO_GO.**

## RCA observado, sin hipótesis convertida en hecho

La observación protegida [#43364745527](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43364745527)
sobre `main=01bb7d6ca1f7c933adbbad5aefc204bf981e122c` terminó con un
recibo de rechazo canónico esquema 2: `failure_boundary=INODES`,
`remote_status=HOST_REFUSED`, `observer_writes=0`. El acceso SSH y la
verificación del rechazo fueron efectivos. El código alcanzó la subfase de
lectura de inodos de los tres archivos privados bajo la lease Boca, pero el
recibo anterior **no identifica qué comprobación falló**. No hay evidencia
para afirmar que sea un UID subordinado, archivo ausente o permisos.

Los runs antiguos [#43360372904](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43360372904),
[#43362162288](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43362162288)
y [#43362853913](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43362853913)
fallaron sin esa clasificación; no se repiten ni se tratan como GO.

## Decisión de diagnóstico limitado

El mismo observador existente preserva el recorrido no-follow/O_PATH, la
validación de volúmenes y CIDs, flock exclusivo y doble lectura real. La ruta
de éxito y su comprobante esquema 1 permanecen inalterados. La ruta de
rechazo únicamente distingue códigos **literales** de metadatos:

| Código | Comprobación que rechazó |
| --- | --- |
| `INODES_OWNER_HOST` | Owner del inode coincide con UID/GID de servicio host, no con el par mapeado; no autoriza chown ni cambiar expectativas |
| `INODES_OWNER_PARTIAL` | Coincide sólo una componente del owner mapeado |
| `INODES_OWNER_OTHER` | No coincide el par mapeado ni el owner host |
| `INODES_ABSENT` | Ruta esperada ausente |
| `INODES_ACCESS` | SO denegó una apertura de metadatos |
| `INODES_PATH` | Recorrido no seguro o error de ruta |
| `INODES_TYPE` | Inode no regular, incluido symlink |
| `INODES_DRIFT` | Inode cambió entre descriptor y nombre |
| `INODES_LINK` | El archivo no tiene exactamente un enlace |
| `INODES_MODE` | Modo no es 0400 ni 0600 |
| `INODES_OTHER` | Falla interna de inode no clasificable |

Ninguna categoría incluye número real, ruta privada, archivo concreto,
nombre de clave/BD, PID/CID, hash de contenido ni secretos. El motivo de
excepción se suprime; sólo un recibo host canónico y verificado puede
publicar la categoría. El Action sigue rojo ante **todo** rechazo. La
categoría `INODES` original permanece admitida para continuidad histórica,
sin fabricar un éxito.

## QA y camino crítico

- TDD RED capturado contra `INODES` genérico; GREEN con clasificación de
  propietario host, parcial, ajeno, ausencia, modo, hardlinks y symlinks,
  además de rechazo de categorías no permitidas.
- Suite local con `uv run --no-sync pytest -n 2`: 8.193 PASS, 1 SKIP por
  AF_UNIX EPERM del sandbox; `check_rca_lessons.py` rechaza ese SKIP por
  diseño. **No se declara RCA GREEN local**; se exige el runner Linux real
  de GitHub sobre el SHA exacto. La primera invocación con `.venv/bin/python`
  sin el paquete editable provocó cinco fallas R88 de import y se reemplazó
  por la invocación canónica; R88 dio 10/10 PASS con `uv run`.
- Los controles originales `pair/binding`, lease, volúmenes, no-follow,
  ZIP protegido, source pin y presupuesto no se relajan.
- La siguiente observación física sólo es elegible tras PR revisado,
  CI exacto, merge y confirmación de `main`/PR0. Una sola operación
  `boca-rootless-mapping-observe`, sin R186 replay ni mutaciones.
- Aun con respuesta `PRELIMINARY_PREDEPLOY`, persisten release dual,
  preflight same-lease, cleanup V2 y aceptación física de 8443, passkey,
  SITE_URL, worker, monitor y SQLite.

El resultado de ese futuro diagnóstico definirá **una** corrección
fix-forward documentada para la causa concreta; no se modifica owner,
permisos, Docker ni host a partir de conjeturas. Porota y recursos externos
quedan fuera del alcance.
