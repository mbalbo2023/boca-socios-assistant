# ADR 0196 — R87: recuperación exacta stopped-only del worker #819

**Fecha:** 2026-11-07 ART. **Ownership:** [RCA #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417), [continuidad #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45). **Decisión:** reutilizar el recovery R80/R82, con nuevo target/Action fijo y revisión independiente; **la implementación CODE_ONLY no acredita limpieza física**.

**Coordinación de scope:** el issue [#352](https://github.com/mbalbo2023/boca-socios-assistant/issues/352) reservó históricamente el workflow al frente `workflow_wiring`, pero no existe PR/branch concurrente de ese frente. Para R87 hay **un solo escritor** del YAML, el integrador del RCA #417; Arquitectura/Infra/QA revisan, sin un segundo PR de wiring ni dos escritores. El trabajo de ACK lifecycle/Telegram de #352 queda intacto y no se considera implementado por esta recuperación.

## Evidencia que permite diseñar, no ejecutar a ciegas

El preflight único [#819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231) falló `CLEANUP/INDETERMINATE` en `STOP`. R86 fue fusionado mediante [PR #428](https://github.com/mbalbo2023/boca-socios-assistant/pull/428), `main=2859b9d31621e3cbec70b1aec649cc281ba130f5`, CI y seguridad postmerge GREEN. Su inventario protegido [#821](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42355552701) produjo **`READ_ONLY_NO_GO`, cero escrituras**. Acredita para ese instante:

- Probe exacto #819 `PRESENT_PIN_MATCH`, `probe_running=false`, CID `4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547`; JSON completo `BELOW_CLEANUP_LIMIT`.
- Seccomp de intento `ABSENT`; Docker rootless/socket `PRESENT_OWNED`.
- Controlador legacy exacto `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`, `RUNNING_HEALTHY`, `LOOPBACK_8443`.
- No se puede inferir por qué falló STOP ni que la limpieza haya concluido. No repetir #819.

## Opciones examinadas y consenso de diseño

1. Reintentar STOP o preflight: rechazado; estado posterior indeterminado y posible efecto ya consumado.
2. Limpieza general, `prune`, ruta nueva o CID ingresado por usuario: rechazados; no demuestran ownership y ampliarían la superficie de escritura.
3. **Elegido por Arquitectura, Infra y QA**: ampliar el módulo y la operación única ya existentes de recuperación *stopped-only* con `TARGET_819` y una nueva admisión exacta. No tocar la superficie de Cutover, otros Docker/Porota, BLACKBOX ni el controller sano.

## Contrato físico limitado

Única operación `cutover-a-worker-recover-819`, visible `BOCA-R87-WORKER-819-RECOVER-ONCE`; servicio `controller`, presupuesto `1.5cpu-1024m-192pids`, resto de inputs vacío. Sólo GitHub Actions manual protegido, main HEAD del día, owner `mbalbo2023`, intento 1, PR0, SHA exacto y variables protegidas. Gate contra REST genuino de #819 (failed), #821 (READ_ONLY success), release dual [#732](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42352641660) (success, fuente histórica R85), y **156 números de pasos/estados** de ambos jobs históricos. Una sola dispatch R87 en toda la historia consultada, incluso si cambia main; evidencia incompleta o nueva PR cancela antes de SSH.

El ZIP memfd es el recovery existente de siete entradas; no importa otras fuentes ni lee navegación. Bajo **lease rootless exclusivo Boca**, se hacen dos snapshots independientes y dos inspecciones Docker `inspect` de JSON completo contra pins de intento/CID/nombre/imagen/SHA/labels, flags de aislamiento, ausencia de binds/mounts/red/puertos, estado no Running y legacy sano. Perfil seccomp bajo hash exacto `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`, seccomp temporal observado `ABSENT`.

Sólo si todo coincide: **un único `docker container rm` sin fuerza** del CID inmutable. Nada de `stop`, `-f`, imágenes, red, volúmenes, containers vecinos, `exec`, apps externas o puerto 8443. Verifica ACK, ausencia exacta de CID, nuevo snapshot con legacy sano y recibo JSON canónico. Fallo, timeout, ACK perdido o resultado contradictorio → `INDETERMINATE`, **NO_RETRY**, no Cutover/GO_B/APPLY automático.

El workflow ahora recibe stdout SSH dentro de directorio aleatorio privado `0700`, archivo `0600`, `ulimit -f 8` confirmado **antes** de SSH; terminal `always()` verifica recibo y retira sólo ese directorio/archivo. El artefacto de runner se crea en modo *noclobber*; symlinks preplantados no se siguen. No se publica salida Docker o secretos; el único artefacto remoto aceptable es `boca-worker-recovery-42353468231` cuando el verificador concluye `CLEANED`.

## Criterios de aceptación y siguiente frontera

- CODE_ONLY: pruebas reales de Bash con GitHub REST/SSH falsos, matriz adversarial de identidad/no-reintento, regresiones R79/R80/R82/R86, ZIP/caps, tests globales, Ruff/mypy/política, review independiente y PR/CI exact SHA.
- Físico: **GO independiente Arquitectura/Infra/QA sobre SHA exacto y PR0**, un único Action protegido y recibo terminal + artefacto verificables en GitHub; sin resultados implícitos ni autorización nueva del usuario dentro del alcance ya concedido.
- Recuperación física `CLEANED` **sólo quitaría ese residuo**. Continuar Cutover requiere nueva revisión de causalidad `STOP`, release dual correspondiente al nuevo main, preflight fresco y gates completos. Si R87 queda NO_GO, documentar, observar en READ_ONLY si está justificado, **jamás reintentar R87**.

Véanse el [diseño](../superpowers/specs/2026-11-07-r87-exact-stopped-worker-819-recovery.md) y el [plan TDD](../superpowers/plans/2026-11-07-r87-exact-stopped-worker-819-recovery.md). Los números de pruebas y runs futuros se registran en los issues, sin anticipar GREEN.
