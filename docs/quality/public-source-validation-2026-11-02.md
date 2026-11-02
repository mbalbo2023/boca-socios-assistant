# Validación pública Boca Socios — 2026-11-02

**Resultado: observación del documento inicial ejecutada; sitio completo todavía no validado.**
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

La política vigente permite un único documento y mantiene JavaScript apagado
y los subrecursos bloqueados. El clasificador conservador rechaza como prueba
positiva un formulario cuyo documento contiene scripts o estilos. Las
referencias JS/CSS observadas son compatibles con ese rechazo; `unknown` no
demuestra una caída de Boca ni un fallo del navegador o del instalador.

Clasificación: **límite de validación impuesto por la política y dependencias
externas aún no verificadas**. No es evidencia de un defecto de despliegue y
no justifica reinstalar la BETA. La simulación permanece separada. No hubo
repetición, descarga adicional ni nueva modificación de código para este informe.

## Propuesta concreta pendiente de aprobación

Recomendación: una única captura ampliada, anónima y secuencial en un runner
desechable de Actions; después, render de los bytes reales capturados en
Chromium **sin salida de red**. No se propone una página inventada ni navegación
libre. Este paso permitiría comprobar el render con las dependencias conocidas;
no acreditaría por sí solo el sitio conectado completo, una sesión o reservas.

| Límite propuesto | Alcance exacto |
| --- | --- |
| Documentos | Un GET nuevo a `/auth/login`; el HTML anterior no fue conservado |
| Estáticos | Como máximo los 24 paths exactos enumerados abajo; cada uno una sola vez |
| Presupuesto público total | Hasta 25 GET; concurrencia 1; al menos 500 ms entre solicitudes |
| Destino | Solo `https://bocasocios.bocajuniors.com.ar:443`, TLS verificado y barrera de red comprobada |
| Exclusiones | Sin GET a `/` ni `/favicon.ico`; sin otros dominios, paths, queries, redirects, reintentos, POST, credenciales o cookies entrantes |
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

### Paths estáticos conocidos que delimitarían la autorización

Todos pertenecen al único origen indicado arriba. La lista es una allowlist
propuesta de referencias observadas, **no una declaración de necesidad runtime**.

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

La ampliación supera la autorización vigente de un GET. **No está ejecutada
ni implementada por este informe.** Requiere aprobación de ese alcance,
implementación revisada, CI sobre el SHA exacto y comprobación previa del
aislamiento. Ninguna parte necesita cambiar el droplet, sus puertos, servicios
o contenedores.
