# Backlog y dependencias de la BETA

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. En la base verificada
`main=032de0ebb923b4f80154e93cee3dfd1b254687ed` (2026-11-02) la aplicación BETA
no está instalada. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | [41471945717](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41471945717), 12:28:47 ART: daemon loaded/inactive/dead, socket ausente, prerequisite NO_GO; SSH UID10001/bus/cgroup observados. [41473018271](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41473018271), 12:35 ART: `127.0.0.1:8443 FREE reserved=no` | Arranque protegido del daemon ya preparado, Engine>=28, capacidad funcional y aislamiento; no repetir #120. El port-check no reserva ni instala |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164, TLS #173 y RCA UUID #187 integrados | Acceder desde host/tablet con identidad privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, panel/controles #163, custodia #208, HTTP localhost #224/#226 y alta protegida #229 integrados | #209/#225: entrega privada de llave, `owner-prepare` → `owner-enroll`, UV real, forwarding, E2E y rechazo de terceros; no HTTPS/certificados/Termux |
| Persistencia de acceso | #217 exige passkey descubrible; la clave privada queda en el proveedor Android y la cookie del panel es temporal | Google Password Manager, segundo acceso y persistencia tras reinicio/reanudación del servicio; compatibilidad iOS separada, sin certificado que renovar |
| Aceptación | HTTP loopback #170, probe TLS #190 y operación protegida de aceptación/parada #200 integrados | Host/tablet/Site/Telegram y recursos/latencia reales con recibos aparte |
| Imagen/deploy | Publicación dual #239, seguridad #242, Compose #243, staging/instalación/limpieza #244–#249 integrados; CI41459830809 y scan41459831000 PASS en baseline032de0, sin publicación dual ni instalación actuales | Corrección/revisión del ciclo completo, CI y dos digests del mismo release/HEAD final; marcas BETA/BROWSER, owner, capacidad y aprobación concreta |
| Ciclo operativo | Auditoría del baseline reproduce huecos de arranque tras owner, stop/acceptance/Telegram incompatibles con browser-worker y reinicio/reanudación no servidos | Corregir y probar sin relajar identidad, topología o cleanup; revisión independiente antes de publicar/activar |
| Navegador | Runtime IPC #237 y smoke offline integrados | Validación pública autorizada con egress comprobable, sin login/cola/reserva; ninguna fixture acredita sitio real |
| Recuperación de deploy | `first-install` ya tenía limpieza selectiva #97; #219/PR #220 corrigió que el rollback BETA conservaba restos Docker/Compose descartables | Integrado tras CI y revisión; en un fallo real, mismo Actions intenta limpiar artefactos inequívocos, preserva volúmenes y verifica recibo; incierto implica NO_GO/inventario, jamás prune global ni retry ciego |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Fence/adapter, worker #188 apagado, stop-test #194, helper #199, custodia #203 y prueba única #204 | #168: bot y destino verificados, provisión y ejecución host, aceptación API/recepción humana separadas sin reintento ciego |
| Documentación | Reconciliación de baseline032de0, inspección41471945717, puerto41473018271 y entornos GitHub; históricos separados | Registrar PR/review/checks del candidato final y operaciones reales en #45, sin reutilizar checks de otro SHA |

La secuencia de host es: candidato funcional revisado y checks exactos →
aprobación concreta/release dual → preflight de recursos/aislamiento →
owner-prepare y owner-enroll con Chrome/custodia privada → instalación manual
serial por Actions → recorrido sintético en interfaz, Telegram, reinicio y
reanudación, denegación/avisos/medición. La publicación de un
Site privado y la aprobación del alcance no sustituyen esos gates. El daemon
dedicado estaba cargado pero detenido en 41471945717; no se intentó instalar
la app ni se generaron residuos de instalación. La ubicación global de una DB anterior sigue UNVERIFIED;
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
