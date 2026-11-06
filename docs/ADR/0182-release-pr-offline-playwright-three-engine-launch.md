# ADR 0182 — Smoke offline de los tres motores Playwright antes del release

**Fecha:** 2026-11-05 ART. **Estado:** candidato CODE_ONLY, PR; no release ni host.
**Ownership:** QA/Release del Boca Socios Assistant; continuidad [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45) y capacidad [#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).

## Evidencia que motivó el cambio

El PR [#397](https://github.com/mbalbo2023/boca-socios-assistant/pull/397) mantuvo la imagen completa de Microsoft Playwright, midió su tamaño real en runner descartable y comprobó la **existencia** de los binarios Chromium, Firefox y WebKit. El job de validación también lanza Chromium mediante `scripts/verify_chromium_worker.py`. Esos checks no probaban que Firefox y WebKit pudieran **arrancar** bajo la identidad y los límites previstos. Esta distinción está registrada en [ADR0179](0179-release-pr-dual-image-capacity-measurement.md).

El owner requiere conservar los **tres** motores de Playwright; no se elimina ninguno, no se edita el Dockerfile ni el código de navegación BLACKBOX. La imagen browser full conserva su desafío independiente de capacidad: los bytes lógicos y el TAR del runner **no** equivalen al delta físico de pull en el droplet.

## Decisión acotada y límites

Agregar **una única etapa al job `pr-validation`** de `.github/workflows/release-image.yml`, antes de los escaneos de ambas imágenes, que en el runner descartable:

1. Reutiliza la **imagen browser local exacta** del SHA del PR, sin nueva descarga GHCR.
2. Ejecuta un solo `docker run --rm`, `--network none`, UID/GID10002, filesystem read-only, capabilities mínimas con `SYS_CHROOT` ya comprobada para Chromium, `no-new-privileges`, seccomp pinneado, `--ipc private`, límite de 128 PIDs, 768 MiB, 1 CPU y `tmpfs` acotados; timeout global de 120 segundos.
3. Mediante la API pública `playwright.sync_api`, lanza **Chromium, Firefox y WebKit secuencialmente**, abre únicamente `about:blank`, confirma `page.url` y cierra cada navegador antes del siguiente. Chromium conserva el sandbox y el argumento de red en segundo plano usados en el smoke existente. No hay interacción con Boca, Queue-it, Internet, login ni datos/secretos reales.
4. Sólo emite `BOCA_FULL_PLAYWRIGHT_LAUNCH chromium=PASS firefox=PASS webkit=PASS offline=true blackbox=UNTOUCHED` si los tres pasan. Ante error el job queda **rojo/NO_GO**, con engine y clase de excepción, sin ruta, traceback, credenciales ni datos del sitio. No relajar una falla de sandbox o dependencias: investigar RCA y corregir en PR posterior si fuera necesario.

La implementación no lee, importa, modifica ni prueba los módulos `browser/synthetic.py` o `browser/ipc_worker.py` protegidos; no instala ni inicia el worker real. No toca el job `publish`, su workflow manual protegido, los checks de SHA único, imágenes GHCR, otro servicio Docker, Porota, puerto 8443 ni recursos del droplet.

## Regresiones y evidencia requerida

- `tests/test_release_image_capacity_observer.py` requiere exactamente una etapa PR, orden después de build/antes de scan, tres `browser_type.launch`, `about:blank`, límites de contenedor, aislamiento sin red, sin imports BLACKBOX ni SSH/push/pull, y **ausencia de esa etapa en `publish`**.
- TDD: RED inicial porque faltaba el paso; GREEN del test estructural después de agregarlo. El test local verifica el **contrato de workflow**, no ejecuta Firefox/WebKit: sólo el recibo de Actions sobre el **SHA exacto de la candidata** puede acreditar el smoke físico del runner.
- Antes del único release manual, exigir éxito terminal de `release-image-pr-validation` con la nueva etapa y de los demás Actions requeridos del PR/árbol final. Un PR verde **no** comprueba Pull/ACK en droplet, Telegram, sesión persistente ni Selenium/Queue-it real.
- Mantener CAPACITY NO_GO de instalación hasta que se pruebe margen físico de bytes e inodos conforme al guard de 4GiB y limpieza selectiva de recursos Boca atribuibles por ID exacto. `workflow_dispatch` de release protegido se decide separadamente para el **main congelado**.

**Registro de resultado:** completar evidencia exacta SHA/Actions en conversación del PR y #45; el merge por sí solo no acredita función en host.
