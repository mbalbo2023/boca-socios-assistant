# ADR 0118 — Chrome real del droplet, prueba pública acotada sin credenciales

**Fecha:** 2026-11-03 ART. **Issue:** #283. **Estado:** candidato a revisión.

## Evidencia y motivación

- PR #282 integrado en main `4f9718ddb7477ec346d31da7f85c086ee669cc64`.
- [Run protegido #347](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41655307167) confirma `BOCA_HOST_CHROME state=PRESENT kind=google-chrome-stable uid=10001`.
- [Run #345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41653887958) de ICC=true: NO_GO `unclassified`, limpieza VERIFIED y daemon STOPPED. Docker BETA sigue bloqueado.
- El login cloud de Fernando no alcanzó sesión autenticada pese a credenciales confirmadas por el usuario; no existe evidencia de reserva o cola.

## Decisión acotada

Nueva operación `chrome-host-public-smoke` en el **mismo** workflow manual protegido: ejecutar por SSH como UID 10001 el Chrome Stable **ya instalado** una sola vez, con perfil efímero y sandbox del navegador habilitado, contra la URL fija HTTPS `https://bocasocios.bocajuniors.com.ar/auth/login`. Sólo carga GET en navegador headless, con timeout y cierre del grupo de procesos. Clasifica localmente formulario password visible, otro documento, challenge o fallo; no imprime DOM ni stderr, ni ingresa usuario/contraseña, ni cookies, ni acciona cola/reserva/compra. Verifica y elimina el perfil temporal incluso ante fallo. No usa Docker, instala software, publica puertos, altera kernel/red/otras apps, ni desprotege workflow.

Si hay CAPTCHA o verificación humana, **detener** y reportar CHALLENGE, jamás sortearla. Esta prueba no valida autenticación de Fernando ni BETA operativa; exige un flujo posterior de credenciales privadas y autorización del usuario final, sin GitHub logs o secret inputs manuales.

## Gate de calidad

Test unitario que confirma URL fija, ausencia de bypass de sandbox/TLS/WAF y perfil efímero, validación de SHA/UID, salida allowlisted y workflow. CI, análisis de imagen, smoke sintético, review SHA, merge, CI postmerge, único dispatch y recibo real. Falla = NO_GO, sin reintentos ciegos.
