# ADR 0233 — R178: diagnóstico categórico del Origin de inicio del bot

**Estado:** candidato CODE_ONLY. No constituye prueba de Chrome, del worker ni del
droplet. Rama aislada `feature/417-r178-origin-diagnostics`, derivada de
`e6a11ed293bab996d656dbe1a2d0ad1dc3dfa07b`.

## RCA, alcance y decisión

El titular observó «Origen no autorizado» al pulsar Iniciar bot y vio la
dirección `http://localhost:8443/control/bot/iniciar`. En el código, esa
dirección es el destino normal de un formulario `POST`; un rechazo HTTP puede
dejar el navegador allí, sin redirección. El guard de
`panel/private_http.py` exige que el encabezado `Origin` coincida **exactamente**
con el origen privado configurado. Los tests offline comprueban la rama de
rechazo, pero aún no hay evidencia física del encabezado efectivamente
recibido en el Samsung Chrome. La causa subyacente concreta permanece
**UNVERIFIED**; no atribuirla a Docker, a un proxy ni al dispositivo sin
captura diferenciada.

Se añade solamente al `POST /control/bot/iniciar` **ya autenticado** una
clasificación visible, fija y sin contenido recibido:

| Código fijo | Significado limitado |
| --- | --- |
| `BOCA_ORIGIN_DIAG_MISSING` | Encabezado ausente o vacío |
| `BOCA_ORIGIN_DIAG_SCHEME` | Mismo authority, esquema diferente |
| `BOCA_ORIGIN_DIAG_HOST` | Mismo esquema, authority diferente |
| `BOCA_ORIGIN_DIAG_MALFORMED` | Estructura inválida o no canónica |
| `BOCA_ORIGIN_DIAG_UNTRUSTED` | Otra discrepancia, inclusive múltiple |

Todos estos resultados siguen devolviendo **403** y nunca encolan START.
No se refleja, registra ni persiste ningún valor de cabecera, cookie, URL,
token o secreto; la clasificación depende de entrada controlada por el
cliente y **no es una atestación de que este sea legítimo**. La verificación
exacta de `Host` y del esquema WSGI, la sesión passkey, el CSRF y el UUID
único permanecen intactos. Los demás POST conservan su error genérico.

**No se autoriza una tolerancia todavía:** un `Origin` ausente o distinto no
prueba un navegador legítimo. Si Chrome demuestra una omisión genuina, un
ajuste adicional debe especificar otra señal no falsificable por una página
externa, más CSRF/session/Host, y probar previamente que cross-origin y
peticiones sin sesión siguen rechazadas. No desactivar Origin globalmente.

## Prueba física pendiente y evidencia esperada

1. Instalar primero el candidato nuevo bajo el workflow protegido de Boca y
   su recepción por imagen digest, UID rootless, volúmenes, limpieza y puerto
   `127.0.0.1:8443`, sin otros proyectos.
2. En Samsung Chrome, mantener el túnel privado y abrir exactamente
   `http://localhost:8443/`, autenticar la sesión passkey existente y pulsar
   **Control → Iniciar bot** con `SITE_URL` previamente configurada en un
   destino de ensayo autorizado. No abrir ni navegar Boca real.
3. Si el POST devuelve 403, documentar **solamente el código fijo visible**, la
   fecha ART, la versión exacta del controlador y el recibo de ejecución; no
   extraer cookies, cabeceras completas ni credenciales.
4. Una aceptación HTTP 303 indica solicitud persistida, **no** inicio físico,
   navegación ni reserva. El inicio requiere recibo del ejecutor, socket
   verificado y un STOP posterior con cero procesos, todo por controles Boca.

Sin ese experimento, el origen histórico del fallo sigue abierto, y el release
no puede figurar GREEN físico por estas pruebas sintéticas.

## Evidencia local de la rama aislada

- TDD: caso nuevo inicialmente **RED** por categoría ausente; otro RED por
  puerto `Origin` inválido, ambos GREEN tras la mínima implementación.
- `pytest -q -n 2`: **6861 PASS, 34 subtests PASS, 1 SKIP** en 88,81 s.
  El SKIP corresponde exclusivamente a
  `tests/test_r177_fixture_probe_transport.py:72`: el sandbox local deniega
  crear un socket `AF_UNIX` (`EPERM`). Esa prueba es **UNVERIFIED** aquí y
  debe ejecutarse sin omisiones en GitHub Actions Linux, sobre el SHA exacto.
- `ruff check .`: PASS; `ruff format --check .`: **846 archivos PASS**;
  `mypy src`: **155 archivos PASS**; `git diff --check`: PASS.
- No se hizo push, desplegó, reinició ni inspeccionó el host. El despliegue,
  Chrome y su `Origin` siguen sin evidencia física nueva.
