# Cómo recuperar este checkpoint

Este respaldo es documentación y trabajo candidato: no es una aprobación de despliegue.

1. Leer el registro vivo de issue417, comentario6899119716, y el documento 2026-11-16-network-checkpoint.md.
2. Reconciliar main y operaciones posteriores. El corte conocido es main b3200f7bc4391156205dab992989a609253ec6ee; CI1283 y Security1094 SUCCESS. El diagnóstico telegram-prepare-diagnose no fue enviado.
3. El código R310 está en feature/531-capacity50, commit remoto9b1adb1c4862bd1b34fcac364c84e85dc155ffef, árbol005277a347390f637df9a3ed362d2eae0343b2f4. Coincide byte por byte con el local9c08e90d7c16fe12261f7fac35905ced9ebc8541. No existe PR531 ni revisión final R310.
4. El paquete de evidencia conserva informes originales, logs, ZIP revisados, notas de QA/Operaciones, snapshots del registro anterior y bundle del historial local. El manifest enumera cada archivo, tamaño y SHA256.
5. El bundle Git requiere que el checkout conozca la base canónica1ab24a696bf473f57cdae1ee1f01af024ce1b8e8; contiene HEAD9c08e90. Ya fue verificado. El asistente puede importar ese historial a una rama aislada si necesita los SHAs originales. No sobrescribir main ni eliminar worktrees existentes.
6. Si el workspace original sigue disponible, los worktrees boca-r307 y boca-capacity50 están en /workspace/scratch/6fbf8bcd39e6; el primero conserva la .venv usada por el segundo. El estado tracked está limpio. Los logs originales siguen en .superpowers/sdd/r308, r309 y r310.
7. Root opera GitHub/Actions; los autores sólo sus rutas. Reconstituir Arquitectura, QA y Operaciones como revisores separados. No sumar al autor como voto ni inventar aprobaciones.
8. Prioridad siguiente: un único diagnóstico R309 con los inputs registrados, lectura D8 y decisión mínima de custodia/adopción; después revisión final R310 y su secuencia de CI/ensayo runner. Nada autoriza reserva, envío, navegación a proveedor o medición de droplet.

No se requiere que Tincho ejecute comandos. La instrucción de continuidad para el nuevo chat apunta al registro vivo y éste enlaza todos los respaldos.

