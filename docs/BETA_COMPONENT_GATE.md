# BETA de componentes: gate de integración #35

**Fecha:** 2026-10-28 (America/Argentina/Buenos_Aires). **Estado:** rama de
verificación, sin merge a `main`, despliegue ni acceso autenticado a Boca.

**Actualización de continuidad:** [PR #36](https://github.com/mbalbo2023/boca-socios-assistant/pull/36)
integra componentes; [PR #38](https://github.com/mbalbo2023/boca-socios-assistant/pull/38)
añade el guard de intento único y [PR #40](https://github.com/mbalbo2023/boca-socios-assistant/pull/40)
el recifrado interno. Son **borradores apilados**, no una versión fusionada.
En otra rama, [PR #33](https://github.com/mbalbo2023/boca-socios-assistant/pull/33)
corrige la ruta pública y [PR #43](https://github.com/mbalbo2023/boca-socios-assistant/pull/43)
construye el worker Chromium. Esos cambios **no** están incorporados en el
árbol de esta rama ni en sus 157 pruebas. [PR #44](https://github.com/mbalbo2023/boca-socios-assistant/pull/44)
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

La integración de estos snapshots no tuvo conflictos de código. El PR #34
partió de una HEAD anterior de #30; la regresión posterior del vault de #30
se incorporó explícitamente. Las ramas de origen continúan abiertas para
revisión independiente.

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
en ambos jobs. En **esta rama** el build sigue siendo sólo del controlador.
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
| 1 | Revisión humana de #28 y seguridad de identidad/admin/TLS | Pendiente; bloquea formulario expuesto y claves reales |
| 2 | Revisión de cada PR fuente y activación verificable de protección `main` (#10) | Pendiente; bloquea merge de borradores |
| 3 | #36 → #38 → #40 y CI de la HEAD de integración final | CI verde en cada HEAD; revisión humana pendiente; no habilita operaciones externas |
| 4 | Worker aislado #27 y una observación **anónima** de la portada real con egress acotado | #43 pasa smoke offline y #33 apunta a `/auth/login`; falta ejecución del script con egress de sistema acotado |
| 5 | Canal privado, identidad externa única, backup/restore, cuenta autorizada y reconciliación de Boca | Pendiente; impide credenciales reales y reserva |
| 6 | Despliegue Docker exclusivo Boca por Actions | Requiere aprobación específica posterior con SHA, digest y recursos |

El dueño pidió trabajar sobre Boca Socios real en vez de un laboratorio
funcional con página ficticia. Los tests de componentes permanecen offline y
**no se cuentan como prueba del sitio**. #27 tiene un worker en borrador con
Chromium arrancado en CI sin red; #11 mantiene pendiente la medición de una
sesión sin carga a Boca.
No se simularán varias visitas a la web del tercero para extrapolar capacidad.

## Límites antes de una BETA operativa

1. #28 requiere revisión humana del diseño. #31 no expone formulario ni
   endpoint, ni autentica administrador. Falta TLS, CSRF, sesiones, identidad
   de socio única verificada, baja completa, backup/restore y rotación de
   master key. **No cargar contraseñas todavía**.
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
   sandbox en el kernel de destino, egress acotado, scan de imagen,
   canal privado de credenciales ni workflow de despliegue aprobado. #10 no tiene protección de
   `main` verificada. Ningún PR tiene revisión humana registrada.
6. #40 permite recifrar datos sintéticos y rechazar escritores con versión
   vieja. No se ha probado backup/restore cifrado, custodia, compatibilidad de
   arranque con versión nueva ni retiro seguro de claves. El runtime por
   defecto continúa en versión `v1` y el servicio de recifrado está apagado.

**GO:** desarrollo, revisión y CI en ramas. **NO-GO:** credenciales reales,
reservas, notificaciones externas, merge sin revisión o despliegue. El dueño
recibirá una solicitud separada y concreta para desplegar después de cerrar
los gates, con SHA, digest y recursos; cualquier operación del droplet será
por GitHub Actions exclusivo de Boca.

## Revisión accesible

Abrir primero [#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28)
para revisar el diseño de alta, luego los PRs de la tabla en orden de
dependencia. En cada PR usar «Files changed» y «Checks» y registrar la
aprobación humana de una persona distinta del autor. La CI apilada no sustituye
la revisión del PR fuente.
No hace falta ejecutar comandos en el droplet ni copiar datos de socios al
portapapeles para esta revisión.
