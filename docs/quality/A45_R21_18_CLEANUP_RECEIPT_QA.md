# Boca A45-R21.18 — recibo posdespliegue y certificación pendiente

Fecha: 2026-11-05 (ART). Estado: CODE_ONLY. Ningún GO físico, merge, publicación de imagen ni deploy ejecutado.

## Identidad del corte

- Candidato único DRAFT: PR #319, rama feature/45-beta-integral-candidate.
- Padre anterior R21.17: 82c7c3edf75911805218149d4907ecb37b374a66 (TREE d6ca906f517571c0025cce7780b674cdc3956fc3; siete de siete Actions SUCCESS; 3645 PASS +34).
- Overlay de diez archivos de DRAFT #372: source HEAD 1eb69c0e3558b994f85802c38057e72f736ef8f6, TREE 6519e122ac37da04648b52cbca0eaedfde46e204, 4/4 Actions SUCCESS, 3652 PASS +34; ownership liberado.
- Primer commit CAS R21.18 del candidato: 17fac7992b5c9a8118c277cfc12574f1dd17e353, TREE 6519e122ac37da04648b52cbca0eaedfde46e204. Este archivo de checkpoint se agrega mediante Contents API para sincronizar la rama PR y disparar QA del nuevo HEAD. El SHA definitivo será el commit que lo contiene, no el SHA CAS inicial.
- main físico preexistente: cabce9f1e452e63ded115f447559a358dc0f4d1b; sin cambios.

## Cambio comprobado

- Limpieza selectiva BocA únicamente dentro del Cutover A, tanto COMMITTED como recovery verificada, bajo la lease propia.
- Nuevo recibo posoperación legible: bytes e inodos antes/después, recursos Boca retirados por IDs exactos y residuos pendientes/inciertos.
- GO_B: ACK histórico compatible y segunda línea validada estrictamente contra el recibo, sin conservar datos confidenciales ni inventar recuperaciones.
- Las seis operaciones de instalación históricas continúan NO_GO antes de SSH; esta mejora NO certifica limpieza universal ni autoriza borrados globales.

## Pendientes P0 y próximos criterios

1. Confirmar PR #319 HEAD sincronizado y ejecutar las siete Actions del SHA final de este checkpoint, registrando los IDs y resultados. No trasladar como GREEN los checks del padre o del source #372.
2. Integrar observador host Cutover A y Official en DRAFT #375 una vez verificado su QA.
3. Integrar wiring GO_B PREPARE/APPLY #371 cuando tenga pruebas y correlación de GH artifacts/IDs reales.
4. Integrar sólo cambios Telegram con autenticación fresh WebAuthn que estén validados y mantengan sender NO_GO hasta atestación real.
5. Actualizar docs DRAFT #363 al HEAD definitivo antes de consolidar; probar predeploy real, GO independiente y post-deploy Samsung Chrome + Termius localhost:8443.

Sin compras/reservas reales, backups, otros puertos, HTTPS, cambios BLACKBOX, Porota ni otros contenedores. La limpieza real del droplet sólo se evalúa tras despliegue autorizado y con su recibo exacto. Registro canónico continuo: issue #45; RCA #323.
