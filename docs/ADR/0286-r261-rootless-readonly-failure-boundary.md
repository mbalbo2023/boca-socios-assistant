# ADR0286 — R261: diagnóstico acotado del rechazo PREDEPLOY rootless

**Fecha:** 13-NOV-2026 UTC. **Issue:** #417. **Estado:** CODE_ONLY;
**DEPLOY NO_GO**. Owner: observador rootless y su paso existente de Actions.

## Evidencia y límite del RCA

En `main=32bb9546f0962b3615f2b9cb84c9c84d4a72d758`, el primer
`workflow_dispatch` de `boca-rootless-mapping-observe` fue
[#43360372904](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43360372904),
job `131672177534`. En `Observe Boca rootless mapped inode custody READ_ONLY`
se registró `BOCA_MAIN_REF_PASS` y después `exit 1` (~6 segundos). No existe
recibo positivo, terminal de deploy ni datos que permitan distinguir la
subfase: el script desechaba el stderr SSH y comprobaba `remote_rc`, verificación
y estado bajo un único `HOST_OR_RECEIPT_UNVERIFIED`.

Las lecturas anteriores del par, binding e inode SQLite
[#43350008105](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350008105),
[#43350251999](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350251999)
y [#43350432873](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43350432873)
no prueban el mismo lease, ni el UID/GID traducido de **los tres** ficheros.
**RCA físico: UNKNOWN** hasta nueva observación. No se atribuye a Porota,
proveedor externo, presupuesto (fijado en 1.5 CPU/1024 MiB/192 PID), ni
una condición concreta del host sin medirla.

## Corrección diagnóstica, sin mutaciones ni GO

La ruta de éxito conserva su byte-formato esquema 1:
`PRELIMINARY_PREDEPLOY`, `lease_verified=true` y sin campos nuevos.
Un rechazo generado por el host tiene esquema **2** e incorpora exclusivamente `failed_boundary`
de un vocabulario cerrado: `LEASE`, `PAIR_BINDING`, `VOLUMES`, `PID_MAP`,
`INODES`, `STABILITY`, `INTERNAL`. Es la **subfase alcanzada**, no la causa
raíz de sistema de archivos o Docker. El éxito esquema 1 no admite el campo
adicional ni un downgrade del rechazo al esquema 1. El texto de una excepción real nunca
sale del host. El verificador local rechaza campos nuevos arbitrarios,
duplicados, múltiples líneas, datos no canónicos y estados GO. Un recibo
host malformado sale con código 4 **sin re-emitir** un falso NO_GO validado.

El único paso ya existente de `boca-first-deploy.yml` publica la categoría
únicamente si SSH devuelve código 3 **y** el verificador devuelve código 3
para un rechazo estructuralmente canónico; el verificador no firma el recibo.
En otros casos informa
`UNVERIFIED`; sólo añade estados fijos de transporte `RETURNED`,
`HOST_REFUSED`, `TIMEOUT`, `SSH_255` u `OTHER`, sin copiar stdout/stderr
privados, rutas, PIDs, UIDs, CIDs, configuración, claves ni nombres de DB.
El job permanece rojo en **todo** rechazo. No habilita cleanup, efecto,
release, passkey ni aceptación BETA.

## Verificación y continuación

- TDD: cuatro regresiones RED antes del cambio, que cubren categorías
  `VOLUMES`/`LEASE`, rechazo de datos malformados y publicación acotada.
- Repetir suite focal, bundle ZIP bajo límite propio de 1.400.000 B,
  Ruff, formato, mypy, política y suite total antes de promover el PR.
- Tras merge/revisión y checks exactos, un **nuevo** dispatch READ_ONLY
  puede localizar el límite sin repetir el run fallido. Toda anomalía sigue
  `NO_GO`. La observación NO certifica instalación, cleanup V2 ni postflight.
- Para instalación futura siguen faltando release dual auténtico, mismo
  lease, cleanup V2, panel privado 8443, passkey de Tincho, SITE_URL,
  worker bajo demanda, monitor y SQLite. Sin acceso a Porota, otros
  servicios, navegación de terceros, tickets ni reservas reales.
