"""CLI de healthchecks: s9k-health.

Uso:
  python -m app.cli.health check [--component NAME]
  python -m app.cli.health report
  python -m app.cli.health json

Códigos de salida: 0 healthy · 1 degraded/unknown · 2 unhealthy · 3 configuration error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_VIEWER_ROOT = _HERE.parents[2]  # viewer/
if str(_VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(_VIEWER_ROOT))

from app.health import runner, storage
from app.health.models import EXIT_CONFIG_ERROR, HealthReport, HealthStatus

_ICON = {HealthStatus.HEALTHY: "OK ", HealthStatus.DEGRADED: "DEG",
         HealthStatus.UNHEALTHY: "ERR", HealthStatus.UNKNOWN: "?? "}


def _print_report(report: HealthReport) -> None:
    print("S9 Knowledge — estado operacional: %s (%s)" % (report.overall.value, report.generated_at))
    for c in report.components:
        lat = "" if c.latency_ms is None else " %.0fms" % c.latency_ms
        print("  [%s] %-18s %s%s" % (_ICON[c.status], c.component, c.message, lat))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="s9k-health")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="Ejecuta checks y muestra resumen")
    c.add_argument("--component", help="Comprobar solo este componente")
    sub.add_parser("report", help="Informe legible del último estado")
    sub.add_parser("json", help="Salida JSON del estado")
    args = p.parse_args(argv)

    cmd = args.cmd or "check"

    try:
        if cmd == "check":
            only = [args.component] if getattr(args, "component", None) else None
            if only and only[0] not in runner.COMPONENT_NAMES:
                print("Componente desconocido: %s" % only[0], file=sys.stderr)
                print("Disponibles: %s" % ", ".join(runner.COMPONENT_NAMES), file=sys.stderr)
                return EXIT_CONFIG_ERROR
            report = runner.run_report(only=only)
            _print_report(report)
            storage.save_report(report)
            return report.exit_code()
        if cmd == "json":
            report = runner.run_report()
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            storage.save_report(report)
            return report.exit_code()
        if cmd == "report":
            last = storage.load_last()
            if last is None:
                print("Sin informe previo; ejecute 's9k-health check'.", file=sys.stderr)
                return EXIT_CONFIG_ERROR
            print(json.dumps(last, ensure_ascii=False, indent=2))
            overall = last.get("overall", "UNKNOWN")
            from app.health.models import EXIT_CODES
            return EXIT_CODES.get(HealthStatus(overall), 1)
    except Exception as exc:
        print("Error de configuración: %s" % type(exc).__name__, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
