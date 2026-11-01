# HTTP servido para aceptación sintética de la BETA

El issue #166 añade una prueba de composición por socket loopback para el
panel privado #163 y el ciclo local #164. El test arranca `wsgiref` en
`127.0.0.1` con puerto efímero, y se conecta con un cliente HTTP real. Una
envoltura **sintética de pruebas** fija `wsgi.url_scheme=https` como lo haría
un gateway confiable; el socket de la prueba no tiene TLS. La llave WebAuthn
se genera en memoria y firma una respuesta para un RP/origen reservado de
prueba. SQLite, clave y demás artefactos se crean bajo un directorio temporal,
con datos exclusivamente sintéticos. El browser port sólo devuelve un resultado
local; no existe cliente Boca en este recorrido.

| Recorrido servido | Aserción |
| --- | --- |
| Acceso y sesión | Rutas privadas denegadas antes de login; desafío y firma ES256 habilitan cookie segura; cookie del proceso anterior rechazada tras reinicio |
| Alta y consulta | Formulario y POST por HTTP, reintento de operación idempotente, listado enmascarado y una credencial persistida sin contraseña en respuesta |
| Comando y estado | Cross-origin denegado; inicio/reintento con mismo UUID, estado completado local, una intención de cantidad uno y una única llamada al simulador |
| Parada | HTTP sin sesión u origen ajeno denegados; parada válida cancela el browser sintético en curso; estado detenido y ausencia de aviso permanecen tras reinicio sin replay |
| Aviso | `/avisos` muestra el outbox persistido, sin email ni entrega Telegram inventada |
| Reinicio | Cerrar servidor/runtime, reabrir DB/clave sin migración implícita, volver a autenticar y consultar comando/aviso sin repetir browser |

`tests/test_beta_served_acceptance.py` imprime `BOCA_SYNTHETIC_HTTP` con
número de solicitudes, mediana, p95 de latencia y errores inesperados de
**esa ejecución de loopback**; las denegaciones previstas 401/403 no son
errores inesperados. No hay umbral de rendimiento que pueda presentarse como SLA.
Registrar SHA, ambiente y muestras del CI/ejecución relevante antes de usar
las cifras. El test impone timeout finito al cliente y al polling, cierra el
servidor y la hebra de comandos y no deja listeners después de completar.

Esta prueba no valida gateway/TLS real, configuración o bootstrap de passkey,
browser humano, Android/iOS/voz, Site conectado, Telegram recibido, Chromium,
recursos de droplet, despliegue ni navegación autenticada Boca. La recepción
Telegram sigue sin bot/destino privados y el Site publicado permanece offline
sin origen backend. La aceptación sobre host requiere otro recibo de Actions,
interfaz real y la parada posterior. Ver [plan BETA](../BETA_DELIVERY_PLAN.md)
y [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
