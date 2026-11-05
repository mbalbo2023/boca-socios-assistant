# ADR 0145 — Transporte privado por stdin para owner y Site en Actions

**Estado:** implementación code-only R21 sobre candidato #319; **NO MERGE,
NO RELEASE, NO HOST, NO DEPLOY**. Los tests RED iniciales del PR #335
preservan la evidencia y los tests GREEN posteriores demuestran la corrección
mínima owner/Site. No es aceptación del droplet. RCA constatado en
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

## Contrato implementado (código-only)

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

El módulo nuevo `src/boca_socios/owner_site_ssh_transport.py` implementa el
emisor y bootstrap remoto exclusivamente de stdlib con magic
`BOCA-OWNER-SITE-SSH-STDIN-V1`, longitud de frame máxima 1.200.000 bytes,
helper UTF-8 máximo 1.048.576 bytes, checksum SHA-256 y esquema JSON estricto.
El receptor sólo permite `owner-prepare/install/verify`,
`owner-enroll-start/wait/finish` y `site-prepare/install/verify`; preserva el
`--` antes de datos que comiencen con guion. Reconstituye `sys.argv` **en
memoria** del mismo proceso remoto, no como argumento de su invocación OS.
El shell recibe `remote_command` estático, y `emit` lee las coordenadas desde
variables del runner para enviarlas por el único stdin SSH ya autorizado.
`env -u` deshereda del SSH bearer owner, Site, subject/origin y Telegram.
Se preservan las mismas fases, host CLI y patrón de recibo; Site ahora captura
su recibo y sólo publica éxito tras formato cerrado. Cualquier error de
transporte produce estado fijo sin imprimir valores.

La implementación toca **cinco pasos** owner/Site (la custodia es un paso
para tres fases owner, tres fases Site y tres pasos de enrolamiento Chrome).
No toca las rutas Telegram ni el helper `telegram_ssh_transport`, que el
frente #315 integró antes de transferir ownership del workflow. La cobertura
del viejo `test_owner_enrollment_argv` se divide: **11 invocaciones directas
históricas restantes** aún validan parser/opciones, y nueve fases owner/Site
prueban argv reconstruido detrás del frame. No hay test silenciado.

**Deuda P2 explícita tras priorización funcional de Tincho:** permanecen
11 bloques BETA/browser con `BOCA_BETA_OWNER_SUBJECT`/origen en SSH argv
mediante `shlex.join` que **no forman parte de este parche mínimo de custodia**.
El test inicial que inventariaba 20 rutas se reconcilia con el nuevo alcance:
comprueba ahora la confidencialidad exacta de las cinco rutas owner/Site y
conserva inventario de al menos 15 pasos sensibles para impedir que
desaparezcan silenciosamente de revisión. No afirmar que todos los SSH
están saneados. La remediación P2 necesita issue/PR/ownership posterior.
El test estructural `tests/test_owner_site_ssh_secret_transport.py` tuvo
**3 FAIL / 1 PASS** de reproducción antes de modificar el workflow; queda
GREEN sólo cuando los cinco caminos protegidos cumplen el nuevo contrato.

## Relación con Opción B / SQLite legacy

La sesión persistente de Chrome usa exclusivamente
`/data/boca_owner_session.sqlite3`, dentro del volumen Boca existente,
según ADR0137 y PR DRAFT #322. Jamás agregar SQL 0008 bajo
`storage/migrations` ni a `_MIGRATIONS` del lector legacy. El RCA P0
de compatibilidad demuestra que el controller instalado reconoce 0001–0007;
un 0008 aplicado al controller impediría recuperación sin riesgo al usuario.
El nuevo test fija esta separación como regresión y **no migra ninguna base**.

## Evidencia y límites

El trabajo R21 partió del candidato #319 R17
`24dc03352c19ee056e3dc023ba049000f2f2eb11`, y recibió el último
candidato integrado #319 SHA `59e5102a3a3118e9da67290652900f3790a77fa5`
(Telegram #317 incluido). El main físico histórico era
`cabce9f1e452e63ded115f447559a358dc0f4d1b`.
**QA local de la corrección (árbol previo a commit):**
`uv run --offline pytest -q` **3146 PASS +34 subtests PASS** (123,81 s),
focal `test_owner_enrollment_argv.py` + nuevo transporte **66 PASS**,
Ruff lint PASS, Ruff formato **467 archivos PASS**, MyPy **113 fuentes
PASS**, política `POLICY_PASS` y `git diff --check` limpio. No se alteró
ninguno de los dos módulos BLACKBOX. El SHA remoto final y Actions
exact-head deben registrarse con Regla84; estas pruebas son solo offline.
**NO_GO de host** y seguridad/GO de BETA siguen separados; no confundir
tests del transporte con autorización para efectuar la custodia real.
No hubo merge, release, host dispatch, instalacion ni aceptación física.
