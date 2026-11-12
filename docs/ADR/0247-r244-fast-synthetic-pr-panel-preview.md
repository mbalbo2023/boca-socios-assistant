# ADR0247 — Preview sintético temprano en PR internos Boca

Fecha: 2026-11-12 (ART). Issue #417. Estado: **CANDIDATO / CODE_ONLY**.

## Contexto y decisión

El workflow `Boca panel preview` ya ejecuta `synthetic-preview` para PR del
mismo repositorio, condicionado a cambios del propio panel, generador, tests
o workflow. Su salida HTML sólo se subía como artifact mediante una ejecución
manual sobre `main`. La vista previa del PR #489 corrió aproximadamente en
cuatro segundos, pero su upload se omitió por esa condición histórica.

Extender **únicamente** la subida y el enlace del resultado sintético a PR
internos cuyo destino sea `main` del repositorio exacto. Las contribuciones
desde forks siguen fuera del job y del paso de subida. Se conserva el modo
manual en `main` sólo para el propietario. El artifact tiene retención de
siete días, se etiqueta por el `github.sha` del run y se enlaza desde el
resumen del propio workflow. No se crea sitio, puerto, servicio ni imagen.

## Frontera de privacidad

Se mantiene el generador original `scripts/generate_panel_preview.py` y sus
cuatro estados **fijos y ficticios**. Se ejecuta con entorno limpio
(`env -i`, PATH y PYTHONPATH explícitos), sin claves/DB/servicios/SSH. Antes
de subir, el mismo job rechaza un archivo ausente, simbólico, no regular o
mayor de 64 KiB; exige marcas visibles de ficción y descarta correos, URL,
formularios, recursos externos, iframes, imágenes, atributos `on*`, código
JavaScript remoto y patrones obvios de credenciales. La validación falla
cerrada antes del artifact; no revisa secretos de un host porque nunca los
lee ni los posee. El resultado es material público del repositorio, **no**
el verdadero panel autenticado.

Los PR internos pueden contener código modificado: por eso se limita al
repositorio y base exactos, se evita suministrar tokens al proceso render y
se exige inspección de código y CI regular antes de fusionar. No presentar
la comprobación de cadenas como garantía contra cualquier contenido privado
que un autor malicioso pudiera introducir deliberadamente. No usar el
artifact como una entrada a release, despliegue o verificador protegido.

## Pruebas y promoción

TDD local: 10 pruebas nuevas fallaron contra el antiguo upload manual o
un guard inexistente. Luego 14 pruebas focales aprobaron con el guard,
incluyendo rechazo activo de URL, formulario, correo, script externo,
handler, `javascript:` y tamaño excesivo. Los tres últimos casos tuvieron
su propio ciclo RED→GREEN. Faltan todavía la suite completa y un run real
de GitHub sobre el SHA candidato; un pass local no prueba que Actions suba
el artifact. La vista previa de PR **no modifica ni sustituye** los
contextos requeridos `CI / quality-and-tests` y `CI / image-build`, los dos
Trivy, release exact-SHA, passkey ni postflight del puerto 8443.

**Rendimiento:** se espera feedback visual temprano en el rango histórico
del job de ~4 s, no una reducción del pipeline CI principal de ~254 s ni
del tiempo del deploy. Registrar tiempo y URL artifact reales antes de
afirmar disponibilidad o ganancia tras merge. No disparar builds ni pruebas
Docker adicionales para este cambio.

Supersede solamente el párrafo histórico de artifact manual en
[ADR0013](0013-accessible-simulation-panel.md), no su renderer ni el
producto de simulación. Regla 84: informar al dueño del candidato y
reconciliar el checkpoint #417 al integrar el PR único.

## Evidencia real en el PR R244

[Actions #43307951109](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43307951109)
terminó **SUCCESS** desde la rama interna del [PR #493](https://github.com/mbalbo2023/boca-socios-assistant/pull/493).
La subida concluyó y GitHub registró artifact **13985245354**, 1 888 bytes,
`boca-panel-synthetic-preview-b6a0403d58296f24f0119ca64a079ed5fc056005`,
digest ZIP `sha256:3751d0f551ae7373b1579b2d404ecbf99fddc64c7d90d83e9b4b9d77c38c932b`,
retención hasta 19-NOV-2026. Head PR
`c49b1ba83b6d528e22bc556f9596439dc9c787f8`; el nombre usa el SHA de
merge sintético del run, no un SHA de release. Esta disponibilidad rápida
no demuestra el funcionamiento del dashboard físico del droplet.
