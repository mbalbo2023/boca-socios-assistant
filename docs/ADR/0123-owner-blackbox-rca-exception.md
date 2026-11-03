# ADR0123 — excepción RCA estricta para caja negra del titular

**Fecha:** 2026-11-03 ART. **Estado:** candidato de [issue #295](https://github.com/mbalbo2023/boca-socios-assistant/issues/295), pendiente de CI exacto y merge.

## Decisión y autoridad

El titular declaró `src/boca_socios/browser/synthetic.py` e
`src/boca_socios/browser/ipc_worker.py` como **caja negra validada
externamente** el 03/11/2026. Prohibió a los agentes abrir, interpretar,
refactorizar, corregir o alterar esos archivos, y ordenó excluirlos de
linters y pruebas sintéticas de Chromium. Esta ADR implementa sólo el
efecto sobre el gate de regresiones históricas; no interpreta los módulos
ni presenta su validación externa como prueba funcional propia.

El gate conserva intacto `docs/quality/rca-lessons.json`: todos los IDs
y todos los selectores históricos siguen registrados. En condiciones
normales **cada selector debe figurar aprobado en el JUnit actual**.
La nueva excepción no se aplica a otros tests ni a nuevas regresiones.

## Alcance exacto de la excepción

Sólo se pueden sustituir 11 pruebas históricas cuyo archivo de test
importa los módulos exclusivos del titular:

| Lección retenida | Archivo de test | Selectores exceptuados |
| --- | --- | ---: |
| RCA-227 | `tests/test_browser_on_demand.py` | 3 |
| RCA-235 | `tests/test_browser_ipc.py` | 3 |
| RCA-257 | `tests/test_browser_ipc.py` | 5 |

La lista completa de 11 selectores, autoridad del titular y dos SHA-256
figura en
`docs/quality/owner-blackbox-exclusions.json`. El validador compara
esa declaración con una lista cerrada en código. No se admiten prefijos,
glob, selectores agregados, hashes variables, otros módulos ni excepciones
de futuros RCA.

La excepción se habilita únicamente si se cumplen **todos** los requisitos:

1. Los tests exceptuados faltan del JUnit por la exclusión explícita del
   pipeline. Si todos se ejecutaron, se usa el gate histórico sin excepción.
2. No falta **ningún** selector RCA distinto de los 11 permitidos.
3. La declaración externa coincide exactamente con la lista cerrada y
   los archivos permanecen idénticos a los recibidos del dueño:
   `synthetic.py` 2.784 bytes, SHA-256
   `52cd3996548eb318253aecd11d9ffc5bfa04c609be400fdb1ce4863dba4eeeaa`;
   `ipc_worker.py` 1.163 bytes, SHA-256
   `b1286e77b0ff2ee0bc2473b27895bbe1b0f376a4efcf921f5f1c88aabc649ebe`.
   Se calculan huellas **opacas**, sin importar, ejecutar ni analizar Python.
4. El JUnit contiene la ejecución aprobada de
   `test_inert_controller_selects_local_adapter_without_owner_modules`
   (prueba de frontera del [PR #292](https://github.com/mbalbo2023/boca-socios-assistant/pull/292)).
5. El JUnit incluye **dos casos distintos aprobados** del test parametrizado
   `test_protected_owner_file_exact_bytes` del
   [PR #289](https://github.com/mbalbo2023/boca-socios-assistant/pull/289).

Ante un hash cambiado, symlink, manifiesto ausente, evidencia faltante,
caso paramétrico omitido o cualquier otro selector RCA no ejecutado, el gate
retorna **NO_GO**. No se relaja el aislamiento, la política de credenciales,
el resto de linters, tests del controlador ni seguridad de imagen.

## Alcance operacional y calidad de evidencia

- **Declaración del titular:** existe una validación externa de los dos
  módulos; su contenido y funcionamiento no son objeto de certificación
  de agentes. No se almacena código, credenciales, cookies o tokens aquí.
- **Prueba del agente:** la exclusión está acotada; retiene regresiones
  históricas, verifica huellas opacas y exige que el controlador no importe
  los módulos con backend `off`.
- **No acreditado por esta ADR:** funcionamiento interno de caja negra,
  Playwright en host, autenticación real, cola de Boca, reserva, emisión de
  Telegram, instalación o recepción física en el droplet.
- **Operación permitida:** avanzar con CI y distribución exact-SHA por la
  ruta de Actions protegida, sin navegación del sitio por agentes y sin
  tocar otras aplicaciones. Los fallos de red rootless #275, imagen,
  firma, identidad, limpieza y puerto 8443 no se exceptúan.

El gate informa por separado cuántos selectores tuvieron ejecución real
y cuántos sólo la atestación externa acotada. La distinción es obligatoria
en PR y checkpoint Rule84; nunca comunicar “114 regresiones ejecutadas”
si 11 fueron reemplazadas por excepción externa.
