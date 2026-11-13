# ADR 0274 — SITE_URL vacía hasta la configuración del titular

**Fecha:** 12-NOV-2026 ART / 13-NOV UTC. **Issue:** #417, R259.
**Estado:** propuesta CODE_ONLY; instalación y aceptación física NO_GO.

## Decisión del titular y RCA

El propietario exige que `SITE_URL` esté **vacía por defecto**. Sólo la
configurará en el panel privado 8443 después de ingresar con passkey. El
controller, sus datos sintéticos y `/healthz` se deben poder instalar y
verificar antes de ello, sin que el worker navegue ni arranque por omisión.

El panel ya representaba `None` como campo vacío, y `read_site_url()` ya
rechazaba una configuración faltante en el START del worker. El desacople
estaba en el contrato de postflight: exigía siempre una huella SHA-256 de
una URL guardada y replicada, aun cuando el dueño nunca había suministrado
ninguna. La lectura guardada emitía `UNVERIFIED`; la lectura de la copia
del worker rechazaba la ausencia. Eso hacía circular la instalación: la
comprobación técnica pedía una URL que sólo el panel instalado permite guardar.

## Contrato aprobado para la prueba técnica

El postflight **schema 2 exclusivamente** puede recibir una expectativa
tipada `NOT_CONFIGURED`. El adaptador físico del controller lee por separado:

- La configuración propietaria en el volumen privado Boca mediante el
  almacén existente con verificaciones de directorio, inode y formato.
- La copia de URL para el worker mediante el lector opcional, que acepta
  `None` sólo cuando falta el archivo en un directorio de propiedad y modo
  verificados; un symlink roto, archivo inválido o permisos inseguros
  continúan dando error.

Ambas lecturas deben coincidir exactamente con la expectativa. Cuando
ambas constatan ausencia, el recibo técnico conserva `schema=2`,
`TECHNICAL_PROOF_ONLY`, `passkey_chrome=NOT_ATTESTED`, `beta_deploy=NO_GO`,
worker `CREATED/PID0`, y expresa:

```json
{
  "site_url": {
    "state": "NOT_CONFIGURED",
    "fingerprint": null,
    "mirror": null,
    "startup": "READ_FRESH_FILE_AT_NEXT_START"
  }
}
```

No se calcula una huella falsa ni se confunde `NOT_CONFIGURED` con una URL
válida. El postflight legacy schema 1 rechaza esa expectativa **antes de
leer el host**; tampoco se admite sin estar vinculada a `HEALTH_HTTP_200`
real, par, lease, storage, release y limpieza auténticos. El modo configurado
mantiene su representación histórica de dos SHA-256 idénticos. Ni esta
modificación ni la instalación borran o sobrescriben una URL que el dueño
ya haya guardado.

`read_site_url()` en el worker continúa rechazando ausencia y corrupción.
Guardar una URL exige el POST privado con passkey/origen/CSRF; el nuevo valor
se replica en el volumen de configuración y sólo se consume en el **próximo
inicio explícito** del worker. No hay navegación, login, fila, token,
reserva real, acceso a Porota ni cambio de TLS en esta propuesta.

## Evidencia y límites

TDD reproduce el rechazo anterior a la ausencia legítima (RED) y comprueba
después el recibo de ausencia, rechazo de divergencias y adulteraciones,
contrato legacy estricto, lectura de archivos seguros y probes Python
ejecutados localmente. La suite completa, el tamaño del ZIP y las Actions
de SHA final se registran por separado en el PR y el checkpoint #417.
Esto **no demuestra** que exista un archivo físico, passkey, monitor o un
worker funcional en el droplet. El DEPLOY permanece NO_GO hasta el resto
del camino crítico y su postflight auténtico.
