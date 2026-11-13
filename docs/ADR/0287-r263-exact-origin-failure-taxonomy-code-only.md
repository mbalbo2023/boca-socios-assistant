# ADR 0287 — R263: fallos tipados del observador 8443 (CODE_ONLY)

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** candidato
`CODE_ONLY / DEPLOY NO_GO`. Base de desarrollo:
`4bc94474492943cefc4069cb751ca4b7f89a3202`. Ninguna Action remota,
instalación, PR o despliegue se ejecutó desde este cambio.

## Síntoma y límite de RCA

Los observadores físicos READ_ONLY rootless
[#43362162288](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43362162288)
y exact-origin
[#43362853913](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43362853913)
terminaron fallidos. El observador exact-origin descartaba stderr SSH y
agrupaba transportes, UID, inodes y recibos ausentes o inválidos en
`HOST_OR_RECEIPT_UNVERIFIED`. **Ese código no permite identificar la causa
física retrospectiva**. Esta ADR no asigna culpa al SSH ni al host con esa
sola evidencia. La otra Action rootless tiene ownership y RCA separados.

## Decisión de observabilidad acotada

Se amplía **solo** el selector existente
`boca-panel-exact-origin-observe`, su módulo host y sus pruebas.

1. El host, al reconocer un error de entrada validada, UID efectivo distinto
   de 10001, metadata SITE_URL, metadata de almacenamiento, drift de inodes,
   drift HTTP o rechazo de su recibo, emite únicamente un marcador de fase
   `BOCA_PANEL_ORIGIN_FAILURE_V1` con run ID y SHA de main exactos. Es una
   **afirmación NO_GO de origen remoto**, nunca aceptación ni prueba de
   identidad Docker. Los errores internos desconocidos continúan sin
   atribución causal. La captura y el marcador no incorporan rutas,
   contenido, URL, cookies, claves, PID, CID ni valores de UID/subuid.
2. El runner conserva stdout remoto **sólo en archivo temporal 0600** y
   descarta stderr. Un clasificador local lee como máximo 513 bytes, compara
   el marcador con el run/SHA esperado y entrega exclusivamente categorías
   finitas. Exit 255 o timeout SSH genera `SSH_TRANSPORT_UNVERIFIED`, sin
   creer contenido remoto; salida host 3 con marcador correcto distingue
   `HOST_UID_UNVERIFIED`, `HOST_SITE_METADATA_UNVERIFIED`,
   `HOST_STORAGE_METADATA_UNVERIFIED`, `HOST_METADATA_DRIFT_UNVERIFIED`,
   `HOST_HEALTH_DRIFT_UNVERIFIED` o `HOST_SCRIPT_VALIDATION_UNVERIFIED`.
   Sin bytes de salida y rc=0 informa `RECEIPT_MISSING`; bytes no canónicos
   o marcador equivocado informan `RECEIPT_MALFORMED`. Un fallo de ejecución
   sin marcador confiable mantiene `REMOTE_EXECUTION_UNVERIFIED`.
3. Antes de SSH, la verificación real de main distingue
   `PRE_SSH_MAIN_REF_UNVERIFIED`, los errores locales de preparación
   `PRE_SSH_RUNNER_UNVERIFIED` y una falla anterior del Environment/owner/
   configuración de SSH `PRE_SSH_AUTH_OR_SETUP_UNVERIFIED`. Esa última es
   una categoría **agrupada**, no determina qué comprobación falló. Un
   fallo de la propia clasificación queda `CLASSIFIER_UNVERIFIED`.
4. Únicamente un recibo original `BOCA_PANEL_ORIGIN_READONLY_V1` canónico,
   con remoto exit 0 y run exacto, puede publicarse como observación técnica
   `OBSERVED_NO_GO`. **Siempre** lleva `observer_writes=0`,
   `namespace_map=UNVERIFIED`, `volume_provenance=UNVERIFIED` y
   `deploy=NO_GO`. Toda categoría negativa mantiene Actions en rojo.

## Efectos y seguridad

No se cambia `O_PATH|O_NOFOLLOW`, propietario/mode de inodes, doble
captura, URL predeterminada (sigue **sin configurar** hasta que Tincho la
guarde), `Content-Length: 15` del cuerpo fijo de `/healthz` (15 bytes),
puerto, cabezera `Host: localhost:8443`, SSH de usuario fijo, permisos de
Actions, presupuesto, branch/main gate, ni alcance Docker/Porota.
El nuevo marcador es **diagnóstico de fallo**, no habilita acceso, lease,
worker, cleanup, navegación, pagos ni tickets. No se recuperará una causa
exacta de los dos runs históricos solo por fusionar este parche; hará falta
una futura observación autorizada de un nuevo SHA exacto.

**Verificación local:** casos TDD RED registrados antes de implementar:
15 FAIL por APIs/clasificaciones ausentes, 2 FAIL adicionales para
clasificación de validación y workflow. Tras corregirlos, **33 pruebas
focales PASS**, incluido `bash -n` del paso existente; suite total
**8197 PASS, 34 subtests PASS, 1 SKIP** por la restricción AF_UNIX EPERM
del sandbox (`tests/test_r177_fixture_probe_transport.py:72`). Ruff, formato,
mypy y policy pasan sobre el alcance modificado; ninguna de estas pruebas
es evidencia de la lectura física del droplet. Los dos runs históricos
permanecen fallidos y sin RCA causal definitiva.
