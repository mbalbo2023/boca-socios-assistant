# ADR 0070: paquete servido BETA aislado y puerta de instalación separada

**Estado:** aceptada; PR #171 integrado en
`472574ca380e9c14d665b8aab97790b9a05e1f71`.
El candidato `e498c8d1f4d09202b09fcda19d6accd09850d8f2` pasó
CI 41271723362, scan 41271723366 y validaciones release/deploy
41271723342/41271723422; revisión 5726348620. Compose y pruebas no instalan ni
habilitan una BETA en el droplet.

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
plan B7–B10. Esos checks probaron paquete desechable; no prueban la
operación del droplet.
