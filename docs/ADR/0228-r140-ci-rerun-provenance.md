# ADR0228 — R140: reintento autenticado del mismo CI no bloquea Cutover

Fecha: 2026-11-10 ART. Owner: #417. Estado: CODE_ONLY, pendiente CI y recibo físico.

## Incidente y causa

El `main=ff3eda2888112013aa7dbcf6d0925b0bb13ad4a1` ejecutó CI
`42759806927`: `quality-and-tests` pasó, pero `image-build` falló en el
primer intento al agotarse una conexión con el espejo Ubuntu Security durante
`apt-get update`. El propietario repitió **solamente** el trabajo fallido.
El mismo CI, SHA y `check_suite_id=115805917037` terminó en SUCCESS con
`run_attempt=2` y ambos checks requeridos GREEN. El gate V3 exigía que
también el CI tuviera `run_attempt=1`: habría rechazado el Cutover **antes
de SSH**, pese a su conclusión autenticada. No se ejecutó otro Cutover.

## Decisión de alcance mínimo

`verify_completed_ci` acepta `run_attempt` entero `1` o `2` de un único
`ci.yml` `push/main` para el SHA exacto, y exige `triggering_actor=mbalbo2023`
si hubo el único reintento permitido. Un tercer intento queda NO_GO y exige
revisión fix-forward. Conserva `conclusion=success`, `status=completed`,
repositorio original y cabeza, `check_suite_id` del CI, ambos checks únicos
`quality-and-tests` e `image-build`, su aplicación GitHub Actions, mismo
SHA/suite y conclusión SUCCESS. Las dos lecturas pre-SSH de Checks usan
explícitamente `filter=latest`: `filter=all` incluye fallos históricos del
primer intento y no es una representación de los checks vigentes.

**No se flexibiliza el Cutover**: su `GITHUB_RUN_ATTEMPT=1`, actor/triggering
actor propietario, único dispatch en el historial, main inmutable, PR0,
release dual exacta, Environment, UID10001 rootless, lease, limpieza y ACK
físico siguen siendo obligatorios. Tampoco hay reintento automático de CI,
Cutover ni Docker, ni se autoriza reemplazar un CI fallido por un workflow
extraño que publique los mismos nombres de checks.

## Pruebas de regresión y verificación pendiente

- RED antes del cambio: CI `run_attempt=2` del mismo dueño/SHA/suite se
  rechazaba. GREEN después del ajuste.
- Rechazo: intento ausente, `bool`, cadena, cero, negativo; rerun de actor
  ajeno; checks fallidos, ausentes o suite extranjera.
- Prueba de wiring: las dos adquisiciones para V3 piden Checks `latest`.
- Falta CI exact-SHA, seguridad, revisión, merge, CI de main, nueva release
  dual, único Cutover y recibo físico. **El ExitCode=1 del worker #899 sigue
  sin causa interna demostrada** y la nueva BETA no se declara instalada.

Los módulos BLACKBOX `synthetic.py` e `ipc_worker.py` no se leen, importan,
prueban ni modifican. No se toca otro Docker, host, puerto, credencial,
volumen ni servicio ajeno. Referencias: ADR0206 y #417/R140.
