# R309 — Diagnóstico de preparación Telegram

## Necesidad demostrada y alcance previo

Prepare1167 terminó FAILED_STATE_PRESERVED. La observación1170 completó inventario y encontró helper ausente, pero no observa clave ni documentos públicos; no demuestra PREPARED ni causa1167. `publish_prepared_recipient` rechaza un binding diferente y no hay adopción pública implementada para el siguiente producto. Hace falta estado útil antes de preparar o promover.

**Consenso previo 4/4:** Operaciones, Arquitectura, QA y root GO al contrato D1–D10, con las precisiones de D2 y D5. Autor separado; ningún código de este diagnóstico está implementado al abrir esta issue.

## Contrato D1–D10

1. Selector `telegram-prepare-diagnose` en CLI y Action instaladas. Diagnóstico con efectos Docker acotados, distinto de R307. Objetivo fijo R845f31abfb1762dff27e6fc3274fcc40507f3f18/APPLY1153/incidente1167; nuevo W/run. Sin publicación, prepare, provision, migración, sender ni stop/start del par; causa histórica UNDETERMINED.
2. Lease nueva, binding exacto y healthy antes/después. Comprobar explícitamente sender ausente y ausencia de helpers/escritores extraños mediante inventario/perfiles, además de worker detenido y engineSTOPPED. Volumen Telegram exacto; si no existe, no crearlo ni montarlo. Guardas actuales de main/release/manifest/rootless/aislamiento intactas.
3. Público A/B por exec del controller exacto como10001:10001, Python -I -B y programa literal fijo. Sólo los dos documentos públicos existentes, límites1024/4096, parsers instalados R y metadata no-follow. No SQL, wrapper load_telegram_admin, fallback host, errores crudos ni bytes inválidos. Validar fuente declarada antes de comparar conR. Separar ABSENT/INVALID/MISMATCH/NOT_READ/CHANGED; conservar run/fecha histórica, TTL300 no invalida historia.
4. Un helper: suboperación host finita `recipient-observe`, request vacío. Reutiliza factory action recipient, MOUNTS recipient sin cambio y lifecycle existente. Sólo Cmd cambia a programa literal exacto, también atestado. ImagenR y perfil networknone/rootfsRO/TelegramRO/10001:10001/capdropALL/0.25CPU/64MiB/16PID/lognone intactos; sin código nuevo requerido en imagen.
5. Dos snapshots internos con descriptores nuevos, metadata antes/después, máximo2 entradas de directorio. EMPTY/KEY_ONLY/EXTRA_ENTRIES_PRESENT sin exportar nombres. Derivar público sólo KEY_ONLY más regular0400/10001:10001/nlink1/size32, usando _read/_receipt deR. INVALID/EXTRA no leen bytes privados. ABSENT sólo ENOENT hoja bajo padre válido; EACCES/IO=NOT_READ, enlace/metadata=INVALID, drift=CHANGED. No abrir token/chat/markers ni exportar secreto.
6. Secuencia guardas→públicoA→helper único/doble snapshot→públicoB→guardas. A/B y clave estables; comparar derivación con público. Conservar compensación stop -t5 exclusivamente del helper exacto atestado y rm; incertidumbre preserva y nunca crea otro helper/retry. Recibo conserva CID alcanzado y retiro RETIRED/INDETERMINATE.
7. Codec específico cerrado, V1 intacto, recibo<=4096 contando frame sujeto a medición. Estado OBSERVED_NO_GO o INCOMPLETE_NO_GO; fases/razones finitas, coordenadas, estados públicos/admin/custodia, identidad/efectos/retiro del helper, engine/sender. data/custody/status writes0 y prepare/adopt_authorized=false. Sin rutas privadas, nombres arbitrarios, errores o secretos. Adquisición/transporte/retiro incierto nunca completo.
8. Recomendaciones no ejecutables: públicoABSENT+claveVALID/KEY_ONLY→PREPARE_FINAL_REUSE_KEY; públicoMATCH_R+claveMATCH→PUBLIC_REBIND_REQUIRED; públicoABSENT+claveABSENT/EMPTY o volumen ausente→PREPARE_FINAL_CREATE_KEY; público presente+clave ausente→INCONSISTENT_PRESERVE; extras→CUSTODY_PRESENT_REVIEW; inválido/mismatch/no leído/drift→PRESERVE_REVIEW. Admin inválido/mismatch impide ruta coherente; histórico válido sólo informa. Stage no inspeccionado ni presumido ausente.
9. Seis rutas productivas: host_telegram_status.py, host_telegram_maintenance.py, host_telegram_backend.py, host_telegram_cli.py, workflow existente y memfd bootstrap. Builder sólo por adenda si tamaño medido lo exige. Misma closure47 entradas; fuentes450000 y ZIP300000 intactos inicialmente. No R307, MOUNTS, código de imagen, BLACKBOX ni otros productos. Elevar sólo cota installed requeriría medición y cuatro votos nuevos; no minificar código ajeno.
10. Tests focales de fronteras reales: parserR/dependencia ausente; ENOENT/EACCES/enlace/metadata/extras sin secretread; doble lectura/drift/mismatch; comando atestado/tamper; retiro incierto; ZIP/CLI/workflow y codec cruzado; exclusión de todos los pasos legacy. No repetir suites históricas. Root registra evidencia real en417 y decide continuación posterior; CI no acredita host/preparación/adopción.

## Ownership y salida

Autor separado posee las rutas del plan y tests focales; root documentación, GitHub y única Action posterior. Arquitectura/QA/Operaciones/root revisan independientemente. Mantener SIMULATION_ONLY, senderOFF, datos/passkeys y aislamiento Porota/PPI. La autorización del titular permite cerrar el trabajo sin permisos rutinarios; no permite inventar evidencia o repetir operaciones ciegas.

## Límites de la interpretación

Este diagnóstico informa el estado presente y una recomendación no ejecutable.
No declara PREPARED, no atribuye causa1167 y no autoriza automáticamente la
continuación. La configuración por socio sigue pendiente del contrato global
completo; no construir scaffolding mientras esa dependencia esté abierta.

