# R88 worker preflight: diseño de RCA/observabilidad

**Objetivo:** diagnosticar STOP sin nuevos efectos y cerrar dos defectos de test/captura descubiertos durante la investigación de #819.

**Estado autorizado:** continuidad del Cutover aprobado, únicamente CODE_ONLY y sus pruebas hasta QA/merge; ningún permiso implícito para repetir #819 o lanzar host. Fuente principal [ADR0197](../../ADR/0197-r88-worker-preflight-evidence-and-runner-hardening.md) y #417.

**Opciones evaluadas:** (1) timeout/retry especulativo: rechazado porque un STOP puede haber ocurrido; (2) omitir preflight: rechazado porque retira garantías; (3) diagnóstico por tipos + boundary explícito + runner privado acotado: elegido por evidencia de pérdida de información y fallos reproducibles, preservando el flujo físico existente.

**Contrato:** Los únicos subtipos adicionales al NO_GO son `NONE`, `TIMEOUT`, `NONZERO`, `OSERROR`, `ACK_MISMATCH` y `UNVERIFIED`; nunca raw Docker. PASS actual no cambia. Ningún segundo STOP/`rm`, ruta de host nueva, privilegio o acceso a software de navegación. El runner usa el patrón seguro ya empleado en observer/recovery. QA modela `python -O` y transporte host falso con stdout hostil. Un único PR integrado actualiza código, pruebas y documentación; la siguiente Action física sigue pendiente de nuevo GO técnico tras release exacto.
