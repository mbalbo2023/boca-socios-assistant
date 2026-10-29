# Auditoría de infraestructura y cableado BETA — 2026-10-29

**Alcance:** lectura del repositorio público, PRs draft, Actions y un ensayo
local de integración. No hubo acceso al droplet, secretos, GHCR publicado ni
tráfico a Boca. Esta auditoría no afirma que el host tenga una configuración
que no se pudo observar. Las propuestas de PR aún no están en `main`.

## Evidencia verificable

- `main` seguía en `09f390e483a9ad93caf460cb6e161fee22e6bd8d`, con
  `protected:false` y `GET /rulesets` igual a `[]`. El diseño de alta
  [#28](https://github.com/mbalbo2023/boca-socios-assistant/pull/28) y la
  pila de deploy no tenían revisión independiente al corte.
- Pila de infraestructura draft:
  [#57](https://github.com/mbalbo2023/boca-socios-assistant/pull/57) →
  [#59](https://github.com/mbalbo2023/boca-socios-assistant/pull/59) →
  [#61](https://github.com/mbalbo2023/boca-socios-assistant/pull/61) →
  [#63](https://github.com/mbalbo2023/boca-socios-assistant/pull/63) →
  [#66](https://github.com/mbalbo2023/boca-socios-assistant/pull/66) →
  [#69](https://github.com/mbalbo2023/boca-socios-assistant/pull/69) →
  [#71](https://github.com/mbalbo2023/boca-socios-assistant/pull/71) →
  [#73](https://github.com/mbalbo2023/boca-socios-assistant/pull/73).
  Actions de #73 en HEAD `65657cedf8ebdc4f082acf7dcbb1c956a52bde56`:
  [CI 40939697074](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40939697074),
  [scan 40939697128](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40939697128),
  [release 40939697150](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40939697150)
  y [deploy smoke 40939697151](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40939697151)
  exitosos en sus jobs de PR; publicación y operación de host omitidas.
- Ensayo local inicial: #71 + #42 + #44 +
  #47. Merge limpio; inicialmente 1 test falló y 272 pasaron por contaminación
  del `umask` global en tests de runtime. [#72/#73](https://github.com/mbalbo2023/boca-socios-assistant/pull/73)
  aísla la llamada sin modificar el runtime. Repetición: `uv sync --frozen`,
  Ruff, mypy de 33 módulos, política de aislamiento y **273 tests PASS**.
  La composición se publicó después como
  [PR draft #77](https://github.com/mbalbo2023/boca-socios-assistant/pull/77),
  HEAD `803996176f3b5dfa858e0bb967df23cad9d74eee`:
  [CI 40940923866](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40940923866)
  validó tests, Compose, lint, tipos, política, auditoría de Actions,
  imagen controller y worker Chromium offline; [scan 40940923880](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40940923880),
  [release PR 40940923843](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40940923843)
  y [deploy smoke 40940923944](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/40940923944)
  también pasaron; publish y host quedaron omitidos. Es CI del árbol
  combinado, no release en `main` ni recorrido de Boca.

## Controles y brechas

| Área | Evidencia de código/CI | Brecha antes de declarar GO |
| --- | --- | --- |
| Imagen/controller | Base Python Alpine fijada por digest, lock, escaneo HIGH/CRITICAL y smoke del controller en runner; Compose nonroot, root read-only, sin puertos, 0,5 CPU/256 MiB/64 PIDs. | Ningún digest GHCR fue publicado y ejecutado en el host. Escaneo de imagen y health sintético no acreditan seguridad/función en producción. |
| Motor bajo demanda | `BOCA_ENGINE_MODE=off` obligatorio y rechazado si cambia; #69 diagnostica estado sin arrancar navegador; #71 exige postflight antes de `PASS`. | No hay operación revisada para prender un motor real; `diagnostic` sólo lee salud. El controller saludable seguirá inerte. |
| Gobierno de GitHub | Acciones fijadas por SHA y publicación/host sólo por `workflow_dispatch` desde `main` y actor dueño. | `main` carece de ruleset activo; reviews independientes ausentes; entornos/revisores/restricción de rama no verificados. La variable `ready` **no** demuestra aprobación. GitHub puede crear un entorno referenciado sin reglas. |
| Identidad Docker en host compartido | Se propone `boca-deploy` UID 10001 con acceso a Docker y script acotado al namespace Boca. | **Riesgo alto condicionado al host:** si ese usuario accede al daemon rootful por el grupo/socket `docker`, Docker documenta privilegios equivalentes a root. Un Compose project o una validación de script no limita lo que podría hacer una credencial SSH comprometida. Aún no se sabe cómo está configurado el daemon del droplet. |
| Recursos y navegador | Un Chromium offline #44 midió una única corrida de CI bajo 1 CPU/768 MiB/128 PIDs; no se añadió al Compose de deploy. | Esa muestra no dimensiona el droplet ni sesiones reales; el límite 256 MiB es sólo del controller. Sin cupo/egress del navegador medidos en host separado, no añadir worker al host compartido. |
| Clave, base y respaldo | Clave host propuesta owner-only 0400; DB con credenciales AEAD; #47 ensaya backup cifrado/restauración offline. | Sin custodia externa ni política de retención/borrado, ni prueba de restauración de datos reales autorizada. No ingresar contraseñas todavía. |

Fuentes primarias: [Docker: grupo `docker` y root](https://docs.docker.com/engine/install/linux-postinstall/),
[Docker rootless](https://docs.docker.com/engine/security/rootless/),
[Compose secrets sobre file bind mount](https://docs.docker.com/reference/compose-file/services/#secrets),
[GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[Playwright Docker](https://playwright.dev/python/docs/docker).
Las capacidades de proveedores no prueban que el droplet ya las aplique.

## Cableado de módulos: qué haría realmente el primer deploy

| Línea | Existe en PR draft | Conectado al controller que instalaría #63/#71 |
| --- | --- | --- |
| Vault/SQLite y salud | Sí; `runtime.py` abre clave, migra DB y espera señal. | Sí, en modo `simulation`, motor `off`. |
| Simulador/estado, intención, guard y outbox | #42 y dependencias, probados offline y en CI combinada #77. | No. El entrypoint no crea ni invoca esos servicios. |
| Panel accesible/Telegram/alta privada | Panel de estados simulados #29, servicio interno #31, outbox #34; diseño #28 pendiente. | No hay servidor autenticado/TLS ni canal de alta/avisos externos. |
| Chromium/observador | #33→#43→#44, imagen separada y smoke offline. | No hay worker en Compose ni sesión abierta; nunca se probó login/cola/reserva real. |
| Backup cifrado | #47 offline. | Sin scheduler, almacenamiento ni recuperación operativa aprobada. |

Por tanto, instalar el controller sería un **primer despliegue de fundamento
inerte**, no una BETA funcional. La suite de módulos no prueba cableado
runtime, autenticación, elegibilidad, entrega de avisos ni reserva externa.

## Decisiones y pruebas necesarias

1. Revisar independientemente los PRs fuente y el diseño #28; activar y
   verificar reglas de `main` (#10) y ambos entornos con revisores y ramas
   restringidas. GitHub documenta que el job sólo recibe secretos después de
   superar las reglas realmente configuradas.
2. Resolver la frontera del daemon Docker antes de entregar SSH a Actions:
   verificar tipo de daemon/socket y permisos reales; decidir con revisión si
   Boca usa daemon rootless exclusivo, un host aislado o un operador limitado
   que no exponga el daemon rootful compartido. Probar compatibilidad de
   Compose, claves, volúmenes, capacidad y recuperación en un entorno
   separado. No cambiar el Docker daemon compartido a ciegas.
3. Publicar imagen escaneada de `main` por digest y confirmar accesibilidad
   GHCR desde el host sólo tras revisar la pila. Una autorización de primer
   install debe nombrar SHA, digest, servicio, recursos y ventana, con
   identidad SSH y espacio del host verificados. Ningún PR despliega.
4. Etiquetar ese hito como controller inerte. Para BETA operativa faltan
   interfaz privada accesible, autenticación de dueño/TLS/CSRF, identidad de
   socio única, custodia/restauración de claves, conexión de módulos y un
   diseño de observación real y reserva con consentimiento/revisión. Cada
   acción externa precisa evidencia y límites propios; no se infiere de CI.

**Decisión actual: NO-GO para primer deploy y BETA.** El hallazgo de acceso
root-equivalente es una condición a comprobar y resolver, además de los gates
ya abiertos. No se elude cola ni se solicitan credenciales por conversación.
