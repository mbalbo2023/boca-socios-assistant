# ADR 0096: Chromium real con fixtures de login público, estrictamente offline

**Estado:** candidato de código/pruebas en [PR #240](https://github.com/mbalbo2023/boca-socios-assistant/pull/240),
publicado inicialmente sobre `main=46f184fc49747f98246ac82047d9786b65239168`.
La ejecución del smoke en GitHub Actions y su SHA definitivo quedan pendientes
de revisión y CI sobre ese mismo SHA. **No se ejecutó una visita pública**
como parte de esta decisión. El droplet y sus puertos, contenedores y claves
quedan fuera de alcance.

## Motivo y corrección de una aceptación engañosa

El modo manual de [ADR0014](0014-public-home-observer.md) exige un GET exacto
anónimo a `/auth/login`, con JavaScript apagado y assets abortados. El predicado
inicial podía aceptar como `login_form_disabled` controles HTML presentes y
aparentemente visibles **porque faltaba el CSS externo que los ocultaría**.
También podía aceptar un formulario cuya hidratación mediante script cambiaría
su estado, o controles cuyo contenedor tenía `aria-hidden=true`. Otra carrera
semántica de [RCA #238](https://github.com/mbalbo2023/boca-socios-assistant/issues/238)
fue un atributo inline `onload` o cualquier otro `on*`, sin etiqueta `script`,
capaz de cambiar el DOM al permitir JavaScript. Las regresiones locales se
introdujeron primero y fallaron contra el predicado anterior.

El modo estructural se vuelve deliberadamente más conservador: si el documento
contiene `script`, hoja externa `link[rel~=stylesheet]` o `style`, o si el
formulario queda bajo `aria-hidden=true`/`inert`, la observación es `unknown`.
Un probe acotado de solo lectura detecta **genéricamente nombres** de atributos
`on*` en el DOM ligero y raíces shadow abiertas; devuelve solo un booleano,
sin leer valores ni ejecutar handlers, y también produce `unknown`. El probe
lo envía Playwright, con JavaScript de la página deshabilitado. Si Chromium
no puede evaluar ese booleano, la prueba falla cerrada: nunca se relaja la
comprobación ni se marca positivo con un resultado no verificado.
Si el navegador intentó solicitar cualquier asset que la ruta de un solo GET
abortó, también es `unknown`, aunque los campos iniciales den `is_visible`.
Solo un HTML autocontenido, con exactamente un formulario, email/contraseña
visibles y submit inicialmente deshabilitado, puede producir
`login_form_disabled`. No se cambia el modo textual original ni se amplía la
red, los argumentos de CLI, el origen o el número permitido de GET.

Esto no demuestra visibilidad efectiva ante superposiciones, accesibilidad,
comportamiento de CSS remoto, ejecución de JavaScript, estado de una sesión,
login ni capacidades de reserva. El resultado significa **forma semántica de
HTML inicial sin dependencias externas observadas**, no compatibilidad con
Next.js hidratado. Un shell CSR o un portal real con scripts/estilos se detiene
como `unknown` y jamás se transforma en verde por asumir que Chrome cloud
mostró un formulario en otra sesión.

## Evidencia sintética sin salir a Internet

El nuevo `scripts/run_public_observer_offline_chromium.py` no navega a ningún
URL: ejecuta `page.set_content()` con once fragmentos **inventados**, sin
datos Boca o credenciales. Usa Chromium real con JavaScript deshabilitado,
service workers y downloads bloqueados, sandbox y una ruta que aborta toda
solicitud de subrecurso. El selector de aceptación es el mismo que el del
observador opt-in; no se implementa un segundo clasificador de producción.

Las once expectativas son: SSR simple con submit deshabilitado (positivo
estructural), CSR sin form, hoja CSS externa abortada, script de hidratación
que hipotéticamente habilitaría el submit, dos atributos `on*` inline
(`onload` que habilitaría submit y `onpointerdown` no enumerado en un denylist),
CSS inline no comprobable,
challenge visible, submit habilitado, formulario oculto y ancestro
`aria-hidden=true` (negativos o `challenge`). El runner exige UID/GID 10002 y
solamente interfaz `lo`; un único recibo contiene solo estado `PASS`, modo,
cantidad de casos y número de requests de página abortados. No escribe HTML,
HAR, screenshots, valores de campos, URL ni texto del navegador.

El job existente **CI / image-build** construye la imagen browser de origen
fijo y monta únicamente el script de fixtures como archivo de solo lectura,
ejecutándolo en un contenedor desechable `--network none` con seccomp, usuario
10002, `no-new-privileges`, capacidades recortadas, root filesystem de solo
lectura, límite 1 CPU/768 MiB/128 procesos y cierre acotado. Su paso
`if: always()` verifica y limpia solo los dos contenedores con nombres
deterministas del mismo runner y las imágenes con tags de ese SHA; ningún
comando aborda Docker de un host remoto. Los tests de calidad sin Chromium
comprueban permisos/gates/fixtures/recibo y el contrato estático del YAML;
la ejecución genuina del navegador pertenece solo al job de imagen.

## Gate para actividad pública posterior

La URL real no se visita en este PR ni se incorpora al CI/PR automático.
`.github/workflows/boca-source-status.yml` permanece intacto: hoy ya tiene
un GET público manual vía `check_public_source.py`, sin Chromium. Sumar otro
GET sería contrario al máximo de uno por ejecución, y un runner
`ubuntu-24.04` normal no prueba egress OS por **dominio FQDN**. Playwright
`context.route()` y reglas solo por IP/CDN no sustituyen esa barrera. Una
eventual propuesta distinta precisa aprobación expresa, modos mutuamente
excluyentes, política de red real verificable, sandbox comprobado y hard stop
antes de cualquier tráfico. Sin ese gate: **NO-GO para un Chromium público**.

El scope sigue siendo `SIMULATION_ONLY`; ni login, cookies, Queue-it, CAPTCHA,
fila, checkout ni reserva forman parte de esta prueba.
