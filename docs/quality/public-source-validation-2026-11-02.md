# Validación pública Boca Socios — 2026-11-02

**Estado vigente: segunda captura expresamente autorizada ejecutada; 25 GET/200, render UNKNOWN. Sitio completo todavía no validado.**

El recibo actual es
[41537796470/job125593993374](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470/job/125593993374),
sobre main `7300c1021522a28091387a1b53c4f21dd8ad5e12`, con #261/#266 integrados.
[CI 41522036069](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41522036069)
pasó 2166 pruebas +31 subtests y 34 RCA/114 selectores;
[seguridad 41522035980](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41522035980)
PASS. El propietario autorizó esta captura y el preflight de infraestructura;
ambas pruebas se ejecutaron. No se mantiene pendiente aquella autorización ni
se extiende a nuevos GET, reintentos o recursos.

| Comprobación de la nueva captura | Resultado |
| --- | --- |
| Paths públicos permitidos | 25 GET, todos HTTP 200 |
| Proxy | 25 conexiones; sin ampliación del presupuesto |
| Chromium | Arranque y `network=none` PASS; render UNKNOWN |
| Rechazo causal saneado | `method=GET`, `kind=script`, `same_origin=false`, `query_redacted=true`, `path=null`, `path_class=external` |
| Contabilidad interna | 25 solicitudes evaluadas; cinco cancelaciones posteriores al STOP |
| Aislamiento previo/posterior y limpieza selectiva | PASS |
| Host y función del script denegado | Desconocidos; no hay URL ni contenido que permitan inferirlos |

Los [recibos saneados completos](public-capture-diagnostic-2026-11-02.json)
conservan los diez eventos de esta ejecución, incluidos los 25 paths permitidos
y sus hashes; no contienen los cuerpos ni la URL redactada.

El rechazo describe una solicitud fuera del origen exacto aceptado por el
sanitizador; no revela un dominio ni identifica una función. No permite
atribuirlo a analítica, CAPTCHA, un proveedor concreto o un bloqueo de Boca.
La consulta está redactada y el path no se publica. Las cinco cancelaciones
posteriores no son cinco dependencias nuevas ni cinco GET públicos adicionales.
El renderer sin red no descargó el script denegado. Los 25 GET/200 y las
barreras PASS tampoco demuestran el sitio completo conectado.

La primera captura 41512196530, conservada más abajo, no registró su URL
denegada. El nuevo recibo no permite reconstruirla ni afirmar que ambos
rechazos correspondan al mismo recurso. No se conservan cuerpos privados para
una inspección posterior. No hay nuevos GET, expansión automática ni retry
autorizados por este informe; la siguiente decisión necesita evidencia concreta.

## Antecedente histórico: observación de un documento
Recibo saneado: [public-observation-2026-11-02.json](public-observation-2026-11-02.json).
Ejecución: [Actions 41481095746](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481095746),
SHA `b0e46dbd1cc09ae625c65799a2fb75ca052ab5d8`,
observación `2026-11-02 13:25:15 ART`.

| Comprobación | Evidencia observada |
| --- | --- |
| Documento inicial público | `state=unknown`; un `route.fetch` |
| Transporte | Un túnel TLS aceptado y una conexión upstream; no inspección del HTTP cifrado |
| Aislamiento real del runner | Probes anteriores y posteriores `PASS` |
| Limpieza del intento | `PASS` |
| Inventario saneado | 26 referencias; `inventory_truncated=false` |
| Subrecursos abortados | 7 intentos; el recibo no identifica individualmente sus URLs |
| Login, fila, reserva, compra | No ejecutados |
| Página completa con JavaScript/CSS | No verificada |

El inventario contiene 17 referencias JavaScript, una CSS, seis fuentes TTF,
`/favicon.ico` y `/`. Son **referencias presentes en el documento**, no prueba
de que todas sean necesarias ni un inventario completo de dependencias de
ejecución. No se puede asignar los siete abortos a siete URLs concretas ni
afirmar, por coincidencia numérica, que fueron la hoja CSS y las seis fuentes.

## Causa y efecto sobre el despliegue

La política de aquel modo permitía un único documento y mantenía JavaScript apagado
y los subrecursos bloqueados. El clasificador conservador rechaza como prueba
positiva un formulario cuyo documento contiene scripts o estilos. Las
referencias JS/CSS observadas son compatibles con ese rechazo; `unknown` no
demuestra una caída de Boca ni un fallo del navegador o del instalador.

Clasificación: **límite de validación impuesto por la política y dependencias
externas aún no verificadas**. No es evidencia de un defecto de despliegue y
no justifica reinstalar la BETA. La simulación permanece separada. En aquel
corte no hubo repetición ni descarga adicional; las capturas autorizadas
posteriores se registran por separado en este informe.

## Contrato histórico de la ampliación autorizada antes del primer dispatch

El propietario autorizó continuar este alcance concreto. El candidato de
[ADR 0105](../ADR/0105-bounded-public-capture-offline-render.md) implementa una
única captura ampliada, anónima y secuencial en un runner
desechable de Actions; después, render de los bytes reales capturados en
Chromium **sin salida de red**. No se propone una página inventada ni navegación
libre. Este paso permitiría comprobar el render con las dependencias conocidas;
no acreditaría por sí solo el sitio conectado completo, una sesión o reservas.

| Límite autorizado | Alcance exacto |
| --- | --- |
| Documentos | Un GET nuevo a `/auth/login`; el HTML anterior no fue conservado |
| Estáticos | Como máximo los 24 paths exactos enumerados abajo; cada uno una sola vez |
| Presupuesto público total | Hasta 25 GET; concurrencia 1; al menos 500 ms entre solicitudes |
| Destino | Solo `https://bocasocios.bocajuniors.com.ar:443`, TLS verificado y barrera de red comprobada |
| Exclusiones | Sin GET a `/` ni `/favicon.ico`; sin otros dominios, paths, queries, redirects, reintentos, POST o credenciales; no enviar `Cookie` ni conservar/reutilizar `Set-Cookie` |
| Tiempo | 8 s por solicitud y 120 s para toda la captura; el primer límite alcanzado detiene el intento |
| Tamaño | HTML ≤1 MiB; JS ≤2 MiB por archivo; CSS ≤512 KiB; fuentes ≤1 MiB por archivo; total ≤12 MiB |
| Persistencia | Bytes únicamente en almacenamiento temporal privado del runner, eliminados al terminar; sin HTML, headers, cookies, HAR ni capturas en artefactos públicos |
| Recibo público | SHA de código, timestamp, estados, contadores, paths saneados, tamaños y hashes; sin contenido del sitio |
| Render posterior | Chromium aislado, egress cero, respuestas locales de los bytes capturados en sus URLs originales; 20 s y máximo 64 solicitudes internas |

Antes de descargar los estáticos, se contrasta el inventario del nuevo HTML
con esta lista. Una referencia nueva, redirección, challenge, rechazo, cambio
de publicación incompatible o dependencia no autorizada produce STOP; no se
amplía la lista automáticamente. Los paths de la lista que ya no estén
referenciados no se descargan por inercia.
El recibo anterior eliminó query y fragmentos: no prueba que faltaran en los
atributos originales. La nueva captura debe comprobar las referencias completas;
si requieren query o no coinciden con la allowlist exacta, se detiene en vez
de descargar silenciosamente una URL diferente.

Durante el render offline se permite ejecutar únicamente los scripts ya
capturados. Cualquier XHR/fetch, WebSocket, navegación, dominio o recurso fuera
del mapa de captura queda bloqueado y detiene la validación. No se inicia
sesión, no se completa CAPTCHA ni se interactúa con filas o formularios. Una
dependencia nueva se informa de forma saneada para una decisión posterior;
no se declara GREEN porque la página esté parcialmente renderizada.

### Paths estáticos conocidos que delimitan la autorización

Todos pertenecen al único origen indicado arriba. La lista es una allowlist
de referencias observadas, **no una declaración de necesidad runtime**.

| Tipo | Path exacto |
| --- | --- |
| CSS | `/_next/static/css/110f3266bb0e84b9.css` |
| Fuente | `/_next/static/media/ed68d641ffbc51c9-s.p.ttf` |
| Fuente | `/_next/static/media/c5521e49e0ab5d76-s.p.ttf` |
| Fuente | `/_next/static/media/d5b340b61a9d747a-s.p.ttf` |
| Fuente | `/_next/static/media/542b704cac92f33f-s.p.ttf` |
| Fuente | `/_next/static/media/9079e785e8d9e991-s.p.ttf` |
| Fuente | `/_next/static/media/309b60d940dcc6d8-s.p.ttf` |
| JavaScript | `/_next/static/chunks/polyfills-42372ed130431b0a.js` |
| JavaScript | `/_next/static/chunks/webpack-ccfdb9bd91362889.js` |
| JavaScript | `/_next/static/chunks/framework-d1ea9e652f7756a8.js` |
| JavaScript | `/_next/static/chunks/main-2bcb7c5cd03d4c7a.js` |
| JavaScript | `/_next/static/chunks/pages/_app-e24083c41ff8470e.js` |
| JavaScript | `/_next/static/chunks/9819-2c4a72013c59320c.js` |
| JavaScript | `/_next/static/chunks/2739-6943ce35cb75f338.js` |
| JavaScript | `/_next/static/chunks/4860-acdc20894c93fa01.js` |
| JavaScript | `/_next/static/chunks/83-a1c7ae20bcf7e033.js` |
| JavaScript | `/_next/static/chunks/5326-c518c1546ef3384f.js` |
| JavaScript | `/_next/static/chunks/3955-5547d64248c3c4c2.js` |
| JavaScript | `/_next/static/chunks/7216-4aebbb51b60525b0.js` |
| JavaScript | `/_next/static/chunks/7243-ddb1335e09b2ad50.js` |
| JavaScript | `/_next/static/chunks/7507-47dcca8ca6668a7a.js` |
| JavaScript | `/_next/static/chunks/pages/auth/login-148f8537fd25f3f5.js` |
| JavaScript | `/_next/static/ZjtPdUbA-bZTrUy51xKDH/_buildManifest.js` |
| JavaScript | `/_next/static/ZjtPdUbA-bZTrUy51xKDH/_ssgManifest.js` |

La ampliación se autorizó para una sola ejecución con estos límites;
se ejecutó después en 41512196530, con el resultado incompleto registrado abajo.
La segunda captura 41537796470 tuvo una autorización posterior propia y mantuvo
los mismos límites. El código exige coincidencia exacta
de los 24 estáticos; una referencia ausente también produce STOP, sin
descargar las demás por inercia. Requiere revisión independiente, CI y smoke
Docker/Chromium sobre el SHA exacto antes del dispatch manual único. La
observación de DOM auténtico offline conservará `connected_site=false` y no
satisface por sí sola la carga completa del sitio conectado. Ninguna parte
necesita cambiar el droplet, sus puertos, servicios o contenedores.

## Evidencia histórica del candidato #263, sin tráfico público en sus tests

El [PR #263](https://github.com/mbalbo2023/boca-socios-assistant/pull/263),
head `9c693cb296e037af397e3ade2634f6264f717782`, pasó
[CI 41508912214](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912214)
con 1902 tests y 31 subtests, y
[seguridad 41508912267](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912267).
El [smoke real Docker/Chromium 41508912351](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41508912351),
job `125495324095`, verificó aislamiento anterior/posterior, renderer sin red,
formulario sintético creado por JS, rechazo esperado de fetch, WebSocket,
navegación y Worker, y limpieza selectiva: PASS; `public_connections=0`.

El checkout ejecutado fue el merge de prueba
`c470c530c3f93895722fe22c7168a6957ced723e`, cuyo árbol
`b3d12d0d09f224e0ba25316024dbd7a78be13cf7` coincide exactamente con el head.
La revisión independiente comprobó los 12 blobs y 134 pruebas focales, sin
P0/P1 pendientes. RCA #262 conserva los dos defectos detectados durante esa
revisión y sus regresiones. Esta evidencia corresponde a ese corte: cambios
posteriores de documentación, registro RCA o base requieren checks del nuevo
candidato. Este smoke no ejecutó la captura pública ni validó el sitio real;
la posterior ejecución autorizada y su resultado se registran a continuación.


## Primera captura pública autorizada: resultado incompleto

[Run 41512196530](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41512196530),
job `125506598762`, intento 1, ejecutó `chromium-capture-25` sobre main
`6f7fa0939d28df7c315440bba15237b0c1bfbe77`, después de
[CI 41511631024](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41511631024)
y [seguridad 41511631004](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41511631004)
PASS. El PR #263 ya está integrado. La observación comenzó el
2026-11-02 a las 16:41:50 ART y la limpieza finalizó a las 16:42:13 ART.

| Comprobación real | Resultado |
| --- | --- |
| Captura de los 25 paths autorizados | 25 GET, todos HTTP 200; 2287897 bytes de cuerpos |
| Proxy TLS | 25 túneles aceptados y 25 conexiones upstream; estado complete |
| Chromium con los bytes reales | Arranque PASS; renderer con network none PASS |
| Resultado del render | UNKNOWN, resource_outside_map, 30 solicitudes internas |
| Identidad del recurso adicional | NO REGISTRADA por el recibo actual; no inferir URL ni número exacto de dependencias faltantes |
| Aislamiento antes/después y limpieza selectiva | PASS |
| Login, credenciales, fila, reserva, droplet | No ejecutados |

[Recibos saneados completos](public-capture-observation-2026-11-02.json)
conservan paths aprobados, tamaños, hashes y estados. Los cuerpos, headers,
cookies y HTML no se guardaron en artifacts ni logs. La copia privada temporal
se eliminó. No hay evidencia de caída de Boca ni de un bloqueo anti-bot: los
25 recursos respondieron; el render se detuvo por la barrera local al intentar
una dependencia fuera del mapa permitido. El sitio sigue sin aceptación completa.

La diferencia entre 30 solicitudes internas y 25 cuerpos capturados no identifica
cinco dependencias nuevas: pueden existir repeticiones y solicitudes detenidas
tras el primer rechazo. No inventar URLs, necesidades de API o permisos desde
ese conteo. RCA #264 registra la insuficiencia diagnóstica del renderer: sólo
se imprimió el motivo, sin identidad saneada del recurso denegado.

En ese corte se propuso el diagnóstico limitado y sus regresiones, conservando
el STOP, presupuesto y allowlist. Se integró después en #266 y la segunda
ejecución recibió autorización propia, como se registra arriba. Ninguna de las
dos capturas publicó imágenes ni instaló/modificó recursos del droplet; no
amplían la lista ni habilitan una repetición automática.



## Diagnóstico integrado en #266 antes de la segunda captura

[ADR0106](../ADR/0106-sanitized-public-render-denials.md) conserva la primera causa del rechazo y separa las cancelaciones posteriores al STOP. Sólo expone enums, flags de redacción y paths públicos estrictamente reconocidos: hasta ocho entradas y 4096 bytes; nunca valores de query/fragment, credenciales, cookies, cuerpos ni paths arbitrarios. El supervisor revalida el esquema. La lista de captura, los destinos, los 25 GET, el límite de 64 respuestas internas y la prohibición de reintentos permanecen intactos.

La revisión independiente obtuvo 151 pruebas focales PASS y casos adversariales
de privacidad/contabilidad satisfactorios. El primer corte reprodujo la ausencia
del diagnóstico; otra regresión reprodujo su pérdida al contar cancelaciones
posteriores al STOP como nuevas decisiones. Las correcciones se integraron en
#266; sus recibos exactos de revisión/checks/smoke se conservan en #45 y los
checks de main `7300c1` figuran arriba. La segunda captura real comprobó la salida
saneada, manteniendo UNKNOWN. Esto no identifica retrospectivamente el recurso
de 41512196530, no valida el sitio completo ni autoriza otro GET.

## Extensión candidata de metadata, sin una nueva captura

[ADR0110](../ADR/0110-public-denied-authority-metadata.md) amplía el mismo primer
rechazo con `scheme` (`http`, `https`, `ws`, `wss` o null), `authority`
(hostname/IP canónico con puerto explícito válido, o null) y `host_kind`
(`dns_syntax`, `global_ipv4`, `global_ipv6` o `redacted`). El supervisor vuelve
a validar el esquema y mantiene ocho entradas/4096 bytes. Se omiten userinfo,
query y fragmento; el tratamiento anterior de paths seguros no cambia.

Una autoridad DNS aceptada se publica intencionalmente: `dns_syntax` no prueba
resolución pública, propiedad, ausencia de etiquetas identificadoras ni función
del script. No se consulta DNS ni se contacta esa autoridad. El código conserva
STOP, los 25 GET y paths exactos, 64 respuestas internas, proxy, red y limpieza.
Revisión y checks del SHA exacto preceden su integración.

41537796470 sigue UNKNOWN y no registró autoridad. Esta extensión no puede
recuperarla ni atribuirle una función retrospectivamente. Una nueva observación
real necesita autorización concreta y todavía no se ha realizado; el candidato
no autoriza nuevos GET, destinos ni reintentos.
