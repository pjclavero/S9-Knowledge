"""Comprobaciones sobre los DATOS de un grafo (READ-ONLY, sin corrección).

Cada comprobación tiene identificador estable D0x y explica por qué existe.
Ninguna función de este módulo modifica el dataset que recibe.
"""
from __future__ import annotations

from typing import Any, Iterable

from .dataset import Dataset
from .registry import (
    ALLOWED_RELATION_TYPES,
    AMBITOS_CONOCIDOS,
    CAMPOS_POR_NOMBRE,
    VOCABULARIOS_DISPONIBLES,
    campos_de,
)
from .report import CRITICAL, INFO, UNKNOWN, WARNING, Finding

CHECKS_DATASET = ["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10"]

#: Tipos de entidad que hacen de "fuente" y a los que puede apuntar
#: `source_document` si se ha modelado como nodo.
TIPOS_FUENTE = frozenset({"Document", "Session", "Transcript", "Chapter", "Image"})


def _rel_id(i: int, e: dict[str, Any]) -> str:
    return f"rel#{i}:{e.get('from')}-[{e.get('type')}]->{e.get('to')}"


# --- D01: propiedades obligatorias ausentes ---------------------------------
def d01_campos_obligatorios(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    for n in ds.nodes:
        for campo in campos_de("node"):
            valor = ds.node_field(n, campo.name)
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                if campo.ausencia == "TOLERADA":
                    continue
                out.append(
                    Finding(
                        "D01",
                        campo.nivel_si_falta,
                        f"nodo sin campo obligatorio '{campo.name}' (ausencia={campo.ausencia})",
                        ds.node_id(n) or "(nodo sin id)",
                        {"campo": campo.name, "productor_declarado": campo.producer},
                    )
                )
    for i, e in enumerate(ds.edges):
        for campo in campos_de("relationship"):
            if campo.ausencia == "TOLERADA":
                continue
            valor = e.get(campo.name)
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                out.append(
                    Finding(
                        "D01",
                        campo.nivel_si_falta,
                        f"relación sin campo obligatorio '{campo.name}'",
                        _rel_id(i, e),
                        {"campo": campo.name},
                    )
                )
    return out


# --- D02: valores inválidos --------------------------------------------------
def d02_valores_invalidos(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    if not VOCABULARIOS_DISPONIBLES:
        out.append(
            Finding(
                "D02",
                UNKNOWN,
                "no se pudo importar schemas.rpg_schema: los vocabularios controlados "
                "NO se han comprobado. No poder comprobarlo no es que esté bien.",
            )
        )
    for n in ds.nodes:
        for campo in campos_de("node"):
            if campo.validador is None:
                continue
            valor = ds.node_field(n, campo.name)
            if valor is None:
                continue
            motivo = campo.validador(valor)
            if motivo:
                out.append(
                    Finding("D02", CRITICAL, f"valor inválido en '{campo.name}': {motivo}",
                            ds.node_id(n), {"campo": campo.name})
                )
    for i, e in enumerate(ds.edges):
        for campo in campos_de("relationship"):
            if campo.validador is None or campo.name not in e:
                continue
            motivo = campo.validador(e[campo.name])
            if motivo:
                out.append(
                    Finding("D02", CRITICAL, f"valor inválido en '{campo.name}': {motivo}",
                            _rel_id(i, e), {"campo": campo.name})
                )
    return out


# --- D03: entity_id duplicado ------------------------------------------------
def d03_ids_duplicados(ds: Dataset) -> list[Finding]:
    vistos: dict[str, int] = {}
    for n in ds.nodes:
        eid = ds.node_id(n)
        if not eid:
            continue
        vistos[eid] = vistos.get(eid, 0) + 1
    return [
        Finding("D03", CRITICAL, f"entity_id duplicado ({c} apariciones): la identidad "
                                 "del grafo deja de ser una función", eid, {"apariciones": c})
        for eid, c in sorted(vistos.items()) if c > 1
    ]


# --- D04: relaciones con extremos inexistentes -------------------------------
def d04_extremos_inexistentes(ds: Dataset) -> list[Finding]:
    ids = {ds.node_id(n) for n in ds.nodes if ds.node_id(n)}
    out: list[Finding] = []
    for i, e in enumerate(ds.edges):
        for extremo in ("from", "to"):
            destino = e.get(extremo)
            if destino is None:
                out.append(Finding("D04", CRITICAL, f"relación sin extremo '{extremo}'",
                                   _rel_id(i, e)))
            elif str(destino) not in ids:
                out.append(
                    Finding("D04", CRITICAL,
                            f"relación con extremo '{extremo}' inexistente: {destino!r}",
                            _rel_id(i, e), {"extremo": extremo, "id": destino})
                )
    return out


# --- D05: tipos desconocidos -------------------------------------------------
def d05_tipos_desconocidos(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    if not VOCABULARIOS_DISPONIBLES:
        return [Finding("D05", UNKNOWN,
                        "sin ontología importable no se pueden validar los tipos")]
    for i, e in enumerate(ds.edges):
        ty = e.get("type")
        if ty is None:
            out.append(Finding("D05", CRITICAL, "relación sin 'type'", _rel_id(i, e)))
        elif ty not in ALLOWED_RELATION_TYPES:
            out.append(Finding("D05", CRITICAL,
                               f"tipo de relación fuera de la ontología: {ty!r}",
                               _rel_id(i, e)))
    # los tipos de nodo los valida D02 con el validador del campo entity_type
    return out


# --- D06: contradicciones de ámbito -----------------------------------------
def d06_contradicciones_de_ambito(ds: Dataset) -> list[Finding]:
    """Ámbito = (workspace, scope, partida_id). Mezclar ámbitos en una arista
    es exactamente la fuga que los invariantes anti-mezcla deben impedir."""
    out: list[Finding] = []
    por_id = {ds.node_id(n): n for n in ds.nodes if ds.node_id(n)}
    for n in ds.nodes:
        scope = ds.node_field(n, "scope")
        pid = ds.node_field(n, "partida_id")
        if scope == "partida" and not pid:
            out.append(Finding("D06", CRITICAL,
                               "scope='partida' sin partida_id: el aislamiento entre "
                               "partidas no puede evaluarse", ds.node_id(n)))
        if scope == "lore" and pid:
            out.append(Finding("D06", CRITICAL,
                               f"scope='lore' con partida_id={pid!r}: lore compartido "
                               "atado a una partida", ds.node_id(n)))
    for i, e in enumerate(ds.edges):
        a, b = por_id.get(str(e.get("from"))), por_id.get(str(e.get("to")))
        if a is None or b is None:
            continue  # ya lo reporta D04
        for campo in ("workspace", "scope", "partida_id"):
            va, vb = ds.node_field(a, campo), ds.node_field(b, campo)
            if va != vb:
                out.append(
                    Finding("D06", CRITICAL,
                            f"relación entre ámbitos distintos: {campo} {va!r} vs {vb!r}",
                            _rel_id(i, e), {"campo": campo})
                )
            ve = e.get(campo)
            if ve is not None and va is not None and ve != va:
                out.append(
                    Finding("D06", WARNING,
                            f"la relación declara {campo}={ve!r} y sus extremos {va!r}",
                            _rel_id(i, e), {"campo": campo})
                )
        if e.get("scope") not in (None,) and e.get("scope") not in AMBITOS_CONOCIDOS:
            out.append(Finding("D06", CRITICAL,
                               f"ámbito desconocido en relación: {e.get('scope')!r}",
                               _rel_id(i, e)))
    return out


# --- D07: referencias huérfanas ---------------------------------------------
def d07_referencias_huerfanas(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    ids = {ds.node_id(n) for n in ds.nodes if ds.node_id(n)}
    nombres = {
        str(ds.node_field(n, "canonical_name")).strip().lower()
        for n in ds.nodes
        if ds.node_field(n, "canonical_name")
    }
    fuentes = {
        str(ds.node_field(n, "entity_id"))
        for n in ds.nodes
        if ds.node_field(n, "entity_type") in TIPOS_FUENTE
    }
    hay_nodos_fuente = bool(fuentes)
    for n in ds.nodes:
        for lista in ("known_by", "known_by_characters"):
            valores = ds.node_field(n, lista)
            if not isinstance(valores, list):
                continue
            for v in valores:
                if not isinstance(v, str):
                    continue
                if v in ids or v.strip().lower() in nombres:
                    continue
                if v in {"party", "public", "narrator", "admin_only", "*"}:
                    continue
                out.append(
                    Finding("D07", WARNING,
                            f"'{lista}' referencia a '{v}', que no existe como entidad "
                            "ni como nombre canónico en el dataset",
                            ds.node_id(n), {"campo": lista, "referencia": v})
                )
        sd = ds.node_field(n, "source_document")
        if sd and hay_nodos_fuente and str(sd) not in fuentes:
            out.append(
                Finding("D07", WARNING,
                        f"source_document '{sd}' no corresponde a ningún nodo fuente",
                        ds.node_id(n), {"referencia": sd})
            )
    if not hay_nodos_fuente:
        out.append(
            Finding("D07", UNKNOWN,
                    "el dataset no contiene nodos de tipo fuente "
                    f"({sorted(TIPOS_FUENTE)}): la integridad de 'source_document' "
                    "no se ha podido comprobar")
        )
    return out


# --- D08: procedencia incompleta --------------------------------------------
CAMPOS_PROCEDENCIA = ("source_document", "confidence", "source_hash", "extractor_version")


def d08_procedencia(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    for n in ds.nodes:
        faltan = [c for c in CAMPOS_PROCEDENCIA if ds.node_field(n, c) in (None, "", [])]
        if not faltan:
            continue
        criticos = [c for c in faltan
                    if CAMPOS_POR_NOMBRE.get(c) and CAMPOS_POR_NOMBRE[c].ausencia == "ROMPE"]
        nivel = CRITICAL if criticos else (WARNING if "source_document" in faltan else INFO)
        out.append(
            Finding("D08", nivel,
                    f"procedencia incompleta, faltan: {', '.join(faltan)}",
                    ds.node_id(n), {"faltan": faltan})
        )
    return out


# --- D09: estado de revisión incoherente ------------------------------------
def d09_estado_de_revision(ds: Dataset) -> list[Finding]:
    out: list[Finding] = []
    for n in ds.nodes:
        rs = ds.node_field(n, "review_status")
        conf = ds.node_field(n, "confidence")
        vis = ds.node_field(n, "visibility")
        if rs == "rejected":
            out.append(Finding("D09", CRITICAL,
                               "entidad con review_status='rejected' presente en el grafo: "
                               "lo rechazado no debe seguir siendo consultable",
                               ds.node_id(n)))
        if rs in ("auto_extracted", "needs_review") and vis == "player":
            out.append(Finding("D09", WARNING,
                               f"contenido sin revisar (review_status={rs!r}) expuesto con "
                               "visibility='player'", ds.node_id(n)))
        if rs in ("reviewed", "corrected") and isinstance(conf, (int, float)) and conf < 0.5:
            out.append(Finding("D09", WARNING,
                               f"marcado como {rs!r} pero con confianza {conf}",
                               ds.node_id(n)))
        if rs is None:
            out.append(Finding("D09", UNKNOWN,
                               "sin review_status: no se puede afirmar que esté revisado "
                               "ni que no lo esté", ds.node_id(n)))
    return out


# --- D10: campos no declarados en el registro --------------------------------
def d10_campos_no_declarados(ds: Dataset) -> list[Finding]:
    from .registry import ALIAS_DE_PROYECCION

    conocidos = set(CAMPOS_POR_NOMBRE) | set(ALIAS_DE_PROYECCION)
    # campos de forma, no de contenido
    conocidos |= {"from", "to", "description", "aliases", "display_name",
                  "session_index", "party", "is_public", "known_by_characters",
                  "source_pages", "source_kind", "updated_at", "prompt_version",
                  "manual_review_required", "relation_label_es", "evidence"}
    vistos: dict[str, int] = {}
    for elem in list(ds.nodes) + list(ds.edges):
        for k in elem:
            if k.startswith("_") or k in conocidos:
                continue
            vistos[k] = vistos.get(k, 0) + 1
    return [
        Finding("D10", INFO,
                f"campo presente en los datos y no declarado en el registro ({c} elementos): "
                "o se declara o es un campo que nadie garantiza", k, {"apariciones": c})
        for k, c in sorted(vistos.items())
    ]


TODAS = (
    ("D01", d01_campos_obligatorios),
    ("D02", d02_valores_invalidos),
    ("D03", d03_ids_duplicados),
    ("D04", d04_extremos_inexistentes),
    ("D05", d05_tipos_desconocidos),
    ("D06", d06_contradicciones_de_ambito),
    ("D07", d07_referencias_huerfanas),
    ("D08", d08_procedencia),
    ("D09", d09_estado_de_revision),
    ("D10", d10_campos_no_declarados),
)


def ejecutar(ds: Dataset, solo: Iterable[str] | None = None) -> tuple[list[Finding], list[str]]:
    """Ejecuta las comprobaciones de dataset.

    Si una comprobación revienta, NO se traga el error: se convierte en un
    hallazgo UNKNOWN (nunca en un silencio verde) y se propaga en el veredicto.
    """
    seleccion = set(solo) if solo else None
    findings: list[Finding] = []
    ejecutadas: list[str] = []
    for nombre, fn in TODAS:
        if seleccion is not None and nombre not in seleccion:
            continue
        ejecutadas.append(nombre)
        try:
            findings.extend(fn(ds))
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(nombre, UNKNOWN,
                        f"la comprobación falló internamente: {type(exc).__name__}: {exc}")
            )
    return findings, ejecutadas
