## R302 — observar esquema instalado después del fallo1144, sin otro intento de migración

### Corte posterior: selector integrado y observación1148 consumida

PR521 integró R302 en Q `7112a4878097bc1696a60a7b1056cd1e7b559ce5`,
con CI1268/Security1088 SUCCESS. El único observe fue
[1148](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43700038712),
attempt1: SCHEMA_0007_REQUIRED/NOT_NEEDED/OFF sobre M. El recibo de226 bytes
se leyó en el Summary real y pasó el verificador estricto de fallo;
SHA256618b1eeb289b7772f69cef467fdbda3130f080ce04aa22be3eba06eb2bad4c3b.
Queda acreditado baseline válido sin0007, no causa histórica1144 ni ausencia
de objeto homónimo. No repetir esta observación ni preparar M. El siguiente
delta registrado es R303/#524: STOP portable reutilizado, revisiones y gates
antes de evaluar una migración corregida. Las secciones siguientes conservan
el diseño y los resultados locales previos a esta operación física.

Continúa #417/#520 y se integra como delta de mantenimiento en el mismo candidato #521, no como otra promoción. El run1144 `43692644776` devolvió FAILED_STATE_PRESERVED/CONTROLLER_HEALTHY_ENGINE_OFF/senderOFF sobre M `5281efae7dafe89be047073796b3e0a7e19785ed`, con workflow P `c14f98d6adf4c4042f29e11f23f8a76545a1b0f9`. El esquema actual es UNKNOWN; no se infiere rollback, OOM, timeout o fallo SQL.

Arquitectura y Operaciones revisaron independientemente la cadena y no encontraron causa demostrada. Existe la primitiva readonly instalada `InstalledMaintenance.call("verify-schema", {})`, pero no un selector público que la ejecute sin continuar hacia efectos. La etapa del fallo no quedó preservada en el recibo v1. Este delta resuelve únicamente la pregunta actual del esquema; no inventa la causa retrospectiva.

### Contrato previo R302-01..08

1. Añadir `telegram-schema-observe` al camino instalado existente, con operación de recibo `observe`. M, los dos digest y release siguen independientes del workflow W; conservar entorno protegido main-only, lease única, manifest/ascendencia/main gates y exclusión completa del camino legacy.
2. Reutilizar `_execute`/resolve_installed_context/InstalledMaintenance y el verificador canónico instalado. Una rama cerrada antes de owner-identity/stop retorna después de la lectura y comprobación de health/OFF. El CLI puede enlazar esa rama con functools.partial y literal fijo, sin nuevo módulo, wrapper duplicado ni operación configurable.
3. Lectura de boca_data RO, helper fijo attestado por CID, network none, UID10001, 64MiB/16PID/.25CPU y retiro existente. No nuevo SQL, DDL, archivos de base, mounts, permisos, timeout o recursos. El lease y la creación/retiro del helper son efectos de control existentes: no afirmar cero efectos host.
4. Conservar recibo v1 de ocho campos. Éxito `observe/SCHEMA_READY/NOT_NEEDED/OFF/UNVERIFIED` sólo después de prueba canónica0007 y health posterior. Baseline válido sin0007 conserva `SCHEMA_0007_REQUIRED/NOT_NEEDED/OFF` y el workflow queda NO_GO para preparación. Estados inválidos, errores o identidad/cleanup inciertos nunca se presentan como éxito. `observe` no puede afirmar restauración `CONTROLLER_HEALTHY_ENGINE_OFF`, PREPARED, activación o senderVERIFIED.
5. No stop/start del controller/worker/sender, provision, owner read, bind, publicación de estado/recipiente, custodia, token/chat, mensajes o backup. La limpieza genérica de fallo sólo puede ser el no-op existente cuando no se provisionó red; probar ese límite. No cambiar migrate ni prepare.
6. Mantener 47 entradas instaladas y caps450000 fuente/300000 ZIP. El baseline deja738B: medir cierre real. Si el delta no cabe, detener esa implementación para revisión concreta; no aumentar caps ni introducir minificación/refactor general.
7. Regresiones focales significativas: schema7/missing/invalid/health-error; cero llamadas prohibidas; verificador exacto positivo/negativo y receipt<1024; CLI aislado del ZIP con W!=M y lease; selector y gate Bash/legacy exclusión. Consumir los tests ya certificados del baseline y R301, sin repetirlos.
8. Cuatro votos previos sobre este diseño, autor separado y nueva revisión final de código. Una vez CI/main exactos aceptados, raíz despacha una observación protegida, lee el Summary real y verifica el recibo. Sólo SCHEMA_READY físico admite prepare; missing/NO_GO exige RCA adicional, sin retry automático.

### Límites explícitos

No se consulta la tabla0007 huérfana ni se crea un diagnóstico SQL nuevo: la imagen M no ofrece ese selector. Si falta0007, ese caso y la etapa de1144 continúan UNKNOWN. No se promete que esta lectura resuelva toda la migración.

Los cambios del monitor #521 permanecen congelados y con sus pruebas/revisiones. SIMULATION_ONLY/BLACKBOX/datos/Porota/PPI se preservan. El registro original precedió código; los cuatro votos reales posteriores constan en la sección de ejecución y en #417/comment6891704268.


## Ejecución autorizada

Cuatro GO previos reales de Arquitectura, QA, Operaciones y Producto/Seguridad
registrados en #417/comment6891704268 antes del código. Autor separado.
Contrato y diseño exactos: SHA256 bb1b2284d63fd1f013181382133b05fb35179afb5d2afe2eda7eab2475d7345c.

Una tarea: agregar selector instalado y rama readonly/receipt estricto; tests
focales antes de producto (RED por funcionalidad faltante, no infraestructura),
implementación mínima y GREEN. Fijar reader=None en el partial literal.

Ocho archivos del autor: .github/workflows/boca-first-deploy.yml,
scripts/boca_protected_memfd_bootstrap.py, src/boca_socios/host_telegram_backend.py,
src/boca_socios/host_telegram_cli.py, tests/test_r296_telegram_backend.py,
tests/test_r296_telegram_installed_bundle.py, tests/test_browser_ipc_workflow.py,
tests/test_telegram_release_lineage_r34.py. No editar mantenimiento/imagen/SQL,
R301, caps, builder, entradas ZIP, full-cutover pin o dependencias.

Pruebas: positivo7/missing/invalid/health/retirement error sin efectos prohibidos;
finally no-op real; verify estricto también allow_failure; ZIP aislado W!=M;
gate Bash real/exclusión legacy. Medir cierre47/caps inalterados. No repetir
suite base ni tests R301 certificados. Usar intérprete congelado existente.

Después: revisión SPEC/QUALITY, cierre raíz de docs/RCA, cuatro votos finales
sobre árbol completo, GitHub PR521, CI exacto/main; observación física única
por raíz y recibo real antes de considerar prepare. Autor no opera host.

## Orden físico de cierre acordado con Operaciones

La única observación standalone se realiza sobre M después de los gates del
nuevo main. Si SCHEMA_READY es aceptado, promover el nuevo par Q conservando
SQLite y preparar Telegram sólo sobre Q. prepare incluye su propio preflight
canónico; no repetir schema-observe después del APPLY. Un resultado missing
o NO_GO conserva RCA, sin reintento ni preparación.

No preparar sobre M antes de Q: telegram_recipient_public_v2.json se liga al
SHA/fingerprint, read_prepared_recipient exige el SHA y el publicador rechaza
sobrescribir bytes distintos. El código de panel/telegram_recipient.py prueba
ese riesgo; no se inventa una renovación o borrado. La preparación post-Q
requiere el par, administración y postflight correctos, sin activación/envíos.

## Ruling de empaquetado posterior al hardstop

El autor detuvo el trabajo al medir47 entradas y450110/450000B de fuentes;
exceso110B, sin ZIP emitido. Backend+660B/CLI+188B. Raíz inspeccionó el delta
y autorizó exclusivamente cinco sustituciones editoriales en esos mismos
dos módulos: docstrings de módulo/backend, migrate, verify y CLI más el
comentario de interrupción. Conservan significado y lógica; no minificación
general, refactor, cap, builder o allowlist. La propuesta ahorra159B, pero
el builder real debe verificarlo antes de continuarGREEN. Revisores finales
deben comprobar esas sustituciones y el cierre final, sin dar por aprobado
el resultado por la estimación. El hardstop fue respetado; no hubo host.

El primer cierre posterior dio450021B (+21). El builder existente ya compacta
comentarios: el ahorro de159B en fuentes de repo no se traslada entero al ZIP.
El autor identificó únicamente las dos entradas previstas, sin drift ajeno.
Raíz autorizó sólo acortar las dos docstrings de módulo a «Installed Telegram
transactions.» y «Protected Telegram CLI.». Semántica de funciones/guardas
intacta; medir el cierre real nuevamente, sin cap nuevo.

Cierre real posterior:47 entradas,449978/450000B fuente (22B margen),
126479/300000B ZIP, SHA2569cd38d614eb5ed38f772a8f13a6b473cd82acbc5e5942b3132bb3b247f440da8.
No se cambiaron guards/caps/allowlist/builder. Tests focales backend/CLI/ZIP
26PASS y workflow24PASS; Ruff/tipos y revisión final se registran en el
reporte del autor y en el cierre del árbol, no se deducen de estos conteos.

Mypy detectó que el mapa mixto de funciones y partial infería object. El
adaptador explícito partial(...).__call__ mantiene los argumentos fijados y
resolvió tipos; Ruff lo distribuyó en tres líneas (+63B), llevando el cierre
a450041B. El autor volvió a detenerse. Raíz autorizó sólo dos docstrings de
función: «Migrate installed schema.» y «Verify strict receipts.». El contrato
opt-in y las guardas no cambian; la medición final se realizará tras formato.

## Corte final de autor, previo a revisión independiente

Ocho archivos congelados, árbol de tarea d05249b9e2abca10f1e1932eec5f1d95c66e7d52;
patch ddbca66e7fd1b3653e2fd12a41cbab90079758b5d659ea8422f733a052b01bec.
Backend/CLI RED12; GREEN26, más5casos aislados del CLI después del ajuste
tipado. Workflow RED11 y GREEN24. Ruff/formato/mypy/diff y YAML/Bash4 PASS.
No suite base/R301 repetida. Once hashes R301 preservados.

Cierre FINAL real:47 entradas,449973/450000B fuente (27B margen),
126453/300000B ZIP, SHA256ab221a27639a363917e8ad6b453097dbf0eeb070aa8308b09a9ef0fcb68878d4.
Caps/builders/allowlist/guardas intactos. Los valores anteriores documentan
los intentos locales intermedios; éste es el único cierre candidato final.
Cuatro votos finales sobre el agregado y gates publicados todavía pendientes.
