# ADR 0237 — R187: POST privado compatible con navegadores móviles

**Estado:** cambio de código candidato, sin despliegue ni aceptación física.
**Alcance:** exclusivamente la respuesta HTTP del panel privado 8443 y su
regresión. No se toca Docker, IPC, `SITE_URL`, la persistencia, el navegador
legacy, los flujos de tokens ni aplicaciones externas.

## RCA y decisión

El titular confirmó `Origen no autorizado` al guardar `SITE_URL`; antes había
observado el mismo texto al iniciar el bot. El guard de
`src/boca_socios/panel/private_http.py` compara el encabezado `Origin` con el
origen configurado y rechaza el POST antes de escribir o encolar una orden.
La misma aplicación emitía `Referrer-Policy: no-referrer` en las páginas con
formularios HTML nativos. Según el comportamiento documentado para `navigate`
POST en el estándar Fetch, esta política puede convertir `Origin` en `null`
incluso desde el propio origen. Es una incompatibilidad real entre la política
de respuesta y el requisito del controlador; **no se capturó el encabezado
efectivo del dispositivo del titular**, de modo que la causalidad física se
verificará después del despliegue.

Se evaluaron: desactivar el guard Origin (rechazado: pierde el control de
origen), reescribir cada formulario como `fetch` (rechazado: duplica lógica y
dificulta accesibilidad) y ajustar sólo la respuesta privada a
`Referrer-Policy: same-origin` (**seleccionado por el titular** al aprobar
relajar la política). Esto permite conservar una señal Origin real en POST
nativos sin enviar el encabezado Referer a otros sitios. Los GET de
configuración/emparejamiento Telegram que no emplean formularios HTML nativos
conservan su política `no-referrer` explícita.

Las comprobaciones de sesión passkey, `Origin` exacto, host/esquema, CSRF,
permisos y operación de un solo uso permanecen sin cambios. Las URL con
`queueittoken` no se validan ni visitan y las reservas siguen en simulación.

## Verificación y aceptación pendiente

Se añadió un caso de regresión sobre las respuestas GET `/`, `/control` y
`/configuracion`: tres fallos RED con `no-referrer`; el cambio candidato los
lleva a GREEN sin eliminar los tests de rechazo de POST forjados. Las páginas
de Telegram siguen exigiendo `no-referrer`. Registrar resultados completos de
CI y SHA del PR antes de promoverlo; el test de navegador local con Chromium
no pudo abrir su socket (`EPERM` en el sandbox), por lo que no constituye
evidencia de un navegador real.

**Aceptación física futura:** en Chrome del titular, guardar una URL sintáctica
de ensayo, observar `303 → /configuracion` y que el valor se conserva, y
probar START/STOP manual con captura protegida del worker. Un `303` certifica
sólo el formulario; no prueba navegación, Queue-it ni obtención de tokens.
