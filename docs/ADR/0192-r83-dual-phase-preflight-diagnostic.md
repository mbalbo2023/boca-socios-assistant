# ADR 0192 — R83: doble diagnóstico acotado del preflight #807

**Fecha:** 2026-11-07 ART. **Estado:** candidato CODE_ONLY verificado localmente, GO de cuatro disciplinas para PR; sin GO físico.
**Owner:** [#417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417); continuidad [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Hecho probado y límite de la evidencia

El preflight #807 (`42341290485`) acabó con `failed_phase=CLEANUP cleanup=INDETERMINATE`; el inventario sin escrituras #809 encontró su contenedor exacto **detenido**. La recuperación única #811 (`42344899979`) lo retiró y verificó legacy saludable y terceros intactos, con `retry=NO_GO cutover=NO_GO`. En el R80 histórico, `execute()` reemplaza la fase original cuando la limpieza o el control final del legacy falla. Dos errores iniciales distintos, seguidos por limpieza fallida, generaban un mismo recibo. Por ello **la causa física original de #807 sigue indeterminada**. No atribuirla a `docker stop`, `docker rm` o a la red sin prueba.

## Decisión de Arquitectura, QA, Infra y CI/CD

Se aplica **instrumentación diagnóstica exclusivamente CODE_ONLY**, sin nuevos efectos ni reintentos sobre el host:

1. Conservar la clasificación histórica `failed_phase=... cleanup=...` para los consumidores existentes, pero añadir `primary_failed_phase=... cleanup_failed_stage=...` al recibo de error, en una única línea ASCII acotada.
2. `primary_failed_phase` indica la fase de la **primera excepción**, conservada incluso si el cierre del seccomp, la limpieza Docker o la inspección final del legacy también fallan. Valores: `NONE|ATTEST|GHCR_PULL|SECCOMP_ENTER|WORKER_CREATE|WORKER_START|WORKER_BOUNDARY|UNVERIFIED`. `SECCOMP_ENTER` evita atribuir a GHCR_PULL un error del seccomp local después de descargar las imágenes.
3. `cleanup_failed_stage` indica el **primer** problema de compensación constatado; valores `NONE|TEMP_SECCOMP|PS|INSPECT|OWNERSHIP|STOP|RM|POST_ID|LEGACY|UNVERIFIED`. El valor `NONE` no certifica el host: sólo `cleanup=VERIFIED` y el recibo PASS exacto lo hacen.
4. Una falla en la subfase de cierre sigue produciendo `failed_phase=CLEANUP cleanup=INDETERMINATE` (compatibilidad y fail-closed), **sin borrar** el primer fallo. Una falla primaria con limpieza íntegra conserva `failed_phase=<fase> cleanup=VERIFIED`.
   La clasificación secundaria conserva el **primer fallo de compensación**; si falla adicionalmente la revalidación legacy, todo sigue NO_GO/INDETERMINATE aunque no se emita un segundo substage. No se afirma postflight saludable en un recibo fallido.
5. El step de Actions interpreta exclusivamente la línea exacta de `NO_GO`, ASCII, límite explícito, una sola línea, orden fijo y enums allowlist; para cualquier malformación, duplicación, truncamiento, transporte fallido o salida inesperada informa `UNVERIFIED`, `NO_GO`, `no_retry=1`. El recibo `PASS` permanece byte por byte igual.
6. Sin stderr, excepciones crudas, payloads Docker, secretos, JSON completos ni identificadores del host en el diagnóstico. No incorporar a la salida ningún texto controlado por el servidor.

## Alternativas rechazadas

- **Supuesto arreglo a `stop`/`rm`:** no hay evidencia que identifique esa causa; cambiaría efectos sobre el host, prohibido sin RCA.
- **Reejecutar #807 para recopilar logs:** contra anti-replay, puede recrear residuos; prohibido.
- **Usar la recuperación #811 como PASS preflight:** #811 sólo acredita retirada exacta y no verificó la frontera de runtime de un worker nuevo.
- **Agregado `cleanup=PROBE`:** no distingue las seis etapas del RCA y perpetúa el diagnóstico indeterminado.

## R83: separación estricta de transporte, sin aumentar los límites de Cutover

QA descubrió que añadir el diagnóstico a las fuentes del paquete Cutover
excedía el presupuesto de **860.000 bytes descomprimidos** (medición inicial
863.116 bytes, +3.116); la misma versión ocupaba **213.204 bytes comprimidos**
frente al límite de 512.000. Las fuentes siguieron creciendo levemente al
agregar la clasificación `SECCOMP_ENTER`.

Arquitectura, Infra y QA rechazaron dos atajos: compactar el `finally` crítico
para recuperar >3 KB de forma ilegible, o elevar el límite de 860.000 bytes,
que **sí sería una relajación técnica** aunque preservara el cap comprimido.
La opción consensuada **C** separa el preflight:

- El Cutover completo deja de incluir `host_cutover_worker_preflight.py` y su
  modo de ejecución. Conserva exactamente **860.000/512.000 bytes**,
  los módulos de Cutover, su verificador de SHA256, modos y reglas GO_B.
- El **preflight sólo** recibe siete entradas: `__main__.py`, seccomp fijo,
  `boca_socios/__init__.py`, `host_first_deploy.py`, `host_boca_cleanup.py`,
  `scripts/__init__.py` y `host_cutover_worker_preflight.py`. Valores iniciales
  medidos al cierre: **467.201 bytes de fuente y 100.597 bytes ZIP**; caps propios
  **480.000/128.000 bytes**.
- El bootstrap usa el **modo inmutable** `cutover-worker-preflight` para
  seleccionar la allowlist y el presupuesto preflight **antes** de ejecutar
  el ZIP por memfd. Ni el paquete completo ni el recuperador son aceptados
  en modo preflight, ni el ZIP preflight en modos Cutover/recovery. Los dos
  marcadores recovery #795 y #807 y sus límites 256.000/128.000 no cambian.
- No se altera ninguna operación de Docker, permisos, CPU/RAM/PIDs, puerto,
  seccomp, actor, environment, SHA/release, lease, anti-replay o GO_B.
  El hash del ZIP Cutover sí cambia por el retiro de un módulo: **cualquier
  binding de GO_B/PREPARE previo queda obsoleto**, nunca se reutiliza.

Pruebas obligatorias: tamaños exactos y ±1, whitelists, hashes, ZIP mode,
symlink/entradas especiales, tres perfiles por los tres modos de bootstrap,
import de ZIP preflight con `python -S` y cero efectos de host, el PASS exacto
sin modificar. Referencias: ADR 0176 justificó históricamente ajustar un cap
de código; ADR 0188 dejó explícitamente inalterado el límite del Cutover y
**R83 lo respeta**.

## Evidencia CODE_ONLY antes de PR

El builder actual generó tres variantes SHA256 verificadas por su verificador
memfd independiente: full **39 entradas, 844.099 B fuente / 207.943 B ZIP**;
preflight **7 entradas, 467.201 / 100.597 B**; recovery **7 entradas,
160.152 / 40.471 B**. Cada una cumple su límite propio sin tocar los dos
caps históricos del Cutover. El archivo completo histórico R81 conserva su
digest documentado; R83 fija un **nuevo** digest en la regresión porque el
retiro del script/mode cambia deliberadamente los bytes. No arrastrar PREPARE
o GO_B atados al digest antiguo.

QA reprodujo RED para primer fallo enmascarado, salida/seccomp y subetapas;
TDD GREEN, además de matriz adversarial de ZIP/digest/allowlist y cruce de
las tres variantes con `python -S` y `os.memfd_create` instrumentado. El
verificador de Actions ahora limita la lectura de recibos NO_GO a 257 bytes,
y de PASS a exactamente un byte más que el recibo esperado, sin exponer
salida remota cruda. Los cuatro dictámenes técnicos (QA, Arquitectura,
Infraestructura y CI/CD) son **GO CODE_ONLY**, Critical=0 e Important=0.
No constituyen prueba física ni autorizan otro preflight.

## Condiciones para una operación futura

RED/GREEN de fallos primario+cleanup, subetapas, parser y empaquetado aislado; suite completa; Ruff/MyPy/YAML/política; revisión independiente QA/Arquitectura/Infra/CI; PR único, 4/4 Actions, merge, cero PR abiertos, postmerge GREEN; release dual controller/browser **del SHA nuevo y exacto**. Sólo después, decisión técnica distinta para un nuevo `GITHUB_RUN_ID` de preflight protegido. Ni esto ni un futuro PASS sustituyen GO_B/PREPARE/APPLY ni validación de Chrome; todas las operaciones reales siguen sólo por GitHub Actions.
