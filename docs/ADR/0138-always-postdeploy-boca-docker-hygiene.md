# ADR 0138 — Limpieza Docker selectiva después de todo despliegue Boca

**Decisión owner:** 2026-11-04 ART. **Estado:** política aprobada; implementación
en código/pruebas DRAFT, sin operación física ni autorización nueva de deploy.

## Contexto

La limpieza selectiva existente cubre principalmente intentos fallidos.
El propietario exige que **también después de una instalación o actualización
exitosa** no persistan imágenes antiguas o artefactos de prueba del proyecto
Boca que ya no se utilicen. La regla forma parte de la aceptación de toda
futura operación mediante el **único** workflow protegido Boca.

## Contrato permanente

1. **Siempre, PASS o FAIL:** el mismo intento protegido lleva un marcador y
   lease exclusivos, registra antes/después bytes libres e inodos en el área
   Boca y el Docker rootless dedicado, e inventaría sólo identidades de
   imágenes, contenedores, redes y staging de Boca. El recibo es acotado y
   redactado, sin secretos ni identificadores de socios.
2. **Después de PASS:** preservar primero el contenedor sano, su imagen por
   digest, el puerto `127.0.0.1:8443`, el socket permitido y los volúmenes
   owner/clave/datos. Eliminar sólo contenedores de intento definitivamente
   parados, redes temporarias Boca sin endpoints, archivos temporales exactos
   e imágenes Boca obsoletas sin referencia desde **ningún** contenedor, tras
   verificar ownership por labels/digest/proveniencia. Probar ausencia de cada
   ID eliminado y estabilidad de la topología activa.
3. **Después de FAIL:** ejecutar primero el procedimiento de compensación
   positivo y acotado vigente, conservar el estado original FAIL, luego la
   misma higiene de residuos exclusivamente disponibles y sin uso. No borrar
   un candidato/legado ante identidad o restauración incierta.
4. **Fail-closed:** si Docker/SSH/runner/lease se pierde, la proveniencia es
   dudosa, el contenedor todavía referencia una imagen, no se puede completar
   el inventario o el recurso no coincide exactamente, no borrarlo. Informar
   `NO_GO` / `INDETERMINATE`, el motivo y qué quedó retenido; requerir un nuevo
   inventario Boca-only antes de reintentar. Una aplicación arrancada pero sin
   comprobante de limpieza no tiene aceptación integral GREEN.
5. **Prohibiciones:** ningún `docker system prune`, `docker image prune -a`,
   `docker volume prune`, fuerza de eliminación, glob de IDs, eliminación de
   volúmenes persistentes, `compose down` global, acceso a otros servicios,
   redes/puertos ajenos o tareas manuales del propietario para limpiar.

## Implementación y aceptación

- Un único enganche de finalización del workflow manual Boca, incluso en
  error/cancelación recuperable, invoca inventario y limpieza exact-ID. Nunca
  otro deploy workflow ni un cron periódico.
- Probar runner descartable con (a) instalación exitosa + imagen anterior no
  referenciada que desaparece, (b) instalación fallida + compensación +
  basura identificada que desaparece, (c) imagen activa o compartida que se
  retiene, (d) intento/lease ajeno o estado desconocido que se retiene con
  NO_GO, (e) volúmenes owner/clave/DB inmutables, (f) verificación pre/post
  y fallo de limpieza que no se marca verde.
- Publicar SHA exacto, PR, workflows de validación y resultados en #45.
  **No** certificar un deploy físico ni espacio recuperado usando únicamente
  pruebas Docker desechables. Todo intento futuro requiere evidencia del host.

## Impacto

La limpieza agrega tiempo acotado al final del deploy, pero reduce acumulación
de imágenes Boca no usadas y mejora los recibos operativos. Su alcance está
deliberadamente limitado para proteger Porota Trading y todos los servicios
ajenos en el mismo droplet. No incluye backups ni borrado de datos del dueño.
