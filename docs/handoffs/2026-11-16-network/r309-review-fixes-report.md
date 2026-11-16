# R309 — Correcciones de revisión independiente

## Entrega y autorización

Commit inmutable: **25ed05ed05f9f7db47cdc489e69922ddc1450ec9**.
Base corregida: `bb0b0227a5d99616741f033d06f6f48b2a247b7e`.
Rama: `feature/529-r308-countdown`.
Autor separado: `/root/r309_author`, sin voto independiente.

Root comunicó NO_GO sobre la base y consenso root/Arquitectura/QA/Operaciones sobre tres correcciones mínimas, registradas **antes del nuevo código** en issue530, comentario **6903460039**. Se aplicaron recepción de code review y TDD focal. Este informe complementa el informe original; no cambia sus resultados históricos ni presenta la base rechazada como aprobada.

El nuevo commit modifica cinco rutas dentro del scope autorizado de diez:

- `.github/workflows/boca-first-deploy.yml`
- `src/boca_socios/host_telegram_maintenance.py`
- `src/boca_socios/host_telegram_status.py`
- `tests/test_r309_telegram_prepare_diagnose.py`
- `tests/test_r309_telegram_prepare_transport.py`

Los dos documentos WIP de root permanecen fuera del commit y no fueron editados por el autor. No hubo fetch/rebase/reset, push, PR, host, SSH, Docker daemon, proveedor ni Telegram. No se modificaron cotas, MOUNTS, fuentes instaladasR, BLACKBOX ni otros proyectos.

## 1. D3 — Adquisición mediante lectores existentes de R

`PUBLIC_OBSERVE_PROGRAM` ya no implementa su propia adquisición de bytes mediante `os.read` y apertura del archivo público. Usa las APIs reales existentes en R:

- `bootstrap._directory(Path('/data'), 10001)` para resolver y validar el padre de cada observación.
- `bootstrap._read(parent, name, 10001, maximum=1024)` para el documento público de recipient.
- `projection._read_admin_receipt(Path('/data') / name)` para el recibo administrativo.

El literal conserva guardas de identidad, metadata no-follow y witnesses antes/después para distinguir estado inválido, ausencia válida, lectura incierta y cambios observados. La ausencia se declara sólo tras ENOENT de la hoja bajo el padre validado por R. Los fallos inciertos de adquisición/dependencia son NOT_READ, y los bytes inválidos o excepciones no se exportan. Se mantienen los parsers de R, la validación de source declarada antes de compararla con R, y la fecha/run históricos sin rechazo por TTL300. No se usa `load_telegram_admin`, SQL ni fallback host.

La nueva prueba registra los eventos reales de llamada con `sys.setprofile`, comparando los objetos de código de `_directory`, `_read` y `_read_admin_receipt`. No reemplaza, envuelve ni copia sus validadores. Comprueba argumentos exactos y el orden de los lectores, con casos normal, EACCES del recipient, EIO del admin y EACCES del padre. Una comprobación AST adicional impide que el literal conserve adquisición propia mediante `os.read`/`os.fdopen`. Los fixtures sólo traducen I/O externo, incluyendo la ruta absoluta del documento admin usada por el lector de R.

## 2. D4 — Intérprete absoluto del helper

El productor del Cmd y su attestor usan exactamente:

```text
/app/.venv/bin/python -I -B -c <RECIPIENT_OBSERVE_PROGRAM literal>
```

La factory sigue siendo `recipient`; los cambios siguen limitados a su cola de comando. MOUNTS y el perfil restringido no cambian.

La regresión captura el Cmd realmente enviado a create. La variante manipulada sustituye el intérprete por `python`: debe rechazarse antes de start, conservar el CID, dejar `start_attempted=false` y retiro INDETERMINATE, sin stop/rm de una identidad no atestada. El positivo conserva el retiro RETIRED. Los negativos previos de tamper/incertidumbre y el límite de un helper también pasan.

## 3. D7/D10 — Transporte incierto visible como incompleto

La Action ahora examina `remote_rc` antes de publicar un frame de diagnóstico como resultado principal. Para `remote_rc!=0` con frame válido, la primera línea visible es:

```text
BOCA_TELEGRAM_PREPARE_DIAGNOSIS state=INCOMPLETE_NO_GO reason=TRANSPORT_UNVERIFIED prepare_authorized=0 adopt_authorized=0
```

El frame original se conserva íntegro sólo en la segunda línea, precedido por esta etiqueta inequívoca:

```text
BOCA_TELEGRAM_BACKEND_EVIDENCE_NON_AUTHORITATIVE transport=UNVERIFIED receipt=
```

La Action termina en fallo. Ninguna línea comienza con el prefijo de frame completo como resultado principal en ese caso. La evidencia backend conserva todos los campos, incluido CID y retiro, y queda explícitamente sin autoridad para afirmar completitud del transporte. Root confirmó esta alternativa mínima durante la ejecución. No fue necesario introducir verbos CLI, cambiar el codec, agregar fases o abrir un nuevo flujo host.

La regresión de la rama shell real ya no verifica sólo el exit. Comprueba el orden y contenido de las líneas, ausencia de frame principal no etiquetado y round-trip del frame original mediante el codec existente, incluyendo igualdad completa de la evidencia, CID exacto y retiro RETIRED.

| Entrada simulada a la rama real | Resultado comprobado |
|---|---|
| remote0 / verifier0 / OBSERVED_NO_GO válido | Resultado completo publicado; exit0 |
| remote7 / verifier0 / OBSERVED_NO_GO válido | INCOMPLETE_NO_GO / TRANSPORT_UNVERIFIED primero; evidencia backend no autoritativa; exit1 |
| remote0 / verifier2 | INCOMPLETE_NO_GO / TRANSPORT_UNVERIFIED; no publica el frame; exit1 |
| remote0 / verifier0 / prefijo incorrecto | Rechazo sin resultado completo; exit1 |
| remote0 / verifier0 / INCOMPLETE_NO_GO válido | Conserva el resultado incompleto; no afirma completitud; exit1 |

En todas las variantes se mantiene ausencia de PREPARED y del epílogo OWNER_ACCEPTANCE.

## RED/GREEN reales y comandos

Todos los logs están en `.superpowers/sdd/r309/`. Las corridas siguientes son focales y pueden solaparse; no se presenta su suma como una suite única.

### D4

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_diagnose.py -k review_d4
```

RED real: **2 failed, 63 deselected** (`review-red-d4.log`), porque create enviaba `python` relativo.

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_diagnose.py -k 'review_d4 or uncertainty or one_helper_empty'
```

GREEN real: **10 passed, 55 deselected** (`review-green-d4.log`).

### D3

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_diagnose.py -k review_d3
```

RED real: **4 failed, 65 deselected** (`review-red-d3.log`), porque el programa no llamaba a los lectores nativos requeridos.

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_diagnose.py -k 'review_d3 or d3_public or invalid_parent or historical_parser_valid or full_diagnosis'
```

GREEN real: **22 passed, 47 deselected** (`review-green-d3.log`).

### D7

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_transport.py -k actual_result_branch
```

RED real: **1 failed, 21 deselected** (`review-red-d7.log`), porque con remote7/verifier0 la primera línea seguía siendo el frame completo.

Mismo selector después de la corrección: **1 passed, 21 deselected** (`review-green-d7.log`). Ese test recorre las cinco variantes de la tabla.

### Integración directamente afectada y calidad

```text
.venv/bin/python -m pytest -q tests/test_r309_telegram_prepare_diagnose.py tests/test_r309_telegram_prepare_transport.py -k 'non_actionable or (uncertainty and public-drift) or zip_and_memfd or owns_one_real'
```

GREEN real: **11 passed, 80 deselected in 2.24s** (`review-green-integration.log`). Cubre recomendaciones conservadoras al usar los lectores de R, deriva pública A/B, la lease única y su cierre incierto, y el ZIP/CLI/memfd real bajo aislamiento. El caso de deriva pública se solapa con la selección D4; no se suman las corridas como casos distintos.

No se repitió la suite86, baseline, R308 ni tests históricos. El builder real se ejecutó mediante el único caso ZIP seleccionado para verificar y medir el contenido cambiado.

Calidad de los archivos cambiados: **Ruff clean**, **4 archivos con formato correcto**, **mypy sin incidencias en 2 archivos productivos**, y `git diff --check` limpio. Logs: `review-ruff.log`, `review-format.log`, `review-mypy.log`. La revisión del diff confirmó que los cambios productivos están limitados a las tres correcciones acordadas.

## Nueva medición del ZIP final

Medición del archivo realmente construido y ejercitado en la última corrida focal, después de las correcciones y del formato:

| Propiedad | Medida | Cota sin cambios |
|---|---:|---:|
| Entradas instaladas | 47 | 47 exactas |
| Fuentes agregadas | 490980 bytes | 500000 |
| Entrada individual más grande | 40833 bytes | 450000 |
| ZIP comprimido | 135443 bytes | 300000 |

Margen de fuentes: **9020 bytes**. Respecto del ZIP de `bb0b022`, el contenido de fuentes crece6 bytes y el ZIP27 bytes.

SHA256 del nuevo ZIP:

```text
16ddd612de408141176811ab6f2c7592cd74ea02055760dc6c7ae0e6b9dcfc60
```

Medidas: `.superpowers/sdd/r309/review-fixes-measures.json`.
Archivo probado: `.superpowers/sdd/r309/r309-review-installed.pyz`.

Los límites default, individual, agregado installed, ZIP y codec se mantienen. Tampoco cambia el algoritmo/umbral del compactador, el closure47 ni el presupuesto de CPU/RAM/PID. No se repitió el baseline default.

## Entrega a revisión

El selector continúa siendo **telegram-prepare-diagnose** y mantiene R/APPLY/incidente fijos. El nuevo commit está disponible para los revisores independientes. Este informe no acredita una ejecución del diagnóstico en el host, estado de custodia real, PREPARED, adopción ni causa histórica. Root conserva la operación e integración; el autor no emite voto independiente.
