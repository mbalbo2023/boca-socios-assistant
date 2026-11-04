# ADR0129 — Recuperación explícita del controlador BETA después de aceptación (04/11/2026)

Estado: **candidata bajo issue #305** hasta merge y verificaciones por SHA. No constituye instalación física.

## Contexto y evidencia

- El workflow protegido `owner-enroll` termina ejecutando `stop-test`, que detiene el daemon Docker rootless privado de Boca. El `beta-install` previo comenzaba con `beta-preflight` sin restaurarlo; eso impide un primer deploy pese a controles CI GREEN.
- `src/boca_socios/host_rootless_setup.py::start_existing` ya autentica la unidad systemd y el socket privado UID 10001, exige daemon detenido y ausencia de contenedores arrancados, arranca únicamente ese daemon y conserva los datos. Se reutiliza sin modificar.
- `beta-acceptance` ejecuta su sonda sintética y luego `stop-test`. La BETA legítima queda detenida. Repetir `beta-install` sería peligroso: su contrato exige namespace vacío e inicializa nuevamente clave/DB/volúmenes. `beta-browser-start` habilita otra topología que no corresponde al controlador singleton protegido.

## Decisión

1. Tras revalidar `main`, invocar `start-existing` **antes del primer `beta-preflight`**, validar recibo acotado, y detener exclusivamente Boca ante fallos posteriores; jamás volver a ejecutar `prepare-rootless` para este propósito.
2. Agregar operación manual protegida `beta-start`, vinculada al SHA exacto de `main`, digest de imagen, release con manifiesto, entorno BETA y presupuesto `0.5cpu-256m-64pids`. El servicio es siempre `controller` y la imagen browser debe estar vacía.
3. `beta-start` exige exactamente **un controlador Boca previamente instalado y detenido**, etiqueta, imagen/digest/revisión, runtime simulation/engine off, red, puerto host exclusivo `127.0.0.1:8443`, límites, configuración y los tres montajes persistentes exactos. Si existe el volumen Telegram legítimo, debe superar su verificador de identidad: no habilita worker ni red adicional.
4. Se ejecuta exclusivamente `docker start <ID verificado>`; nada de `docker compose up`, pull, reset de base, recreación, migración, navegador, login, Telegram ni descargas. Se valida salud real, HTTP loopback y custodia después del arranque. El recibo permite correlacionar `BOCA_BETA_START state=RUNNING source_sha=...` sin material sensible.
5. En fallo posterior al inicio, detener **solo el ID Boca autenticado**; el workflow remata con `stop-test` de la unidad privada si la restauración de ese daemon fue verificada. Nunca eliminar volúmenes, acceso de propietario o recursos ajenos.

## Alcance, seguridad y propiedad

- Esta decisión no relaja la protección de `synthetic.py`/`ipc_worker.py`, no contacta el sitio real de Boca y no habilita reservas, compras ni autenticación automática.
- Mantiene Docker rootless de Boca aislado, su enlace local detrás del túnel SSH de Termius, sin HTTPS adicional, kernel/firewall global ni afectación de Porota Trading u otros servicios.
- El riesgo de disponer de un controlador activo se mantiene circunscrito al panel privado y al runtime simulación, con validación estricta de identidad y un único puerto.
- Aceptación: Ruff, Mypy, pruebas negativas de identidad/puerto/volumen y flujo, seguridad de imágenes, revisión técnica, PR gobernado, CI y seguridad postmerge sobre SHA exacto. Después: release protegido y evidencia de host del propietario. Ningún PASS de CI equivale a BETA instalada.

## Secuencia administrada

`owner-prepare` → `owner-enroll` (daemon detenido) → `beta-install` (start-existing primero) → `beta-acceptance` (detiene) → operaciones Telegram protegidas (pueden detener) → `beta-start` final (reanudación controller-only) → medición de recursos/Chrome físico por el propietario.

La evidencia de cada paso y el identificador del último run deben quedar en #45 y #305 según regla 84.
