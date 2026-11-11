# A45-R178 — diagnóstico de Internet del worker Boca (solo salida)

**Fecha:** 11/11/2026 ART. **Ámbito:** Boca Socios Assistant solamente.
**Estado:** CODE_ONLY; ninguna conexión real ni SSH al droplet ejecutado.

## RCA de topología

- `compose.beta.browser.yaml` conecta `browser-worker` únicamente a
  `boca-socios_boca_browser_egress`, bridge dedicada `internal: false`,
  sin puerto publicado, sin red del controller, sin Porota y sin host mode.
  Esto **permite la posibilidad** de salida IP/DNS desde el proceso normal,
  pero no demuestra DNS, NAT rootless, firewall de destino ni TLS físicos.
- `docker run --network none` en `release-image.yml`, CI offline y
  `host_worker_physical.py` corresponde a smokes deliberadamente aislados
  de red. **No es la configuración del worker instalado por Compose.**
- Recibo físico R177 del Action `#43066120206` identificó un **worker
  histórico** con `network_name=none`, `status=exited`, `exit_code=1`,
  PID0 y health unhealthy. Esa instancia no puede aportar prueba de
  Internet: R178 devuelve NO_GO antes de `docker exec` si no está RUNNING
  o si el único bridge efectivo no es Boca egress. Se necesita migración
  de la pareja al release nuevo y un arranque propietario separado.
- Pruebas Chromium `offline=True` / `about:blank` R177 son fixtures
  locales y tampoco demuestran salida externa.

## Operación mínima nueva, reutilizando Action existente

`boca-first-deploy.yml` incorpora la opción manual
`operation=beta-browser-egress-readonly`. Reutiliza el mismo runner,
validaciones de pins, checkout exacto, SSH protegido, ZIP en memfd y
atestador de `beta-browser-status`; no crea workflow ni usuario nuevo.

1. Solo en topología `BOCA_BOT_CONTROL=on-demand`, verifica SHA e imágenes
   inmutables y accede al dueño rootless existente UID10001.
2. El atestador bajo lease Boca comprueba vínculo instalado, CID exacto,
   worker `running/healthy` y única bridge `boca_browser_egress`.
3. Solo si está en ejecución invoca `docker exec --user 10002:10002` **por
   CID** del worker ya existente. No llama `docker start/stop/create/run`,
   no instala paquetes, no monta ni modifica volúmenes, no publica puertos,
   no usa sudo ni socket de Docker global.
4. El módulo del contenedor `browser.egress_probe --once` hace una resolución
   DNS IPv4 pública del host neutro `example.com` y una única solicitud
   `HEAD /` al puerto 443 con validación TLS estándar, máximo 5s por conexión.
   **P1 TOCTOU corregido en commit incremental:** valida todas las A de la
   resolución inicial, elige una dirección IPv4 pública y abre TCP a **esa
   dirección literal**; envuelve el socket con TLS `CERT_REQUIRED`,
   `check_hostname=True`, SNI `example.com` y `Host: example.com` fijo.
   `HTTPConnection` recibe el socket TLS ya conectado: jamás vuelve a
   resolver el hostname ni permite cambiar de IP después del gate DNS.
   No permite parámetros de URL; no usa SITE_URL, usuario, cookies, tokens,
   Queue-it ni sitio de socios. No sigue redirects ni lee el cuerpo HTTP.
5. Emite solo una categoría de resultado `dns`, `tls` o `https`, o PASS,
   ligada al ID de ejecución y al SHA del origen. El runner revalida el
   recibo, registra NO_GO como fracaso del Action; se reprueba la identidad
   y el estado antes/después de la observación.

Si el worker está apagado, la respuesta es `state=NO_GO stage=worker_stopped`.
La operación **no lo arranca**: esa es una decisión separada del control
START/STOP autenticado del panel 8443. El diagnóstico tampoco activa el
modo offline-fixture ni invoca acciones transaccionales del bot.

## Evidencia y gates pendientes

- **Stomper de capacidad encontrado y corregido:** el full ZIP protegido
  resultó de 1.154.236 bytes descomprimidos después de su compacción
  AST-equivalente, **2.236 bytes sobre el antiguo máximo 1.152.000**.
  Se elevó el límite **únicamente del full bundle en 4 KiB** a
  1.156.096 tanto en builder como en bootstrap. Se mantienen intactos
  `MAX_ARCHIVE_BYTES=512000`, las allowlists exactas, SHA-256, validación
  de inode/tipo y límites separados de recovery, W1, physical y census.
  Los 49 tests de paquetes protegidos/regresión cap pasan CODE_ONLY.
- Ciclos TDD RED→GREEN y suite local completa tras TOCTOU: **6.859 PASS,
  1 SKIP, 34 subtests PASS, 0 FAIL** (50,91s). El SKIP es la prueba AF_UNIX
  física de R177: kernel sandbox local devuelve EPERM; permanece en CI.
  Nuevas 24 pruebas focales R178 PASS (incluida regresión TOCTOU con HTTPConnection
  estándar y redial prohibido) y 49 contratos de ZIP/caps PASS.
  Ruff y formato de fuentes modificadas PASS; mypy **155 módulos PASS**;
  `check_repo_policy.py` PASS; `git diff --check` PASS. Tests de
  observación usan factories falsas, sin conexiones externas.
- El digest completo del ZIP protegido cambió de R173 a R178
  `80c458fbe314eadbd47e474dbdefa9d2f055f2e70137ef28110cc9ad241568fb`;
  quedó fijado en la regresión, conservando el digest R173 como historial.
- Pendiente GitHub Actions sobre SHA fusionado: build imagen que contenga
  `egress_probe.py`, verificación del ZIP memfd, CI, Trivy y dispatch manual
  `beta-browser-egress-readonly` con `service=controller` y pins exactos
  del release instalado. No usar PR para realizar SSH ni simular resultado.
- Pendiente físico: worker corriendo, bridge rootless `internal=false`,
  DNS público y HTTPS/TLS comprobados en su namespace; revisar recibo
  `BOCA_ON_DEMAND_EGRESS` del Action y estado de servicios posterior.
  Los flags Compose habilitan salida pero **no sustituyen esta prueba**.
- Mantener seguridad previa, autenticación del panel y prohibición de
  reservas reales. Porota, Docker ajeno y PPI Watch quedan intocables.

Este cambio se apila después de
[R177](2026-11-11-r177-offline-fixture-probe-code-only.md).
