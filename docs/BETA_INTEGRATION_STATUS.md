# Plan de integración y estado de BETA

**Corte:** 2026-10-28, America/Argentina/Buenos_Aires. **Base inmutable:**
`main` `09f390e483a9ad93caf460cb6e161fee22e6bd8d`. Rama de verificación
`feature/24-offline-integration`, issue #24. Ningún PR de la matriz se ha
fusionado a `main` ni desplegado.

## Recuperación del trabajo existente

| PR | HEAD recuperada | Componente | Estado de integración |
| --- | --- | --- | --- |
| #18 | `b145273dd3b04223ef4456aa2106b49a17d2df04` | Auditoría CI y Dependabot | Incorporado a rama de verificación |
| #23 | `d4786aa60ad94622621a399cf098c42b5ac35b46` | Imagen y lectura de clave | Incorporado |
| #22 | `5442616e7a03c713755ccb3dbd1157d59906494d` | Intención SQLite idempotente | Incorporado |
| #21 | `d8120eb8ccba669eadedac237ed6109cb46b1273` | Cola offline | Incorporado como modelo, nunca como Queue-it real |
| #20 | `b7d28a4860c4481e973d0a2339fe885dc32c04ae` | Avisos en memoria | Incorporado; no hay entrega Telegram |
| #19 | `c85f33e05e8bce743d1c2a76413e364ff4dcb72f` | Instrumento de benchmark opt-in | Código recuperado; sin capacidad medida |
| #26 | `97334bd266823f0926a24ea3dcd33ddd12e385d7` | Contratos/navegación HTML ficticia | Código de prueba recuperado; **no valida Boca** |

El PR #15 de protocolo de observación y los cinco PRs automáticos de
Dependabot (#1–#5) siguen abiertos para revisión independiente. #28 propone
el diseño de alta privada (#17); #29 propone un panel accesible de lectura
offline (#16). No se duplican sus módulos en esta rama. Los PRs de trabajo
anteriores tienen CI verde en sus HEAD exactas, pero **ninguno tiene una
aprobación humana registrada**. Las primeras ejecuciones fallidas de algunos
PRs fueron corregidas con commits posteriores; sólo valen sus HEAD actuales.

## Dependencias y prioridad

| Orden | Entrega | Depende de | Gate para avanzar |
| --- | --- | --- | --- |
| P0 | Revisión humana, checks exactos y protección efectiva de `main` (#10) | #18 y configuración del dueño | Ruleset activo verificable; hoy la API del conector devuelve 403 al leer protección |
| P1 | Base cifrada e idempotencia, integración de cola y avisos | #23, #22, #21, #20, #26 | Tests cruzados, imagen CI y revisión de cada PR |
| P2 | Observador Playwright de Boca de una sola sesión y sin reserva | Observación pública, política del sitio, #17 | Prueba limitada real documentada; stop ante barreras |
| P2 | Panel privado y alta accesible | #28, #29, autenticación propia, TLS | Diseño #17 aprobado antes de exponer endpoint; pruebas de acceso indebido |
| P3 | Outbox durable, backup/restore y rotación de claves | #22, #20, #17 | Reinicios, carreras, retención y recuperación verificados |
| P3 | Docker independiente y medición de recursos | #23 y worker aislado | Build/scan, presupuesto real; sin tocar otro Compose |
| P4 | Integración de reserva real y notificaciones externas | Observación legítima, consentimiento, términos y reconciliación | Revisión humana separada, evidencia de Boca y autorización específica |

## Evidencia y límites actuales

- Baseline combinado local: `uv sync --locked`, Ruff, mypy strict, política
  de aislamiento y **94 pruebas** verdes antes de los nuevos adaptadores.
- Con los adaptadores, **97 pruebas** locales pasaron; la CI de GitHub Actions
  para el candidato `f5392603a5c5222420c8bc803650cc0f21f5a4d2` terminó
  **success** en el run `40761344117`: jobs `quality-and-tests` e
  `image-build` completos. Este resultado no constituye revisión humana.
- La integración de `OfflineSimulation` enlaza el `TicketIntent` idempotente
  de SQLite, una admisión del modelo en memoria, el puerto de navegador y un
  aviso estático deduplicado en memoria. Las regresiones adicionales comprueban
  identidad, cantidad 1, TTL, fallo del navegador y reintento local. El estado
  de la DB queda `planned`: jamás se marca una compra externa.
- La observación de la portada pública está en
  [BOCA_PUBLIC_OBSERVATION_2026-10-28.md](BOCA_PUBLIC_OBSERVATION_2026-10-28.md).
  No se ha visto un flujo autenticado ni se han probado reservas en Boca.
- Las pruebas con dobles y HTML ficticio verifican contratos internos;
  **no son un laboratorio de integración real**. El usuario pidió priorizar
  Boca Socios directamente; no se ejecutará un smoke fake como sustituto de
  la prueba real.
- El entorno local carece de Docker; `image-build` de GitHub Actions validó
  el candidato indicado. No hay benchmark Chromium con resultado medido ni
  capacidad demostrada del droplet.
- La lectura de rulesets devolvió lista vacía y la protección de `main` no
  fue legible con la integración (403). Por tanto, la aplicación efectiva de
  la regla **no está verificada**. La política del repositorio sigue exigiendo
  PR, checks y revisión humana.

## GO / NO-GO

**GO de desarrollo:** revisar PRs separados, corregir conflictos en rama,
seguir con tests internos y un observador público acotado. **NO-GO de BETA
operativa:** faltan alta segura aprobada y expuesta, autenticación del dueño,
outbox durable, flujo real observado de login/cola/reserva, reconciliación de
resultado incierto, pruebas del navegador real, rendimiento en entorno
  aislado, scan de imagen y protección/revisión humana. La CI integrada
  exacta de la versión anterior de esta rama está verde; cualquier nuevo
  commit requiere repetirla.

**NO-GO de despliegue:** no existe autorización para un SHA/digest y servicio
concretos. Todo cambio futuro en el droplet se hará por GitHub Actions de
Boca, con preflight de aislamiento; Porota Trading y PPI Watch quedan fuera
del alcance.

## Instrucciones accesibles para la revisión

1. Abrir cada PR desde la lista del repositorio y leer su sección «Files
   changed» y el resultado de los dos checks, `quality-and-tests` e
   `image-build`, para la HEAD indicada.
2. Revisar el diseño de alta segura en #28 antes de habilitar cualquier
   pantalla de credenciales. **No enviar usuarios ni contraseñas por chat**.
3. Registrar la aprobación o cambios pedidos en el PR correspondiente; no
   fusionar esta rama de verificación directamente como reemplazo de las
   revisiones individuales.
4. Una CI verde o una portada pública visible no habilitan despliegue ni
   reserva. La aprobación de despliegue se solicitará después con SHA,
   digest, recursos y workflow específicos; no hay comandos para el droplet.
