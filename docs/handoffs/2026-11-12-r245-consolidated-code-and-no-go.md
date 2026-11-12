# A45-R245 — Integración de cinco frentes; BETA física aún NO_GO

**Fecha:** 2026-11-12 ART. **Fuente canónica:** issue #417, R244
`6836566308`; continuidad técnica en ADR0248. Este archivo refleja el
estado previo al CI hospedado y al release final, no un certificado host.

## Recuperado y reconciliado

- Base de la revisión: `main=3e0d6e6adbf372316aa07685575a3ed3cf3c1a98`,
  PR abiertos 0, CI `43310658142` e Image Security `43310658077` SUCCESS.
- Instalación **última atestiguada**, no revalidada hoy: `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`,
  intento protegido `43217075287`. R189 READ_ONLY `43281507903` SUCCESS,
  sin artefacto de Step Summary reutilizable como prueba GitHub.
- Historial recuperado sin duplicación: R240 Safe6, R242 auth y R243 reusable.
  No repetir el APPLY R186 ni crear procedimientos SSH paralelos.

## Trabajo consolidado R245

| Ownership | Resultado de código/prueba | Evidencia que falta |
| --- | --- | --- |
| Release | Descargar, autenticar y verificar controller+worker por REST antes de extraer; escritura privada exclusiva y durable | Release final desde `main` posterior, tokens/steps/run reales |
| Same-lease | Lectores de par, systemd, R108, SITE y health; bug real de campos State.* corregido | Acople effectful al CLI, muestras con lease real y postflight completo |
| Cleanup V2 | Reprueba lease por cada efecto; montajes exactos before/after; preserva R108 | Inventario físico Boca positivo, misma lease y recibo de eliminación selectiva |
| Panel | POST owner, CSRF/Origin, SITE persistente y worker cold read aceptados offline | Passkey Chrome, START/STOP, monitor y SQLite en el 8443 instalado |
| CI rápido | Clasificador seguro para PR documentales internos, dos jobs nombrados conservados | Checks GitHub SHA final y medición alojada de caché/latencia |

### Pruebas integradas

- `pytest -q -n 4`: **7753 PASS**, 1 SKIP `AF_UNIX EPERM` local, 34 subtests PASS.
- Ruff check/format, mypy 187 módulos, policy y diff --check: PASS.
- `test_r82_recovery_bundle` verifica hash R245 determinístico
  `1fa860223310087e592fac249e7a16cf01ec1dd642b1a3121469bd137fc74048`;
  el hash previo R244 sigue intacto.
- La revisión independiente no encontró P0 en los cambios. El tipo de
  ejecución productiva sigue `requires_persistent_receipt=False`; sólo
  corresponde certificar este trabajo como CODE_ONLY.

## Bloqueantes sin cerrar

1. **P0: CLI sucesor no conecta ninguna transacción effectful con recibo
   persistente auténtico.** El preflight devuelve NO_GO sin tocar Docker.
2. **P1: R188 V1 fija SHA/attempt/CIDs de R186.** No soporta una segunda
   actualización: separar prueba histórica de creación de recursos de
   observador dinámico del par actual; probar dos upgrades consecutivos.
3. **P1: falla de cleanup de sucesor.** La ruta ante fallo del par aún usa
   cleanup etiquetado SUCCESS; no habilitarla hasta preservar recursos y
   emitir recibos NO_GO con pruebas de fallo de cada fase.
4. **P0 físico:** falta evidencia de estado actual del droplet, release dual
   SHA exacto, passkey, SITE_URL, worker bajo demanda, monitor, SQLite e
   inventarios de limpieza exclusiva. `HEALTH_HTTP_200` no es login real.
5. **Velocidad:** 8 builds nominales repartidos en PR/main/security/release.
   En la muestra CI 254 s, builds ~50 s, Trivy ~33 s, labs ~171 s.
   R244 de paralelización tardó 313 s, revertido. Cache BuildKit y separación
   uv dep/src requieren A/B; no prometer 8→4 hasta preservar procedencia.

## Próxima intervención sin perder contexto

1. Publicar un solo PR R245 y comprobar los dos contexts de CI y escaneos
   finales para el SHA exacto; no crear un build protegido redundante.
2. Tras revisión, fusionar; verificar PR0, main y postmerge CI. Documentar
   run IDs y duraciones reales en #417.
3. Continuar en paralelo R246: adaptador de cleanup de fallos y observador
   dinámico; ejecutar tests y revisión independiente antes de proponer GO.
4. Una vez elegible el nuevo actor, usar **solo** `boca-first-deploy.yml`
   protegido y empezar por observación READ_ONLY reciente. No invocar R186.
5. Release única y despliegue definitivo sólo con procedencia, lease y
   postflight completo; pruebas simuladas, cero reservas o compras reales.

**Nunca afirmar `DEPLOY COMPLETE`, `HOST GREEN` o limpieza efectiva de Docker
sin recibo físico del droplet.**
