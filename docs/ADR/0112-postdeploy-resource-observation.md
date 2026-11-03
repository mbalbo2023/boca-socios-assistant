# ADR 0112 — Medición posdespliegue y separación de márgenes preventivos

**Estado:** candidato PR #273, pendiente de CI/revisión/merge. **Fecha:** 2026-11-02 (ART).  
**Issue:** [#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259).  
**Decisión del dueño:** [#45, corrección vigente](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6592430471).

## Contexto y evidencia

La BETA funcional todavía no fue instalada en el droplet. El preflight protegido
[run #290](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41554595096)
sobre `main=ea753ccab29d112b374a07b167d92e68c714cddd` finalizó FAILURE
en «Observe infrastructure and evaluate unchanged reserve before release».
La inspección inicial y el arranque temporal del daemon dedicado pasaron, y
el paso «Always restore verified stopped daemon after infrastructure attempt»
terminó SUCCESS. No hubo instalación, publicación ni cambios a otras apps.
Los valores exactos del recibo de observación están en el resumen protegido,
no en los logs públicos; no se puede atribuir de manera demostrada ese FAIL a
un único recurso sólo a partir del nombre del paso.

[#259](https://github.com/mbalbo2023/boca-socios-assistant/issues/259)
ya establecía que 1536/1792 MiB, 1.75/2.0 CPU y 256/288 PIDs eran márgenes
preventivos elegidos para dos o tres servicios, **no mediciones** del consumo
real de BETA. Un máximo configurado de contenedor no es memoria reservada ni
mínimo físico requerido. El dueño ordenó medir y observar **después de
desplegar** la BETA y rechazó esos umbrales como requisito de admisión.

## Decisión de arquitectura para el candidato

1. **Observación previa sin veto de holgura:** `infrastructure-preflight`
   conserva validación de UID/bus/rootless, unidad efectiva, inventario Boca
   vacío, puerto exclusivo 127.0.0.1:8443, Docker/Compose, identidad de
   almacenamiento y restauración del daemon detenido. Los valores de RAM,
   techo estructural CPU, PIDs y almacenamiento se publican como observación
   y referencias de dimensionamiento: `BOCA_INFRA_POLICY ... result=OBSERVED
   meaning=postdeploy_measurement_required`, con estados PASS/BELOW informativos.
   El parser exige exactamente dos líneas canónicas, SHA y budget exactos y
   `phase_rc=0`; no acepta errores de transporte, datos malformados ni firmas
   distintas. Nunca se convierte un NO_GO técnico en PASS.
2. **Instalación y lifecycle:** los controles `_browser_capacity` anteriores
   a descarga, posteriores a descarga y antes de reinicio conservan la lectura
   de metadata válida, la identificación de Docker rootless y la comprobación
   de almacenamiento; no rechazan sólo porque RAM/CPU/PIDs estén por debajo
   de una holgura no calibrada. Contadores imposibles/no positivos siguen
   fallando antes de efectos. La protección por Docker cgroups, namespace,
   seccomp, `network:none` del worker, engine off y límites exactos de
   CPU/RAM/PIDs **no se modifican**.
3. **Seguridad de disco:** los controles existentes de espacio/inodos para
   proteger el store Docker compartido y evitar residuos siguen siendo gates
   de seguridad. El valor de 4 GiB/50 000 inodos no debe presentarse como
   consumo medido de BETA ni extrapolarse a los recursos CPU/RAM/PID. Si
   impide una instalación, se requiere diagnóstico específico del tamaño
   real de imágenes y espacio, no `prune` ni desplazamiento de otras apps.
4. **Medición después del despliegue:** tras la instalación aislada se debe
   registrar un recibo del host para el par controller/Chromium con salud,
   consumo/latencia observada y comportamiento bajo la carga sintética
   prevista, usando los mecanismos de aceptación y observación ya existentes.
   El envío de Telegram exige su custodia y comprobación independientes.
   Estas mediciones validarán el dimensionamiento futuro; sus valores no se
   anticipan con la prueba de runner ni con `MemAvailable` aislado.
5. **Contención si aparece presión real:** detener sólo componentes Boca con
   sus identidades positivas; preservar datos/clave/owner/Telegram y limpiar
   únicamente residuos demostrados del intento. No se tocan otros servicios,
   puertos, datos ni configuración del droplet.

## Alternativas descartadas

- Bloquear una BETA no medida por márgenes de holgura elegidos en código.
- Suponer que requiere ampliar/comprar otro servidor sin medirla.
- Eliminar todos los límites o desactivar controles de identidad, disco,
  namespace y cleanup.
- Reintentar #290 automáticamente o usar SSH fuera del workflow protegido.

## Evidencia para integración y operación

El PR #273 debe incluir regresiones que prueben observaciones por debajo de
los márgenes, parser estricto y rechazo de metadata inválida/almacenamiento,
más CI, seguridad, revisión técnica y postmerge sobre el SHA exacto. Sólo
entonces podrá haber release dual inmutable y operaciones manuales protegidas.
Ningún paso de este PR constituye despliegue ni valida Chrome/Telegram
físicos. Mantener congelado main durante release y activación.
