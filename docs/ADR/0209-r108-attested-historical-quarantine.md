# ADR0209 — Retención probatoria exacta de imagen histórica en Cutover V3

Fecha: 2026-11-07 ART. Alcance: issues #417 y #45. Estado: CODE_ONLY hasta
PR, controles completos, merge, release nueva y recibo físico del droplet.

## Evidencia y causa independiente

El inventario READ_ONLY #862 / run `42415370909` confirmó un controller legacy
saludable en `127.0.0.1:8443`, stage ausente, cero workers/candidatos y una
única imagen Boca no referenciada con ID
`sha256:a44453ab30cb17fa42f71723cf64b1097dabdf0e56369186077c47bc8224f90b`.
Su release #41559973013, artefacto #13196392925, commit
`0e830e3eed941de1da70cef8b42bda9f20258b65` y digest
`sha256:7afe5429e34bd39b289e9d1da700fd5cd436cd2bdd413a2c4f8039829f1d034e`
figuran en #386/R26.1. El label OCI `source` ausente obliga al clasificador
genérico a considerarla desconocida. `_precommit_legacy_image_cleanup` y el
finalizador del Cutover rechazaban la incertidumbre de modo independiente.

El retiro histórico específico #746 / `42261978336` ya falló con exit 3 sin
ACK verificable. La imagen sigue presente. No conocemos la subcausa exacta
del fallo de ese retiro, ni la subcausa física original de `PREPARE_WORKER`
en Cutover #853; este ADR no atribuye ninguna de ellas a Docker/espacio.

## Consenso de Arquitectura, DevOps y procedencia

Se eligió retenerla **explícitamente como evidencia forense** hasta RCA
separado, en lugar de repetir a ciegas una eliminación. Dos revisores
independientes (arquitectura/Cutover y procedencia de imágenes) recomendaron
el mismo alcance sin disenso: prueba de ID/digest/revisión/tamaño, cero tags,
alias y referencias, inventario fresco bajo el mismo lease y aplicación tanto
antes del commit irreversible como en cada probe del finalizador.

La excepción a AGENTS.md es real y deliberada: la norma general exige borrar
imágenes Boca obsoletas después del éxito. **Se admite conservar solamente
este ID histórico probado** y se debe declararlo en recibo. No es correcto
decir que el host quedó sin imágenes antiguas. Ningún otro `unknown` puede
pasar, tampoco un ID global fuera del inventario Boca o un cambio de
filesystem; no se usa `prune`, `rm -f` ni limpieza global.

Se rechazaron (a) repetir el retirement fallido #746 y (b) convertir
referencias Boca o `preserve_images` en autorización genérica para ignorar
incertidumbre. La procedencia se obtiene del observador de metadatos públicos
que ya existía; no se inspeccionan imágenes ni contenedores ajenos.

## Contratos implementados

- `attest_historical_retained_image` valida la coincidencia completa del
  único artefacto histórico; no crea ni elimina recursos.
- Precommit preserva únicamente ese ID si la prueba aparece y sigue
  rechazando cualquier otro residuo desconocido, antes del retiro original.
- `execute_protected` bajo lease vuelve a obtener y probar cada inventory
  antes/después de borrados exactos de otros recursos Boca. Si falla la
  identidad o el Docker graph, no genera un falso `ACCEPT`.
- El recibo habitual V1 sigue inalterado cuando no hay cuarentena; en el caso
  excepcional el recibo V2 expone `retained_attested` con clasificación,
  ID, digest, revisión, run y artefacto. `retained_uncertain` y
  `known_residue` deben seguir vacíos para `ACCEPT`.
- El runner valida ese esquema exacto; campos extras, otro ID, otra versión
  o cualquier mutación siguen `NO_GO`.
- El bundle protegido ajusta únicamente el límite de bytes de código sin
  comprimir de 860.000 a 868.000, según el tamaño medido del código nuevo.
  Se conservan el allowlist fijo, pin SHA256, máximo comprimido 512.000,
  límites de recuperación/preflight y demás controles de seguridad.

## Pruebas y definición de éxito

TDD: los tests del nuevo contrato fallaron RED antes de implementarlo.
Se cubren coincidencia exacta, variaciones negativas, ref compartida,
ausencia, drift entre probes, otro residuo y parser de receipt V2.
QA/arquitectura y CI exact-SHA son requisitos antes de fusionar.

La release #759 ya existente corresponde al SHA anterior
`8134a04239ec1ddce841c5dc9cf91da07d2951d2`; **no podrá usarse**
para instalar código R108. La BETA no queda desplegada hasta una nueva
release dual de `main`, PR0, el único Cutover V3 protegido por Actions,
ACK físico, cleanup V2 e inspección funcional del servicio. Se mantienen
SIMULATION_ONLY y prohibición de navegar Boca real o modificar blackboxes.
