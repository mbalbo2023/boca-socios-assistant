# Backlog y dependencias de la BETA

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. Al corte
`main=9e923af56e76a04069bfad6f8ca9c68db0edd890` la aplicación BETA
no está instalada. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | Rootless preparado #120; preflight read-only #124 PASS sólo para controlador dormido; `stop-test` #156/41272785626 STOPPED, `containers=0` detenidos en ese run | Root: capacidad funcional, operación manual, postflight y nueva parada después de pruebas futuras; no repetir #120 |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo local #164 y entrypoint TLS explícito #173 integrados | Empaquetar/acceder en host con configuración privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, adaptadores #128/#148, owner passkey/controles #163 y prueba de registro #174 integrados | Origen TLS accesible, inscripción física del dueño, E2E servido/tablet y rechazo real de terceros |
| Aceptación | Composición en proceso #152 y HTTP loopback desechable #170 integrados | TLS/tablet/host, recursos y latencia reales con recibos aparte |
| Imagen/deploy | `compose.beta.yaml` #171 y smoke TLS/aislamiento desechable integrados; `first-install` actual sólo dormido | Release protegido/digest, capacidad y operación `beta-install` separada con acceso privado; no despachar un candidato no apto |
| Site #113 | Demo privada v10 con D1 desactivado; helper #178, cliente #179 y custodia Actions #181 integrados | Release, bypass+HMAC host, flag y E2E; hoy offline |
| Telegram #162 | Fence durable opt-in, transporte y proyección local; RCA #176 corrige estado con schema0007 | #168: bot y destino verificados, custodia, worker y prueba de recepción sin reintento ciego |
| Documentación | ADR de cada cambio y checkpoint #45; #154 candidato revisado en PR #180 | Integrar revisión de README/plan/status/roadmap y recibos según regla 84 |

La secuencia de host es: candidato funcional revisado y checks exactos →
provisión privada sin secretos en repo/logs → release por digest/manifiesto →
preflight de recursos/aislamiento del mismo candidato → instalación manual
serial por Actions → recorrido sintético en interfaz, persistencia/reinicio,
denegación/avisos/medición → parada verificable de Boca. La publicación de un
Site privado y la aprobación del alcance no sustituyen esos gates. El daemon
dedicado quedó detenido en #156/41272785626, con enablement preservado; la app
no existe en el host al corte. La ubicación global de una DB anterior sigue UNVERIFIED;
no migrar ni reemplazar una DB por inferencia.

## Alcance de interfaz y diferidos

La [matriz completa del plan](BETA_DELIVERY_PLAN.md#matriz-completa-de-alcance-ui-panel-propio-y-site-complementario)
conserva alta/consulta y ciclo de credenciales, eventos/categorías/horarios,
simulación, sesiones, avisos, diagnóstico, trazabilidad, operación y elementos
diferidos. Un control queda operativo sólo con ruta, identidad/permiso,
servicio conectado y recibo del entorno. Se debe mostrar motivo claro para
funciones aún no habilitadas, sin botones con efectos falsos. Accesibilidad de
tablet/voz, foco, etiquetas y blancos táctiles requiere validación real, no
sólo pruebas HTML.

Observación de Boca en la sesión de navegador interno llegó de forma
**sólo lectura** a home, partidos y detalle; no acredita login automatizado,
cola, elegibilidad ni reserva. No almacenar capturas o identificadores
personales públicos. El flujo real, intervención humana en eventual reserva,
modalidades no definidas y consentimiento/custodia real conservan sus propias
decisiones. El simulador FIFO/lotería y aliases locales no describen Queue-it.

## Requisitos anteriores aún abiertos

- Horarios de eventos en America/Argentina/Buenos_Aires e ingesta de avisos
  oficiales con procedencia de cada fuente; modelos de identidad/evento/
  categoría coherentes con una entrada por socio/evento.
- BrowserContext aislado por sesión aprobada, límite configurable y medición
  de recursos/egress; varias sesiones no prueban posiciones independientes
  en Queue-it ni autorizan concurrencia real.
- Trazas redactadas y objetivos medibles de visibilidad/latencia; no hay SLA
  operativo demostrado por CI. Retry, backpressure y diagnóstico observer-only
  necesitan aceptación de integración y fallos.
- Fuente pública como semáforo asesor con procedencia/hora. Su fallo por sí
  solo no habilita o bloquea el deploy seguro; defectos de código, seguridad,
  imagen, recursos e identidad sí conservan gates.
- PR históricos #77/#83/#87 y documentos #75/#67/#15: reconciliar aportes
  puntuales contra `main`, sin fusionar árboles antiguos ni inferir que un
  issue abierto prueba un componente ausente.

## Recuperación diferida

Backup/restore operativo sigue diferido hasta una versión productiva fiable.
#47 es biblioteca offline; #40 integró recifrado dormido y migración 0004
opt-in, sin rotación real ni protección DELETE/coordinación de escritores
demostradas. Esto no bloquea la BETA sintética ni permite alta real. No hacer
backups ahora. Porota y PPI Watch permanecen fuera de alcance.

El [backlog histórico anterior](https://github.com/mbalbo2023/boca-socios-assistant/blob/1441d55a632d4a545b21ee7f6f2b0a4140ab2320/docs/ROADMAP.md)
conserva el detalle de cortes previos, pero sus frases de estado no son
afirmaciones actuales. Actualizar este archivo y #45 al cambiar evidencia.
