# ADR 0121 — módulos de navegador bajo control exclusivo del dueño

**Fecha:** 2026-11-03 ART. **Estado:** propuesta asociada al Draft de issue #288;
no es una integración aprobada ni un recibo de despliegue.

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
atribuye ninguna semántica al contenido recibido, ni se garantiza que pase
la suite, preserve contratos o sea seguro de ejecutar.** El dueño conserva
el control de su revisión funcional. Un test de integridad impide cambios
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
2. Ejecutar sólo pruebas automatizadas autorizadas y conservar su resultado
   completo; si la suite falla, **NO_GO**, sin cambiar los archivos protegidos
   para que pase.
3. El borrador no puede fusionarse hasta que los contratos, la integridad y
   la revisión técnica exigida estén resueltos. Si para revisarlos fuera
   necesario interpretar esos dos archivos, se delega esa parte al dueño.
4. No lanzar publicación, `beta-browser-*`, `chrome-host-*`, CDP, probes de
   navegación ni flujos de login/Queue-it en el host por cuenta del agente.
5. La BETA controlador-only requiere, además, RCA rootless #275, exact-SHA
   CI/seguridad/release, alta del dueño/passkey y aceptación sintética real.
6. Todo FAIL, falta de recibo, capacidad desconocida o limpieza incierta se
   documenta como tal; nunca inferir `GREEN` por una rama o un archivo subido.

## Evidencia

- Owner instruction: [issue #288](https://github.com/mbalbo2023/boca-socios-assistant/issues/288).
- Main referencia: `a9842d63a4c6865c5a45b5d871bfacd06493d64d`.
- Rootless: [issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275).
- Integración BETA: [issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
- Despliegue exclusivo: `.github/workflows/boca-first-deploy.yml`.
