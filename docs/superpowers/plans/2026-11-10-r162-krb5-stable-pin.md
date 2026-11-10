# R162 — Controlador Kerberos Stable Pin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Producir un controlador Boca nuevo sin `CVE-2026-107364`, preservando Alpine estable y release exact-SHA.

**Architecture:** Una única capa `apk add --no-cache 'krb5-libs=1.22.3-r0'` en `Dockerfile` runtime antes del `USER 10001`; resto inalterado. El `image-security.yml` existente y el escaneo de `release-image.yml` mantienen su bloqueo de HIGH/CRITICAL.

**Tech Stack:** Docker multi-stage, Alpine v3.24, GitHub Actions, Trivy.

**Spec:** `docs/superpowers/specs/2026-11-10-r162-krb5-stable-pin-design.md`.

## Global Constraints

- No Alpine `edge`, no paquetes Python duplicados, no pruebas de módulos BLACKBOX ni cambios a `Dockerfile.browser`.
- Solo GitHub Actions Boca puede operar el droplet; jamás usar Docker rootful, Porota ni recursos ajenos.
- El resultado de instalación requiere digest de release dual y recibo físico; CI no sustituye Cutover.

## Review Focus

- Mirror estable sin `1.22.3-r0`: `docker build` debe fallar cerrado; no fallback a `edge`.
- Base anterior con `1.22.2-r1`: el pin instala la nueva versión sin mantener la vulnerable.
- Un hallazgo HIGH/CRITICAL residual: el scanner continúa en rojo, no se modifica el umbral.
- La etapa `build` y la imagen browser deben permanecer iguales; sólo la etapa controller runtime cambia.
- SHA de fuente nuevo: manifests y eventual release deben usar ese SHA, nunca #810 ni el `main` previo.

---

### Task 1: Corrección mínima de imagen y regresión real

**Files:** `Dockerfile`; prueba existente `.github/workflows/image-security.yml` y `scripts/trivy_scan_image.sh` (sin alterarlos).

- [ ] RED observado: `image-security` run `42897140865` falló por HIGH en `krb5-libs 1.22.2-r1`.
- [ ] Insertar pin estable exclusivamente en etapa runtime.
- [ ] Verificar que no aparezca una URL `edge` ni dependencias Python redundantes; revisar diff.
- [ ] Construir/scanear imagen con Actions PR exact-SHA: requiere Trivy SUCCESS real y artefacto íntegro; registrar límites.

### Task 2: Documentación y ruta de entrega

**Files:** `README.md`, `docs/ADR/0230-r162-controller-krb5-stable-security.md`, issues #417/#45.

- [ ] Documentar RCA, variante elegida, fase en código, riesgos de mirror, SHA y runs en PR.
- [ ] Revisión técnica y CI completo del SHA; merge por PR, PR abiertos cero antes del release.
- [ ] Release dual protegida y Cutover V3 únicamente si SHA, scans, identidad y recibos pasan; usuario valida runtime del bot.
