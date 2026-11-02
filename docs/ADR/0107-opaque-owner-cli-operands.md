# ADR 0107: tratar las coordenadas opacas del owner como operandos de CLI

**Estado:** candidato de corrección para [RCA #265](https://github.com/mbalbo2023/boca-socios-assistant/issues/265)
en PR #261, 2026-11-02. No se ejecutó en el droplet ni se reintentó una
instalación. Se conservan los contratos de aislamiento de ADR0092.

## Defecto demostrado y alcance de la evidencia

Al investigar el [smoke 41514375981](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41514375981)
del candidato `7cfc9b60564f8c7bb8a589c86e15153c77bc948d`, se encontró un
defecto determinístico en el argv de owner enrollment.
Una clave pública base64url válida puede empezar con `-`. Sin terminador de
opciones, argparse la interpreta como una opción y sale con código 2 antes
de llamar a `serve`. La reproducción usa exclusivamente 32 bytes sintéticos
con valor 251, convertidos a base64url canónico, y su fingerprint SHA-256;
no recupera ni registra la clave concreta de aquella ejecución.

El run observado terminó antes de comprobar el listener, omitió los pasos
posteriores y ejecutó las limpiezas del runner. Ese comportamiento es
**compatible** con el defecto, pero no identifica retrospectivamente su
causa exacta: la clave del run no está conservada en la evidencia disponible.
No se presenta una hipótesis como diagnóstico confirmado del valor aleatorio.

La auditoría encontró la misma clase de problema con un subject que empieza
con `-`: los validadores de owner lo admiten, pero tanto el CLI interior
`owner_bootstrap.main` como el CLI exterior `host_first_deploy.main` lo
interpretaban como opción. Las reproducciones verificaron SystemExit 2 y
ninguna llamada a la operación mock. No se cambia la política de subject
para esconder el fallo ni se sesga/regenera la clave aleatoria.

## Corrección mínima de los productores

- El comando del contenedor temporal y su smoke pasan
  `python -m boca_socios.owner_enrollment -- SUBJECT DIGEST PUBLIC FINGERPRINT`.
  El separador precede todos los operandos, no sólo la clave pública.
- El productor de custodia offline y sus seis invocaciones de smoke pasan
  `python -m boca_socios.owner_bootstrap -- PHASE ORIGIN SUBJECT`.
- Las 18 invocaciones remotas del workflow que transportan owner usan
  `python3 - OPCIONES -- PHASE ... SUBJECT ...`. Las opciones browser/Telegram
  y sus arrays conservan exactamente sus valores y se ubican antes de `--`.
  Los operandos permanecen en el mismo orden y siguen escapados por
  `shlex.join`; no se cambia el parser central ni se crea otro transporte.

Los CLI y validadores existentes permanecen intactos. Se conservan límites,
puerto, red, volúmenes, revisión, digest, pins, origin y marker de intento.
Las otras invocaciones sin owner opaco no se modifican. Las claves públicas
usadas por `python -c` se consumen mediante `sys.argv`, sin argparse. El CLI
de Site sólo recibe una fase de lista cerrada; sus sobres entran por stdin.
No se identificó allí el defecto y no se amplía ese alcance.

## Limpieza y continuidad de intentos previos

El reconocimiento estricto de cleanup acepta sólo dos formas del mismo
comando: la anterior de siete elementos y la nueva de ocho cuyo prefijo
es exactamente `python`, `-m`, `boca_socios.owner_enrollment`, `--`.
Sólo en esta última se normaliza el separador antes de aplicar las mismas
comprobaciones de subject, capability digest contra el marker, clave pública,
fingerprint, imagen, revisión, UID, límites, red, puerto y único mount.

Un subject literal `--` es válido en el contrato existente: en la forma
anterior de siete argumentos sigue siendo un dato y no se descarta. La forma
nueva también puede transportarlo después del terminador. Argumentos extra,
otro módulo, un separador desplazado, opciones no reconocidas, tipos erróneos
o un digest distinto del intento bloquean antes de cualquier stop/rm.

Aceptar la forma anterior permite retirar de forma selectiva los residuos de
un intento que haya terminado en argparse antes de escuchar. No se añade una
nueva categoría de contenedor ni se amplía qué recursos puede eliminar la
limpieza. Persisten owner/key/data y los recursos de identidad incierta.

## Regresiones y límites

Las primeras regresiones produjeron 14 fallos y nueve casos negativos/legacy
satisfactorios; otras 18 reprodujeron el parser exterior antes del cambio.
Las pruebas pasan el argv real de producción y del Bash del smoke al CLI
original, sustituyendo sólo la operación final por un mock para no abrir
puertos ni ejecutar custodia. Las invocaciones remotas se prueban con arrays
opcionales vacíos y presentes, verificando operandos, pins, IDs y opciones.
La limpieza usa sus fixtures de Docker aisladas y comprueba cero efectos ante
identidad dudosa, además de preservación de owner en ambas formas válidas.

Selectores principales de `tests/test_owner_enrollment_argv.py`:

- `test_dash_prefixed_public_key_from_real_caller_reaches_enrollment_cli`
- `test_dash_prefixed_owner_from_production_bootstrap_reaches_cli`
- `test_each_protected_owner_transport_reaches_host_cli_without_changing_options`
- `test_cleanup_recognizes_exact_legacy_and_terminated_enrollment_commands`
- `test_uncertain_enrollment_argv_preserves_every_resource_before_cleanup`

La prueba local no acredita listener real, Chrome/passkey ni un despliegue.
El candidato exacto requiere revisión independiente, CI/seguridad y el smoke
Docker real antes del merge. Un fallo previo no se convierte en PASS por esta
corrección y no autoriza repetir operaciones protegidas automáticamente.
