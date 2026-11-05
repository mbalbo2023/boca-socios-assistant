# ADR 0150 — Importador CODE-ONLY de una noticia oficial revisada al volumen Boca

**05/11/2026 ART · #314 · R23 · Estado: PR DRAFT, no integrado ni instalado.**

## Problema con evidencia

El lector del controlador (`events.official_snapshot.load_official_snapshot`)
consulta un archivo opcional llamado `boca_official_notices.jsonl`, junto a
`/data/boca.sqlite3` en el volumen Boca **existente**. No crea, modifica ni
autentica por sí mismo el contenido de ese archivo. Sin un productor instalado,
el panel puede indicar «NO_EVENTOS_VERIFICADOS» aunque exista un artículo público.

El primer Action de recibo + extractor con artículo real
[42029320757](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42029320757)
concluyó correctamente `EXTRACTED_UNVERIFIED`: GET anónimo único, HTTPS/TLS,
HTTP200, 76.355 bytes, hash del HTML
`db3b4cb424d5b6282dd7a562960be834705b8274637710b477d4154c26f14889`,
11/11 marcadores, cero credenciales. El artifact de **ese** run
`boca-official-news-receipt-42029320757`, ID **13414624349**,
contiene `boca-official-news-receipt.json` y
`boca-official-news-catalog.jsonl`. Su digest publicado es
`sha256:629e0b728057afb2f149efeec0126cc8697bfca67bbacd43dc6aa70e0843a958`.
Este recibo acredita *una noticia pública puntual*, no feed general de eventos,
canal de tickets real, elegibilidad, cupos, venta ni acceso a Boca Socios.
Tampoco demuestra que el ZIP haya sido importado o que el servicio físico lo lea.

La noticia no declara expresamente zona horaria por cada ventana; su expresión
ART dentro del JSONL es una interpretación que requiere revisión específica.
El importador **no** reemplaza esa revisión ni obtiene un GO por sí mismo.

## Decisión R23: paquete íntegro y pins fuera de banda, nunca red al importar

Un futuro Cutover protegido y **separadamente autorizado** podrá llamar
`events.host_official_notice_import.import_reviewed_official_artifact` con:

1. Directorio `/data` **ya existente** suministrado por configuración Boca
   confiable; no acepta rutas relativas, alias ni volúmenes nuevos.
2. Bytes de ZIP descargados/revisados **fuera de este módulo**; máximo 128 KiB.
   Únicamente dos miembros ZIP de nombre exacto: recibo JSON (≤8.192 B) y
   JSONL (≤16.384 B). Rechaza miembros repetidos/extra, rutas anidadas,
   symlinks, cifrado, formatos de compresión desconocidos y descompresión
   superior a presupuestos. No extrae ningún archivo del ZIP al filesystem.
3. `ReviewedOfficialArtifactPin` con SHA-256 del ZIP original, SHA-256 de bytes
   JSONL, URL de artifact exacta del repositorio `mbalbo2023/boca-socios-assistant`
   bajo `/actions/runs/<run>/artifacts/<id>`, URL fija del artículo público,
   SHA-256 del HTML **declarado por el GET** y `observed_at_utc` exacto.
   Los digests se cotejan contra bytes efectivamente recibidos; el URL es
   allowlist sintáctica, **no** una atestación online ni firma del club.
   Quien ejecute el Cutover debe cotejar antes el ZIP/metadata con GitHub,
   la identidad de run/PR/SHA y la revisión semántica del artículo.
4. Reutilización de `split_public_observation_envelope` para exigir única
   noticia v2 con digest, URL, minuto ART, cinco franjas, canal **declarado**
   Boca Socios, TLS/200, un solo GET, cero redirects/credenciales, todos los
   marcadores, `actionable=false`, `availability_verified=false` y
   `feed_verified=false`. El evento conocido debe conservar la identidad
   `boca-defensa-y-justicia-20261107`; no descubre otros partidos.

Si cualquiera de estas condiciones falla, no se abre ni modifica el directorio
de datos. La presencia del ZIP no certifica origen si los pins fueran
construidos por el mismo paquete no confiable: ese control **necesita dos
fuentes de evidencia independientes** en el flujo protegido posterior.

## Publicación atómica sin backup ni sobrescritura implícita

- Se reutiliza el recorrido `openat` + `O_NOFOLLOW` del lector: UID efectivo
  debe ser dueño del directorio Boca, que no puede ser escribible por grupo
  ni otros; se rechazan symlinks de cualquier componente.
- Si el snapshot opcional **no existe**, se escribe una etapa privada de
  nombre aleatorio mediante `O_EXCL`, modo `0600`, I/O acotada y `fsync`.
  Un hardlink al nombre final publica el archivo completo en forma atómica
  **sin reemplazar** una ruta existente; el segundo nombre temporal se
  elimina de inmediato. La ventana breve de `nlink=2` provoca rechazo
  temporal del lector estricto, nunca lectura parcial. Postflight exige
  un solo enlace, modo 0600 y una observación no accionable.
- Si existe **el mismo** JSONL exacto, se devuelve `UNCHANGED` sin escribir,
  cambiar mtime o solicitar un lease.
- Si existe un JSONL **diferente**, el default es NO_GO. Para actualizarlo
  se requiere un `OfficialSnapshotReplaceLease` activo del **mismo directorio**,
  obtenido con flock no bloqueante sobre lock privado `0600`, y SHA-256 exacto
  del archivo actual. Se coteja el digest bajo lease y otra vez justo antes
  de `os.replace` atómico. Un lease vencido, ajeno, disputado o cuyo archivo
  cambió no habilita reemplazo. El lock persistente no contiene secretos ni
  copia de datos.
- **No hay backup**, archivo anterior renombrado, tabla, migración SQLite,
  cron, puerto, red, llamada a GitHub, ni paso de compra. El módulo sólo
  manipula su snapshot y una etapa/lock del volumen Boca indicado. Si falla
  I/O, limpia la etapa identificada; una interrupción irrecuperable podría
  dejar una etapa privada y deberá auditarse selectivamente antes de reintento.
  Jamás usa glob de borrado, `prune`, otro volumen ni servicio.
- Los bloqueos flock son **advisory** entre escritores que respetan este
  protocolo; un proceso con permisos de dueño que ignore el lease puede
  provocar una carrera. La futura integración de host debe garantizar un
  único escritor Boca y coordinar Cutover, no compartir la ruta con un
  productor externo. Fallo posterior a publicación atómica puede implicar
  durabilidad incierta y exige inspección/read-only; no rollback ciego.
- Postflight vuelve a usar el **lector real** `load_official_snapshot` y
  comprueba exactamente una noticia, cinco ventanas, fuente declarada y
  `SOURCE_OBSERVED_UNVERIFIED`, siempre no accionable.

## Pruebas y próximo paso

`tests/test_host_official_notice_import.py` construye exclusivamente archivos
y ZIP **sintéticos** en directorios temporales de runner. Cubre create,
replay idempotente, reemplazo con lease y digest correctos, disputa de lock,
lease vencido/ajeno, pins ZIP/JSONL/fuente/observación contradictorios,
miembros ZIP ilegales, claims operables prohibidos, cinco franjas,
symlinks/permisos, conflicto de publicación y ausencia de restos tras un
error recuperable. No tiene credenciales ni acceso al droplet. El test real
de lector comprueba que el JSONL publicado es visible desde la API existente
sin promover disponibilidad.

**Estado operativo:** CODE-ONLY / PR DRAFT / SIN MERGE / SIN HOST / SIN GO
de importación. El owner de Cutover y del workflow de deploy conserva
exclusividad sobre ellos. Integrar este importador con una futura tarea
manual protegida de importación requiere revisión exacta de fuente+artifact,
decisión de lease, QA del candidato combinado, aprobación de operación
concreta y evidencia física en Samsung Chrome; este ADR no dispara nada.
Seguridad de imágenes es P2 por la prioridad funcional del dueño, pero
aislamiento, privacidad de datos, no compras y exact-SHA continúan.

## Regla 84

Anotar SHA/tree/PR de R23, tests locales y Actions **del HEAD exacto**, y
diff de integración a #319 en el issue [#314](https://github.com/mbalbo2023/boca-socios-assistant/issues/314).
No extrapolar la prueba real de GET R22 como evidencia de una instalación.
