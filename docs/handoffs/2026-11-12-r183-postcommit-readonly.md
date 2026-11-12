# R183 — RCA postcommit del despliegue BETA consolidado Boca (#417 + #12)

**Fecha:** 12 de noviembre de 2026 ART. **Fuente:** GitHub físico,
no estado de conversaciones. **Owner:** agente que recibió la transferencia
expresa del #417; scope exclusivo Boca. **Ejecución:** `NO_GO` hasta que
el upgrade se certifique. Esta nota distingue evidencia, hipótesis y acción.

## Estado físico comprobado antes de este PR

- Merge [#484](https://github.com/mbalbo2023/boca-socios-assistant/pull/484):
  `main=b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`.
  7135 pruebas + 34 subpruebas aprobaron en el candidato, una prueba
  AF_UNIX sandbox fue SKIP; CI postmerge y seguridad SUCCESS.
- [Release #43215180354](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43215180354)
  SUCCESS, controller digest `sha256:b13d08fae35ca48799cbd3134b32bbcb94098f6616692ef86820f81544d5a256`,
  worker digest `sha256:fa40e8f0e3937c42082be5854ab3fcfc0e83218fb1313a310402f7d54a628d98`.
- [APPLY #43217075287](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217075287):
  `state=NO_GO`, `commit_started=true`, `failed_phase=RETIRE_OLD`,
  `old_restored=false`, `cleanup=INDETERMINATE`; **prohibido afirmar ACCEPT**.
- [Censo #43217501562](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217501562)
  READ_ONLY: un controlador y un worker Boca, ningún tercero Boca;
  no demuestra por sí solo la identidad de esos dos contenedores.
- [Observador de par #43217639570](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43217639570)
  READ_ONLY `NO_GO/HOST_UNVERIFIED`, sin categoría fina del rechazo.
- [Estado de navegador #43218455801](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43218455801)
  READ_ONLY validó binding nuevo exacto, controlador
  `85316ccec82b11fe2832b6f86473ac2e88167533dda82b5ab86bbe46d7bbf7c2`
  HEALTHY y worker
  `8fc47f7981b71a33ae836d6ae36253292c9ef915e463d6c83e2e4451b8cf7def`
  CREATED/PID0. Motor STOPPED.
- [SQLite #43218833807](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43218833807)
  NO_GO; el observador `host_boca_sqlite_identity._attest_boundary`
  requiere que pase antes el mismo observador de par que falló.
  **Por tanto el resultado NO prueba corrupción ni cambio de inode**.

## RCA reproducible y punto de incertidumbre

`host_boca_pair_upgrade_backend.retire_old` elimina los dos CID previos
y luego llama `host_on_demand_replace.commit_binding`, que exige
`_new_pair_only(new)`. Este último invoca el **observador estricto de par**:
un rechazo puede impedir la limpieza de bytes ya aparcados aunque el
controlador nuevo esté HEALTHY. También podrían fallar la comprobación
del binding o el retiro de los archivos antiguos. No decidir causa raíz
definitiva sin identificar la rama exacta de fallo, y nunca reejecutar
`boca-pair-upgrade-apply` contra un host ya modificado.

## PR de diagnóstico R183, sin efectos

Nuevo `workflow_dispatch` `boca-postcommit-observe`:

1. SHA de `main` comprobado inmediatamente antes de SSH, usuario exclusivo
   `boca-deploy`, Python fuente transportada por ZIP allowlisted y memfd
   con hash, sin ejecución de comandos arbitrarios.
2. Doble snapshot de censo Boca y reconocimiento de los **dos CID exactos**
   de #43217075287 (guardas globales de ID/nombre únicamente, sin inspección
   de objetos ajenos). El mismo observador de par
   se invoca bajo excepción controlada y traduce a **categorías limitadas**
   como `MOUNT_PROFILE`, `NETWORK_PROFILE`, `HEALTH_FIELD`, etc. Una aprobación
   genérica solo se declara `pair=PASS` si también coinciden el SHA, el run
   del intento fallido, ambos CIDs/digests, controlador healthy y worker
   CREATED/PID0. Ningún error/valor/credencial de Docker sale al runner.
3. `lstat` **de tipo exclusivamente**, nunca contenido, de cuatro rutas
   Boca de ese intento, anclado mediante `openat(O_NOFOLLOW)` en cada padre:
   raíz apartada, marcador, su directorio `socket`
   y su nodo `control.sock`. Doble lectura debe coincidir.
4. Recibo acotado a 768 bytes, en categorías, con
   `observer_writes=0`, `foreign_resources_touched=0` y
   `cutover_authorized=false`. `state=OBSERVED` **no equivale a ACCEPT**.

La operación no contiene `docker rm`, `docker start`, llamadas systemd,
socket writes, cambios de volúmenes, archivos SQL, navegación, envío de
credenciales o consultas a Boca/Queue-it. El motor permanece detenido.
Se mantienen aparte los dos contratos reales de tokens de #12, que
se incorporan sin gate de proveedor y sin probar URLs/token mientras el
servicio externo esté indisponible. Reservas reales prohibidas.

## Toma de decisión posterior al dato físico

- Si `pair=NO_GO`, resolver la categoría que reporte el host, añadir TDD
  del perfil instalado y validar con un PR exclusivo antes de cualquier
  limpieza acotada. No relajar perfil arbitrariamente ni falsificar PASS.
- Si `pair=PASS`, eso solo demuestra el par **actual**; no prueba lo que
  `RETIRE_OLD` vio durante el APPLY ni identifica por sí solo su RCA.
  Contrastar la ruta de binding/archivos apartados y el journal causal del
  intento; diferenciar precondición, `control.sock`, unlink o rmdir.
  Cualquier posterior limpieza requerirá prueba de propiedad de los bytes
  inequívocamente Boca de este intento y compensación explícita.
- En todos los casos comprobar SQLite inode, owner/passkey, worker on-demand,
  panel 8443 y pruebas BETA **sin navegar a proveedor**. Entregar
  `BOCA_PAIR_UPGRADE state=ACCEPTED cleanup=ACCEPT` o `NO_GO` evidenciado;
  jamás declarar GREEN por mera sintaxis, CI o panel HEALTHY.

El PR R183 no habilita ningún APPLY; sirve para hallar un RCA verificable.
