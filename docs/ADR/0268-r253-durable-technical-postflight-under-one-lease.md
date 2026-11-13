# ADR 0268 — R253 one-shot durable technical postflight V2 (CODE_ONLY)

**Estado:** implementado y probado de manera local, **sin conexión a CLI ni
autoridad de despliegue**. La decisión física permanece `DEPLOY NO_GO`.

## Decisión

El comprobante R252 `BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2` es una captura de
estado técnico; antes de R253 no se almacenaba como comprobante independiente
con identidad de inode, persistencia y relectura. R253 agrega un **único
productor** `OneShotDurableTechnicalPostflightV2` en
`host_boca_durable_technical_postflight_v2.py`, sin alterar las rutas de
ejecución existentes. Su invocación requiere el **mismo** objeto
`BocaJobLease`, `PairCoordinates` y `PostflightExpected` provenientes del
intento protegido, la instancia ya completada de
`OneShotFinalCleanupBridge`, y un `volume_attestor` Boca de montajes y
volúmenes revisado independientemente: exactamente el objeto
`ProductionBocaVolumeAttestor` del mismo `expected` y `lease`, no una
función arbitraria. Ninguna dependencia opcional se
convierte en prueba positiva si falta.

El productor:

1. Marca `started=True` antes de llamar a productores externos: un fallo
   ambiguo no habilita un segundo intento contra el mismo archivo.
2. Comprueba plan/expected por **identidad**, lease activo bajo la misma
   identidad y finalización SUCCESS V2 mediante
   `completed_final_cleanup(plan, lease)`, que no reejecuta el cleanup. Exige
   que el comprobante oficial corresponda byte a byte al esperado.
3. Construye fuentes **reales**, no objetos de resultado suministrados por
   el workflow: `build_protected_postflight_sources` R247 con directorio
   fijo `stage.ROOT`, `volume_attestor` obligatorio, sin productores de
   passkey, propietario o monitor autenticado.
4. Llama a `ProductionPostflightSnapshotReader(technical_only=True)` vía
   `capture_technical_postflight`; esta última relee dos veces y rechaza
   diferencias, salud `/healthz` distinta de `HEALTH_HTTP_200`, identidad
   de par, SQLite/sesión, SITE_URL, worker, cleanup y lease inválidos.
5. Correlaciona la prueba con `verify_technical_completion` R252 y vuelve
   a verificar el lease; no obtiene un nuevo flock.
6. En el directorio Boca privado `/srv/boca-socios` abre un descriptor de
   directorio protegido y crea **una sola vez** el archivo:
   `.boca-pair-upgrade-{attempt_id}.technical-postflight-v2`. Usa
   `O_EXCL|O_NOFOLLOW`, modo `0600`, `fsync(file)`, `fsync(directory)`,
   `O_NOFOLLOW` para lectura acotada, SHA-256, identidad de inode y
   comprobación del path del directorio antes y después. Exige una relectura
   byte a byte idéntica y lease vigente tras la escritura.

Si cualquier paso falla, retorna un error `NO_GO` sin filtrar paths ni
mensajes privados; **no borra ni reemplaza residuos**. Un recibo exitoso
retiene el SHA, bytes, inode y la asociación con el cleanup oficial, pero
expone siempre `apply_authorized=False`,
`terminal_accept_authorized=False`, `beta_deploy=NO_GO`.

## Fronteras estrictas

- No modifica CLI, interlock de clase del backend, engine, workflow, ZIP
  allowlist, imagen, Docker, systemd, puerto ni recurso Porota.
- No obtiene cookies, usuario, credenciales, tokens, turnos ni reservas.
- No confunde `/healthz` con el ingreso Chrome/passkey; monitor permanece
  `NOT_CONNECTED`, observaciones `0`, owner `NOT_ATTESTED`.
- No implementa atestación independiente de volúmenes: **el llamador debe
  proporcionar el atestador de producción R253 de tipo e identidad exactos**
  o fallará cerrado. Las pruebas sustituyen temporalmente solo su método de
  lectura en un entorno sintético; una función vacía suelta se rechaza antes
  de escribir y no constituye evidencia de un droplet.
- No se ejecutó instalación, cutover ni postflight real del droplet. El
  archivo no existe por efecto de esta implementación CODE_ONLY.

## Tests y próxima dependencia

TDD primero RED por ausencia del módulo; después GREEN con casos de
persistencia O_EXCL/fsync/readback, doble snapshot, lease exacto, ausencia
de segunda lease, cleanup no vinculado, capturas inválidas, duplicado y
fallo posterior a escritura que deja residuo en cuarentena y rechazo de
callback de volumen falsificado. Validación local:

```sh
uv run pytest -q tests/test_host_boca_durable_technical_postflight_v2.py
uv run ruff check src/boca_socios/host_boca_durable_technical_postflight_v2.py tests/test_host_boca_durable_technical_postflight_v2.py
```

Siguiente integración independiente: revisar un productor físico de
atestación de volúmenes que no muta Docker, conectar el objeto recién
implementado con **la misma** lease y fuente de SUCCESS en el runner
protegido, cerrar distribución/allowlist y probar físicamente postflight.
Sin esos prerrequisitos y sin passkey/monitor reales, `DEPLOY NO_GO`.
