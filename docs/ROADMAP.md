# Backlog y dependencias de la BETA

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. El baseline `032de0` es histórico; PR #254 y PR #255 se integraron después,
este último en `dada569a2d71ad4411a73ebdaca1186ed3be6936`. El candidato de
ciclo/recuperación PR #253 tiene sus propios gates. No hay BETA instalada
acreditada en esta documentación. La autorización ampliada
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
| Imagen/deploy | Publicación dual #239, seguridad #242, Compose #243, staging/instalación/limpieza #244–#249 integrados; CI 41459830809 y scan 41459831000 PASS en baseline `032de0`, sin publicación dual ni instalación actuales | Corrección/revisión del ciclo completo, CI y dos digests del mismo release/HEAD final; marcas BETA/BROWSER, owner, capacidad y aprobación concreta |
| Ciclo operativo | PR #253 contiene corrección de arranque/stop/acceptance, restart/resume, sender y recovery del run exacto | Integración/checks finales y recibos host; mantener identidad, topología, presupuesto y cleanup |
| Navegador | Runtime IPC #237; observación real 41481095746 UNKNOWN con aislamiento/cleanup PASS | Sitio completo pendiente; captura limitada de 25 GET ya aprobada, código #263/ADR0105 revisado y smoke inicial PASS; falta integración final y única ejecución pública, sin login/cola/reserva |
| Recuperación de deploy | `first-install` ya tenía limpieza selectiva #97; #219/PR #220 corrigió que el rollback BETA conservaba restos Docker/Compose descartables | Integrado tras CI y revisión; en un fallo real, mismo Actions intenta limpiar artefactos inequívocos, preserva volúmenes y verifica recibo; incierto implica NO_GO/inventario, jamás prune global ni retry ciego |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Custodia/one-shot existentes; formulario privado #255 y Chromium UI offline PASS; sender durable en #253 | Configurar y probar antes de primera simulación persistente; API/recepción humana separadas, pins y readiness ligados al SHA |
| Documentación | Baselines históricos, observación pública UNKNOWN y formulario #255 reconciliados | Terminar commits antes de release y congelar main; registrar SHA/checks/operación/cleanup en #45 sin invalidar lifecycle |

La secuencia de host es: candidato funcional revisado y checks exactos →
aprobación concreta/release dual → preflight de recursos/aislamiento →
owner-prepare y owner-enroll con Chrome/custodia privada → instalación manual
serial por Actions → aceptación temporal → Telegram con outbox vacío →
primera simulación persistente → reinicio/reanudación, denegación y medición.
Par: `1.5cpu-1024m-192pids`; ciclo con owner Telegram listo:
`1.75cpu-1152m-224pids`. Recovery exige run fallido exacto y termina detenido,
sin iniciar apps ni reenviar. Main permanece congelado durante estas fases. La publicación de un
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
afirmaciones actuales. Actualizar los documentos antes de release; durante activación, añadir
evidencia a #45 sin mover el SHA congelado.
