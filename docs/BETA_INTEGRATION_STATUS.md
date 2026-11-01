# Estado de integración BETA

## Corte verificado y alcance

Al corte de este documento, `main` es
`9e923af56e76a04069bfad6f8ca9c68db0edd890` (PR #181).
Revalidar la HEAD, Actions y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
antes de una operación: este SHA no se traslada automáticamente a candidatos
posteriores. Rige la [autorización ampliada](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
para completar BETA de simulación, Site conectado, Telegram y despliegue
validado; se excluyen reservas, compras y mutaciones reales en Boca.

**BETA operativa en el droplet: NO_VERIFICADA / aplicación no instalada.**
Código integrado, Site publicado, CI verde y servicio rootless preparado son
evidencias distintas. El controlador de `compose.yaml` todavía espera con
`engine=off`, sin listener ni puerto; `compose.beta.yaml` #171 empaqueta
un entrypoint BETA TLS para pruebas desechables, no instalado. #120/#124 no
crearon DB, clave ni volumen de aplicación en el host y #156 sólo detuvo el
servicio dedicado. La ubicación global de una DB Boca anterior sigue
UNVERIFIED; el destino lógico futuro es `/data/boca.sqlite3` en el volumen
`boca-socios_boca_data`, sin permiso para reemplazar datos encontrados.

| Frente | Código o ejecución comprobada | Gate restante |
| --- | --- | --- |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo local #164 y entrypoint TLS #173 integrados; alta cifrada #31/#148 | Empaquetar/servir en host con identidad y acceso privado; E2E host. No hay cliente Boca real |
| Panel | Adaptadores #128/#148, owner passkey/controles #163 y prueba de registro WebAuthn #174 integrados | Inscripción física del dueño, origen TLS privado, tablet y rechazo de terceros |
| Avisos/Telegram | Outbox/dispatcher, #162 fence/migración0007/adapter/proyección y #176 corrección de estado local con schema0007 | Sin bot/destino privados, provisión, worker ni envío/recepción real; `api_accepted` tampoco probaría lectura humana |
| Site #113 | Versión privada v10 con cola D1 desactivada; #178 helper cifrado, #179 cliente outbound opt-in y #181 custodia host protegida integrados | Sin release/digest, bypass+HMAC host, flag ni E2E; aún offline y no conectado a DB/comandos. Ver issue #113 |
| Host | Preparación rootless #120 SERVICE_READY; preflight read-only #124 PASS para controlador dormido; `stop-test` #156/41272785626 STOPPED, `containers=0` detenidos en ese run | No prueba presupuesto BETA/Chromium; sin instalación funcional. Ningún contenedor Boca quedó en ejecución; los ya detenidos, si existían, se preservaron |
| Chromium | Imagen y smoke offline #43/#44 con límite sintético | Capacidad/egress del droplet y visita real no acreditadas |
| Calidad/release | CI frozen, Ruff/mypy/tests/policy, build/scan y gates de digest; #171 smoke de paquete TLS/aislamiento en runner | Release de imagen funcional, capacidad, pre/postflight y aceptación host sobre SHA/digests exactos |
| Aceptación sintética | #170 integra HTTP loopback desechable con alta, comandos, aviso, reinicio y parada; muestra de 21 requests | Sin TLS, tablet, Site, Telegram ni recursos del droplet |

## Evidencia exacta de este corte

- [PR #161](https://github.com/mbalbo2023/boca-socios-assistant/pull/161)
  integró el loop de comandos en `77bf93c29dc59d5db0b5cf57c2c6ba2a14e8f39e`;
  [CI 41269055409](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269055409)
  y [scan 41269055410](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269055410)
  fueron verdes sobre el candidato revisado. No agregó listener.
- [PR #162](https://github.com/mbalbo2023/boca-socios-assistant/pull/162)
  integró Telegram en `466517d90991d3c9b600502af69424a84b82fabc`.
  HEAD candidato `e93bd190798d0974183935c21965b046b6ff965e`:
  [CI 41269298595](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269298595),
  [scan 41269298533](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269298533)
  y validaciones release/deploy 41269298646/41269298514 SUCCESS; sin envío real.
- [PR #165](https://github.com/mbalbo2023/boca-socios-assistant/pull/165)
  integró `stop-test` en `1441d55a632d4a545b21ee7f6f2b0a4140ab2320`.
  Candidato `4a812a275387bf18ba70b63a6c28ad865fcd34a0`:
  [CI 41269572935](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269572935),
  [scan 41269572802](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269572802)
  y validaciones release/deploy 41269572673/41269572784 SUCCESS.
  [Revisión técnica 5726252792](https://github.com/mbalbo2023/boca-socios-assistant/pull/165#pullrequestreview-5726252792).
  El dispatch posterior #156/41272785626 se registra abajo.
- [PR #164](https://github.com/mbalbo2023/boca-socios-assistant/pull/164)
  integró ciclo de vida local en `df668e066d2967ad7eb82e3c9f96935af282e2e2`.
  Candidato `46f9a48e6e6c2c7a738e5559a536e3de6011170f`,
  [CI 41269722611](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269722611),
  [scan 41269722595](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41269722595)
  SUCCESS, [revisión 5726257987](https://github.com/mbalbo2023/boca-socios-assistant/pull/164#pullrequestreview-5726257987).
  Es biblioteca local: no instaló servicio ni abrió socket.
- [PR #163](https://github.com/mbalbo2023/boca-socios-assistant/pull/163)
  integró el panel en `ebb5e95399233eec629c8c52d4176092e97c5f34`.
  Candidato `4b608b1ae8dedd4ad9fe541ecbd5f45fac42958c`,
  [CI 41270060363](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270060363),
  [scan 41270060350](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270060350),
  validaciones release/deploy 41270060360/41270060361 y
  preview 41270060364 SUCCESS;
  [revisión 5726269111](https://github.com/mbalbo2023/boca-socios-assistant/pull/163#pullrequestreview-5726269111).
  Código WSGI sin credencial/origen/servidor de host: no acredita login.
- [PR #170](https://github.com/mbalbo2023/boca-socios-assistant/pull/170)
  integró aceptación HTTP sintética en
  `1ca5c0cf3d83e94e308ed6ef75d410bea31e0d7e`.
  Candidato `a3715286a3f17ce4119ec42eca4a1ff428610ce6`,
  [CI 41270258546](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270258546),
  [scan 41270258580](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270258580)
  y validaciones release/deploy 41270258625/41270258540 SUCCESS;
  revisión 5726279353. En un entorno loopback desechable, 21 requests:
  mediana 0.72 ms y p95 7.18 ms. No extrapolar al host/tablet.
- [PR #173](https://github.com/mbalbo2023/boca-socios-assistant/pull/173)
  integró entrypoint explícito en
  `0161922fb68bad3c36101bf9633ba025faf52f32`.
  Candidato `e86818dd87cbfd6fada494c1fe537aef19ee7834`,
  [CI 41270849469](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270849469),
  [scan 41270849494](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41270849494)
  y validaciones release/deploy 41270849425/41270849419 SUCCESS;
  revisión 5726302585. `init-beta` sólo crea DB nueva/evento de prueba;
  `serve-beta` exige archivos passkey/TLS y sirve WSGI con loop local.
  Sin Compose beta integrado, credencial de dueño ni operación host.
- [PR #174](https://github.com/mbalbo2023/boca-socios-assistant/pull/174)
  integró sólo verificación de registro WebAuthn de dos pasos en
  `74edba458efe8cc2ce3b5f6e0deb1a8da9a0529d`.
  Candidato `91c05f6a75499f3643af06834262ae6a1527e468`,
  CI 41271084422, scan 41271084439, preview 41271084425 y
  validaciones release/deploy 41271084417/41271084459 SUCCESS;
  revisión 5726310354. No inscribió una passkey real.
- [PR #176](https://github.com/mbalbo2023/boca-socios-assistant/pull/176)
  integró RCA #175 en `8d37332f1b4674752963b4e8fda1b52da0925287`.
  Candidato `c4404c2fa8b6bcc8ad7b960b3b397bf834b3b6d3`,
  CI 41271432002, scan 41271432001, preview 41271432063 y
  validaciones release/deploy 41271432029/41271432013 SUCCESS;
  revisión 5726325061. `/estado` acepta sólo checksum conocido de 0007;
  sigue rechazando deriva o versión desconocida. No hubo migración host.
- [PR #171](https://github.com/mbalbo2023/boca-socios-assistant/pull/171)
  integró paquete BETA separado en
  `472574ca380e9c14d665b8aab97790b9a05e1f71`.
  Candidato `e498c8d1f4d09202b09fcda19d6accd09850d8f2`,
  [CI 41271723362](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41271723362),
  [scan 41271723366](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41271723366),
  validaciones release/deploy 41271723342/41271723422 SUCCESS;
  revisión 5726348620. Smoke desechable `init-beta→serve-beta` validó
  TLS, health, bind loopback, mounts, límites efectivos y cgroups. No
  publicación/instalación host ni credencial real.
- [PR #178](https://github.com/mbalbo2023/boca-socios-assistant/pull/178)
  integró helper de provisión cifrada en
  `497028ba49ec509f586051feca8876f2250ff5ac`. Candidato
  `ee11d8eb5332913f28eda48d14b1ec5e1749d0c4`,
  CI 41271955784, scan 41271955801, validaciones release/deploy
  41271955795/41271955816 SUCCESS, revisión 5726355216.
  No hubo secreto ni operación host real.
- [PR #179](https://github.com/mbalbo2023/boca-socios-assistant/pull/179)
  integró cliente/worker outbound opt-in en
  `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163`. Candidato
  `7933550bed4e7cfb6955dc4366be20c659b5cc5b`,
  CI 41272179087, scan 41272165010, validaciones release/deploy
  41272164915/41272164965 SUCCESS, revisión 5726364954.
  Site v10 confirmó vector HMAC y protocolo; default off, sin polling real.
- [PR #181](https://github.com/mbalbo2023/boca-socios-assistant/pull/181)
  integró `site-prepare/install/verify` en el workflow protegido en
  `9e923af56e76a04069bfad6f8ca9c68db0edd890`. Candidato
  `4c8158d79a49924738b2a52573dc37cc91eccc1a`: CI 41273068810,
  scan 41273068858, smoke/validación de deploy 41273068811 y validación
  release 41273068906 SUCCESS; revisión 5726437610. El smoke preparó,
  instaló y verificó un sobre sintético en volumen desechable del runner;
  el job host quedó omitido. Ninguna fase Site se despachó al droplet.

El Site privado v10 (source `d4c7f9094caddc018646b165e5ce42ebbccc93df`,
versión `appgver_1fda8ad8e44881918895842f6b608f77`, deploy
`appgdep_6ae6b9bf1894819199b6c2f7e41bdf91` SUCCEEDED) probó
10/10 casos Node+SQLite. La ruta hosted `/api/bridge/status` devolvió
503 `unconfigured`; no se encolaron comandos ni se instaló secreto/flag.
El feed GitHub v8 queda fail-closed por rate limit del egress, no es un
recibo operativo. #113 conserva configuración y gates.

El [run #120](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41262650418),
attempt 1, preparó sólo el daemon dedicado sobre
`6be606f83c5a6afe0ba7226abbca6a09276d1ca1`: rootless,
cgroup v2/systemd, overlay2 y namespace vacío, con
`application_database=not_accessed`/`application=not_installed`. No repetir
la preparación. El [preflight #124 / 41268626135](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41268626135),
attempt 1, source `213be4903669c6e88122a536ad8fee6785c997ac`,
informó `mem_kib=853288`, `stage_disk_bytes=8009560064`,
`stage_inodes=2902623`, `cpu_headroom=1.60`, `namespace=empty`.
Sólo validó el presupuesto actual 0.5 CPU/256 MiB/64 PIDs, sin instalar.

El [stop-test #156 / 41272785626](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41272785626),
attempt 1, operó desde `main` `c1ecf8ae230bd8d02beef9f4e0d3dbf0c9aa5163`
con imagen y release vacíos. El job protegido revalidó la HEAD antes del
host y emitió `BOCA_STOP_TEST state=STOPPED ... containers=0 data=preserved`.
Detuvo el daemon dedicado Boca y preservó datos/clave; no instaló la BETA ni
afirma que haya probado el panel, Site o Telegram. `containers=0` cuenta los
contenedores detenidos por esa invocación, no el inventario total: la operación
verificó que ninguno quedara en ejecución y preservó los ya detenidos, si
existían. La unidad conserva su
enablement y podría reiniciar en un reboot posterior; revalidar el estado
antes de otro uso.

El entorno protegido `boca-image-release` carece de la variable
`BOCA_RELEASE_ENV_READY`: no hay release exitoso por digest de esta HEAD.
Las fases Site #181 exigen ese release y material cifrado para el destinatario
verificado; el daemon Boca está detenido y el puente permanece desactivado.

La [inspección #98](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41258754195)
es histórica: servicio ausente antes de #120; DB/WAL/SHM candidate-absent
únicamente en tres rutas fijas. No es censo global ni migración. Las DB de CI
son temporales. No se abrió, movió ni migró una DB del host.

## Secuencia de aceptación pendiente

El [plan BETA](BETA_DELIVERY_PLAN.md) exige alta sintética desde
**Socios > Agregar socio**, lista y ciclo de credenciales, iniciar/detener/
estado durable, avisos locales, reinicio, denegación y accesibilidad. Las
funciones diferidas o sin definición en su matriz se muestran con motivo,
sin fingir efectos. Conectar Site y Telegram requiere sus gates de identidad,
transporte y pruebas propias. [Issue #168](https://github.com/mbalbo2023/boca-socios-assistant/issues/168)
registra la provisión/recepción Telegram pendiente; [issue #113](https://github.com/mbalbo2023/boca-socios-assistant/issues/113)
registra el puente Site no resuelto.

La cadena pendiente es: panel/runtime empaquetado con acceso privado verificable
→ imagen/Compose/release por digest sobre SHA exacto → capacidad/aislamiento
del host y datos/clave compatibles → instalación manual protegida → E2E
sintético desde interfaz real y medición → nueva parada Boca verificable. La
parada de 41272785626 cerró las pruebas de preparación, no una instalación
BETA. El workflow actual `first-install` instala sólo un controlador dormido;
#181 añade custodia Site, no `beta-install`. Ninguno
autoriza presentarlo como BETA. El Site privado v10 y el código Telegram no
suplen esos pasos. No hacer backup/restore ahora; sigue diferido.

El historial detallado del candidato offline #24 y de cortes previos permanece
en [la versión anterior de este documento](https://github.com/mbalbo2023/boca-socios-assistant/blob/1441d55a632d4a545b21ee7f6f2b0a4140ab2320/docs/BETA_INTEGRATION_STATUS.md);
sus tablas no describen el estado vigente. Regla 84 exige reconciliar este
archivo, README, ROADMAP, plan y #45 con cada resultado real antes del cierre.
