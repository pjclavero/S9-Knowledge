"""Centro de Estado operativo de S9 Knowledge (solo observación).

Este paquete NO controla nada: no reinicia servicios, no lanza jobs, no
escribe en Neo4j, no habla con Proxmox y no lee secretos. Se limita a leer
fuentes que ya existen en el repositorio y a traducirlas a cuatro estados
explícitos: OK / WARNING / CRITICAL / UNKNOWN.
"""
from app.ops.models import OpsStatus, SectionResult, OpsReport, worst  # noqa: F401
