"""contract.py — Contrato interno `s9-knowledge-export/internal-v1`.

Define el modelo de datos y los VALIDADORES del paquete interno de
export/import de S9 Knowledge. Este modulo es DECLARATIVO y de
VALIDACION: nunca escribe en Neo4j, nunca aplica una importacion.

Alcance (por diseno):
  - MANIFEST del paquete (metadatos + inventario + hashes + politica).
  - Tipos de registro EXPORTABLES y categorias PROHIBIDAS.
  - Estados de importacion en modo DRY-RUN (Enum).
  - Validadores para paquete ZIP manifestado, JSONL, JSON, CSV y
    GraphML DECLARADO.
  - Un validador de import que es SIEMPRE dry-run (nunca APPLY).

Fuera de alcance (intencionado):
  - APPLY de importacion (crear/actualizar/enlazar de verdad).
  - Convertir dumps internos de Neo4j en contrato de usuario.
  - Parser GraphML completo (basta validar la DECLARACION; ver
    `validate_graphml_declared`).

Redaccion de datos sensibles: se REUTILIZA de
`review.export_import` (sanitize_value / sanitize_text). No se
duplica aqui la logica de redaccion.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# Reutilizamos la redaccion existente (NO la duplicamos).
try:  # pragma: no cover - import defensivo segun sys.path del runner
    from review.export_import import sanitize_value, sanitize_text
except Exception:  # pragma: no cover
    from ..review.export_import import sanitize_value, sanitize_text  # type: ignore

__all__ = [
    "CONTRACT_FORMAT",
    "CONTRACT_VERSION",
    "SUPPORTED_VERSIONS",
    "ImportState",
    "RecordType",
    "EXPORTABLE_RECORD_TYPES",
    "FORBIDDEN_EXPORT_CATEGORIES",
    "Limits",
    "Manifest",
    "DryRunRecord",
    "DryRunReport",
    "build_manifest",
    "validate_manifest",
    "validate_safe_path",
    "validate_sha256",
    "remap_external_id",
    "validate_zip_metadata",
    "validate_jsonl",
    "validate_json",
    "validate_csv",
    "validate_graphml_declared",
    "dry_run_import",
    "sanitize_value",
    "sanitize_text",
]

# ─────────────────────────────────────────────────────────────────────────────
# Identidad del contrato
# ─────────────────────────────────────────────────────────────────────────────

CONTRACT_FORMAT = "s9-knowledge-export/internal-v1"
CONTRACT_VERSION = "1.0"
SUPPORTED_VERSIONS = frozenset({"1.0"})
EXPORTER_VERSION = "s9-knowledge-export-import/1.0"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ─────────────────────────────────────────────────────────────────────────────
# Registros soportados y categorias PROHIBIDAS
# ─────────────────────────────────────────────────────────────────────────────

class RecordType(str, Enum):
    """Tipos de registro EXPORTABLES por el contrato interno."""

    ENTITY = "entities"
    RELATION = "relations"
    ALIAS = "aliases"
    PROVENANCE = "provenance"
    DECISION = "decisions"        # decisiones exportables
    PLAN = "plans"
    METRIC = "metrics"
    EVENT = "events"              # eventos permitidos


EXPORTABLE_RECORD_TYPES = frozenset(rt.value for rt in RecordType)

# Categorias que el contrato NUNCA exporta. Presencia => INVALID.
FORBIDDEN_EXPORT_CATEGORIES = frozenset({
    "passwords",
    "sessions",
    "credentials",
    "tokens",
    "internal_paths",
    "sensitive_config",
    "neo4j_dump",       # dumps internos de Neo4j NO son contrato de usuario
    "secrets",
})

# Claves sospechosas dentro de un registro (defensa en profundidad).
_FORBIDDEN_KEY_HINTS = (
    "password", "passwd", "secret", "token", "credential",
    "session", "cookie", "api_key", "apikey", "private_key",
    "bolt_uri", "neo4j_uri", "neo4j_dump",
)


# ─────────────────────────────────────────────────────────────────────────────
# Limites de seguridad
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Limits:
    """Limites de tamano y cardinalidad para validar un paquete.

    Los defaults son conservadores; el llamador puede endurecerlos.
    """

    max_file_count: int = 512
    max_records: int = 200_000
    max_uncompressed_bytes: int = 512 * 1024 * 1024   # 512 MiB
    max_manifest_bytes: int = 8 * 1024 * 1024          # 8 MiB
    # Ratio declarado maximo (descomprimido / comprimido). Defensa
    # anti zip-bomb basada en METADATA declarada, sin descomprimir.
    max_compression_ratio: float = 100.0


DEFAULT_LIMITS = Limits()


# ─────────────────────────────────────────────────────────────────────────────
# Estados de importacion — DRY-RUN (nunca APPLY)
# ─────────────────────────────────────────────────────────────────────────────

class ImportState(str, Enum):
    """Estados posibles de un registro durante import en modo dry-run.

    NINGUN estado implica escritura: describen lo que PASARIA.
    """

    VALID = "VALID"
    INVALID = "INVALID"
    WOULD_CREATE = "WOULD_CREATE"
    WOULD_UPDATE = "WOULD_UPDATE"
    WOULD_LINK = "WOULD_LINK"
    CONFLICT = "CONFLICT"
    DUPLICATE = "DUPLICATE"
    DEFERRED = "DEFERRED"


# Estados que representan un rechazo/no-aplicacion segura.
_REJECTING_STATES = frozenset({
    ImportState.INVALID,
    ImportState.CONFLICT,
    ImportState.DUPLICATE,
    ImportState.DEFERRED,
})


# ─────────────────────────────────────────────────────────────────────────────
# MANIFEST
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Manifest:
    """MANIFEST del paquete `s9-knowledge-export/internal-v1`.

    Campos:
      format            — identificador del contrato.
      version           — version del contrato.
      created_at        — ISO-8601 UTC.
      exporter_version  — version del exportador que lo genero.
      workspace         — workspace propietario (aislamiento).
      filters           — filtros aplicados al exportar (dict libre).
      entity_count      — nº de entidades declaradas.
      relation_count    — nº de relaciones declaradas.
      file_count        — nº de ficheros de datos en el paquete.
      schemas           — mapa {record_type: schema_id/version}.
      hashes            — mapa {nombre_fichero: sha256_hex}.
      compression       — metadatos de compresion (algoritmo, ratios).
      redaction_policy  — politica de redaccion aplicada.
    """

    workspace: str
    format: str = CONTRACT_FORMAT
    version: str = CONTRACT_VERSION
    created_at: str = ""
    exporter_version: str = EXPORTER_VERSION
    filters: dict[str, Any] = field(default_factory=dict)
    entity_count: int = 0
    relation_count: int = 0
    file_count: int = 0
    schemas: dict[str, str] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    compression: dict[str, Any] = field(default_factory=dict)
    redaction_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "version": self.version,
            "created_at": self.created_at,
            "exporter_version": self.exporter_version,
            "workspace": self.workspace,
            "filters": self.filters,
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "file_count": self.file_count,
            "schemas": self.schemas,
            "hashes": self.hashes,
            "compression": self.compression,
            "redaction_policy": self.redaction_policy,
        }

    @staticmethod
    def from_dict(data: Any) -> "Manifest":
        if not isinstance(data, dict):
            raise TypeError("El manifest debe ser un dict JSON")
        return Manifest(
            workspace=data.get("workspace", ""),
            format=data.get("format", ""),
            version=data.get("version", ""),
            created_at=data.get("created_at", ""),
            exporter_version=data.get("exporter_version", ""),
            filters=data.get("filters", {}) or {},
            entity_count=int(data.get("entity_count", 0) or 0),
            relation_count=int(data.get("relation_count", 0) or 0),
            file_count=int(data.get("file_count", 0) or 0),
            schemas=data.get("schemas", {}) or {},
            hashes=data.get("hashes", {}) or {},
            compression=data.get("compression", {}) or {},
            redaction_policy=data.get("redaction_policy", {}) or {},
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_manifest(
    workspace: str,
    *,
    filters: dict[str, Any] | None = None,
    entity_count: int = 0,
    relation_count: int = 0,
    schemas: dict[str, str] | None = None,
    hashes: dict[str, str] | None = None,
    compression: dict[str, Any] | None = None,
    redaction_policy: dict[str, Any] | None = None,
) -> Manifest:
    """Construye un MANIFEST bien formado con `created_at` en UTC.

    `file_count` se deriva de `hashes` (un hash sha256 por fichero de
    datos declarado). La politica de redaccion por defecto referencia
    la reutilizacion de `review.export_import`.
    """
    hashes = hashes or {}
    redaction_policy = redaction_policy or {
        "source": "review.export_import.sanitize_value",
        "redacts": ["internal_paths", "private_ips", "tokens", "secrets", "neo4j_uris"],
    }
    return Manifest(
        workspace=workspace,
        created_at=_now_iso(),
        filters=filters or {},
        entity_count=entity_count,
        relation_count=relation_count,
        file_count=len(hashes),
        schemas=schemas or {},
        hashes=hashes,
        compression=compression or {},
        redaction_policy=redaction_policy,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validadores atomicos
# ─────────────────────────────────────────────────────────────────────────────

def validate_safe_path(name: str) -> tuple[bool, str]:
    """Valida que `name` sea una ruta relativa segura dentro del paquete.

    Rechaza: rutas absolutas, path traversal (`..`), raices Windows
    (`C:\\`), separadores de backslash y bytes nulos.

    Returns:
        (ok, motivo) — motivo == "" si ok.
    """
    if not isinstance(name, str) or not name:
        return False, "nombre de fichero vacio o no textual"
    if "\x00" in name:
        return False, "byte nulo en el nombre"
    if name.startswith("/") or name.startswith("\\"):
        return False, "ruta absoluta no permitida"
    if re.match(r"^[A-Za-z]:[\\/]", name):
        return False, "raiz de unidad Windows no permitida"
    # Normalizar separadores y comprobar segmentos.
    parts = re.split(r"[\\/]+", name)
    for part in parts:
        if part == "..":
            return False, "path traversal detectado ('..')"
    return True, ""


def validate_sha256(value: str, data: bytes | None = None) -> tuple[bool, str]:
    """Valida el formato de un sha256 hex y, si se da `data`, su match.

    Returns:
        (ok, motivo)
    """
    if not isinstance(value, str) or not _SHA256_RE.match(value.lower()):
        return False, "hash sha256 con formato invalido"
    if data is not None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != value.lower():
            return False, "hash sha256 no coincide con el contenido"
    return True, ""


def remap_external_id(external_id: str, workspace: str) -> str:
    """Remapeo DETERMINISTA de un ID externo no confiable a un ID interno.

    Los IDs externos NUNCA se confian tal cual. Se derivan de forma
    determinista y aislada por workspace, de modo que el mismo par
    (workspace, external_id) siempre produce el mismo ID interno, pero
    dos workspaces distintos nunca colisionan.
    """
    digest = hashlib.sha256(
        f"{workspace}\x1f{external_id}".encode("utf-8")
    ).hexdigest()
    return f"s9x_{digest[:24]}"


# ─────────────────────────────────────────────────────────────────────────────
# Validador de MANIFEST
# ─────────────────────────────────────────────────────────────────────────────

def validate_manifest(
    data: Any,
    *,
    expected_workspace: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ImportState, list[str]]:
    """Valida el MANIFEST de un paquete interno.

    Comprueba: manifest presente y bien tipado, format/version
    reconocidos, aislamiento de workspace, hashes en formato sha256,
    schema obligatorio para tipos declarados, coherencia de file_count
    y limites de cardinalidad.

    Returns:
        (estado, errores). Estado VALID solo si no hay errores.
    """
    errors: list[str] = []

    if data is None:
        return ImportState.INVALID, ["manifest ausente"]
    if not isinstance(data, dict):
        return ImportState.INVALID, ["manifest no es un objeto JSON"]

    fmt = data.get("format")
    if fmt != CONTRACT_FORMAT:
        errors.append(f"format desconocido o ausente: {fmt!r}")

    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        errors.append(f"version no soportada: {version!r}")

    workspace = data.get("workspace")
    if not workspace:
        errors.append("falta workspace (aislamiento obligatorio)")
    elif expected_workspace is not None and workspace != expected_workspace:
        errors.append(
            f"workspace ajeno: paquete={workspace!r} esperado={expected_workspace!r}"
        )

    hashes = data.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        errors.append("hashes obligatorios ausentes (sha256 por fichero)")
    else:
        for fname, h in hashes.items():
            ok_path, why = validate_safe_path(fname)
            if not ok_path:
                errors.append(f"fichero '{fname}' con ruta insegura: {why}")
            ok_hash, why_h = validate_sha256(h if isinstance(h, str) else "")
            if not ok_hash:
                errors.append(f"fichero '{fname}': {why_h}")

    schemas = data.get("schemas")
    if not isinstance(schemas, dict) or not schemas:
        errors.append("schema obligatorio ausente (mapa 'schemas')")

    # Coherencia de file_count con los hashes declarados.
    if isinstance(hashes, dict):
        declared = data.get("file_count")
        if declared is not None and declared != len(hashes):
            errors.append(
                f"file_count declarado ({declared}) != nº de hashes ({len(hashes)})"
            )
        if len(hashes) > limits.max_file_count:
            errors.append(
                f"demasiados ficheros: {len(hashes)} > {limits.max_file_count}"
            )

    # Limites de cardinalidad declarada.
    total_records = int(data.get("entity_count", 0) or 0) + int(
        data.get("relation_count", 0) or 0
    )
    if total_records > limits.max_records:
        errors.append(
            f"nº de registros declarado {total_records} supera limite {limits.max_records}"
        )

    # Categorias prohibidas declaradas en filtros/redaccion.
    forbidden = _forbidden_categories_in(data)
    if forbidden:
        errors.append(f"categorias prohibidas declaradas: {sorted(forbidden)}")

    if errors:
        return ImportState.INVALID, errors
    return ImportState.VALID, []


def _forbidden_categories_in(data: dict) -> set[str]:
    """Detecta categorias prohibidas declaradas en el manifest."""
    found: set[str] = set()
    # En schemas / filters keys.
    for section in ("schemas", "filters"):
        sec = data.get(section)
        if isinstance(sec, dict):
            for key in sec:
                if str(key).lower() in FORBIDDEN_EXPORT_CATEGORIES:
                    found.add(str(key).lower())
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Validador de paquete ZIP (por METADATA, sin descomprimir)
# ─────────────────────────────────────────────────────────────────────────────

def validate_zip_metadata(
    entries: list[dict[str, Any]],
    *,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ImportState, list[str]]:
    """Valida la METADATA declarada de un ZIP SIN descomprimirlo.

    `entries` es la lista de entradas del directorio central del ZIP,
    cada una con al menos: {name, compress_size, file_size}. NO se abre
    ni descomprime ningun contenido: la defensa anti zip-bomb se basa en
    el RATIO declarado y en los limites de tamano/cardinalidad.

    Returns:
        (estado, errores)
    """
    errors: list[str] = []

    if not isinstance(entries, list) or not entries:
        return ImportState.INVALID, ["ZIP sin entradas declaradas"]

    if len(entries) > limits.max_file_count:
        errors.append(
            f"ZIP con demasiadas entradas: {len(entries)} > {limits.max_file_count}"
        )

    total_uncompressed = 0
    for i, e in enumerate(entries):
        name = e.get("name", "")
        ok_path, why = validate_safe_path(name)
        if not ok_path:
            errors.append(f"entrada[{i}] '{name}': {why}")

        comp = int(e.get("compress_size", 0) or 0)
        raw = int(e.get("file_size", 0) or 0)
        total_uncompressed += raw

        if raw < 0 or comp < 0:
            errors.append(f"entrada[{i}] '{name}': tamanos negativos")
            continue
        # Ratio declarado excesivo => zip-bomb simulada.
        if comp > 0:
            ratio = raw / comp
            if ratio > limits.max_compression_ratio:
                errors.append(
                    f"entrada[{i}] '{name}': ratio {ratio:.1f} supera "
                    f"limite {limits.max_compression_ratio} (posible zip-bomb)"
                )
        elif raw > 0:
            # Descomprimido no nulo con comprimido 0 => ratio infinito.
            errors.append(
                f"entrada[{i}] '{name}': compress_size=0 con file_size>0 "
                "(ratio infinito, posible zip-bomb)"
            )

    if total_uncompressed > limits.max_uncompressed_bytes:
        errors.append(
            f"tamano descomprimido declarado {total_uncompressed} supera "
            f"limite {limits.max_uncompressed_bytes}"
        )

    if errors:
        return ImportState.INVALID, errors
    return ImportState.VALID, []


# ─────────────────────────────────────────────────────────────────────────────
# Validadores de formato de datos
# ─────────────────────────────────────────────────────────────────────────────

def validate_json(
    text: str,
    *,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ImportState, list[str], Any]:
    """Valida un documento JSON. Devuelve tambien el objeto parseado."""
    if not isinstance(text, str):
        return ImportState.INVALID, ["contenido JSON no textual"], None
    if len(text.encode("utf-8")) > limits.max_uncompressed_bytes:
        return ImportState.INVALID, ["documento JSON supera limite de tamano"], None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return ImportState.INVALID, [f"JSON invalido: {exc}"], None
    return ImportState.VALID, [], obj


def validate_jsonl(
    text: str,
    *,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ImportState, list[str], list[Any]]:
    """Valida un documento JSONL (un objeto JSON por linea no vacia)."""
    errors: list[str] = []
    rows: list[Any] = []
    if not isinstance(text, str):
        return ImportState.INVALID, ["contenido JSONL no textual"], []
    if len(text.encode("utf-8")) > limits.max_uncompressed_bytes:
        return ImportState.INVALID, ["documento JSONL supera limite de tamano"], []

    count = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        count += 1
        if count > limits.max_records:
            errors.append(f"JSONL supera limite de registros {limits.max_records}")
            break
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"linea {lineno}: JSON invalido ({exc})")

    if not rows and not errors:
        errors.append("JSONL vacio")

    if errors:
        return ImportState.INVALID, errors, rows
    return ImportState.VALID, [], rows


def validate_csv(
    text: str,
    *,
    required_columns: list[str] | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ImportState, list[str], list[dict[str, str]]]:
    """Valida un CSV con cabecera. Comprueba columnas requeridas y limite."""
    errors: list[str] = []
    if not isinstance(text, str):
        return ImportState.INVALID, ["contenido CSV no textual"], []
    if len(text.encode("utf-8")) > limits.max_uncompressed_bytes:
        return ImportState.INVALID, ["documento CSV supera limite de tamano"], []

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return ImportState.INVALID, ["CSV sin cabecera"], []

    if required_columns:
        missing = [c for c in required_columns if c not in reader.fieldnames]
        if missing:
            errors.append(f"faltan columnas requeridas: {missing}")

    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= limits.max_records:
            errors.append(f"CSV supera limite de registros {limits.max_records}")
            break
        rows.append(row)

    if errors:
        return ImportState.INVALID, errors, rows
    return ImportState.VALID, [], rows


def validate_graphml_declared(
    manifest_schemas: dict[str, Any],
    *,
    file_name: str = "",
) -> tuple[ImportState, list[str]]:
    """Valida que un GraphML este DECLARADO correctamente en el manifest.

    NOTA DE ALCANCE: aqui NO se parsea el GraphML completo. Se valida
    unicamente que el paquete DECLARA su presencia y schema. El parser
    XML completo (con defensa XXE / billion-laughs) queda para otra
    tarea; documentado a proposito.

    Returns:
        (estado, errores)
    """
    errors: list[str] = []
    if not isinstance(manifest_schemas, dict):
        return ImportState.INVALID, ["schemas del manifest ausente para GraphML"]

    decl = manifest_schemas.get("graphml")
    if not decl:
        errors.append("GraphML no declarado en manifest.schemas['graphml']")

    if file_name:
        ok_path, why = validate_safe_path(file_name)
        if not ok_path:
            errors.append(f"GraphML '{file_name}': {why}")
        if not file_name.lower().endswith(".graphml"):
            errors.append(f"GraphML '{file_name}': extension inesperada")

    if errors:
        return ImportState.INVALID, errors
    return ImportState.VALID, []


# ─────────────────────────────────────────────────────────────────────────────
# Import DRY-RUN (nunca APPLY)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DryRunRecord:
    """Resultado dry-run de un registro individual."""

    index: int
    record_type: str
    external_id: str
    internal_id: str
    state: ImportState
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "record_type": self.record_type,
            "external_id": self.external_id,
            "internal_id": self.internal_id,
            "state": self.state.value,
            "reasons": self.reasons,
        }


@dataclass
class DryRunReport:
    """Informe global de un import dry-run. NUNCA aplica nada."""

    workspace: str
    applied: bool = False   # invariante: SIEMPRE False
    manifest_state: ImportState = ImportState.VALID
    manifest_errors: list[str] = field(default_factory=list)
    records: list[DryRunRecord] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in ImportState}
        for r in self.records:
            counts[r.state.value] += 1
        return counts

    @property
    def rejected_any(self) -> bool:
        if self.manifest_state != ImportState.VALID:
            return True
        return any(r.state in _REJECTING_STATES for r in self.records)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "applied": self.applied,
            "manifest_state": self.manifest_state.value,
            "manifest_errors": self.manifest_errors,
            "summary": self.summary,
            "records": [r.to_dict() for r in self.records],
        }


def _record_has_forbidden(record: dict) -> list[str]:
    """Detecta claves/valores prohibidos dentro de un registro."""
    reasons: list[str] = []
    for key in record:
        kl = str(key).lower()
        for hint in _FORBIDDEN_KEY_HINTS:
            if hint in kl:
                reasons.append(f"clave prohibida '{key}'")
                break
    return reasons


def dry_run_import(
    manifest: Any,
    records: list[dict[str, Any]],
    *,
    target_workspace: str,
    existing_internal_ids: set[str] | None = None,
    known_entity_ids: set[str] | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> DryRunReport:
    """Simula una importacion SIN aplicar nada (siempre dry-run).

    Para cada registro determina el estado que TENDRIA (WOULD_CREATE,
    WOULD_UPDATE, WOULD_LINK, DUPLICATE, CONFLICT, DEFERRED o INVALID).
    Nunca escribe en Neo4j ni en disco.

    Reglas:
      - Manifest invalido => report con manifest_state != VALID; no se
        procesan registros (fail-closed).
      - Aislamiento de workspace: cualquier registro de otro workspace
        => CONFLICT.
      - IDs externos no confiables: se remapean de forma determinista.
      - Duplicados (mismo internal_id ya presente) => DUPLICATE.
      - Registro con secretos/sesiones/credenciales => INVALID.
      - record_type no exportable => INVALID.
      - Relacion cuyos extremos no existen (ni conocidos ni en el lote)
        => DEFERRED (no CONFLICT: podria resolverse mas tarde).
    """
    existing_internal_ids = set(existing_internal_ids or set())
    known_entity_ids = set(known_entity_ids or set())

    report = DryRunReport(workspace=target_workspace)

    # 1) Validar manifest primero (fail-closed).
    m_state, m_errors = validate_manifest(
        manifest, expected_workspace=target_workspace, limits=limits
    )
    report.manifest_state = m_state
    report.manifest_errors = m_errors
    if m_state != ImportState.VALID:
        # No procesamos registros con manifest invalido.
        report.applied = False
        return report

    # Limite de nº de registros del lote.
    if len(records) > limits.max_records:
        report.manifest_state = ImportState.INVALID
        report.manifest_errors.append(
            f"lote con {len(records)} registros supera limite {limits.max_records}"
        )
        report.applied = False
        return report

    # IDs internos que este lote crearia (para detectar duplicados intra-lote).
    batch_internal_ids: set[str] = set()
    # IDs de entidad que el lote aportaria (para resolver relaciones).
    batch_entity_internal_ids: set[str] = set(known_entity_ids)
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("type") in ("entities", "entity"):
            ext = str(rec.get("id", ""))
            if ext:
                batch_entity_internal_ids.add(
                    remap_external_id(ext, target_workspace)
                )

    # 2) Procesar cada registro (solo determina estado; nada se aplica).
    for i, rec in enumerate(records):
        reasons: list[str] = []
        if not isinstance(rec, dict):
            report.records.append(
                DryRunRecord(i, "?", "", "", ImportState.INVALID,
                             ["registro no es un objeto"])
            )
            continue

        rtype = str(rec.get("type", ""))
        external_id = str(rec.get("id", ""))
        internal_id = (
            remap_external_id(external_id, target_workspace) if external_id else ""
        )

        # a) Tipo exportable.
        norm_type = _normalize_type(rtype)
        if norm_type not in EXPORTABLE_RECORD_TYPES:
            reasons.append(f"tipo no exportable: {rtype!r}")
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.INVALID, reasons)
            )
            continue

        # b) Secretos/credenciales prohibidos.
        forbidden = _record_has_forbidden(rec)
        if forbidden:
            reasons.extend(forbidden)
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.INVALID, reasons)
            )
            continue

        # c) Aislamiento de workspace.
        rec_ws = rec.get("workspace")
        if rec_ws is not None and rec_ws != target_workspace:
            reasons.append(
                f"workspace ajeno: {rec_ws!r} != {target_workspace!r}"
            )
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.CONFLICT, reasons)
            )
            continue

        # d) ID externo obligatorio.
        if not external_id:
            reasons.append("registro sin id externo")
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.INVALID, reasons)
            )
            continue

        # e) Duplicados intra-lote.
        if internal_id in batch_internal_ids:
            reasons.append("id duplicado dentro del lote")
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.DUPLICATE, reasons)
            )
            continue
        batch_internal_ids.add(internal_id)

        # f) Relaciones: extremos deben existir (conocidos o en el lote).
        if norm_type == RecordType.RELATION.value:
            src = rec.get("from")
            dst = rec.get("to")
            if not src or not dst:
                reasons.append("relacion sin extremos from/to")
                report.records.append(
                    DryRunRecord(i, rtype, external_id, internal_id,
                                 ImportState.INVALID, reasons)
                )
                continue
            src_int = remap_external_id(str(src), target_workspace)
            dst_int = remap_external_id(str(dst), target_workspace)
            if (src_int not in batch_entity_internal_ids
                    or dst_int not in batch_entity_internal_ids):
                reasons.append("extremos de la relacion aun no presentes")
                report.records.append(
                    DryRunRecord(i, rtype, external_id, internal_id,
                                 ImportState.DEFERRED, reasons)
                )
                continue
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.WOULD_LINK, reasons)
            )
            continue

        # g) Entidad/otros: crear o actualizar.
        if internal_id in existing_internal_ids:
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.WOULD_UPDATE, reasons)
            )
        else:
            report.records.append(
                DryRunRecord(i, rtype, external_id, internal_id,
                             ImportState.WOULD_CREATE, reasons)
            )

    # Invariante duro: jamas se aplica nada.
    report.applied = False
    return report


def _normalize_type(rtype: str) -> str:
    """Normaliza singulares/plural a los valores de RecordType."""
    singular = {
        "entity": "entities",
        "relation": "relations",
        "alias": "aliases",
        "decision": "decisions",
        "plan": "plans",
        "metric": "metrics",
        "event": "events",
    }
    return singular.get(rtype, rtype)
