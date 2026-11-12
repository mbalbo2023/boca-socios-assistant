# R186 — Finalización postcommit de Boca, incidente #43217075287

**12/11/2026 ART · issue #417 · scope exclusivo Boca · no repetir APPLY.**

## RCA comprobado

El [APPLY #43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287)
instaló el par nuevo y cruzó el marcador irreversible; falló en
`RETIRE_OLD` y conserva `NO_GO/INDETERMINATE`. R184 atribuyó el obstáculo
`WORKER_HEALTH_UNAVAILABLE` a leer Docker `State.Health` de un worker
`CREATED/PID0` donde el objeto no existe. La corrección R185 [PR #487](https://github.com/mbalbo2023/boca-socios-assistant/pull/487)
fue integrada como `main=b07947602d49148067ba4ce09191b680d2811301`.

Los tres observadores READ_ONLY posteriores:

| Run | Evidencia física | Lo que no acredita |
| --- | --- | --- |
| [#43229793525](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43229793525) | Par nuevo `PASS`, CIDs viejos ausentes, respaldo intacto, worker `CREATED/PID0` | Retiro del respaldo |
| [#43230025523](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43230025523) | Binding `MATCHED_EXACT`, archivo `VERIFIED_SHA256`, user systemd `VERIFIED_LISTENING` | SQLite |
| [#43230212167](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43230212167) | Inode SQLite `VERIFIED_STABLE` | Lectura de credenciales/servicio externo |

No hay aquí validación de URL con token, login Boca, Queue-it ni reserva;
el titular dispuso expresamente que la disponibilidad externa no frene la
promoción de los contratos #12, pero no permite inventar éxito real.

## Solución R186: únicamente respaldo histórico

Se incorpora la opción `boca-postcommit-finalize` a **la Action Boca existente**
`.github/workflows/boca-first-deploy.yml`. No se crea otro workflow con SSH:
el chequeo canónico `scripts/check_repo_policy.py` lo prohíbe y el mismo
mutex manual `boca-first-deploy` ya protege al resto de operaciones.

1. Action manual de propietario, `main` exacto, primera tentativa, cero
   PR abiertos, **CI e Image security postmerge SUCCESS del mismo SHA**,
   marcadores de entorno y las cuatro ejecuciones de arriba.
   El usuario selecciona `service=controller`, presupuesto normal; todos
   los pins y demás campos se dejan vacíos. La opción fija presupuesto
   `1.5cpu-1024m-192pids` e infiere `source_sha` desde `main`.
2. El ZIP memfd privado `--postcommit-finalize` se autentica por SHA256 y
   allowlist reducida, con smoke en Python aislado y dependencias transitivas
   declaradas, distinta del programa de upgrade. Sólo corre bajo
   UID/GID10001 y una **lease nueva**, distinta del intento fallido.
3. Relee dos veces el journal original `.intent/.commit/.terminal` con
   O_NOFOLLOW, dueño/modo/links, digest y forma canónica. Exige que siga
   `NO_GO`, haya cruzado commit y fallado en `RETIRE_OLD`; NO lo modifica.
4. Reprueba CID/imagen exactos, `8443` loopback, worker detenido, sistema
   de binding/units/archivo, cinco archivos históricos, intento original,
   SQLite inode y socket antiguo ausente; no lee datos SQLite.
5. Persiste un `.claim` O_EXCL+fsync exclusivo del incidente **antes** de
   borrar ningún inode. Repetición o interrupción queda en cuarentena.
6. Reutiliza `commit_binding_postcommit` para eliminar solamente unidades,
   archivo, binding, marca/socket directorio y metadatos antiguos Boca;
   **no Docker, no systemctl, no volumen, no otros proyectos**.
7. Comprueba par/binding/SQLite idénticos y respaldo ausente; crea su
   `.terminal` O_EXCL con `ACCEPTED` o `INDETERMINATE`. Nunca declara el
   APPLY original aceptado ni automatiza retry/rollback.

## Evidencia de implementación y próximo hito

- TDD aislado para journal corrupto/ausente, symlink, lease distinta, claim
  único, orden claim-antes-unlink, parada antes de claim, interrupción luego
  de claim, receipt canónico, ZIP determinista y contrato del workflow.
- El resultado de laboratorio y el SHA final de PR se registran al cerrar
  la revisión; no reemplazan certificado de Actions ni host.
- Tras CI exact-SHA y merge, despachar una única vez `Boca first deploy` con
  `operation=boca-postcommit-finalize`; no ejecutar `boca-pair-upgrade-apply`.
- Exigir `BOCA_POSTCOMMIT_FINALIZE state=ACCEPTED`, luego READ_ONLY del
  par/binding/SQLite y aceptación privada de panel/passkey/STOP-START.
- Si el host emite `NO_GO`/`INDETERMINATE`, seguir solo con RCA READ_ONLY,
  sin nueva ejecución effectful ni borrar la claim.

El browser permanece detenido a demanda, el sender Telegram OFF hasta
rotación de token y tickets siempre `SIMULATION_ONLY`. No se validan URL
con tokens mientras el servicio externo esté indisponible.

Decisión arquitectónica: [ADR 0236](../ADR/0236-r186-one-shot-postcommit-retirement.md).
