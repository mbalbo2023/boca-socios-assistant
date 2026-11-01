# Backlog y dependencias de la BETA

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. Al corte previo a esta
actualización documental `main=6d3007a3ca1dfdba428cb7595486b1166a1d02b6` la aplicación BETA
no está instalada. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | Rootless preparado #120; preflight #124 PASS sólo para controlador dormido; `stop-test` [41282301501](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) ALREADY_STOPPED, `containers=not_queried`, datos preservados. `port-check` #211 [41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281) observó `127.0.0.1:8443` FREE `reserved=no`, sin arrancar Boca | Root: ruta tablet y custodia física, luego capacidad funcional, release exacta, operación manual, postflight y parada; no repetir #120 |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164, TLS #173 y RCA UUID #187 integrados | Acceder desde host/tablet con identidad privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, adaptadores #128/#148, owner passkey/controles #163, registro #174, preflight #189 y custodia cifrada #208 integrados en código; #213 propone `https://localhost:8443` y #215 un emisor local de un solo uso, sin inscripción física | #209: confianza TLS Android, UV real, entrega privada del sobre, forwarding, mismo credential en iOS, E2E y rechazo real de terceros |
| Aceptación | HTTP loopback #170, probe TLS #190 y operación protegida de aceptación/parada #200 integrados | Host/tablet/Site/Telegram y recursos/latencia reales con recibos aparte |
| Imagen/deploy | `compose.beta.yaml` #171, `beta-install` #191, release protegido [41301618285](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41301618285) con digest/manifiesto para integración #208; sin instalación | Release coincidente con la HEAD que se vaya a instalar, marca BETA, archivos privados, capacidad y dispatch exacto; no despachar candidato no apto |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Fence/adapter, worker #188 apagado, stop-test #194, helper #199, custodia #203 y prueba única #204 | #168: bot y destino verificados, provisión y ejecución host, aceptación API/recepción humana separadas sin reintento ciego |
| Documentación | #205/#206 integraron los cortes previos; esta reconciliación registra #208 y release 41301618285, sin host | Mantener #45 y los documentos al día con cada SHA/run; revisar antes de merge según regla 84 |

La secuencia de host es: candidato funcional revisado y checks exactos →
provisión privada sin secretos en repo/logs → release por digest/manifiesto →
preflight de recursos/aislamiento del mismo candidato → instalación manual
serial por Actions → recorrido sintético en interfaz, persistencia/reinicio,
denegación/avisos/medición → parada verificable de Boca. La publicación de un
Site privado y la aprobación del alcance no sustituyen esos gates. El daemon
dedicado estaba ALREADY_STOPPED en 41282301501, con enablement preservado; la app
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
