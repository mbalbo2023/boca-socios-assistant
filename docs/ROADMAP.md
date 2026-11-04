# Backlog y dependencias de la BETA

## Prioridades operativas — 04/11/2026, posterior al primer deploy

`main=cabce9f1e452e63ded115f447559a358dc0f4d1b`:
[release #41893887078](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41893887078),
[install #41896871289](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41896871289),
[aceptación #41897278258](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897278258)
y [start #41897569928](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41897569928)
GREEN. El último observó controller `RUNNING` localhost:8443 con motor
apagado. El acceso Android y BETA integral siguen sin aceptación real.

1. Verificar Samsung Chrome + Termius (`/ingresar`), passkey/cookie y panel;
   evitar repetir PIN y no solicitar secretos en chat.
2. Diagnosticar e implementar transición controller instalado → navegador
   opcional sin reejecutar `beta-browser-install` new-only ni perder datos,
   y probar recursos combinados [#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).
   La navegación BLACKBOX queda bajo control del propietario.
3. Reconciliar formulario privado/alta/SQLite cifrada, durabilidad,
   idempotencia y avisos en pruebas integrales. [#285](https://github.com/mbalbo2023/boca-socios-assistant/issues/285)
   y [draft #287](https://github.com/mbalbo2023/boca-socios-assistant/pull/287)
   no están desplegados.
4. Habilitar custodia/identidad Telegram por vía protegida y obtener recibos
   API y recepción humana sin publicar tokens.
5. Validar conjunto, recuperación, recursos reales y experiencia por voz;
   registrar cada cierre en [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6640165355)
   (Regla 84). Nunca navegar ni reservar en Boca por agentes.

## Historial de bloqueo rootless — 04/11/2026 (superado para controller)

**Actualización 04/11/2026 (Regla 84, RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)):** El [run protegido #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848) verificó `module=absent`, `nf_call_iptables=unavailable`, `index=listed`, `modules_disabled=0`, `write_ops=none` en `main=41fc15e261d002dc614124ac0f2d2e1bea81f896`; fue una **lectura exitosa**, no un deploy.

El propietario ordenó flexibilizar el obstáculo y llegar a BETA. [PR #304](https://github.com/mbalbo2023/boca-socios-assistant/pull/304) / [ADR0128](ADR/0128-boca-only-owner-enroll-icc-compat.md) implementan el cambio **solo en la red temporal de `owner-enroll`**: `ICC=true`, UID rootless Boca, cero masquerade, exactamente un peer autorizado, host loopback `127.0.0.1:8443`; limpieza positiva con opciones concordantes. El `network-probe` histórico ICC=false y la variante diferencial ICC=true siguen separados; **no** se cargan módulos ni se modifica kernel/firewall global, Porota u otros servicios. Riesgo residual: menor aislamiento entre potenciales contenedores de esa única red; ningún segundo contenedor está autorizado.

**Estado físico vigente: BETA NO instalada.** PR/CI, release dual exacto, alta Chrome real, `beta-install`, aceptación, recursos y Telegram todavía requieren evidencia. Además [issue #305](https://github.com/mbalbo2023/boca-socios-assistant/issues/305) rastrea arranque del daemon antes de instalación y reanudación controller-only después de aceptación. Nunca reutilizar `beta-install` para reanudar, ni activar el navegador BLACKBOX desde agente. Los apartados anteriores del 03/11 abajo son **cortes históricos**, no la instrucción operativa actual.


## Corte vigente rootless — 2026-11-03 ART

PRs #289, #290, #296 y #298 ya fueron integrados, último `main`
`a83e105d4ccec2cc59dfabce77142750de733630`. El
[diagnóstico protegido #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589)
fue GREEN como **lectura** y encontró `module=absent`,
`nf_call_iptables=unavailable`, `write_ops=none`. El alta privada real
`ICC=false` [#41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453)
permanece NO_GO, aun cuando la red diagnóstica `ICC=true` sí pasó.
**No hay BETA instalada**. Siguiente candidato únicamente de lectura:
[ADR0126](ADR/0126-readonly-kernel-module-availability.md); obtener recibo
de disponibilidad de módulo con SHA/CI de nuevo PR antes de decidir una
intervención global, rediseño de aislamiento o host exclusivo. La carga de
módulos y el debilitamiento de ICC=false **no están aprobados**. Después de
resolver este bloque, completar `owner-prepare`/`owner-enroll`, release
inmutable, `beta-install`, aceptación, acceso por túnel a 8443 y Telegram,
con cada gate y prueba física en el [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
Los apartados siguientes son cortes anteriores, no estado actual de main.

## Decisión vigente sobre recursos (2026-11-02, candidato #273)

El dueño corrigió expresamente la condición anterior: la BETA debe
**desplegarse de forma aislada y medirse después de su instalación**, no
bloquearse por márgenes preventivos de CPU/RAM/PIDs que nunca se calibraron
con el runtime real. [Issue #259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
y [ADR0112](ADR/0112-postdeploy-resource-observation.md) contienen el
razonamiento y los límites. El PR #273 sigue **candidato, no integrado**:
ningún documento atribuye esta conducta a main hasta merge y checks.
Permanecen obligatorios SHA/digests, identidad rootless, seguridad,
aislamiento, puerto único 8443, espacio seguro para Docker y limpieza
selectiva ante fallo; los caps del contenedor no son una medida de uso real.
El run #290 falló en observación; la restauración detenida pasó. La BETA
aún no fue instalada y la captura pública continúa bloqueada.

La reiteración del dueño está registrada, pero la revisión automática volvió a bloquear el dispatch antes de ejecutarlo; no existe un nuevo run. Véase el [bloqueo actualizado](https://github.com/mbalbo2023/boca-socios-assistant/issues/27#issuecomment-6591174050). La captura sigue pendiente por ese control de plataforma.

El [plan de entrega](BETA_DELIVERY_PLAN.md) define aceptación; el
[estado](BETA_INTEGRATION_STATUS.md) y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
separan código, comprobaciones y ejecución host. El baseline `032de0` es histórico;
PR #254/#255, el ciclo/recuperación #253 y la captura #263 están integrados en
el corte documentado de main `6f7fa0939d28df7c315440bba15237b0c1bfbe77`, con CI
41511631024 y seguridad 41511631004 PASS. En ese corte #261 seguía sin integrar; los
[checks del corte 42eb497e…](BETA_INTEGRATION_STATUS.md) son históricos, anteriores
a su corrección CPU y al [fix argv revisado de RCA #265](ADR/0107-opaque-owner-cli-operands.md).
El corte actual main `fe70271f940dbc6fc1f422907f5e7254eb2ae508` integra también
#261/#266/#269/#270: CI postmerge 41544296010 y seguridad 41544295980 PASS.
Los cinco checks del candidato #270 pasaron, con 2283 pruebas +31 subtests
y 35 RCA/119 selectores. El preflight, la captura y la inspección diagnóstica
autorizados ya se ejecutaron; sus resultados están abajo. RCA #268 está
integrado por #269. RCA #271 corrige la lectura que rechazó aquella inspección
y requiere revisión/checks propios; el
[checkpoint vigente](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6590928836)
registra los pasos posteriores.
No hay BETA instalada
acreditada en esta documentación. La autorización ampliada
[#45/6552258326](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
incluye Site conectado, Telegram y deploy validado por Actions, con datos
sintéticos y sin reserva/compra real. No convierte un PR o una demo en
funcionalidad operativa.

El siguiente cuadro se conserva como **historial del corte anterior a
PR #272**. El actual main `ea753ccab29d112b374a07b167d92e68c714cddd`
incorporó #272 con CI/seguridad PASS; la inspección #289 pasó y el preflight
#290 falló en observación, con parada exitosa. Su RCA específico es #274.
La corrección del veto preventivo está en **PR #273 candidato**. Las reservas
CPU/RAM/PIDs antiguas de la fila #259 dejan de ser condiciones de entrada
cuando la corrección pase sus checks y se integre. Continuar sin duplicar
preparación rootless ni repetir el run fallido; medir después del despliegue.

## Secuencia con gates verificables

| Frente | Entregado al corte | Próximo gate y responsable |
| --- | --- | --- |
| Host dedicado | #269 integrado; [infrastructure-inspect 41542349197](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41542349197/job/125609403017), 20:03 ART: NO_GO, `effective_preflight_unit_unverified`, transporte confirmado, sin arranque. Preflight anterior 41537794166 falló antes de efectos y perdió su motivo | Revisar/integrar/comprobar la corrección #271 y nueva inspección sólo lectura; establecer causa/estado antes de completar preflight. No repetir #120 ni el intento a ciegas. Último port-check 41497093298 fue instantáneo, no una reserva |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164, TLS #173 y RCA UUID #187 integrados | Acceder desde host/tablet con identidad privada, sin activar Boca real |
| Panel/alta | Servicio cifrado #31, panel/controles #163, custodia #208, HTTP localhost #224/#226 y alta protegida #229 integrados | #209/#225: entrega privada de llave, `owner-prepare` → `owner-enroll`, UV real, forwarding, E2E y rechazo de terceros; no HTTPS/certificados/Termux |
| Persistencia de acceso | #217 exige passkey descubrible; la clave privada queda en el proveedor Android y la cookie del panel es temporal | Google Password Manager, segundo acceso y persistencia tras reinicio/reanudación del servicio; compatibilidad iOS separada, sin certificado que renovar |
| Aceptación | HTTP loopback #170, probe TLS #190 y operación protegida de aceptación/parada #200 integrados | Host/tablet/Site/Telegram y recursos/latencia reales con recibos aparte |
| Imagen/deploy | Publicación dual #239, seguridad #242, Compose #243, staging/instalación/limpieza #244–#249 y ciclo #253 integrados; main `fe70271` con CI/seguridad PASS | Checks del candidato RCA #271 y dos digests del mismo release final; marcas BETA/BROWSER, owner, preflight y aprobación concreta; no publicación dual actual |
| Ciclo operativo | PR #253 integrado: arranque/stop/acceptance, restart/resume, sender y recovery del run exacto | Recibos host; mantener identidad, topología, presupuesto y cleanup |
| Recursos #259 | #261 integrado, `cpu_ceiling` estructural y medición de smoke revisados. Inspección posterior: MemAvailable 1015044 KiB, `cpu_headroom=1.80` legacy no decisorio, PIDs UNKNOWN; binario dockerd 29.7.2, no Engine activo probado | Política NOT_EVALUATED; CPU 1.75/2.0, RAM 1536/1792 MiB, PIDs 256/288 y caps intactos. Inspección sólo lectura no demuestra capacidad; concurrencia de tres servicios no medida |
| Navegador | #263/#266/#270 integrados; [captura autorizada 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470): 25 GET/200, Chromium offline UNKNOWN; script GET denegado con `same_origin=false`, query redactada, `path=null`, `path_class=external`; aislamiento/cleanup PASS | Continuación del mismo diagnóstico de 25 GET reafirmada por el dueño, sin nuevo recibo aún. Host/función desconocidos y sitio sin aceptación. Las cinco cancelaciones no son dependencias nuevas. Sin expansión/reintento automáticos ni diagnóstico de bloqueo de Boca |
| Recuperación de deploy | `first-install` ya tenía limpieza selectiva #97; #219/PR #220 corrigió que el rollback BETA conservaba restos Docker/Compose descartables | Integrado tras CI y revisión; en un fallo real, mismo Actions intenta limpiar artefactos inequívocos, preserva volúmenes y verifica recibo; incierto implica NO_GO/inventario, jamás prune global ni retry ciego |
| Site #113 | Demo privada v10 D1 desactivada; helper #178, cliente #179, custodia #181 y RCA inventario #196 | Ya no bloquea la BETA del panel local. Mantener privado/offline; baja posterior a validar el reemplazo, sin fecha ni activación inferida |
| Telegram #162 | Custodia/one-shot existentes; formulario privado #255 y Chromium UI offline PASS; sender durable en #253 | Configurar y probar antes de primera simulación persistente; API/recepción humana separadas, pins y readiness ligados al SHA |
| Documentación | Main `fe70271`, #269/#270 integrados, inspección diagnóstica ejecutada con rechazo verificable; render sigue UNKNOWN | Revisar candidato RCA #271 y completar sus checks; terminar documentación antes de release y congelar main; registrar cada paso/operación/cleanup en #45 |

La secuencia de host es: revisar/integrar la corrección RCA #271 y sus checks exactos →
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
dedicado estaba inactive/dead en 41538696464; la inspección 41542349197
rechazó la lectura de la unidad sin arrancarlo. La reproducción oficial de
#271 prueba un defecto compatible del parser, sin determinar los campos
omitidos del host. El preflight anterior no pasó su control inicial ni produjo efectos. No se intentó instalar
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
