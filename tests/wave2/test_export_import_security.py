"""test_export_import_security.py — invariantes de seguridad de EXPORT/IMPORT.

Contrato de referencia: docs/coordination/contract-proposals.md §2
(`s9-knowledge-export/internal-v1`, Equipo B / B-EXP-1c) y la matriz de muestras
hostiles de docs/coordination/qa-matrix.md.

AUTOCONTENIDO: el código real de B vive en `data-engine/app/export_import/**` en
rama paralela NO fusionada. Aquí definimos validadores/simuladores de REFERENCIA
mínimos que codifican las reglas de seguridad esperadas. Q no importa código de B.

Invariantes clave verificadas:
  - path traversal (`../`, ruta absoluta) -> RECHAZO
  - hash sha256 incorrecto -> RECHAZO
  - manifest ausente / versión desconocida / formato desconocido -> RECHAZO
  - IDs duplicados / workspace ajeno / tamaño excesivo -> RECHAZO
  - import es DRY-RUN por defecto (APPLY nunca por defecto), 0 escrituras

Los `test_*_mutation` demuestran que relajar la regla dejaría pasar el ataque.
"""
from __future__ import annotations

import copy
import hashlib
import posixpath

import pytest

MANIFEST_VERSION = "internal-1.0.0"
KNOWN_VERSIONS = frozenset({"internal-1.0.0"})
ALLOWED_FORMATS = frozenset({"jsonl", "json", "csv", "graphml", "markdown"})
MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB — límite de referencia anti zip-bomb/JSON gigante


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_path_traversal(path: str) -> bool:
    """True si `path` escapa del paquete (absoluta, drive Windows, o contiene `..`)."""
    if not isinstance(path, str) or not path:
        return True
    if path.startswith("/") or path.startswith("\\"):
        return True
    if len(path) >= 2 and path[1] == ":":  # C:\...
        return True
    norm = posixpath.normpath(path)
    parts = path.replace("\\", "/").split("/")
    if ".." in parts or norm.startswith(".."):
        return True
    return False


def validate_export_package(
    manifest: object,
    files: object,
    *,
    check_hashes: bool = True,
    check_traversal: bool = True,
) -> list[str]:
    """Valida un paquete de export (manifest + {ruta: bytes}). Devuelve vetos.

    `check_hashes`/`check_traversal` existen SOLO para los tests de mutación.
    """
    v: list[str] = []
    if manifest is None:
        return ["MANIFEST_ABSENT"]
    if not isinstance(manifest, dict):
        return ["MANIFEST_MALFORMED"]

    if manifest.get("manifest_version") not in KNOWN_VERSIONS:
        v.append("VERSION_UNKNOWN")

    for fmt in manifest.get("formats", []):
        if fmt not in ALLOWED_FORMATS:
            v.append(f"FORMAT_UNKNOWN:{fmt}")

    hashes = manifest.get("hashes", {})
    files = files or {}

    for path in hashes:
        if check_traversal and _is_path_traversal(path):
            v.append(f"PATH_TRAVERSAL:{path}")

    total = 0
    for path, blob in files.items():
        if check_traversal and _is_path_traversal(path):
            v.append(f"PATH_TRAVERSAL:{path}")
        total += len(blob)
        if check_hashes:
            expected = hashes.get(path)
            if expected is None:
                v.append(f"HASH_MISSING:{path}")
            elif _sha256(blob) != expected:
                v.append(f"HASH_MISMATCH:{path}")

    if total > MAX_TOTAL_BYTES:
        v.append("SIZE_EXCEEDED")

    return v


# --- Import (dry-run) -------------------------------------------------------
IMPORT_STATES = frozenset({
    "VALID", "INVALID", "WOULD_CREATE", "WOULD_UPDATE", "WOULD_LINK",
    "CONFLICT", "DUPLICATE", "DEFERRED",
})


class ImportResult:
    def __init__(self, states, writes, applied):
        self.states = states
        self.writes = writes          # nº de escrituras reales al backend
        self.applied = applied        # ¿se aplicó de verdad?


def run_import(request: dict, entries: list, *, current_workspace: str) -> ImportResult:
    """Simulador de import de REFERENCIA. DRY-RUN por defecto (APPLY explícito).

    NUNCA escribe salvo `request['apply'] is True`. Devuelve estados por entrada.
    """
    apply = request.get("apply", False) is True  # APPLY jamás por defecto
    states: list[str] = []
    seen_ids: set[str] = set()
    writes = 0
    for e in entries:
        eid = e.get("id")
        if eid in seen_ids:
            states.append("DUPLICATE")
            continue
        seen_ids.add(eid)
        if e.get("workspace") != current_workspace:
            states.append("CONFLICT")  # workspace ajeno: nunca cruza
            continue
        if apply:
            writes += 1
            states.append("WOULD_CREATE")  # (en apply real crearía; simulado)
        else:
            states.append("WOULD_CREATE")
    return ImportResult(states=states, writes=writes, applied=apply)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def valid_package():
    files = {
        "entities.jsonl": b'{"id":"e1"}\n',
        "relations.jsonl": b'{"id":"r1"}\n',
    }
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "workspace": "l5r",
        "formats": ["jsonl"],
        "counts": {"entities": 1, "relations": 1, "aliases": 0},
        "schemas": {"entity": "v1", "relation": "internal-v1"},
        "hashes": {p: _sha256(b) for p, b in files.items()},
        "compatibility": {"min_reader": MANIFEST_VERSION},
    }
    return manifest, files


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_reference_package_is_valid(valid_package):
    manifest, files = valid_package
    assert validate_export_package(manifest, files) == []


def test_reject_manifest_absent(valid_package):
    _, files = valid_package
    assert validate_export_package(None, files) == ["MANIFEST_ABSENT"]


def test_reject_version_unknown(valid_package):
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    manifest["manifest_version"] = "internal-99"
    assert "VERSION_UNKNOWN" in validate_export_package(manifest, files)


def test_reject_unknown_format(valid_package):
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    manifest["formats"] = ["jsonl", "exe"]
    assert "FORMAT_UNKNOWN:exe" in validate_export_package(manifest, files)


@pytest.mark.parametrize("evil", ["../../etc/passwd", "/etc/shadow", "..\\..\\win.ini", "C:\\secrets"])
def test_reject_path_traversal(valid_package, evil):
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    files = dict(files)
    files[evil] = b"payload"
    manifest["hashes"][evil] = _sha256(b"payload")
    vetos = validate_export_package(manifest, files)
    assert any(x.startswith("PATH_TRAVERSAL") for x in vetos)


def test_reject_hash_mismatch(valid_package):
    manifest, files = valid_package
    files = dict(files)
    files["entities.jsonl"] = b'{"id":"TAMPERED"}\n'  # contenido alterado, hash viejo
    vetos = validate_export_package(manifest, files)
    assert any(x.startswith("HASH_MISMATCH") for x in vetos)


def test_reject_hash_missing(valid_package):
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    files = dict(files)
    files["extra.jsonl"] = b"x"  # sin entrada en hashes
    vetos = validate_export_package(manifest, files)
    assert any(x.startswith("HASH_MISSING") for x in vetos)


def test_reject_size_exceeded(valid_package):
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    big = b"A" * (MAX_TOTAL_BYTES + 1)
    files = {"big.jsonl": big}
    manifest["hashes"] = {"big.jsonl": _sha256(big)}
    assert "SIZE_EXCEEDED" in validate_export_package(manifest, files)


def test_import_is_dry_run_by_default():
    entries = [{"id": "e1", "workspace": "l5r"}, {"id": "e2", "workspace": "l5r"}]
    res = run_import({}, entries, current_workspace="l5r")
    assert res.applied is False
    assert res.writes == 0  # 0 escrituras en dry-run


def test_import_rejects_duplicate_ids():
    entries = [{"id": "e1", "workspace": "l5r"}, {"id": "e1", "workspace": "l5r"}]
    res = run_import({}, entries, current_workspace="l5r")
    assert res.states.count("DUPLICATE") == 1


def test_import_rejects_foreign_workspace():
    entries = [{"id": "e1", "workspace": "OTRO"}]
    res = run_import({}, entries, current_workspace="l5r")
    assert res.states == ["CONFLICT"]
    assert res.writes == 0


# ---------------------------------------------------------------------------
# MUTATION CHECKS
# ---------------------------------------------------------------------------
@pytest.mark.mutation
def test_mutation_ignoring_hash_breaks(valid_package):
    """Mutación: ignorar el hash (check_hashes=False). Un fichero manipulado
    pasaría -> integridad rota. La regla estricta DEBE detectar el mismatch."""
    manifest, files = valid_package
    files = dict(files)
    files["entities.jsonl"] = b'{"id":"TAMPERED"}\n'
    strict = validate_export_package(manifest, files)
    relaxed = validate_export_package(manifest, files, check_hashes=False)
    assert any(x.startswith("HASH_MISMATCH") for x in strict)
    assert not any(x.startswith("HASH_MISMATCH") for x in relaxed)


@pytest.mark.mutation
def test_mutation_accepting_path_traversal_breaks(valid_package):
    """Mutación: aceptar path traversal (check_traversal=False). Una ruta `../`
    escaparía del paquete. La regla estricta DEBE vetarla."""
    manifest, files = valid_package
    manifest = copy.deepcopy(manifest)
    files = dict(files)
    files["../../etc/passwd"] = b"root:x:0:0"
    manifest["hashes"]["../../etc/passwd"] = _sha256(b"root:x:0:0")
    strict = validate_export_package(manifest, files)
    relaxed = validate_export_package(manifest, files, check_traversal=False)
    assert any(x.startswith("PATH_TRAVERSAL") for x in strict)
    assert not any(x.startswith("PATH_TRAVERSAL") for x in relaxed)


@pytest.mark.mutation
def test_mutation_apply_by_default_breaks():
    """Mutación: si APPLY fuese el valor por defecto, un import escribiría sin que
    el operador lo pida. La invariante: sin `apply=True` explícito -> 0 escrituras."""
    entries = [{"id": "e1", "workspace": "l5r"}]
    default_res = run_import({}, entries, current_workspace="l5r")
    apply_res = run_import({"apply": True}, entries, current_workspace="l5r")
    assert default_res.writes == 0 and default_res.applied is False
    # Solo con APPLY explícito hay escrituras: prueba que el default es seguro.
    assert apply_res.writes == 1 and apply_res.applied is True
