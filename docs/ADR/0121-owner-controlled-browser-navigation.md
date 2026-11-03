# ADR 0121 — módulos de navegador bajo control exclusivo del dueño

**Fecha:** 2026-11-03 ART. **Estado:** caja negra validada externamente por el
propietario y habilitada para integración con exclusiones acotadas; NO es un
recibo de despliegue ni acredita red rootless o sesión real.

## Decisión del propietario

Martín Balbo prohíbe expresamente a cualquier agente abrir, interpretar,
refactorizar o modificar `src/boca_socios/browser/synthetic.py` y
`src/boca_socios/browser/ipc_worker.py` sin otra autorización explícita suya.
La **navegación real por Boca Socios / Queue-it** queda bajo su
responsabilidad exclusiva y no se ejecutará en Chrome del droplet por agentes.

El propietario entregó dos archivos Python y ordenó subirlos exactamente
como los proporcionó. La única manipulación técnica admitida por el agente
en esta propuesta es el transporte **opaco** de los bytes y su comparación
criptográfica, sin leer ni analizar el contenido. Se hizo la copia en una
rama aislada, no directamente en main.

| Archivo protegido | SHA-256 de los bytes entregados | Tamaño |
|---|---|---:|
| `browser/synthetic.py` | `52cd3996548eb318253aecd11d9ffc5bfa04c609be400fdb1ce4863dba4eeeaa` | 2.784 B |
| `browser/ipc_worker.py` | `b1286e77b0ff2ee0bc2473b27895bbe1b0f376a4efcf921f5f1c88aabc649ebe` | 1.163 B |

Ambos difieren de los archivos de `main=a9842d63a4c6865c5a45b5d871bfacd06493d64d`
(3.961 y 12.884 B respectivamente). La diferencia es material. **No se
atribuye ninguna semántica al contenido recibido.** El dueño declaró después
estos dos archivos **caja negra validada externamente**, dispensó expresamente
la certificación funcional de los agentes y autorizó su fusión/despliegue sin
alterarlos. Esa declaración no es una certificación del resto de la aplicación
ni prueba que el host esté listo. Un test de integridad impide cambios
accidentales de bytes sin actualización explícita del contrato.

## Separación operacional

La propuesta de despliegue no incluye navegación del sitio ni uso de browser
worker. `compose.beta.yaml` mantiene el controlador en modo `simulation`,
motor `off` y backend de navegador desactivado por defecto. Sólo se pretende
el panel local, socio/credenciales cifradas, comandos simulados, SQLite y
avisos; Telegram queda con activación privada separada. No crear otro puerto:
host `127.0.0.1:8443`, por túnel SSH del dueño. No modificar servicios,
volúmenes, Docker ni redes de aplicaciones ajenas.

## Gates y límites

1. Verificar que la rama contiene los dos bytes exactos por SHA-256;
   ningún agente lee ni interpreta sus implementaciones.
2. Excluir exclusivamente ambos archivos de Ruff y Mypy, impedir su importación
   por Pytest, retirar el paso Chromium «synthetic ticket flow» que los ejecutaba y
   deselectar sólo los cuatro módulos de tests con importación directa. La
   cobertura de controlador, seguridad, infraestructura y los demás fixtures
   Chromium offline continúa activa.
3. Conservar el historial RCA y eximir únicamente los selectores históricos
   que dependen de estos dos archivos, bajo hashes fijos, manifiesto de
   atestación externa, prueba de integridad y prueba de separación del
   controlador. El detalle verificable está en [ADR0123](0123-owner-blackbox-rca-exception.md).
   Cualquier fallo **no relacionado** con la caja negra sigue siendo NO_GO.
4. No lanzar publicación, `beta-browser-*`, `chrome-host-*`, CDP, probes de
   navegación ni flujos de login/Queue-it en el host por cuenta del agente.
5. El despliegue requiere, además, RCA rootless #275, exact-SHA
   CI/seguridad/release, alta del dueño/passkey y aceptación local del
   controlador. El build de la imagen navegador puede instalar Chromium y
   dependencias por Playwright, sin activar navegación en el droplet.
6. Todo FAIL, falta de recibo, capacidad desconocida o limpieza incierta se
   documenta como tal; nunca inferir `GREEN` por una rama o un archivo subido.

## Evidencia

- Owner instruction: [issue #288](https://github.com/mbalbo2023/boca-socios-assistant/issues/288).
- Main referencia: `a9842d63a4c6865c5a45b5d871bfacd06493d64d`.
- Rootless: [issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275).
- Integración BETA: [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
- Despliegue exclusivo: `.github/workflows/boca-first-deploy.yml`.
