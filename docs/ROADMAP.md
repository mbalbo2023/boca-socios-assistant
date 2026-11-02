# Backlog y dependencias de la BETA

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. El baseline `032de0` es histórico;
PR #254/#255, el ciclo/recuperación #253 y la captura #263 están integrados en
el corte documentado de main `6f7fa0939d28df7c315440bba15237b0c1bfbe77`, con CI
41511631024 y seguridad 41511631004 PASS. En ese corte #261 seguía sin integrar; los
[checks del corte 42eb497e…](BETA_INTEGRATION_STATUS.md) son históricos, anteriores
a su corrección CPU y al [fix argv revisado de RCA #265](ADR/0107-opaque-owner-cli-operands.md).
El SHA final necesita checks propios; el estado posterior se registra en #45.
No hay BETA instalada
acreditada en esta documentación. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | [41495516709](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41495516709), 2026-11-02 14:54:42 ART: daemon inactive/dead, socket ausente; MemAvailable 1020020 KiB, estimación CPU 0.27, PIDs UNKNOWN, capacidad NOT_EVALUATED. [41497093298](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41497093298), 15:04:45 ART: `127.0.0.1:8443 FREE reserved=no` | Integrar/revisar y autorizar preflight de infraestructura #261 antes de release; no repetir #120. El port-check no reserva ni instala |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164, TLS #173 y RCA UUID #187 integrados | Acceder desde host/tablet con identidad privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, panel/controles #163, custodia #208, HTTP localhost #224/#226 y alta protegida #229 integrados | #209/#225: entrega privada de llave, `owner-prepare` → `owner-enroll`, UV real, forwarding, E2E y rechazo de terceros; no HTTPS/certificados/Termux |
| Persistencia de acceso | #217 exige passkey descubrible; la clave privada queda en el proveedor Android y la cookie del panel es temporal | Google Password Manager, segundo acceso y persistencia tras reinicio/reanudación del servicio; compatibilidad iOS separada, sin certificado que renovar |
| Aceptación | HTTP loopback #170, probe TLS #190 y operación protegida de aceptación/parada #200 integrados | Host/tablet/Site/Telegram y recursos/latencia reales con recibos aparte |
| Imagen/deploy | Publicación dual #239, seguridad #242, Compose #243, staging/instalación/limpieza #244–#249 y ciclo #253 integrados; corte `6f7fa0` con CI/seguridad PASS | Checks del SHA final y dos digests del mismo release; marcas BETA/BROWSER, owner, preflight y aprobación concreta; no publicación dual actual |
| Ciclo operativo | PR #253 integrado: arranque/stop/acceptance, restart/resume, sender y recovery del run exacto | Recibos host; mantener identidad, topología, presupuesto y cleanup |
| Recursos #259 | #261/ADR0103 incorpora `cpu_ceiling` estructural de `user.slice` y load advisory; revisión independiente/290 pruebas focales PASS. ADR0104 mide el smoke existente | Checks del candidato final y preflight real; requisitos CPU 1.75/2.0, RAM 1536/1792 MiB, PIDs 256/288 y caps intactos; concurrencia de tres servicios no medida |
| Navegador | #263 integrado; [captura real 41512196530](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41512196530): 25 GET/200, Chromium offline UNKNOWN `resource_outside_map`, aislamiento/cleanup PASS | RCA #264: diagnóstico saneado implementado en esta versión, #266/[ADR0106](ADR/0106-sanitized-public-render-denials.md); checks exactos y nueva captura autorizada pendientes. URL histórica desconocida y sitio completo sin aceptación; no nuevos GET autorizados ni evidencia de caída externa |
| Recuperación de deploy | `first-install` ya tenía limpieza selectiva #97; #219/PR #220 corrigió que el rollback BETA conservaba restos Docker/Compose descartables | Integrado tras CI y revisión; en un fallo real, mismo Actions intenta limpiar artefactos inequívocos, preserva volúmenes y verifica recibo; incierto implica NO_GO/inventario, jamás prune global ni retry ciego |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Custodia/one-shot existentes; formulario privado #255 y Chromium UI offline PASS; sender durable en #253 | Configurar y probar antes de primera simulación persistente; API/recepción humana separadas, pins y readiness ligados al SHA |
| Documentación | Corte de main con #253/#263, implementación de esta versión y captura pública UNKNOWN separados de aceptación operativa | Revisión final antes de release y congelar main; registrar SHA/checks/operación/cleanup en #45 sin invalidar lifecycle |

La secuencia de host es: integrar/revisar candidato final y checks exactos →
autorizar/comprobar `infrastructure-preflight` de #261 y evaluar sus recibos →
aprobación concreta/release dual → preflight de imágenes/aislamiento →
owner-prepare y owner-enroll con Chrome/custodia privada → instalación manual
serial por Actions → aceptación temporal → Telegram con outbox vacío →
primera simulación persistente → reinicio/reanudación, denegación y medición.
Par: `1.5cpu-1024m-192pids`; ciclo con owner Telegram listo:
`1.75cpu-1152m-224pids`. Recovery exige run fallido exacto y termina detenido,
sin iniciar apps ni reenviar. Main permanece congelado durante estas fases. La publicación de un
Site privado y la aprobación del alcance no sustituyen esos gates. El daemon
dedicado estaba inactive/dead en 41495516709; no se intentó instalar
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
