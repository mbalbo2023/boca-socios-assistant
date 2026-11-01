# ADR 0070: paquete servido BETA aislado y puerta de instalación separada

**Estado:** aceptada al integrar el PR #171 de issue #167. El candidato y sus
checks se registran en ese PR; la presencia de Compose y pruebas no instala ni
habilita una BETA en el droplet.

## Decisión de empaquetado

El Compose histórico `compose.yaml` y su `first-install` siguen siendo el
controlador dormido sin puertos. `compose.beta.yaml` define un candidato
separado del **mismo** proyecto `boca-socios`, con un solo servicio `controller`
y la imagen de digest inmutable. Ejecuta explícitamente `serve-beta` del
entrypoint #169; no activa motor ni Boca real. Conserva UID10001, raíz de sólo
lectura, capacidades eliminadas, no-new-privileges, volúmenes de datos/clave
separados y límites 0.5 CPU/256 MiB/64 PID. La única publicación posible es
`127.0.0.1:8443` del host al puerto TLS 8443 del contenedor. El bind
`0.0.0.0` interno se limita a la red bridge Boca y no constituye una interfaz
pública. El runtime termina TLS y valida su propio origen; no confía en
cabeceras de proxy inyectadas.

`boca_owner` es un volumen externo, propio y de sólo lectura que contiene
identificador/clave pública passkey, certificado/clave TLS y CA de health. Su
provisión y la ceremonia del dueño son prerequisitos separados, aún sin
evidencia. El Compose falla si no se suministran origen HTTPS y sujeto del
dueño; el validador rechaza servicios, redes, montajes, permisos, puertos o
entorno fuera del modelo exacto. Las pruebas usan sólo material sintético.

## Operación y límites

El workflow de host vigente no selecciona este Compose. La siguiente etapa
exige una operación `beta-install` **separada dentro del mismo workflow manual**,
con SHA/digest/manifiesto, preflight del presupuesto final, custodia segura y
postflight de puerto/mount/cgroup/health sobre el contenedor real. No usar
`first-install` dormido como sustituto. En ausencia de origen y credencial
privados, capacidad suficiente y configuración completa, el estado de
instalación funcional permanece NO_GO. La prueba local de TLS en loopback no
acredita acceso desde tablet ni Site conectado; Telegram conserva un gate
operativo propio. No hay reserva, compra ni navegación Boca real en esta ADR.

Autorización y continuidad: [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326),
plan B7–B10. El recibo exacto de PR/Actions se agrega tras la validación del
candidato; este documento no presupone su éxito.
