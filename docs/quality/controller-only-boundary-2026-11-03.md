# BETA controlador-only — contrato de importación protegido

**Fecha:** 2026-11-03 ART. **Estado:** prueba candidata de issue #291; no
equivale a despliegue, compatibilidad del navegador ni reserva real.

## Alcance y decisión

El titular reservó los módulos `browser/synthetic.py` y
`browser/ipc_worker.py` en [issue #288](https://github.com/mbalbo2023/boca-socios-assistant/issues/288).
Quedan excluidos de inspección, refactorización y ejecución por agentes,
junto con toda navegación por el sitio. Este cambio añade un control **externo
a esos módulos**, sin abrirlos ni modificarlos.

## Prueba específica

`tests/test_controller_only_owner_boundary.py` inicia un intérprete Python
descartable y bloquea *antes de cargar su código* cualquier importación de
esos dos nombres. En configuración `simulation`, `engine_mode=off` y
`browser_backend=off`, la selección del controlador debe utilizar el adaptador
local y conservar la espera acotada de cinco segundos.

No se inicia servidor HTTP, browser worker, Chrome, Queue-it, compra, reserva
ni tráfico hacia Boca. La prueba no acredita la compatibilidad funcional de
los módulos reservados si el titular decide activarlos más adelante.

## Gates y operación

- El test de frontera acompaña, pero no sustituye, los checks completos de
  lint, tipo, CI, imagen y seguridad para un SHA final.
- El controller-only continúa bloqueado en host por la red rootless
  [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275),
  activación privada [#209](https://github.com/mbalbo2023/boca-socios-assistant/issues/209)
  y ausencia de recibo `beta-install`.
- El despliegue futuro sólo puede realizarse desde el workflow manual Boca,
  sin `beta-browser-install` ni tareas de navegación.

Registrar commit, ejecución y resultado real de este candidato en
[issue #291](https://github.com/mbalbo2023/boca-socios-assistant/issues/291),
[PR #292](https://github.com/mbalbo2023/boca-socios-assistant/pull/292)
y en [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
