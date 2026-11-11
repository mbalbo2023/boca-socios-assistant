# Plan de implementación: actividad worker/Chromium

**Objetivo:** visor privado de eventos seguros, sin ampliar permisos del host.

1. Crear pruebas fallidas de la proyección SQLite/IPC y de la protección de
   rutas; incluir credenciales y datos arbitrarios como entradas maliciosas.
2. Añadir lector de telemetría de archivo limitado y eventos del SQLite
   existente; etiquetar fuente, nivel y hora sin datos privados.
3. Añadir emisor opcional de categorías fijas a los límites de
   `playwright_factory.py`, conservando intacto el flujo de navegación.
4. Añadir página y JSON de lectura con `fetch` a cinco segundos, pausa y
   accesibilidad; ajustar el hash CSP para el script literal.
5. Ejecutar pruebas de regresión específicas, tipos, lint, política y pruebas
   de aislamiento del IPC; revisar contra contrato protegido del desplegador.
6. Documentar evidencia en #417, abrir PR único, integrar después de QA y
   desplegar exclusivamente mediante Actions Boca, con validación física.

No afirmar que el worker está sano ni que la UI está instalada sin pruebas
reales del droplet y sin recibos de host firmes.
