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
Después se integraron #261 y #266 en main
`7300c1021522a28091387a1b53c4f21dd8ad5e12`: CI 41522036069 PASS
(2166 pruebas +31 subtests, 34 RCA/114 selectores) y seguridad 41522035980 PASS.
El propietario autorizó el preflight y la captura posteriores: ambos ya se
ejecutaron y sus resultados están abajo. El candidato diagnóstico RCA #268
necesita revisión/checks/merge propios; el estado posterior se registra en #45.
No hay BETA instalada
acreditada en esta documentación. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | [Preflight 41537794166](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537794166) FAIL en control inicial, antes de efectos; motivo perdido. [Inspección 41538696464](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41538696464), 19:36:40 ART: daemon inactive/dead, socket ausente, capacidad NOT_EVALUATED | Integrar/revisar/checks de RCA #268 y diagnóstico `infrastructure-inspect` sólo lectura; establecer causa/estado antes de completar preflight. No repetir #120 ni el intento a ciegas. Último port-check 41497093298 fue instantáneo, no una reserva |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164, TLS #173 y RCA UUID #187 integrados | Acceder desde host/tablet con identidad privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, panel/controles #163, custodia #208, HTTP localhost #224/#226 y alta protegida #229 integrados | #209/#225: entrega privada de llave, `owner-prepare` → `owner-enroll`, UV real, forwarding, E2E y rechazo de terceros; no HTTPS/certificados/Termux |
| Persistencia de acceso | #217 exige passkey descubrible; la clave privada queda en el proveedor Android y la cookie del panel es temporal | Google Password Manager, segundo acceso y persistencia tras reinicio/reanudación del servicio; compatibilidad iOS separada, sin certificado que renovar |
| Aceptación | HTTP loopback #170, probe TLS #190 y operación protegida de aceptación/parada #200 integrados | Host/tablet/Site/Telegram y recursos/latencia reales con recibos aparte |
| Imagen/deploy | Publicación dual #239, seguridad #242, Compose #243, staging/instalación/limpieza #244–#249 y ciclo #253 integrados; main `7300c1` con CI/seguridad PASS | Checks del candidato RCA #268 y dos digests del mismo release final; marcas BETA/BROWSER, owner, preflight y aprobación concreta; no publicación dual actual |
| Ciclo operativo | PR #253 integrado: arranque/stop/acceptance, restart/resume, sender y recovery del run exacto | Recibos host; mantener identidad, topología, presupuesto y cleanup |
| Recursos #259 | #261 integrado, `cpu_ceiling` estructural y medición de smoke revisados. Inspección posterior: MemAvailable 1015044 KiB, `cpu_headroom=1.80` legacy no decisorio, PIDs UNKNOWN; binario dockerd 29.7.2, no Engine activo probado | Política NOT_EVALUATED; CPU 1.75/2.0, RAM 1536/1792 MiB, PIDs 256/288 y caps intactos. Inspección sólo lectura no demuestra capacidad; concurrencia de tres servicios no medida |
| Navegador | #263/#266 integrados; [captura autorizada 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470): 25 GET/200, Chromium offline UNKNOWN; script GET denegado con `same_origin=false`, query redactada, `path=null`, `path_class=external`; aislamiento/cleanup PASS | Host y función desconocidos, sin base para inferirlos; sitio completo sin aceptación. Las cinco cancelaciones posteriores no son nuevas dependencias. No nuevos GET, expansión/reintento automáticos ni diagnóstico de bloqueo de Boca |
| Recuperación de deploy | `first-install` ya tenía limpieza selectiva #97; #219/PR #220 corrigió que el rollback BETA conservaba restos Docker/Compose descartables | Integrado tras CI y revisión; en un fallo real, mismo Actions intenta limpiar artefactos inequívocos, preserva volúmenes y verifica recibo; incierto implica NO_GO/inventario, jamás prune global ni retry ciego |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Custodia/one-shot existentes; formulario privado #255 y Chromium UI offline PASS; sender durable en #253 | Configurar y probar antes de primera simulación persistente; API/recepción humana separadas, pins y readiness ligados al SHA |
| Documentación | Main `7300c1`, #261/#266 integrados y las dos pruebas autorizadas ejecutadas; fallo inicial sin efectos y render UNKNOWN separados de aceptación | Revisar candidato RCA #268 antes de inspección diagnóstica; terminar documentación antes de release y congelar main; registrar operación/cleanup en #45 |

La secuencia de host es: integrar/revisar RCA #268 y sus checks exactos →
`infrastructure-inspect` sólo lectura → establecer causa/estado y resolver
el bloqueo dentro de un alcance concreto → completar/evaluar el preflight →
aprobación concreta/release dual → preflight de imágenes/aislamiento →
owner-prepare y owner-enroll con Chrome/custodia privada → instalación manual
serial por Actions → aceptación temporal → Telegram con outbox vacío →
primera simulación persistente → reinicio/reanudación, denegación y medición.
Par: `1.5cpu-1024m-192pids`; ciclo con owner Telegram listo:
`1.75cpu-1152m-224pids`. Recovery exige run fallido exacto y termina detenido,
sin iniciar apps ni reenviar. Main permanece congelado durante estas fases. La publicación de un
Site privado y la aprobación del alcance no sustituyen esos gates. El daemon
dedicado estaba inactive/dead en 41538696464; el preflight anterior no pasó
su control inicial ni produjo efectos. No se intentó instalar
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
