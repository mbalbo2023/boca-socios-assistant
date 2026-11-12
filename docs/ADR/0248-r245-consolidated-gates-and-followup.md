# ADR 0248 — R245: autenticación, cleanup y gates de BETA sucesora

**Fecha:** 2026-11-12 ART. **Issue:** #417. **Estado del código:** candidato
R245 en integración. **Estado físico:** NO_GO, sin nuevo release ni APPLY.

## Hechos de referencia reconciliados

- `main` inicial: `3e0d6e6adbf372316aa07685575a3ed3cf3c1a98`, PR abiertos: 0.
- GitHub CI `43310658142` y seguridad `43310658077`: SUCCESS para ese
  `main`, no para la futura integración R245.
- Último par observado en el host: `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`,
  intento de instalación `43217075287`. Lectura física R189
  `43281507903`: SUCCESS pero sin artifact reutilizable autenticado.
- No existe prueba física de instalación del SHA sucesor, ni recibo que cubra
  passkey, `SITE_URL`, trabajador bajo demanda, monitor, SQLite y limpieza.

## Correcciones revisables

1. **Autenticación release:** el selector protegido sucesor no extrae con
   `gh run download` ZIPs previos a verificarlos. El transporte GitHub REST
   autentica primero repo, workflow, SHA, attempt 1, steps, metadatos,
   checksums, ZIP y manifests de controller y worker; recién entonces
   escribe tres archivos en el directorio privado con `O_EXCL`, modo `0600`
   y `fsync`. Bearer permanece en Actions. Los demás selectores históricos
   conservan el transporte anterior; el límite de 25 inputs no cambia.
2. **Cleanup V2:** se verifica la lease antes de cada probe y de cada
   `delete_exact` y al terminar. Los inventarios before/after requieren
   exactamente los mounts `data,key,owner,site,ipc` del controller y
   `site,ipc` del worker. El R108 forense sigue en cuarentena; no existe
   permiso de eliminación global ni de recursos Porota. La versión de ZIP
   worker continúa dentro del presupuesto fijo 520 000 bytes.
3. **Panel y trabajador:** los tests pasan por el POST real autenticado del
   propietario, guardan `SITE_URL` en configuración JSON privada del volumen
   Boca, cotejan el espejo de solo lectura y su lectura en frío tras
   reinicio, y rechazan Origins anómalos. El monitor informa únicamente
   metadatos; ninguna prueba local genera tokens reales.
   Los adaptadores de lectura física agregan observación de par/systemd,
   binding e inventario Boca bajo lease, doble captura de coordenadas R108,
   huellas del SITE y HTTP local `/healthz`. No prueban passkey ni login, no
   se invocan aún desde un actor productivo y no se interpretan como prueba
   de despliegue.
4. **Rendimiento:** un PR de documentación inequívoca puede omitir builds
   y labs descartables sin omitir los contextos CI nombrados; pushes a
   `main`, código, workflows y casos ambiguos recorren ambos Trivy y labs.
   No se promociona la paralelización R244 porque el tiempo alojado empeoró
   de 254 s a 313 s. Caches Docker/GitHub requieren A/B de latencia, coste
   y procedencia antes de reutilizarse en release protegida.

## Hallazgos independientes que mantienen NO_GO

- **P0 lectura Docker:** el adaptador de recurso worker necesitaba
  `State.Status`, `State.Pid` y `State.ExitCode`, fuera de la allowlist
  `host_boca_cleanup._inspect_field`. Un test anterior reemplazaba el
  verificador por un mock permisivo. La corrección usa exclusivamente el
  lector con identidades Boca probadas de R177; nunca se amplía la API de
  limpieza por fuera de su allowlist. Requiere regresión con esa allowlist
  real antes de promover código.
- **P1 observación sucesiva R188:** la observación R188 V1 autentica
  literalmente el par R186, sus dos CIDs, revisión y `attempt`. Tras una
  actualización genuina ya no podrá reconocer la siguiente instalación.
  Mantener V1 como prueba histórica de origen de los volúmenes/red; versionar
  otro observador de par actual con run/artifact/identidad de release
  independiente. La prueba obligatoria abarca dos upgrades consecutivos con
  source/CIDs distintos y recursos persistentes idénticos, rechaza el par
  anterior obsoleto y un release sin procedencia.
- **P0 actor effectful:** `requires_persistent_receipt=False` es una
  deshabilitación deliberada. Los contratos puros, bundles, adaptadores
  inertes y lectura de Actions no constituyen lectura/escritura real del
  host bajo la misma lease, ni acreditan un postflight durable. No cambiar
  ese valor sin revisión independiente y prueba protegida compatible.

## Camino crítico antes del BETA certificada

1. Integrar un único PR, recalcular el SHA determinístico del ZIP Cutover
   en nueva constante R245 sin sobrescribir R244 histórico; ejecutar suite
   integral, lint, mypy, tests de política, presupuestos y revisión ajena.
2. Confirmar en GitHub los dos checks requeridos del SHA final; cerrar PR
   y comprobar PR0. Medir tiempos reales CI antes/después.
3. Resolver y probar los adaptadores effectful, R188 current-pair y una
   observación READ_ONLY auténtica obtenida en lease protegida fresca.
4. Sólo con esos gates, un único release controller+worker del `main`
   definitivo y un APPLY con autorización del workflow existente. Nunca
   reejecutar la migración histórica R186.
5. Postflight físico: loopback 8443, passkey, settings `SITE_URL`, START/STOP
   worker, monitor sin inventar datos, SQLite e identidad/limpieza positiva
   de Boca. Guardar recibos y RCA en #417. Cualquier falta significa NO_GO.

**Regla de evidencia:** la suite local y un CI verde no prueban el droplet;
la ejecución protegida tampoco prueba aceptación hasta que el postflight
físico cierre cada contrato. No emitir `DEPLOY COMPLETE` sin esos recibos.

## Evidencia del candidato integrado antes de publicar

La integración de cinco ámbitos de código y pruebas ejecutó `uv run --no-sync
pytest -q -n 4`: **7 753 PASS, 1 SKIP** por `AF_UNIX EPERM` local,
**34 subtests PASS**, 48.75 s. Ruff, formato (974 archivos), mypy
(187 módulos) y política de aislamiento: PASS. La prueba del ZIP Cutover
reconstruyó la composición determinística R245 con SHA256
`1fa860223310087e592fac249e7a16cf01ec1dd642b1a3121469bd137fc74048`,
preservando el pin R244 como evidencia histórica. Los tests focalizados de
release, cleanup, panel y CI rápido sumaron 215 PASS en integración; los
contratos de los nuevos lectores físicos agregaron 70 PASS focales.
Todas estas pruebas fueron locales y deben repetirse como checks alojados en
el SHA exacto del PR. El único SKIP de AF_UNIX requiere runner Linux apto;
no se elimina el test para lograr un resultado artificial.
