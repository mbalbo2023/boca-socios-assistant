# ADR 0153 — NO_GO pre-SSH para instalaciones legacy sin postflight Boca-only (#323)

Fecha: 2026-11-05 ART. Estado: **DRAFT / CODE_ONLY / NO HOST**.

## Hallazgo y causa raíz

La orden permanente del propietario exige limpieza Docker selectiva **después
de cada instalación/despliegue/actualización Boca, tanto exitosa como fallida**,
con inventario de staging y del Docker rootless, IDs verificados y recibo
terminal. La implementación aislada `host_boca_cleanup.py` y su corrección
dual-filesystem ADR0148 no se ejecutan automáticamente al existir el archivo.

El workflow anterior aún exponía seis operaciones de instalación histórica
fragmentadas entre diferentes procesos SSH:

- `first-install`, `beta-install` y `beta-browser-install` arrancaban servicios,
  pero limpiaban sólo en ramas de fallo; la ruta GREEN carecía de finalizador
  obligatorio con el mismo lease.
- `site-install`, `owner-install` y `telegram-install` tampoco contaban con
  atestación universal de finalizador de éxito y fallo. Son contratos de
  instalación, aunque no necesariamente cambian la imagen del controlador.

Agregar a esas rutas otro comando SSH de limpieza no sería equivalente: los
FD de `flock`, identidades del intento y recibos O_EXCL no atraviesan
transacciones SSH separadas. Tampoco sería correcto ejecutar `docker prune`
ni borrar por nombres aproximados, especialmente porque el droplet comparte
host con Porota y otras aplicaciones. La ruta históricamente instalada del
controlador ya está ocupando `127.0.0.1:8443`, por lo que repetir una primera
instalación no es una solución de migración.

## Corrección mínima y efecto funcional

En el **mismo único** `.github/workflows/boca-first-deploy.yml`, después de
los gates básicos pero **antes de checkout, SSH o cualquier efecto en host**,
un paso obligatorio clasifica estas seis operaciones y retorna:

`BOCA_POSTDEPLOY state=NO_GO reason=legacy_install_without_same_lease_finalizer`

El resultado conserva los recursos Boca y extranjeros, impide que una
instalación sin limpieza obligatoria parezca GREEN, y exige un nuevo cambio
revisado para construir una transacción única por operación antes de volver
a habilitarla. **NO_GO aquí no es un fallo de limpieza física realizada**: la
operación se bloqueó deliberadamente **sin entrar al host**. Tampoco se
elimina ninguna ruta de `workflow_dispatch`, para que se vea claramente el
motivo en vez de recurrir accidentalmente a un flujo alternativo.

La operación **`cutover-a-apply` sigue alcanzable** y conserva sus propios
controles más estrictos: variable de GO independiente atada al run y al SHA,
revisión de manifiestos/ZIP, segundo check de main justo antes del SSH,
transacción memfd con **un solo SSH y lease**, `try/finally` de limpieza
positiva Boca-only, terminal O_EXCL y assertion `if: always()` que rehúsa
aceptar ausencia o ambigüedad de recibo. Que el nuevo paso la deje pasar
**no es una autorización física**; con GO ausente continúa NO_GO antes de
SSH. La aprobación de un PR o los tests verdes no hacen un deploy.

Las operaciones de observación, diagnóstico, reanudación/parada de servicios
ya existentes y enrollment no considerado deploy conservan sus gates y no se
bloquean con esta medida. Futuros `telegram-install` u otros cambios de
almacenamiento deberán tener limpieza propia probada o quedar integrados en
una transacción protegida con el mismo contrato.

## QA, riesgos y próximos pasos

La regresión `tests/test_boca_deploy_finalizer_r23.py` ejecuta **Bash real
sin credenciales ni red**, prueba que los seis `install` históricos salen
rojos antes de SSH, que `cutover-a-apply` y los diagnósticos no se deshabilitan,
y que el GO independiente y el receipt final del Cutover siguen en orden.
El archivo se agrega también al suite focal PR-only de FirstDeploy.

**Limitación esencial:** `if: always()` es un control de recibos, no garantía
de ejecución después de pérdida de runner, corte de energía, SSH/daemon
inaccesible o finalizer bloqueado por drift. El estado queda NO_GO o
INDETERMINATE y requiere inventario Boca-only en lectura, sin retry ciego.
No se realizó SSH, Docker, limpieza, release, merge, compra, reserva ni
backup. No se inspeccionaron ni modificaron `synthetic.py`/`ipc_worker.py`,
ningún secreto o carga de trabajo ajena.

Para cumplir por completo la orden permanente se necesitan: (1) cerrar el
GO exacto de Cutover A y su CI/predeploy, (2) desplegarlo una sola vez con
recibos reales de éxito y limpieza, (3) observar el estado físico en Samsung
Chrome + Termius y (4) sólo si se necesitan nuevos instaladores, refactorizar
específicamente sus rutas a transacciones host single-SSH con cleanup
garantizado por recibo en ambos resultados. Hasta entonces los seis caminos
legacy siguen `NO_GO` y **no** se declaran físicamente validados.

El SHA exacto, PR DRAFT y Actions de esta modificación se anexarán a #323 y
al checkpoint #45 tras publicarla; las pruebas locales se reportarán con
resultados reales.
