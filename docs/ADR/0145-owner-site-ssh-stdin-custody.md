# ADR 0145 — Transporte privado por stdin para owner y Site en Actions

**Estado:** propuesta de regresión R21, **NO_GO_ENROLLMENT**; no es código
desplegado. Alcance de tests/ADR independiente del escritor exclusivo de
`.github/workflows/boca-first-deploy.yml`. RCA constatado en
[#321 / 6649986548](https://github.com/mbalbo2023/boca-socios-assistant/issues/321#issuecomment-6649986548).
Checkpoint canónico: [A45-R20](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6649937545).

## Hallazgo verificable, no incidente de filtración

En el workflow protegido de `main=cabce9f1e452e63ded115f447559a358dc0f4d1b`
y candidato #319 R17, los comandos remotos se elaboran con `shlex.join`.
Esto sitúa el `BOCA_OWNER_ENVELOPE` durante owner-install, el
`BOCA_SITE_ENVELOPE` durante site-install y el identificador/origen del
dueño durante owner-enroll y fases BETA en el **argv del proceso SSH**.
El material puede ser observable por mecanismos de inspección de procesos
del runner y del host remoto; citar `shlex.join` como escape de shell no
prueba confidencialidad. **No hay evidencia de extracción o filtración
real**. No se consultó ninguna clave, input o sobre verdadero.

## Contrato propuesto (código-only, pendiente de implementación)

1. Construir un comando SSH remoto **constante y revisado**, independiente
   del sobre, sujeto, origen, digest, fase y demás valores de ejecución.
   Ninguno de ellos entra en `ssh argv`, argumentos de un shell intermedio,
   `ps`, `/proc/*/cmdline` ni en `GITHUB_STEP_SUMMARY`.
2. El proceso emisor lee el helper `host_first_deploy.py` y las coordenadas
   del entorno protegido del step, valida operación/presencia y construye un
   único frame binario **versionado, limitado de tamaño y con SHA-256** sobre
   script + argv; transmite por **stdin** de la única sesión SSH existente.
   La salida/errores son recibos acotados y redaccionados; nunca contienen
   valores de input, tokens ni sobres. No se confunde un hash con secreto
   suficiente para autenticar el host.
3. El proceso `ssh` recibe entorno mínimo (`env -i`) o deshereda de modo
   explícito `BOCA_OWNER_ENVELOPE`, `BOCA_SITE_ENVELOPE`,
   `BOCA_BETA_OWNER_SUBJECT`, `BOCA_BETA_PANEL_ORIGIN` y cualquier secreto
   Telegram co-residente. No exponerlos tampoco en argumentos del emisor.
4. El receptor remoto valida magic, versión, longitud máxima, longitud
   exacta, integridad, JSON schema, fase allowlist y opciones permitidas
   **antes** de ejecutar en memoria el helper. Frame ausente, corrupto,
   ambiguo, duplicado, truncado, extra bytes o fase desconocida implica
   rechazo sin efectos; sin fallback a la antigua vía argv.
5. Mantener el script integrado por bytes revisados y las identidades,
   receipts, GO exact-SHA, lease Boca, origen `localhost:8443`, rootless
   y limpieza selectiva existente. No añadir archivos de secretos, puertos,
   HTTPS, credenciales reales, navegación Boca o intervención manual en host.
6. Tests con **sólo sentinelas sintéticos**: verificar argv/environ de un
   SSH ficticio, redacción de recibos y logs, roundtrip exacto, frames
   corruptos, detección de fases y rutas, y preservación de contratos del
   helper. Se conservan o adaptan los 19 casos previos de
   `tests/test_owner_enrollment_argv.py` para comprobar parámetros internos
   reconstruidos, no argv remoto plaintext.

El frente #315 Telegram es dueño independiente de sus fases y patrón
`telegram_ssh_transport`; no editar simultáneamente el mismo workflow.
El owner de R21 agregará la implementación owner/Site sólo tras la entrega
explícita de ese ownership. El test estructural inicial
`tests/test_owner_site_ssh_secret_transport.py` debe quedar **RED** contra el
workflow vulnerable y **GREEN** únicamente tras transporte/fase protegida
verificados. No se deshabilita ningún gate para fingir verde.

## Relación con Opción B / SQLite legacy

La sesión persistente de Chrome usa exclusivamente
`/data/boca_owner_session.sqlite3`, dentro del volumen Boca existente,
según ADR0137 y PR DRAFT #322. Jamás agregar SQL 0008 bajo
`storage/migrations` ni a `_MIGRATIONS` del lector legacy. El RCA P0
de compatibilidad demuestra que el controller instalado reconoce 0001–0007;
un 0008 aplicado al controller impediría recuperación sin riesgo al usuario.
El nuevo test fija esta separación como regresión y **no migra ninguna base**.

## Evidencia y límites

El trabajo R21 comienza en candidato #319 R17 `24dc03352c19ee056e3dc023ba049000f2f2eb11`,
apoyado en main físico `cabce9f1e452e63ded115f447559a358dc0f4d1b`.
Resultados de pruebas, SHA del PR y Actions pendientes se registrarán en
GitHub con Regla84 después del commit. Hasta corregir todas las rutas
sensibles y tener CI/security exact-SHA, **NO_GO_ENROLLMENT**. Continúan
independientes NO_GO_SECURITY de imagen browser y NO_GO de host/cutover.
No hubo merge, release, host dispatch, instalacion ni aceptación física.
