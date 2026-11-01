# Estado de integración BETA

## Corte verificado y alcance

Corte de evidencia previo a esta actualización documental: `main` era
`6d3007a3ca1dfdba428cb7595486b1166a1d02b6` (PR #205 integrado). La publicación de imagen #198
corresponde exactamente a ese SHA; una posterior actualización de documentación
mueve `main` y requiere otro release para mantener la vinculación exacta.
Revalidar la HEAD, Actions y el
[checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45)
antes de una operación: este SHA no se traslada automáticamente a candidatos
posteriores. Rige la [autorización ampliada](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
para completar BETA de simulación, Site conectado, Telegram y despliegue
validado; se excluyen reservas, compras y mutaciones reales en Boca.

El corte histórico posterior #208 quedó en `58f57822e95da9574c0a9d5122607616da4a024a`.
Su [release protegido 41301618285](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41301618285)
terminó SUCCESS con digest `sha256:6f067e5078081760dec27f81d95792a4423ff9c1d9cb3bef19ef70dbfc8cf889`
y manifest 13082030761. Es sólo publicación, no instalación. #208 integró
custodia cifrada owner en código y ADR0086; no se ha inscrito una
passkey real, definido el origen privado, configurado un certificado ni
ejecutado su operación en el droplet. #209 sigue la decisión de ruta/ceremonia.
Ese corte ya fue superado; la release #214 previa a este cambio se registra
abajo y una HEAD final distinta exige su propia publicación.

**Corte posterior comprobado 2026-11-01:** #212 integró la comprobación
protegida del puerto; `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d`
con CI 41310796782 y scan 41310796751 SUCCESS. La operación manual
[41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
en ese SHA, intento 1, reportó `FREE address=127.0.0.1 port=8443
reserved=no`. Sólo comprobó disponibilidad instantánea, sin Docker ni Boca
arrancado. La release 41302342233 para `3ef7aff8...` quedó histórica tras
#212; un install exige publicación de la HEAD final exacta. Por decisión del
dueño, el panel local con forwarding privado es primario; Site #113 queda
privado/offline, su baja diferida y fuera del gate BETA local. El cambio
PR #214/ADR0088 integró el origen HTTPS localhost exacto en
`main=8fdbec97262a525821eb87f3fbc27f1841a5d2ec`; CI 41312228362 y
scan 41312228548 SUCCESS. La [release protegida 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820),
intento 1 SUCCESS, publicó sólo
`ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
con manifest 13086161844. Sin pull ni instalación host. Este cambio
#215/PR #216/ADR0089 incorpora código de emisor WebAuthn local de un solo uso, sin prueba física de
Android, confianza CA, clipboard, entrega cifrada ni iOS (#209). La credencial
única tampoco acredita automáticamente ambos sistemas. La HEAD final de
este cambio exige nueva release exacta antes de cualquier host install. Los
runs históricos siguientes conservan su SHA original.

**BETA operativa en el droplet: NO_VERIFICADA / aplicación no instalada.**
RCA #219/PR #220 ya integra en main, **sin ejecutar en host**, una limpieza
selectiva inmediata en el mismo workflow tras fallar un `beta-install` marcado:
parada/identificación del controlador y descarte seguro de contenedor, red,
imagen y Compose exactos si son descartables, con clave/datos/owner preservados.
Los casos inciertos requieren nuevo inventario Boca y nunca permiten un retry
automático. No hubo operación real de limpieza. Ver ADR0090.
El cambio #217 requiere una passkey descubrible en la ceremonia local, para
evitar aceptar una credencial no sincronizable por Google Password Manager.
El navegador sólo recibe una cookie de sesión temporal; la llave privada
reside en el administrador de credenciales elegido. No hay prueba física de
persistencia, sincronización Android/iOS ni renovación TLS (#209).
Código integrado, Site publicado, CI verde y servicio rootless preparado y
detenido son
evidencias distintas. El controlador de `compose.yaml` todavía espera con
`engine=off`, sin listener ni puerto; `compose.beta.yaml` #171 empaqueta
un entrypoint BETA TLS para pruebas desechables, no instalado. #120/#124 no
crearon DB, clave ni volumen de aplicación en el host; #156 detuvo el
servicio dedicado y 41282301501 confirmó ALREADY_STOPPED. La ubicación global de una DB Boca anterior sigue
UNVERIFIED; el destino lógico futuro es `/data/boca.sqlite3` en el volumen
`boca-socios_boca_data`, sin permiso para reemplazar datos encontrados.

| Frente | Código o ejecución comprobada | Gate restante |
| --- | --- | --- |
| Simulación | Coordinador #130, comandos #149, loop #161, ciclo #164 y entrypoint TLS #173; RCA de UUID canónico #187 y probe sintético #190 | Empaquetar/servir en host con identidad y acceso privado; E2E host. No hay cliente Boca real |
| Panel | Adaptadores #128/#148, owner passkey/controles #163, registro WebAuthn #174, preflight #189, custodia #208 y origen `https://localhost:8443` #214 integrados; este cambio #215 incorpora emisor local sólo en código, sin instalación | #209: confianza CA, UV real, entrega privada del sobre, forward y uso Android/iOS, rechazo real de terceros |
| Avisos/Telegram | #162 fence/migración0007/adapter, #176 estado, worker default-off #188, parada opcional #194, helper cifrado #199, fases protegidas #203 y prueba Bot API de un solo intento #204 | Sin bot/destino privados, provisión en host ni envío/recepción real; `api_accepted` tampoco probaría lectura humana |
| Site #113 | Versión privada v10 D1 desactivada; #178 helper, #179 cliente opt-in, #181 custodia Actions y #196 inventario global | Ya no es gate de la BETA del panel local. Sigue offline y privado; baja diferida tras validar reemplazo. Ver #113 |
| Host | Rootless #120, preflight dormido #124, parada #198/41282301501 ALREADY_STOPPED; `port-check` #211/41310958281 observó 8443 FREE `reserved=no`; custodia owner #208, `beta-install` #191 y `beta-acceptance` #200 sólo en código | Sin marca BETA, identidad/archivos privados, instalación funcional ni aceptación host. Revalidar daemon, capacidad, puerto y SHA antes de operar |
| Chromium | Imagen y smoke offline #43/#44 con límite sintético | Capacidad/egress del droplet y visita real no acreditadas |
| Calidad/release | Corte previo a este cambio: main #214 `8fdbec97262a525821eb87f3fbc27f1841a5d2ec`, CI 41312228362 y scan 41312228548 SUCCESS; release 41312460820 publicó imagen/manifiesto sólo para ese SHA | Nueva release y manifiesto para la HEAD final exacta antes de instalar; CI no demuestra capacidad/postflight ni acceso tablet |
| Aceptación sintética | #170 HTTP loopback desechable, #190 probe TLS en contenedor y #200 operación protegida de aceptación/parada | Sin ejecución host/tablet, Site, Telegram ni recursos medidos del droplet |

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
- [PR #187](https://github.com/mbalbo2023/boca-socios-assistant/pull/187)
  integró RCA del redirect a UUID canónico en
  `b92e2abacd63d1654dfb6d795f718af2ea283589`; candidato
  `6c0ade927811f19f331c68b2b6b3e7a0bf8b8ed9`, CI 41274391525,
  scan 41274391451, validaciones release/deploy 41274391657/41274391454,
  preview 41274391653 SUCCESS y revisión 5726518608. Prueba roja previa;
  no hubo efecto host.
- [PR #189](https://github.com/mbalbo2023/boca-socios-assistant/pull/189)
  integró `check-beta-owner/config` sin listener en
  `63965b087fbd6d7a68308302bb8baf2e08975674`; candidato
  `b2b34a17f207f7021d09bb63455f7aafa7ba958d`, CI 41274671069,
  scan 41274671077, release/deploy 41274671053/41274671118 SUCCESS,
  revisión 5726527799. No inscribió al dueño ni configuró TLS host.
- [PR #188](https://github.com/mbalbo2023/boca-socios-assistant/pull/188)
  integró worker Telegram explícito y apagado por defecto en
  `1bdc80b7f50021227cd798e655844b157198ea93`; candidato
  `2e1ee9339b6c2ec83ba235deb2a81699c8c928b9`, CI 41274848402,
  scan 41274848345, release/deploy 41274848336/41274848461 SUCCESS,
  revisión 5726534430. Sin bot, destino ni envío.
- [PR #190](https://github.com/mbalbo2023/boca-socios-assistant/pull/190)
  integró probe TLS sintético desechable en
  `64746289363741c4d85df79fa4e133b07f261efa`; candidato
  `04592f882d1492b03fbe93a3c50e7293237a83a2`, CI 41275005313,
  scan 41275005491, release/deploy 41275005329/41275005377 SUCCESS,
  revisión 5726547113. Sin ejecución host.
- [PR #191](https://github.com/mbalbo2023/boca-socios-assistant/pull/191)
  integró `beta-install` protegido en
  `161043f15befd5b612b71e036c9c1dead21581ce`; candidato
  `5265546027fc8f69f03495202fbfd427a5232af2`, CI 41275510437,
  scan 41275510471, release/deploy 41275510497/41275510438 SUCCESS,
  revisión 5726574754. El smoke corrió preflight e imagen desechables;
  host/publish omitidos, sin instalación.
- [PR #194](https://github.com/mbalbo2023/boca-socios-assistant/pull/194)
  integró reconocimiento fail-closed del worker Telegram en `stop-test` en
  `451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`; candidato
  `ba5f8b4cc42c47dc279a95222c6fff3b4d30748b`, CI 41275762284,
  scan 41275762308, release/deploy 41275762296/41275762254 SUCCESS,
  revisión 5726581135. No hubo nuevo dispatch de parada.
- [PR #196](https://github.com/mbalbo2023/boca-socios-assistant/pull/196)
  cerró RCA de inventario global del daemon antes/después de custodia Site en
  `2768d23dd2e9e58563a13aa80d8b76885448d020`; candidato
  `2676bd9f0cb91e4da0785b0cd149e2d33fd5810a`, CI 41276268828,
  scan 41276268931, release/deploy 41276268935/41276268997 SUCCESS,
  revisión 5726595915. No hubo Site host dispatch.
- [PR #200](https://github.com/mbalbo2023/boca-socios-assistant/pull/200)
  integró `beta-acceptance` y parada Boca obligatoria en el mismo job en
  `f21b55f8cc79f9906b8ce1eff3fa1e6c152e896e`; candidato
  `8d629841832cb32d5435521f222359892f498389`, CI 41277081359,
  scan 41277081440, release/deploy 41277081383/41277081431 SUCCESS,
  revisión 5726623269. El runner ejecutó el probe con límites del
  controlador; job host omitido, sin aceptación del droplet.
- [PR #199](https://github.com/mbalbo2023/boca-socios-assistant/pull/199)
  integró helper de custodia cifrada del bot/destino Telegram en
  `a808a6455e624eea7e1eeb7bedd10f3ab63f9a7c`; candidato
  `e73c6a5c7339e47d6e69bf1e26c9d65749b123e3`, CI 41277311559,
  scan 41277311577, release/deploy 41277311519/41277311599 SUCCESS,
  revisión 5726629731. Ningún secreto real ni volumen host.
- [PR #203](https://github.com/mbalbo2023/boca-socios-assistant/pull/203)
  integró las operaciones protegidas de migración 0007 y custodia Telegram
  posterior a BETA en `487995ca57282e2947d977333e72bd10775fbb98`;
  candidato `6c5dd64b1f5c6302ce309de181ff8d49be3ac3fe`, CI
  41278835729, scan 41278835819, release/deploy 41278835721/41278835778
  SUCCESS y revisión 5726684632. El smoke en runner probó prepare/install/verify
  cifrados con datos sintéticos y stdin canónico; el job host y la publicación
  se omitieron. Main push CI 41278970494 y scan 41278970501 SUCCESS. Sin
  migración, volumen, bot ni destino reales en el droplet.
- [PR #204](https://github.com/mbalbo2023/boca-socios-assistant/pull/204)
  integró prueba protegida de identidad privada y un único aviso Telegram
  sintético en `5cb8ce17715f571979a2ea3bb092da9b470f362d`; candidato
  `6e8205c0063c095bd51e36820e7be89ba98079c4`, CI 41281318516,
  scan 41281318527, release/deploy 41281318543/41281318563 SUCCESS y
  revisión 5726822139. El runner validó metadata Docker real y pruebas
  falsas de Bot API/SQLite; publicación y operación host omitidas. No hubo
  token/chat, tráfico Telegram ni envío real. Main push CI 41281517606 y
  scan 41281517611 SUCCESS.

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

La inspección anterior de entornos protegidos en GitHub del 2026-11-01 halló
`boca-image-release` sin variables ni secretos. Después se configuró sólo la
variable de entorno `BOCA_RELEASE_ENV_READY=ready`, preservando la regla de
rama `main`. La [publicación protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41298346638), attempt 1, SUCCESS,
produjo `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:ab0745a840e35a6d713fed14ec0761512fdc90284c133f2c321c9ffe2d3c9284` para `6d3007a3ca1dfdba428cb7595486b1166a1d02b6` y el artefacto
`boca-release-manifest` ID 13079654802. El push CI 41282070869 y scan
41282070707 del SHA base fueron SUCCESS. La imagen no se descargó ni instaló
en el droplet; un nuevo commit exige release propio antes de cualquier install.
`boca-first-deploy` conserva sólo las dos credenciales SSH y tres variables
de despliegue/lectura; carece de `BOCA_BETA_ENV_READY`,
`BOCA_TELEGRAM_ENV_READY`, `BOCA_TELEGRAM_OWNER_READY`, origen/sujeto owner,
HMAC/bot ID protegidos y material Site. No se ha provisionado la
credencial/passkey/TLS real. Las
fases Site #181/#196, instalación #191, aceptación #200 y Telegram #203/#204
exigen su release y
gates correspondientes. La [parada protegida #198](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41282301501) sobre `6d3007a3ca1dfdba428cb7595486b1166a1d02b6`
fue SUCCESS y emitió `ALREADY_STOPPED containers=not_queried data=preserved`;
no inventariaba contenedores. El daemon puede reiniciar tras un reboot, por lo
que se revalida antes de operar. El puente sigue desactivado.

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
BETA. El workflow `first-install` instala sólo un controlador dormido; #191
agrega `beta-install` y #200 `beta-acceptance` con parada, ambos sin dispatch
host. Su código no autoriza presentarlo como BETA operativa. El Site privado
v10 y el código Telegram no
suplen esos pasos. No hacer backup/restore ahora; sigue diferido.

El historial detallado del candidato offline #24 y de cortes previos permanece
en [la versión anterior de este documento](https://github.com/mbalbo2023/boca-socios-assistant/blob/1441d55a632d4a545b21ee7f6f2b0a4140ab2320/docs/BETA_INTEGRATION_STATUS.md);
sus tablas no describen el estado vigente. Regla 84 exige reconciliar este
archivo, README, ROADMAP, plan y #45 con cada resultado real antes del cierre.
