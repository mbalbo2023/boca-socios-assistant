# Boca Socios: observación pública acotada

**Fecha:** 2026-10-28, America/Argentina/Buenos_Aires. **Alcance:** una
navegación anónima a la portada oficial, sin autenticación ni reserva.

La [web oficial del club](https://www.bocajuniors.com.ar/) enlaza a
`https://bocasocios.bocajuniors.com.ar/`. Al abrir esa portada en un navegador
se mostró el título «Ingresá a Boca Socios», campos etiquetados «Correo
electrónico» y «Contraseña», el botón «Iniciar sesión» deshabilitado sin datos,
y las opciones «Olvidé mi contraseña», «Quiero asociarme» y «Ya soy socio,
activar mi cuenta». No apareció una cola en esta única vista.

No se ingresaron identidades, contraseñas, cookies o tokens; no se enviaron
formularios, no se abrió un partido, no se intentó reservar y no se guardó un
HAR ni una captura en el repositorio. Esta observación **no demuestra** el
orden entre login y cola, elegibilidad, admisión, disponibilidad, sector,
confirmación de reserva ni compatibilidad con una automatización futura.

El [aviso oficial Boca–River del 25 de octubre](https://www.bocajuniors.com.ar/noticias/boca-river-informacion-para-socias-y-socios)
publica horarios diferentes según categoría de socio y operación. Los
horarios son contexto del evento, no una autorización para sondear la cola ni
prueba de que la portada anónima permita reservar.

## Próximo gate real

Un adaptador Playwright de **una sola sesión legítima** debe limitarse a la
navegación permitida por el sitio, con acceso autorizado por el titular y
límites de tiempo/solicitudes. Se detendrá ante CAPTCHA, bloqueo, fila o
estado ambiguo y requerirá intervención humana para el paso correspondiente.
La cuenta se cargará exclusivamente mediante una interfaz privada revisada;
ningún secreto irá por chat, GitHub ni Actions. Reserva o pago real requiere
decisión independiente y confirmación externa, nunca inferida de un test
sintético o de un HTTP 200.
