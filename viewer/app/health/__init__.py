"""Subsistema de observabilidad y healthchecks (solo lectura).

No reinicia servicios ni escribe en Neo4j. Cada check devuelve un
``ComponentResult`` con estado sanitizado. El agregado produce un
``HealthReport`` con el estado global (peor de los componentes).
"""
from app.health.models import ComponentResult, HealthReport, HealthStatus

__all__ = ["ComponentResult", "HealthReport", "HealthStatus"]
