# ADR 0298 — R280: identidad de control según fase PARK/RESTORE/COMMIT

**Fecha:** 13-NOV-2026 (ART). **Alcance:** corrección CODE_ONLY pendiente de
revisión/promoción posterior a la recuperación del servicio antiguo.
**Fuente:** [issue #417, R277](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6861598271).

## Error reproducido

El APPLY #1085 / `43479367282` efectuó PARK y terminó NO_GO antes de
crear worker; la compensación reportó `old_restored=false` e
`INDETERMINATE`. La fuente de `PhysicalSuccessorIntegrations` leía
únicamente `/home/boca-deploy/.boca-on-demand/socket` en todas las fases.
Esa ruta no existe después de `park_binding`, que renombra íntegramente el
root a `.boca-on-demand-parked-<attempt>`. El preguard de `restore_old`
repetía exactamente el fallo. La causa no es un perfil ni una imagen.

## Contrato propuesto

| Fase del actor | Directorio e identidad exigidos |
|---|---|
| NEW, ATTESTED, STAGED | Canónico = inode histórico fijado |
| PARKED, WORKER | Estacionado por attempt = **mismo** inode histórico |
| CONTROLLER, ACCEPTED_COLD, BOUND | Estacionado = histórico; canónico nuevo = otro inode capturado estable |
| RETIRED | Canónico nuevo = inode capturado durante CONTROLLER |
| RESTORED | Canónico anterior = inode histórico original |

**Fase transitoria adicional (PARK iniciado, actor todavía `STAGED`):**
`binding_park_started` se fija antes de entrar en `park_binding()`, que
desenlaza el socket, los units y recién después renombra el root. Una
excepción intermedia conserva `backend.state=STAGED`; no es válido exigir
solo el path canónico para compensar. Antes del RESTORE se leen dos veces
**ambas rutas** del attempt bajo control; se admite exactamente una ruta
existente cuyo hash coincida con el inode histórico. Ninguna, ambas,
hash diferente, cambio entre dos lecturas o falta de un binario ajeno al
path Boca son NO_GO. La prueba de ausencia se limita a un `ENOENT` de los
componentes del path esperado: un error del Docker/runner no se interpreta
como `PARK` exitoso. La prueba del grafo Docker/IPC/SITE/EGRESS y la lease
permanecen obligatorias. Esto habilita la compensación legítima tras un
`rename` completado pero antes de actualizar `state`; no autoriza otro
APPLY ni cura automáticamente estados inciertos después de efectos.

El selector estacionado acepta únicamente el attempt numérico validado;
abre todos los ancestros con `O_PATH|O_NOFOLLOW` y conserva la función de
hash original. No se desactiva la observación doble de IPC/SITE/EGRESS,
CIDs, etiquetas, lease ni el conteo exacto del grafo. La captura del
directorio nuevo no puede inventarse saltando directamente a BOUND/RETIRED.
La compensación desde PARKED primero comprueba la identidad bajo parked;
solo después del RESTORE real vuelve a exigir el canónico original. Un
hash diferente sigue siendo NO_GO.

## Orden de operación y aceptación

1. PR de observador R278, run de custodia física exacta y recuperación
   protegida del par antiguo **antes de usar este código para APPLY**.
2. Revisar y fusionar una sola corrección de guard, pruebas de secuencia
   PARKED → WORKER → CONTROLLER → BOUND → RETIRED y fallo → RESTORED.
3. Una sola release dual del SHA definitivo y un único APPLY fresco con
   evidencia contemporánea. Ningún retry del #1085, R186 ni inventario
   por nombre ambiguo.
4. Recibos de postflight, servicio loopback, worker Created/PID0, sesión
   del titular, IPC y recursos retenidos. Sólo entonces TECHNICAL_ACCEPTED;
   la aceptación funcional personal sigue aparte.

**Regresiones:** `tests/test_r280_park_control_identity.py` y
`tests/test_host_boca_successor_physical_v2.py`, con negativos de drift,
`PARK` interrumpido, dos paths, ningún path, hash de control distinto y
runner ausente.

**Estado del ADR:** diseño probado offline, no evidencia de host recuperado
ni despliegue, `SIMULATION_ONLY`, sin tocar Porota/PPI Watch.
