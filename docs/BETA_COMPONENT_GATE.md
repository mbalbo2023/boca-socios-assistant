# BETA de componentes: gate de integración #35

**Fecha:** 2026-10-28 (America/Argentina/Buenos_Aires). **Estado:** rama de
verificación, sin merge a `main`, despliegue ni acceso autenticado a Boca.

## Candidatos incorporados

| PR | HEAD | Función validada en el árbol combinado |
| --- | --- | --- |
| #30 | `ed69fc2d94843d3835dea06b53033e4f3198cd36` | DB, cola, navegador contractual, avisos seguros |
| #34 | `cfb1abd8d360714e3801554985e1d01fc483e899` | Outbox SQLite, reinicios y leases |
| #29 | `6b1784c715a0b71ef28f8d0785bab2bc138eb42e` | HTML accesible de estados ficticios |
| #28 + #31 | `64452c18a3a74a5b35c81f45d8a42463de140e1f` + `5050c88ea236994abf25c432ab5bfac73f514b70` | Diseño y servicio interno de alta cifrada |
| #33 | `0f68e16698dc8d4aca5998b152669a2f94d51788` | Observador público opt-in, **no ejecutado contra Boca** |

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

**Calidad local:** `uv sync --locked`, Ruff lint/formato, mypy strict (25
módulos), pytest **144 passed**, política de aislamiento PASS. La rama de
verificación necesita sus propios dos jobs de GitHub Actions en la HEAD
exacta. No hay Docker local, navegador Chromium real ni prueba de rendimiento
medida aquí.

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
4. #33 es un observador anónimo opt-in. Puede devolver `unknown` si Boca
   renderiza el login con JavaScript, y no se corrió el script contra el
   servicio real. La única observación real fue la portada anónima documentada
   en `BOCA_PUBLIC_OBSERVATION_2026-10-28.md`. Cola, login, elegibilidad,
   sector y reserva siguen sin validar.
5. Docker CI construye el controlador independiente, pero no existe imagen
   medida de un worker de navegador, canal privado de credenciales, scan de
   imagen ni workflow de despliegue aprobado. #10 no tiene protección de
   `main` verificada. Ningún PR tiene revisión humana registrada.

**GO:** desarrollo, revisión y CI en ramas. **NO-GO:** credenciales reales,
reservas, notificaciones externas, merge sin revisión o despliegue. El dueño
recibirá una solicitud separada y concreta para desplegar después de cerrar
los gates, con SHA, digest y recursos; cualquier operación del droplet será
por GitHub Actions exclusivo de Boca.

## Revisión accesible

Abrir los PRs de la tabla en orden de dependencia, consultar «Files changed»
y los checks de la HEAD actual, y dejar la decisión de revisión en cada PR.
No hace falta ejecutar comandos en el droplet ni copiar datos de socios al
portapapeles para esta revisión.
