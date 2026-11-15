# R303 — STOP portable de Telegram instalado

## Contrato y base previos al código

El requisito se registró en [issue524](https://github.com/mbalbo2023/boca-socios-assistant/issues/524)
antes de implementar. Los cuatro GO reales de diseño, de Arquitectura, QA,
Operaciones y raíz Producto/Seguridad, constan en
[#417/comment6892566944](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6892566944).
Autor y revisores son independientes. Este plan ejecuta ese alcance y no
certifica todavía el código ni una operación física futura.

Main Q es `7112a4878097bc1696a60a7b1056cd1e7b559ce5`, árbol
`3e328752468895f7c712a9ec9f7630e47e585b91`; CI1268/Security1088 SUCCESS.
El worktree local parte del checkpoint `d522c15a7f402486325142a15601945bb9f087ba`,
con ese mismo árbol. No es el commit remoto Q. El sucesor remoto tendrá Q
como padre; no publicar el checkpoint local como si fuera main.

Instalado M sigue en `5281efae7dafe89be047073796b3e0a7e19785ed`,
release866/APPLY1134. [1148](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43700038712)
acredita baseline válido sin esquema0007: SCHEMA_0007_REQUIRED/NOT_NEEDED/OFF.
[1144](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43692644776)
falló con FAILED_STATE_PRESERVED y restauración HEALTHY/engineOFF. Ninguno de
esos recibos conserva la fase o stdout históricos. La causa física continúa
sin demostrar; no inferir rollback, ausencia de objetos huérfanos o DB intacta.

## Diseño mínimo

Reutilizar [ADR0204](../../ADR/0204-r95-portable-docker-stop-flag.md) y
[ADR0227](../../ADR/0227-r139-acuse-de-parada-del-panel.md). La opción larga
`--time` puede producir advertencia en stdout seguida del CID. `_docker`
captura stdout y stderr por separado y devuelve stdout literal. Rechazar ese
acuse ambiguo es correcto; la llamada debe usar el alias portable existente.

Sólo tres sustituciones productivas:

| Archivo | Llamada | Delta |
| --- | --- | --- |
| host_telegram_installed_context.py | InstalledTelegramContext.stop | --time 10 a -t 10 |
| host_telegram_maintenance.py | retirada de call | --time 5 a -t 5 |
| host_telegram_maintenance.py | retirada de _migrate_schema | --time 5 a -t 5 |

Conservar ACK de CID completo, tiempos, atestación por identidad, lease,
writer fence, retiro positivo y restore. No filtrar líneas, aceptar el último
fragmento, cambiar parser, SQL, perfiles, selectors, timeouts, mounts o caps.
Ambas fuentes pertenecen al ZIP Telegram instalado y no al full-cutover.

## Tarea única de autor — regresión, tres literales y cierre

1. Leer únicamente fuentes y pruebas pertinentes. BLACKBOX synthetic.py e
   ipc_worker.py quedan unread/unmodified. No Docker real, proveedor ni host.
2. Añadir regresión de frontera en los tests R296 existentes. Mantener reales
   InstalledTelegramContext.stop, cleanup._docker y migrate_installed_telegram;
   sustituir sólo subprocess y guardas externas sintéticas necesarias.
3. RED funcional: el cliente sintético devuelve warning+CID con --time. Debe
   constar un STOP, writer/migrate-schema no invocado, un restore y recibo de
   fallo con restauración healthy/OFF. No basta comparar el argumento escrito.
4. Cambiar exclusivamente los tres argumentos. GREEN: -t produce CID exacto,
   un STOP y recorrido de migración previsto, sin retry implícito.
5. Negativos: warning aun con -t, vacío, CID ajeno, multilineal y exit no cero
   siguen rechazados. Cubrir las dos retiradas de helpers en su frontera:
   identidad incierta impide eliminar; writer no retirado impide restaurar;
   errores primario y de cleanup conservan su significado.
6. Ejecutar sólo selectores nuevos y regresiones afectadas necesarias. Usar
   intérprete congelado `/workspace/scratch/0bbcce5b467b/boca-ci-r293/.venv/bin/python`.
   No repetir la suite base, laboratorios Docker ni pruebas físicas previas.
7. Construir y medir una vez el ZIP instalado final y su CLI aislada. Mantener
   47 entradas, 450000 bytes fuente y 300000 de archivo; verificar inclusión
   de ambas fuentes y closure. Base Q:449973 bytes fuente/126453 ZIP. Los tres
   literales reducen 12 bytes crudos; medir el resultado, no asumirlo. Si el
   inventario contradice el diseño, detener y reportar. Builders/allowlists y
   pin full-cutover 066214cb4ae6a84f9e88973e38e58f7780dccf9556d1beb75cfb7c3b3a500c0e intactos.
8. Ruff/formato y tipos del delta, diff limpio de espacios. Entregar rutas,
   RED/GREEN, comandos exactos, límites y hashes. No commit, GitHub o host por
   el autor. Raíz integra documentación/RCA y congela el árbol para revisión.

Archivos exclusivos del autor: las dos fuentes anteriores y
tests/test_r296_telegram_backend.py, tests/test_r296_telegram_maintenance.py,
tests/test_r296_telegram_installed_bundle.py si requiere ampliar el harness.
No abrir otro módulo de producto. Raíz posee plan, AGENTS, RCA y documentos.
La evidencia intermedia se guarda fuera de archivos publicables del repo.

## Revisión y secuencia física condicionada

Raíz registra RCA524 con causa limitada al defecto reproducido y prevención;
preserva las 53 lecciones anteriores. Cuatro revisiones finales sobre el árbol
completo preceden PR, gates exactos, merge esperado y gates del nuevo main R.

Sólo después se evalúa una migración corregida sobre M, con release866 y sus
dos manifests/digests ya aceptados. Es una nueva ejecución de código revisado,
no retry de1144. Raíz despacha por la Action Boca protegida, serializada.
Se exige workflow/remote exitosos y recibo estricto del intento exacto:
migrate/M/SCHEMA_READY/CONTROLLER_HEALTHY_ENGINE_OFF/OFF/UNVERIFIED.
Cualquier otro resultado vuelve a RCA, sin bucle de reintentos ni release.

Tras ese éxito: una release pareada del main final R; observaciones actuales
del par y recursos retenidos; una promoción consolidada con postflight,
limpieza selectiva y aceptación; administración y estado del nuevo par;
prepare sólo sobre R. Su preflight verifica el esquema sin otro observe.
No preparar M: el recibo público está ligado a la fuente instalada.

SIMULATION_ONLY, senderOFF, datos, claves, passkeys, volúmenes y recursos se
preservan. No activar/enviar Telegram, navegar proveedores o tocar Porota/PPI.
La aceptación privada del titular y capacidad física50 siguen diferenciadas
del resultado técnico; no se afirma DOM autenticado, reserva, ganador o foto.

## Resultado local previo a revisión final

El autor independiente reprodujo RED:3 fallos,18 aprobados,95 deselectados.
La ruta real backend/stop/_docker rechazó warning+CID antes del writer y
registró una única restauración; fallaron también las dos retiradas cuando
el acuse era ambiguo. Tras los tres literales, GREEN21/95 deselectados.
La selección final nueva y afectada obtuvo42 aprobados/74 deselectados.
Son fronteras sintéticas de subprocess, sin Docker real o servidor.

Un único paquete final instalado:47 entradas,449961 bytes fuente (39 de
margen)/126448 bytes ZIP. SHA256
`4a235926762120596e9a9ccf5cc5f57b464aeba14b65a866f5a2f236c8e792c9`.
La CLI aislada consume ese mismo artefacto para selftest y migración M!=W,
incluida interrupción SIGTERM. Builders, allowlists, caps y full-cutover
pin no cambiaron. RCA524 incorpora seis selectores ejecutables y conserva
íntegras las53 lecciones previas; registro55876 bytes dentro de65536.

Esto prueba el defecto y la corrección local, no la causa histórica1144 ni
la migración del droplet. Revisiones finales, CI/main exactos y recibo físico
se registran por separado en GitHub antes de avanzar la secuencia prevista.
