# A45-R246 — Reingeniería de caché, custodia y postflight; NO_GO físico

**Fecha:** 2026-11-12 ART. **Continuidad:** issue #417, PR #494/R245.
Este documento describe el código candidato R246 y la nueva observación
READ_ONLY; no acredita un despliegue productivo.

## Base real y procedencia

- `main` previamente certificado: `b51b66f0b0af2be54571d464b13bb7ba50523ff7`
  (R245, PR #494 mergeado, cero PR abiertos al control previo).
- PR #494: CI PR `43319578249` SUCCESS; postmerge CI `43320531013`
  SUCCESS e Image Security `43320530967` SUCCESS.
- Instalación física última atestiguada antes de esta intervención:
  `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`, intento protegido
  `43217075287`, con NO_GO histórico postcommit. No se rehizo R186.
- **Observación real nueva:** GitHub Actions protegido, operación
  `boca-retained-resource-observe`, run `43322383932` SUCCESS en el
  `main=b51b66f0`. Generó el artefacto GitHub
  `boca-retained-resources-observation`, ID `13990124679`, ZIP SHA256
  `0bfa7684b4f41a3cb39988d14d61ebb867ddfe213308ddd3b1b3e9cadee021dd`.
  Expira el 2026-11-14 22:42:56 UTC. Esta captura acredita procedencia
  durable de la observación R188, **no instala ni certifica el nuevo par**.

## Cuatro frentes de código independiente, sin efectos host

1. **Falla y limpieza:** el backend reusable deja de invocar limpieza de
   éxito después de recuperación del par previo o falla indeterminada.
   Conserva recursos hasta una operación FAILURE específica y acreditada.
2. **Docker y velocidad:** el Dockerfile controller instala dependencias del
   lock antes de copiar fuentes. Un cambio de Python no debería invalidar
   la capa de dependencias si BuildKit dispone de caché; todavía no se
   midió A/B en runners hospedados.
3. **Custodia histórica versus par actual:** el observador V2 autentica por
   separado R188 histórico y el release previo dinámico, incluso cuando el
   SHA anterior ya no está en main. Incluye pruebas A→B→C y negativas de
   manifiestos falsos. No se conectó todavía al ejecutor host.
4. **Postflight:** capturas doblemente atestiguadas de par, rootless,
   volúmenes, SITE y metadatos de monitor. Sin productor auténtico,
   persiste NO_GO; `/healthz` no equivale a login/passkey real.

Verificación local integrada: `pytest -q -n 4` **7781 PASS, 1 SKIP**
(`AF_UNIX` prohibido por el entorno), 34 subtests PASS; Ruff check/format,
policy y controles tipados se ejecutan para este candidato. El resultado
de CI hospedado y su reloj de latencia deben asociarse al PR exacto, no
atribuirse a un test offline.

## Camino crítico para liberar el deploy

1. **P0 — Actuador sucesor:** el `apply` CLI está deliberadamente NO_GO y
   `requires_persistent_receipt=False`; necesita un integrador único
   bajo lease con recibo duradero `intent/commit/terminal`, sin repetir R186.
2. **P0 — Transporte V2:** conectar la procedencia R188 y la identidad
   dinámica actual al workflow protegido existente. No agregar un input
   26, otro SSH, ni superar límites de bundle (fuentes 1.300.000 bytes,
   ZIP 480.000 bytes).
3. **P0 — Failure Cleanup:** crear y verificar compensación selectiva de
   fallos y presencia persistente del journal; prohibido ejecutar cleanup
   de éxito tras falla o estado indeterminado.
4. **P0 — Postflight físico:** autenticación Chrome/passkey real, `8443`,
   worker START/STOP, SITE guardado y aplicado tras reinicio, SQLite y
   sesión persistente, fuente auténtica de monitor y limpieza Boca-only.
5. **P1 — Velocidad demostrada:** medir BuildKit/caché fría y caliente en
   GitHub, reutilizar manifests por digest y eliminar builds duplicados.
   No prometer un descenso de ocho a seis o menos sin comparar runs reales.

## Decisiones inalteradas

- `NO_GO` de BETA hasta evidencia física completa; cero reservas y compras.
- No tocar Porota ni servicios, puertos, volúmenes y contenedores ajenos.
- No usar rutas HTTP/TLS inseguras ni falsificar token o passkey.
- PR único, CI y seguridad por SHA exacto, único release protegido y
  ejecución en GitHub Actions. Todo fix-forward, sin borrados globales.
