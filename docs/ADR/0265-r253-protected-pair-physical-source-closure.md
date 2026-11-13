# ADR 0265 — R253: tres productores físicos en el ZIP autenticado del par

**Fecha:** 12-NOV-2026 ART. **Issue:** #417. **Base local:** candidato R252
`8d5fdc5`, más tres commits R253 exclusivamente para probar el cierre de
imports. **Estado:** CODE_ONLY; el upgrade y la BETA permanecen NO_GO.

## Causa raíz y decisión

Los productores de postflight duradero y lectura de volúmenes, junto con el
ensamblador de lease única, estaban implementados en módulos Python nuevos,
pero el ZIP memfd del `boca-pair-upgrade-apply` solo permite una lista exacta
de fuentes. Si no se incorporan a **ambas** listas, GitHub puede validar el
árbol de código y el host rechaza la importación de los productores cuando
se necesiten. Un módulo importable desde Git no necesariamente existe dentro
del ZIP aislado del host.

Se incluyen **solamente en el perfil PAIR_UPGRADE**:

- `host_boca_durable_technical_postflight_v2.py`: recibo técnico durable,
  un solo uso y exacta lease.
- `host_boca_postflight_volume_attestor_v2.py`: observación de tres volúmenes
  Boca bajo identidad y nombres comprobados, sin leer datos privados.
- `host_boca_successor_assembly_v3.py`: ensamblador inerte de actores y
  journal compartidos, no autorización de Docker.

Se actualizan `PAIR_UPGRADE_SOURCES` en el builder y
`PAIR_UPGRADE_ENTRIES` en el verificador memfd con las **mismas tres rutas**.
No hay nuevas entradas de navegador, módulo BLACKBOX, sitio externo, scripts
de Cutover u otro proyecto. Los restantes formatos de ZIP, ambos límites,
SHA-256 completo, entrada regular, rechazo de enlaces/entradas inesperadas y
arranque desde `/proc/self/fd` quedan idénticos.

## Evidencia, presupuesto y continuación

- TDD reprodujo **ROJO** por falta de los tres módulos en el artefacto.
  Tras la reparación, dos pruebas nuevas verifican la lista exacta,
  importación en Python aislado `-I -B`, rechazo de una entrada extra con
  digest recalculado, y los topes. **58 pruebas focalizadas PASS** que incluyen
  R179/R247/R252/R253, productor duradero, attestor y ensamblador; Ruff,
  formato, mypy y política de repositorio PASS.
- Compilación local con los commits R253 de prueba: **78 miembros**,
  **360.367 bytes comprimidos**, **1.392.338 descomprimidos**. Siguen bajo
  los topes **480.000 / 1.400.000 bytes**, sin incremento. Quedan **7.662
  bytes de margen descomprimido**; el integrador deberá repetir una medición
  sobre el SHA final, y el builder sólo podrá retirar comentarios mediante
  su mecanismo ya probado de equivalencia AST/bytecode/saltos de línea si el
  nuevo conjunto supera el límite. No se eliminará código funcional para
  forzar la entrada ni se ampliará el máximo sin RCA y revisión.
- Esta rama no ejecuta el ensamblador, no adquiere lease, no inicia worker,
  no accede al droplet, no libera TLS ni acredita passkey o monitor real. El
  único canal futuro de efectos físicos continúa siendo la Action protegida
  Boca, una vez aprobados los interlocks, el código exacto y su evidencia
  física; R186 no se repite y se conservan los recursos R108.

**Ownership:** este cambio toca exclusivamente builder, bootstrap, prueba de
ZIP y este ADR. La activación física, cleanup y postflight auténtico pertenecen
al integrador de #417, con cierre administrativo DEPLOY NO_GO hasta completar
todos los comprobantes de instalación y aceptación del titular.
