#!/usr/bin/env python3
"""Calibración del comprobador de configuración: ¿enrojece de verdad?

Un comprobador que siempre sale OK no comprueba nada, y no hay forma de
distinguirlo de uno que funciona salvo rompiéndolo a propósito. Esto construye
un entorno COMPLETO y válido, verifica que sale en verde, y después retira de
una en una **cada** variable crítica comprobando que el veredicto pasa a ERROR.
Al terminar, el entorno se restaura (vive en memoria: nada que restaurar en
disco).

También comprueba las dos reglas que no pueden negociarse:

  - una ausencia crítica NUNCA puede producir OK;
  - un fallo interno del comprobador NUNCA puede producir código 0.

Uso:
    python3 deploy/release/calibrate_config_check.py
    python3 deploy/release/calibrate_config_check.py --verbose

Salida: 0 si el comprobador está bien calibrado; 1 si alguna variable crítica
puede desaparecer sin que el veredicto se ponga en ERROR.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_check  # noqa: E402
import spec  # noqa: E402
from spec import Level, Status  # noqa: E402


def build_valid_env() -> dict[str, str]:
    """Un entorno completo y plausible, equivalente a un viewer.env correcto.

    El secreto CSRF se genera al vuelo: este fichero no contiene, ni debe
    contener, ningún valor secreto real.
    """
    env = {
        "S9K_VIEWER_HOST": "127.0.0.1",
        "S9K_VIEWER_PORT": "8088",
        "S9K_GRAPH_PROVIDER": "neo4j",
        "S9K_DEFAULT_WORKSPACE": "leyenda",
        "S9K_GRAPH_LIMIT": "300",
        "S9K_NEO4J_URI": "bolt://127.0.0.1:7687",
        "S9K_NEO4J_USER": "neo4j",
        "S9K_NEO4J_PASSWORD_FILE": "/etc/s9-knowledge/secrets/neo4j_password",
        "S9K_AUTH_DB_PATH": "/var/lib/s9-knowledge/auth/auth.db",
        "S9K_JOBS_DB": "/var/lib/s9-knowledge/jobs/jobs.db",
        "S9K_BACKUP_DIR": "/var/lib/s9-knowledge/backups",
        "S9K_AUTH_ENABLED": "true",
        "S9K_CSRF_SECRET": secrets.token_urlsafe(48),
        "S9K_AUTH_MAX_FAILED_ATTEMPTS": "5",
        "S9K_AUTH_LOCK_MINUTES": "15",
        "S9K_AUTH_EXPOSE_DOCS": "false",
        "S9K_AUTH_TRUST_PROXY_HEADERS": "false",
        "S9K_SESSION_COOKIE_NAME": "s9k_session",
        "S9K_SESSION_TTL_HOURS": "12",
        "S9K_SESSION_IDLE_MINUTES": "60",
        "S9K_SESSION_SECURE": "true",
        "S9K_SESSION_SAMESITE": "lax",
        "S9K_SESSION_HTTPONLY": "true",
        "S9K_HEALTH_VIEWER_URL": "http://127.0.0.1:8088",
        "S9K_HEALTH_REPORT_PATH": "/var/lib/s9-knowledge/health/health.json",
        "S9K_HEALTH_UNITS": "s9-knowledge-viewer.service",
        "S9K_HEALTH_DISK_PATH": "/var/lib/s9-knowledge",
        "S9K_VIEWER_DEFAULT_PAGE_SIZE": "50",
        "S9K_VIEWER_MAX_PAGE_SIZE": "200",
        "S9K_VIEWER_QUERY_TIMEOUT_SECONDS": "10",
        "S9K_VIEWER_MAX_SEARCH_LENGTH": "200",
    }
    return env


def env_verdict(env: dict[str, str]) -> tuple[Status, list[config_check.Finding]]:
    """Veredicto restringido a las comprobaciones de variables de entorno.

    Se aísla a propósito de dependencias, versiones y sistema de ficheros: la
    calibración mide si el comprobador reacciona a la CONFIGURACIÓN, y no debe
    darse por buena porque otro eje esté en rojo por su cuenta.
    """
    findings = config_check.check_env_vars(env, production=True)
    return config_check.verdict(findings), findings


def critical_var_names() -> list[str]:
    """Variables críticas cuya ausencia debe enrojecer.

    Se excluyen las que tienen alternativa por fichero de secreto: retirar
    ``S9K_NEO4J_PASSWORD`` con ``S9K_NEO4J_PASSWORD_FILE`` presente es una
    configuración VÁLIDA, no una ausencia.
    """
    return [v.name for v in spec.ENV_VARS
            if v.level is Level.CRITICAL and not v.file_alternative]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    base = build_valid_env()

    print("== Línea base: entorno completo y válido ==")
    status, findings = env_verdict(base)
    print(f"veredicto: {status.value}")
    if status is not Status.OK:
        print("La línea base NO está en verde; la calibración no es concluyente.")
        for finding in findings:
            if finding.status != Status.OK.value:
                print("  " + finding.line())
        return 1

    print("")
    print("== Retirando cada variable crítica, de una en una ==")
    failures: list[str] = []
    for name in critical_var_names():
        broken = dict(base)
        del broken[name]
        status, findings = env_verdict(broken)
        culprit = next((f for f in findings if f.target == name), None)
        marker = "ROJO OK" if status is Status.ERROR else "NO ENROJECE"
        if status is not Status.ERROR:
            failures.append(name)
        print(f"  sin {name:<34} -> {status.value:<7} [{marker}]")
        if args.verbose and culprit:
            print(f"      {culprit.line()}")

    print("")
    print("== Reglas duras ==")

    # Regla: ningún hallazgo crítico en no-OK puede convivir con veredicto OK.
    mixed = [config_check.Finding("env", "X", Status.OK.value, Level.CRITICAL.value, "ok"),
             config_check.Finding("env", "Y", Status.ERROR.value, Level.CRITICAL.value, "falta")]
    if config_check.verdict(mixed) is not Status.ERROR:
        print("  FALLO: un hallazgo crítico en ERROR no produce veredicto ERROR")
        failures.append("regla:critico->ERROR")
    else:
        print("  OK: un solo hallazgo crítico en rojo basta para veredicto ERROR")

    # Regla: un fallo interno sale con código 3, nunca 0.
    code = config_check.main(["--env-file", "/no/existe/viewer.env"])
    if code == 0:
        print(f"  FALLO: un fichero de entorno ilegible salió con código {code}")
        failures.append("regla:interno!=0")
    else:
        print(f"  OK: un fichero de entorno ilegible sale con código {code} (no 0)")

    # Regla: los secretos no aparecen en la salida.
    _, findings = env_verdict(base)
    secret_value = base["S9K_CSRF_SECRET"]
    if any(secret_value in f.message for f in findings):
        print("  FALLO: el valor del secreto CSRF aparece en la salida")
        failures.append("regla:secreto-filtrado")
    else:
        print("  OK: ningún valor secreto aparece en los mensajes del informe")

    print("")
    if failures:
        print(f"CALIBRACIÓN FALLIDA: {failures}")
        return 1
    print(f"CALIBRACIÓN CORRECTA: {len(critical_var_names())} variables críticas "
          "enrojecen al retirarlas; el entorno base queda restaurado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
