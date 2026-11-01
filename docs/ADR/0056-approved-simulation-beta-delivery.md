# ADR 0056: alcance aprobado de preparación de la BETA funcional

**Estado:** histórico, aceptado al integrarse #153. Su reserva de una nueva
aprobación genérica, exclusión de login y alcance sólo preparatorio fueron
sustituidos por [ADR0062](0062-operational-beta-and-recovery.md). El resto de
este documento conserva literalmente la decisión de aquella etapa, no la
autoridad vigente. Registra la dirección explícita del dueño en
issue #45 y el alcance documental #144; no acredita un despliegue.

[Autorización de esta etapa](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6551681142).

## Decisiones de esta etapa

El dueño aprobó comenzar las recomendaciones del plan de BETA y mantener su
seguimiento en GitHub. El desarrollo, revisión y pruebas de los frentes
aprobados continúan sin pedir de nuevo autorización para cada paso rutinario.
ADR0055 sigue rigiendo para decisiones nuevas fuera de este alcance; no se
restablece una autonomía general sobre infraestructura, negocio o datos reales.

- Entrega objetivo: BETA privada funcional de simulación. **El alta de socios
  es obligatoria**, mediante `Socios > Agregar socio`, además de iniciar,
  detener, consultar estado, persistir resultados locales y mostrar avisos.
- Ubicación lógica delegada y decidida para la futura BETA: SQLite en
  `/data/boca.sqlite3`, sobre volumen propio `boca-socios_boca_data`. La clave
  permanece fuera de DB/imagen/repo en el volumen separado Boca. SQLite corre
  dentro del backend; no se introduce un servidor de DB independiente.
- La existencia/ubicación global de una DB operativa actual sigue UNVERIFIED.
  La decisión de destino futuro no crea, abre, mueve ni migra datos. Si aparece
  una DB o instalación existente, preservar y verificar procedencia/clave y
  compatibilidad; no sustituirla ni ejecutar first-install por defecto.
- Preparar Docker rootless dedicado y panel servido por la propia aplicación
  Boca, usando acceso local de backend a SQLite. El Site #113 permanece como
  complemento sintético; no necesita acceso directo al archivo ni una nueva
  plataforma de API separada. Identidad/bootstrap y acceso privado concretos
  se presentan con opciones antes de activarlos; un puerto de identidad denegado
  por defecto permite desarrollar sin fingir autenticación operativa.
- Reconciliar los componentes de coordinador, panel y avisos; mantener pausa
  visible ante ambigüedad y demostrar recuperación antes de cualquier reintento
  cuyo resultado sea desconocido. Avisos locales constituyen el primer canal
  funcional; Telegram sigue como pendiente explícito, sin transporte real
  autorizado por un dispatcher sintético.
- Medir rapidez y recursos de pruebas, preparación, despliegue y recorridos;
  optimizar trabajo redundante sin omitir controles ni usar pruebas de otro SHA.

## Alta privada y aceptación

Reutilizar `MemberEnrollmentService`: alta transaccional de identidad local y
credencial AES-256-GCM, UUID opaco, clave externa y auditoría sin secretos. Su
validación local no verifica identidad, consentimiento o elegibilidad ante
Boca. Probar por la UI datos y credenciales **sintéticos**; no ingresar ni
habilitar credenciales reales, login, cola, reservas o compras reales.

La BETA no se acepta sólo porque un contenedor esté sano: debe completar acceso
privado, alta, simulación, parada/consulta, aviso local, duplicados y reinicio,
con evidencia de persistencia, denegación de terceros, una intención por
socio/evento y cantidad1. Registrar latencia y consumo del candidato, sin
presentar presupuestos no medidos como capacidad ni inventar un SLA cumplido.

## Gates que permanecen

El candidato funcional debe incluir imagen/configuración/arranque y contrato
de salud adecuados: el actual controlador dormido no satisface esta entrega.
La remediación/preparación host y su validación usan únicamente Actions Boca.
La release e instalación final requieren candidato concreto revisado, SHA y
digests, preflight apto, recibo y decisión final según el plan; esta ADR no
publica imágenes ni ejecuta instalación o migración sobre datos existentes.

Backup/restore permanece diferido hasta una versión productiva fiable. Los
requisitos de recuperación/custodia previos a credenciales reales se conservan.
No tocar Porota/PPI Watch. Las operaciones host y merges siguen serializados;
pruebas, revisiones y desarrollo independiente se paralelizan.

## Evidencia de avance, sin ampliar la decisión

La preparación150 se ejecutó en run120 sobre source6be606f83c5a6afe0ba7226abbca6a09276d1ca1:
servicio rootless listo, application_database=not_accessed y app no instalada.
Alta148/comandos149 y composición sintética152 están integrados, pero no hay
listener/identidad real/tablet ni runtime funcional desplegado. El plan conserva
los detalles y pendientes, incluida proyección durable de causa de avisos y la
matriz completa UI; esta ADR no certifica todos los recorridos operativos.

## Seguimiento

[BETA_DELIVERY_PLAN.md](../BETA_DELIVERY_PLAN.md) define entregas, dependencias,
pruebas y evidencia. Cada PR actualiza su contrato/ADR y resultados; el escritor
central reconcilia plan/estado y el responsable de #45/#113 actualiza el
checkpoint antes de cierre. Esta coordinación satisface Regla84 sin escritores
simultáneos ni exigir que todos reescriban los mismos documentos. No se promete
un robot de mantenimiento ni una actualización programada separada.

