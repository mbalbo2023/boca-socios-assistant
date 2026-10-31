# BETA de componentes: estado vigente y registro histórico del gate #35

## Estado vigente — 2026-10-31 (America/Argentina/Buenos_Aires)

Base verificada: `main` `546fbb595b395fb32b3608879590fcc44c833086`.
La integración de componentes **offline** permite revisar una simulación; no
acredita una BETA operativa, credenciales reales, reserva ni estado del host.
Todo el texto bajo «Registro histórico» documenta cortes anteriores, no la
HEAD actual ni una prueba de Boca.

| Alcance | Evidencia en esta base | Decisión actual |
| --- | --- | --- |
| Simulación e intento local | #36 y #38 integrados: coordinación de una sola ejecución por socio dentro de una instancia, y concesión durable SQLite para un intento local | GO para pruebas sintéticas; #38 no está conectado a una reserva externa ni garantiza exactamente una vez en Boca |
| Panel y alta | #29 renderiza estados inyectados y #31 ofrece alta interna; #110 integró un artefacto sintético de vista previa, no una ruta servida. #113 define la futura consola ChatGPT Sites compartible | NO_GO para interfaz privada: faltan API Boca, autenticación administrativa y controles de sesión/TLS/CSRF. No se publicó un Site |
| Navegador y fuente pública | #43 arrancó/cerró Chromium sin egress; #44 midió un solo arranque offline; #33 es opt-in y #96 informa un semáforo público manual | No hay prueba de login, cola, elegibilidad o reserva; el script #33 no fue ejecutado contra Boca en este gate ni se midió una visita real |
| Claves y credenciales | #40 continúa draft; el vault y #31 no exponen un canal seguro de ingreso | NO_GO para contraseñas reales; falta completar y revisar el ciclo de claves, identidad única y alta privada |
| Host y release | #79/#81 fijaron rootless y custodia de clave; #89 vinculó el digest escaneado; #91 inspecciona UID/capacidad; #97 añadió limpieza selectiva; #99/#117 rechazan reruns, main obsoleto y dispatches duplicados. #116 verifica red/cgroups efectivos y capacidad tras pull/up en CI | NO_GO para release/dispatch: faltan prueba real de entorno protegido, identidad SSH, daemon rootless, cgroups y capacidad del host. No hubo publicación GHCR ni operación del host en este corte |
| RCA y continuidad | #114 integró el registro; #116 añadió RCA-105/106. CI exige 6 lecciones y 15 selectores de regresión ejecutados; #45 conserva el handoff | GO para retener regresiones de código; las nuevas lecciones requieren RCA, prueba y PR revisado. No hay autoedición ni deploy automático |
| Backup/restore | El dueño difirió este trabajo hasta contar con una versión productiva fiable | No bloquea esta BETA de simulación ni habilita credenciales reales; antes de un alta real siguen pendientes los requisitos de recuperación/custodia de ADR 0012 y ADR 0022 |

Para cada nuevo PR se registra revisión técnica del agente, checks exactos y
conversaciones resueltas. ADR 0038 sustituyó la antigua exigencia de otra
aprobación humana; fusionar no activa un despliegue. Un futuro dispatch requiere
evidencia de todos los gates objetivos de la única Actions Boca. Una señal
pública adversa se informa como alerta y no sustituye esos gates.

## Registro histórico — cortes del 2026-10-28 y 2026-10-29

**Fecha:** 2026-10-28 (America/Argentina/Buenos_Aires). **Estado:** rama de
verificación, sin merge a `main`, despliegue ni acceso autenticado a Boca.
Este es el estado de aquel corte; los SHA y resultados no acreditan el estado
actual. Consultar [BETA_INTEGRATION_STATUS.md](BETA_INTEGRATION_STATUS.md)
para los componentes ya integrados y su revalidación posterior. Desde
2026-10-29 rige
[ADR 0038](ADR/0038-agent-review-and-operations.md):
revisión técnica registrada del agente y CI exacta, sin aprobación humana
adicional. El diseño #28 se revisó y fusionó el 2026-10-29 en horario de
Argentina, sin habilitar alta real. Revalidar PRs, main y gates antes de operar.

**Revalidación intermedia del 2026-10-30 (UTC):** #30, #34, #33 y #43 ya
estaban en `main`.
#36, #38, #40 y #44 permanecían como borradores; #42 se rehízo como PR
documental directo a `main`. El árbol y las CI de 157 pruebas descritos abajo
son históricos, no el estado de #42 ni de la base vigente indicada arriba. El
smoke offline de Chromium no prueba el sitio ni habilita reserva o despliegue.

Para un agente nuevo, empezar por
[AGENT_HANDOFF_2026-10-28.md](AGENT_HANDOFF_2026-10-28.md), que incluye
procedencia de PRs, evidencias, dependencias y decisiones pendientes.

**Actualización de continuidad:** [PR #36](https://github.com/mbalbo2023/boca-socios-assistant/pull/36)
integraba componentes en aquel candidato; [PR #38](https://github.com/mbalbo2023/boca-socios-assistant/pull/38)
añadía el guard de intento único y [PR #40](https://github.com/mbalbo2023/boca-socios-assistant/pull/40)
el recifrado interno. Eran **borradores apilados** al corte. En otra rama,
[PR #33](https://github.com/mbalbo2023/boca-socios-assistant/pull/33)
corrige la ruta pública y [PR #43](https://github.com/mbalbo2023/boca-socios-assistant/pull/43)
construye el worker Chromium. Esos cambios **no** están incorporados en el
árbol de la rama histórica ni en sus 157 pruebas.
[PR #44](https://github.com/mbalbo2023/boca-socios-assistant/pull/44)
mide un único arranque offline de ese worker en otra rama apilada.

## Candidatos incorporados

| PR | HEAD | Función validada en el árbol combinado |
| --- | --- | --- |
| #30 | `ed69fc2d94843d3835dea06b53033e4f3198cd36` | DB, cola, navegador contractual, avisos seguros |
| #34 | `cfb1abd8d360714e3801554985e1d01fc483e899` | Outbox SQLite, reinicios y leases |
| #29 | `6b1784c715a0b71ef28f8d0785bab2bc138eb42e` | HTML accesible de estados ficticios |
| #28 + #31 | `64452c18a3a74a5b35c81f45d8a42463de140e1f` + `5050c88ea236994abf25c432ab5bfac73f514b70` | Diseño y servicio interno de alta cifrada |
| #33 | `0f68e16698dc8d4aca5998b152669a2f94d51788` | Observador público opt-in, **no ejecutado contra Boca** |
| #36 | `3e754275e4e26884186b9b037b09c6981eda4f72` | Integración cruzada de los componentes de arriba |
| #38 | `3df9d73fcb85d00123988dc1d4528ad8e66792f0` | Concesión local única, vencimiento sin reintento, conciliación manual |
| #40 | `ce1b4aecdd97949b96943c3911cd21482f36e5e1` | Recifrado transaccional y trigger contra escritores de clave antigua |

La integración de estos snapshots no tuvo conflictos de código al corte. El PR #34
partió de una HEAD anterior de #30; la regresión posterior del vault de #30
se incorporó explícitamente. La integración final exige revisión técnica
propia y CI exacta de cada PR fuente; algunos ya se integraron después.

## Prueba cruzada

La nueva regresión crea **sólo datos ficticios**: un socio mediante el
servicio interno, una credencial AES-GCM con clave externa de test, un evento,
dos alias de sesión para una única solicitud, un resultado de navegador doble,
un aviso SQLite que sobrevive reinicio y un panel que oculta IDs, correo y
contraseña. La base conserva una única fila con cantidad 1 y estado `planned`.
La aceptación local del aviso no significa entrega a Telegram. El panel
repite que no existe una reserva real.

**Calidad de la integración #36:** `uv sync --locked`, Ruff lint/formato,
mypy strict (25 módulos), pytest **144 passed**, aislamiento PASS; Actions
[40763679861](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40763679861)
SUCCESS en `quality-and-tests` e `image-build` para su HEAD exacta. En el
árbol apilado #40: `uv sync --frozen`, Ruff, mypy strict (27 módulos), pytest
**157 passed** y aislamiento PASS; Actions
[40770471612](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40770471612)
SUCCESS en ambos jobs. #38 pasó
[40769224759](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40769224759)
en ambos jobs. En **aquella rama** el build seguía siendo sólo del controlador.
Por separado, #33 HEAD `577c52656cbd90d2f6f308340405c456b065a9ce`
pasó [40777337319](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40777337319)
(42 tests locales) y #43 HEAD `9a6311d2be22de76d8f5cf609cba0f46c9e67eb2`
pasó [40779396413](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40779396413)
(45 tests locales, build y arranque/cierre de Chromium **sin red**). #44
HEAD `7106210be6c7d007af45ce547ee116b5c91bfd4a` pasó
[40780641087](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40780641087)
(53 tests locales); su único arranque offline en CI registró 185,2 MiB
de memoria pico, 76 tareas pico, 714 ms de CPU y 834 ms transcurridos.
No hay Docker local, prueba del script observador contra Boca ni prueba de
rendimiento de Boca o del droplet.

## Dependencias y siguiente decisión revisable

| Orden | Gate | Estado / efecto |
| --- | --- | --- |
| 1 | Diseño #28 revisado y fusionado; implementar identidad/admin/TLS | Seguridad del endpoint pendiente; bloquea formulario expuesto y claves reales |
| 2 | Revisión técnica registrada de cada PR fuente y protección verificable de `main` (#10) | CI exacta, conversaciones resueltas y PR listo preceden merge |
| 3 | #36 → #38 → #40 y CI de la HEAD de integración final | Las CI históricas fueron verdes; exigir nueva revisión técnica y checks exactos antes de integrar |
| 4 | Worker aislado #27 y una observación **anónima** de la portada real con egress acotado | #43 pasa smoke offline y #33 apunta a `/auth/login`; falta ejecución del script con egress de sistema acotado |
| 5 | Canal privado, identidad externa única, backup/restore, cuenta autorizada y reconciliación de Boca | Pendiente; impide credenciales reales y reserva |
| 6 | Despliegue de simulación exclusivo Boca por Actions | Operación autónoma sólo con SHA, digest inmutable, SSH fijado, entorno protegido, aislamiento rootless y recursos probados |

El dueño pidió trabajar sobre Boca Socios real en vez de un laboratorio
funcional con página ficticia. Los tests de componentes permanecen offline y
**no se cuentan como prueba del sitio**. #27 dio lugar a un worker ya integrado
con Chromium arrancado en CI sin red; #11 mantiene pendiente la medición de una
sesión sin carga a Boca.
No se simularán varias visitas a la web del tercero para extrapolar capacidad.

## Límites antes de una BETA operativa

1. El diseño #28 fue revisado técnicamente y fusionado. #31 no expone
   formulario ni endpoint, ni autentica administrador. Faltan TLS, CSRF,
   sesiones, identidad de socio única verificada, baja completa,
   backup/restore y rotación de master key. **No cargar contraseñas todavía**.
2. El panel #29 recibe datos inyectados; no tiene API autenticada ni pantalla
   de alta. La UI accesible no acredita acceso seguro desde tablet.
3. El outbox #34 es local y durable, pero no entrega Telegram ni comparte una
   transacción con la intención de ticket. Requiere retención/purga acotada y
   reconciliación ante resultados ambiguos.
   #38 impide una **segunda concesión local** tras un intento ambiguo, pero
   no puede impedir llamadas externas fuera del guard ni confirmar una compra
   en Boca. Falta vincular una sola identidad de socio real al ID interno.
4. #33 es un observador anónimo opt-in corregido para visitar exactamente
   `/auth/login`. Una visita manual directa con navegador normal mostró ese
   formulario sin completar datos, pero **el script con JavaScript deshabilitado
   no se ejecutó contra Boca**. Puede devolver `unknown`; cola, acceso
   autenticado, elegibilidad, sector y reserva siguen sin validar.
5. Docker CI construye el controlador y, en #43, una imagen worker separada
   cuyo Chromium arrancó y cerró sin red. #44 midió **un arranque offline**
   en CI, sin inferir el consumo de una visita real ni del droplet. Faltan
   sandbox en el kernel de destino, egress acotado, scan de imagen y canal
   privado de credenciales para cualquier BETA real. Verificar el estado
   actual de #10 y de los workflows en GitHub; los checks históricos no
   sustituyen revisión técnica de los candidatos actuales.
6. #40 permite recifrar datos sintéticos y rechazar escritores con versión
   vieja. No se ha probado backup/restore cifrado, custodia, compatibilidad de
   arranque con versión nueva ni retiro seguro de claves. El runtime por
   defecto continúa en versión `v1` y el servicio de recifrado está apagado.

**GO:** desarrollo, revisión técnica y CI en ramas. **NO-GO:** credenciales
reales, reservas, notificaciones externas y merge sin revisión registrada o
checks exactos. Un despliegue de **simulación solamente** puede proceder por
Actions bajo la dirección permanente del dueño una vez probados gates de
imagen, SHA, entorno, SSH, rootless, capacidad y servicio. Una fuente externa
fallida se informa con hora y semáforo verde/amarillo/rojo/desconocido tras el
diagnóstico acotado de Actions; no bloquea por sí misma ese despliegue ni
justifica repetirlo. Un fallo en el host exige inventario de disco/inodos y
limpieza por Actions sólo de remanentes Boca descartables y sin uso.

## Revisión accesible

Consultar el diseño ya revisado en
[#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28),
luego los PRs de la tabla en orden de dependencia. En cada PR usar
«Files changed» y «Checks» y registrar la revisión técnica del agente con
SHA exacto y hallazgos resueltos; no llamar
a eso aprobación humana independiente. La CI apilada no sustituye la
revisión del PR fuente.
No hace falta ejecutar comandos en el droplet ni copiar datos de socios al
portapapeles para esta revisión.

## Revalidación del contrato #35 — 2026-10-29 ART

Sobre `main` `37a1b6199f86e9011b7a2dcc73535c76585964e3`, la PR #36 añade
el puerto estructural que acepta outbox en memoria o SQLite, conserva las
validaciones previas de alias y tiempo, y prueba alta interna ficticia,
intención única, aviso durable y panel redactado. Una regresión concurrente
demostró dos invocaciones del navegador ficticio con alias de un socio; el
coordinador ahora concede una sola ejecución local por socio y rechaza la
segunda antes de ese navegador. La barrera se libera también ante fallo.
Esta protección vive sólo en esa instancia; #38 todavía no está integrada ni
conectada al flujo y no se afirma intento único externo o entre procesos.

La medición offline de Chromium #44 y el scan de imagen #55 ya forman parte
de `main` en este corte. Ninguno prueba la capacidad del droplet o una
reserva de Boca. El dueño difirió todo trabajo de backup/restore hasta una
versión productiva fiable; no forma parte de #36 ni de la primera instalación
de simulación. Las credenciales reales siguen deshabilitadas. La evidencia
de pruebas y Actions de la HEAD exacta de #36 queda en su PR; los SHA y
cifras anteriores de este archivo siguen como registro histórico.
