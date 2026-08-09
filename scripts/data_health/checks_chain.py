"""Comprobaciones de CADENA de contrato (estáticas, READ-ONLY sobre el código).

De M5b salió la lección que aquí se aplica a los datos:

    productor → persistencia → serializador → consumidor → semántica de ausencia

Un solo eslabón roto convierte la garantía en decoración, y ninguna prueba de
componente lo detecta porque cada componente por separado está bien. Estas
comprobaciones miran la cadena entera, en las dos direcciones:

  C01  todo campo declarado tiene un PRODUCTOR real que lo escribe
  C02  y un SERIALIZADOR que lo transporta
  C03  y un CONSUMIDOR que lo lee
  C04  todo campo que un consumidor lee está declarado (y por tanto producido)
  C05  todo campo declarado sin consumidor se señala como campo muerto

Limitación asumida y declarada: es análisis textual, no de flujo de datos. Por
eso se exige un patrón de ESCRITURA (no una simple mención) y se ignoran los
comentarios: contar un comentario o un fichero de test como "productor" fue el
defecto que la red anterior de M5b tuvo dentro de sí misma.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .registry import CAMPOS, CAMPOS_POR_NOMBRE
from .report import CRITICAL, INFO, UNKNOWN, WARNING, Finding

CHECKS_CADENA = ["C01", "C02", "C03", "C04", "C05", "C06"]

#: Ficheros que se consideran consumidores a efectos de C04.
CONSUMIDORES_ESCANEADOS = (
    "viewer/app/policies/engine.py",
)

#: Campos que un consumidor puede leer legítimamente sin ser campos de dato
#: persistidos (forma de la proyección o contexto de la petición).
NO_SON_CAMPOS_DE_DATO = frozenset({
    "from", "to", "id", "type", "label", "description", "aliases",
})


def _sin_comentarios(texto: str) -> str:
    fuera = []
    for linea in texto.splitlines():
        sin = re.sub(r"(?<!['\"])#.*$", "", linea)
        if sin.strip().startswith(("#", '"""', "'''")):
            continue
        fuera.append(sin)
    return "\n".join(fuera)


def _leer(repo: Path, rel: str) -> tuple[str | None, str | None]:
    """Devuelve (contenido_sin_comentarios, error). Nunca inventa un vacío."""
    ruta = repo / rel.split("::", 1)[0]
    if not ruta.exists():
        return None, f"fichero declarado inexistente: {rel}"
    if "test" in ruta.name:
        return None, f"un test no puede ser productor ni consumidor: {rel}"
    try:
        return _sin_comentarios(ruta.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, f"no legible ({exc}): {rel}"


def _escribe(texto: str, campo: str) -> bool:
    patrones = (
        rf'["\']{campo}["\']\s*:',          # clave de dict / props de Cypher
        rf'\b{campo}\s*=',                  # asignación o kwarg
        rf'\.{campo}\s*=',                  # SET n.campo =
        rf'\${campo}\b',                    # parámetro Cypher $campo
        rf'\bSET\b[^\n]*\b{campo}\b',
    )
    return any(re.search(p, texto) for p in patrones)


def _lee(texto: str, campo: str) -> bool:
    patrones = (
        rf'\.get\(\s*["\']{campo}["\']',
        rf'\[\s*["\']{campo}["\']\s*\]',
        rf'["\']{campo}["\']',
        rf'\bn\.{campo}\b',
    )
    return any(re.search(p, texto) for p in patrones)


def _campos_leidos_por(texto: str) -> set[str]:
    return set(re.findall(r'\.get\(\s*["\']([a-z_][a-z0-9_]*)["\']', texto))


def c01_productor(repo: Path, campos: Iterable = CAMPOS) -> list[Finding]:
    out: list[Finding] = []
    for c in campos:
        texto, err = _leer(repo, c.producer)
        if texto is None:
            out.append(Finding("C01", UNKNOWN,
                               f"no se pudo verificar el productor de '{c.name}': {err}",
                               c.name))
            continue
        if not _escribe(texto, c.nombre_en_productor):
            out.append(Finding("C01", CRITICAL,
                               f"'{c.name}' se declara producido por {c.producer} pero ahí "
                               "no hay ninguna escritura del campo: la garantía es decorativa",
                               c.name, {"productor": c.producer}))
    return out


def c02_serializador(repo: Path, campos: Iterable = CAMPOS) -> list[Finding]:
    out: list[Finding] = []
    for c in campos:
        if c.serializer is None:
            continue
        texto, err = _leer(repo, c.serializer)
        if texto is None:
            out.append(Finding("C02", UNKNOWN,
                               f"no se pudo verificar el serializador de '{c.name}': {err}",
                               c.name))
            continue
        if not _lee(texto, c.name):
            out.append(Finding("C02", CRITICAL,
                               f"'{c.name}' no viaja en {c.serializer}: se persiste y se "
                               "pierde antes de llegar al consumidor",
                               c.name, {"serializador": c.serializer}))
    return out


def c03_consumidor(repo: Path, campos: Iterable = CAMPOS) -> list[Finding]:
    out: list[Finding] = []
    for c in campos:
        if c.consumer is None:
            continue
        texto, err = _leer(repo, c.consumer)
        if texto is None:
            out.append(Finding("C03", UNKNOWN,
                               f"no se pudo verificar el consumidor de '{c.name}': {err}",
                               c.name))
            continue
        if not _lee(texto, c.name):
            out.append(Finding("C03", CRITICAL,
                               f"'{c.name}' declara consumidor {c.consumer} y ahí no se lee",
                               c.name, {"consumidor": c.consumer}))
    return out


def c04_consumido_sin_productor(repo: Path) -> list[Finding]:
    """Campos que un consumidor espera y que ningún productor declarado genera."""
    out: list[Finding] = []
    for rel in CONSUMIDORES_ESCANEADOS:
        texto, err = _leer(repo, rel)
        if texto is None:
            out.append(Finding("C04", UNKNOWN,
                               f"no se pudo escanear el consumidor {rel}: {err}", rel))
            continue
        for campo in sorted(_campos_leidos_por(texto)):
            if campo in NO_SON_CAMPOS_DE_DATO:
                continue
            c = CAMPOS_POR_NOMBRE.get(campo)
            if c is None:
                out.append(Finding("C04", WARNING,
                                   f"{rel} lee '{campo}', que no está declarado como campo de "
                                   "dato: nadie garantiza que exista en el grafo",
                                   campo, {"consumidor": rel}))
                continue
            prod, perr = _leer(repo, c.producer)
            if prod is None:
                out.append(Finding("C04", UNKNOWN,
                                   f"'{campo}' se consume en {rel} y su productor no es "
                                   f"verificable: {perr}", campo))
            elif not _escribe(prod, c.nombre_en_productor):
                out.append(Finding("C04", CRITICAL,
                                   f"'{campo}' se consume en {rel} y NINGÚN productor lo "
                                   "escribe: la regla se evalúa sobre un campo inexistente",
                                   campo, {"consumidor": rel, "productor": c.producer}))
    return out


def c05_producido_sin_consumidor(repo: Path, campos: Iterable = CAMPOS) -> list[Finding]:
    return [
        Finding("C05", INFO,
                f"'{c.name}' se genera y persiste, y no tiene consumidor declarado: "
                "o alguien lo usa sin declararlo, o es coste de escritura sin lector",
                c.name, {"productor": c.producer})
        for c in campos if c.consumer is None
    ]


def c06_literales_fuera_de_vocabulario(repo: Path, campos: Iterable = CAMPOS) -> list[Finding]:
    """Valores que el PRODUCTOR escribe literalmente y el consumidor no admite.

    Es el eslabón de la semántica: productor y consumidor pueden estar los dos
    verdes por separado y hablar vocabularios distintos.
    """
    from .registry import VOCABULARIO_POR_CAMPO, VOCABULARIOS_DISPONIBLES

    out: list[Finding] = []
    if not VOCABULARIOS_DISPONIBLES:
        return [Finding("C06", UNKNOWN,
                        "vocabularios no importables: no se ha comprobado qué literales "
                        "escriben los productores")]
    for c in campos:
        vocab = VOCABULARIO_POR_CAMPO.get(c.name)
        if not vocab:
            continue
        texto, err = _leer(repo, c.producer)
        if texto is None:
            out.append(Finding("C06", UNKNOWN,
                               f"productor de '{c.name}' no verificable: {err}", c.name))
            continue
        literales = set(re.findall(
            rf'["\']{c.nombre_en_productor}["\']\s*:\s*["\']([^"\']+)["\']', texto
        )) | set(re.findall(rf'\b{c.nombre_en_productor}\s*=\s*["\']([^"\']+)["\']', texto))
        # `%s`, `{x}` y similares son plantillas de log/format, no valores escritos.
        literales = {v for v in literales
                     if "%" not in v and "{" not in v and " " not in v}
        for v in sorted(literales - set(vocab)):
            out.append(
                Finding("C06", CRITICAL,
                        f"{c.producer} escribe {c.name}={v!r}, que NO está en el "
                        "vocabulario declarado del contrato para ese campo",
                        c.name, {"valor": v, "productor": c.producer})
            )
    return out


TODAS = (
    ("C01", c01_productor),
    ("C02", c02_serializador),
    ("C03", c03_consumidor),
    ("C04", c04_consumido_sin_productor),
    ("C05", c05_producido_sin_consumidor),
    ("C06", c06_literales_fuera_de_vocabulario),
)


def ejecutar(repo: Path, solo: Iterable[str] | None = None) -> tuple[list[Finding], list[str]]:
    seleccion = set(solo) if solo else None
    findings: list[Finding] = []
    ejecutadas: list[str] = []
    for nombre, fn in TODAS:
        if seleccion is not None and nombre not in seleccion:
            continue
        ejecutadas.append(nombre)
        try:
            findings.extend(fn(repo))
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding(nombre, UNKNOWN,
                                    f"la comprobación falló internamente: "
                                    f"{type(exc).__name__}: {exc}"))
    return findings, ejecutadas
