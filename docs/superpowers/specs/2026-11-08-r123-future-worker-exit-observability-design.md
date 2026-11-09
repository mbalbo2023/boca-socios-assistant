# R123 — Telemetría futura del worker sin acceso al BLACKBOX (diseño, NO IMPLEMENTADO)

Fecha: 2026-11-08 ART. Issues #417 y #45. Estado: **DISEÑO**, sin permiso
para un nuevo Cutover ni alteración de Docker.

## Problema preciso

El Cutover #878 registró `HEALTH_EXITED`, código `1` y OOM false, pero las
trazas del proceso y metadatos no proyectados desaparecieron después de la
compensación. R122 sólo aclara qué puede inferirse de ese recibo histórico;
**no agrega señales físicas**. Para diferenciar incidentes futuros de
terminación temprana, fallo de healthcheck y errores del runtime Docker,
habría que conservar evidencia limitada *antes* de la compensación.

## Única alternativa candidata: derivaciones cerradas del mismo inspect

`_browser_wait_healthy` ya solicita un `docker inspect` del CID exacto bajo
lease. **No se propone una consulta extra, un reintento ni cambiar el comando
de arranque.** De ese mismo objeto, sin publicar valores originales, evaluar:

| Evidencia propuesta | Valores permitidos | Interpretación máxima |
| --- | --- | --- |
| Error reportado por Engine | `EMPTY`, `PRESENT_UNCLASSIFIED`, `UNKNOWN` | Presencia de metadato de error, no su texto ni causalidad |
| Estado del contenedor | `EXITED`, `DEAD`, `OTHER`, `UNKNOWN` | Estado observado una vez |
| Duración StartedAt→FinishedAt | `EARLY_LT_5S`, `LATE_GE_5S`, `UNKNOWN` | Ventana temporal aproximada, no fuente del error |
| Progreso de healthcheck | `NOT_RUN`, `RAN`, `UNKNOWN` | Si Docker informó checks; no analizar su resultado textual |

No registrar `State.Error` como cadena, timestamps, `Health.Log.Output`,
stdout/stderr, args del proceso, entorno, mounts, tokens, cookies, rutas
del host ni stacktrace. No inspeccionar o ejecutar los dos módulos
`synthetic.py` e `ipc_worker.py`. Un valor ausente/contradictorio es
`UNKNOWN`; la salida `ExitCode`/OOM existentes no se pierde. **Aun con esta
telemetría, la excepción de Python podría seguir siendo UNKNOWN**.

## Contrato y costo a revisar antes de implementar

1. Probar primero que cada campo añade una distinción causalmente útil en
   fixtures sintéticos (no navegación ni Docker físico).
2. Diseñar **terminal V4 explícito** y consumidores strict en CLI host,
   runner, reconciler y pruebas, preservando recibos v1/v2/v3 *byte exactos*.
3. Medir fuente/bundle allowlisted: el techo R119 es 880000 bytes de fuente
   con ~2876 bytes libres, más ZIP comprimido máximo 512000. No elevar límites
   sin evidencia y revisión del productor y bootstrap.
4. Probar input ausente, tipo incorrecto, dobles claves, fusión de líneas,
   canary privado, fases incompatibles, timestamps inválidos/crossed, `-O`,
   compensación fallida y no filtración de texto sensible en cada capa.
5. Revisión unánime Arquitectura, IPC externo, DevOps y QA, PR pequeño,
   suites completa/seguridad exact-SHA y nueva decisión independiente antes
   de cualquier ejecución protegida. No alterar el BLACKBOX ni la imagen
   forense R108.

## Descartes y estado

- Volcar `docker logs`, stderr SSH o `State.Error` libre puede filtrar
  credenciales y trazar el código reservado al propietario: **NO_GO**.
- Repetir Cutover #878 o lanzar un worker para recrear la excepción:
  **NO_GO** (incidente compensado, no-retry; sin autorización física nueva).
- Inferir `ModuleNotFoundError`, permisos/IPC/seccomp u OOM por ExitCode=1:
  **NO DEMOSTRADO**.

R123 no es parte del código R122; su valor debe justificarse frente al
costo de alterar el esquema antes de comprometer implementación.
