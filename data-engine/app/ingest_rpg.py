#!/usr/bin/env python3
"""
Ingesta de PDFs narrativos RPG en el grafo de propiedades.
Uso: property-graph-rpg --workspace leyenda --pdf /ruta/al/archivo.pdf [--pages 1-20]
     property-graph-rpg --workspace leyenda --text /ruta/al/archivo.md --profile short
     property-graph-rpg --workspace leyenda --image /ruta/a/imagen.png --profile image-text
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# ── Exit codes ────────────────────────────────────────────────────────────────
EXIT_OK = 0
EXIT_NO_ENTITIES = 10
EXIT_PDF_READ_ERROR = 20
EXIT_NO_TEXT_PAGES = 21
EXIT_MODEL_ERROR = 30
EXIT_INVALID_JSON = 31
EXIT_NEO4J_ERROR = 40
EXIT_NO_SPACE = 50
EXIT_LOCKED = 60
EXIT_REQUIRES_OCR = 70

NEXTCLOUD_BASE = "/mnt/nextcloud-rol"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("property-graph-rpg")


# ── Config ────────────────────────────────────────────────────────────────────
def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def read_password(password_file: str) -> str:
    with open(password_file) as f:
        return f.read().strip()


# ── Path validation ───────────────────────────────────────────────────────────
def validate_pdf_path(pdf_path: str) -> Path:
    if ".." in pdf_path:
        log.error("Path traversal detectado")
        sys.exit(EXIT_PDF_READ_ERROR)
    p = Path(pdf_path).resolve()
    base = Path(NEXTCLOUD_BASE).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        log.error("La ruta %s no está dentro de %s", pdf_path, NEXTCLOUD_BASE)
        sys.exit(EXIT_PDF_READ_ERROR)
    if not p.exists():
        log.error("El archivo no existe: %s", p)
        sys.exit(EXIT_PDF_READ_ERROR)
    return p


# ── SHA-256 ───────────────────────────────────────────────────────────────────
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── PDF reading ───────────────────────────────────────────────────────────────
def extract_text_by_page(pdf_path: Path, page_range=None) -> dict:
    """Devuelve {page_number (1-based): text}."""
    try:
        from pypdf import PdfReader
    except ImportError:
        log.error("pypdf no disponible")
        sys.exit(EXIT_PDF_READ_ERROR)

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    start, end = (page_range[0] - 1, page_range[1]) if page_range else (0, total)
    start = max(0, start)
    end = min(total, end)

    pages = {}
    for i in range(start, end):
        try:
            text = reader.pages[i].extract_text() or ""
            pages[i + 1] = text.strip()
        except Exception as e:
            log.warning("Error extrayendo página %d: %s", i + 1, e)
            pages[i + 1] = ""
    return pages


def get_page_count(pdf_path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return 0


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_pages(pages: dict, chunk_size: int, chunk_overlap: int) -> list:
    """Divide páginas en chunks manteniendo referencia de página."""
    page_nums = sorted(pages.keys())
    chunks = []
    i = 0
    while i < len(page_nums):
        chunk_pages_nums = page_nums[i:i + chunk_size]
        text = "\n\n".join(pages[p] for p in chunk_pages_nums if pages[p])
        if text.strip():
            chunks.append({
                "text": text,
                "page_start": chunk_pages_nums[0],
                "page_end": chunk_pages_nums[-1],
            })
        step = max(1, chunk_size - chunk_overlap)
        i += step
    return chunks


# ── Ollama extractor ──────────────────────────────────────────────────────────
class OllamaExtractor:
    def __init__(self, config: dict, model_override=None, profile: str = "short"):
        self.base_url = config["ollama"]["base_url"].rstrip("/")
        self.model = model_override or config["ollama"]["model"]
        self.temperature = config["ollama"].get("temperature", 0)
        self.timeout = config.get("processing", {}).get("request_timeout",
                       config["ollama"].get("request_timeout", 600))
        self.profile = profile

    def extract(self, text: str, workspace: str, source_document: str,
                page_start: int, page_end: int) -> dict:
        import urllib.request
        import urllib.error

        from prompts import rpg_extraction_prompt as _pr
        from prompts.rpg_extraction_prompt import (
            SYSTEM_PROMPT, USER_PROMPT_TEMPLATE,
            SYSTEM_PROMPT_TRANSCRIPT, USER_PROMPT_TEMPLATE_TRANSCRIPT,
        )

        if self.profile == "transcript":
            system_msg = SYSTEM_PROMPT_TRANSCRIPT
            user_tpl = USER_PROMPT_TEMPLATE_TRANSCRIPT
        elif self.profile == "book" and hasattr(_pr, "SYSTEM_PROMPT_BOOK"):
            # Fase 6: perfil book usa prompt de manual (knowledge_layer=book)
            system_msg = _pr.SYSTEM_PROMPT_BOOK
            user_tpl = getattr(_pr, "USER_PROMPT_TEMPLATE_BOOK", USER_PROMPT_TEMPLATE)
        else:
            system_msg = SYSTEM_PROMPT
            user_tpl = USER_PROMPT_TEMPLATE

        user_msg = user_tpl.format(
            workspace=workspace,
            source_document=source_document,
            page_start=page_start,
            page_end=page_end,
            text=text[:8000],
        )

        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": self.temperature,
            "stream": False,
        }).encode()

        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            log.error("Error conectando a Ollama: %s", e)
            sys.exit(EXIT_MODEL_ERROR)

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return self._parse_json(content)

    def extract_events_and_relations(
        self,
        text: str,
        entity_names: list,
        workspace: str,
        source_document: str,
        page_start: int,
    ) -> dict:
        """Segunda pasada: extrae Events y relaciones narrativas.
        Solo se llama con profile=='transcript'. Devuelve dict con 'events' y 'relations'.
        Si falla, retorna {} y loguea warning (nunca aborta).
        """
        import urllib.request
        import urllib.error
        from prompts.rpg_extraction_prompt import SECOND_PASS_PROMPT

        try:
            user_msg = SECOND_PASS_PROMPT.format(
                entity_names=", ".join(entity_names) if entity_names else "(ninguna)",
                text=text[:6000],
                workspace=workspace,
                source_document=source_document,
                page_start=page_start,
            )
            payload = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": user_msg}],
                "temperature": self.temperature,
                "stream": False,
            }).encode()
            url = f"{self.base_url}/v1/chat/completions"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Segunda pasada: timeout reducido (max 300s) para no bloquear en cola de Ollama
            second_pass_timeout = min(self.timeout, 300)
            with urllib.request.urlopen(req, timeout=second_pass_timeout) as resp:
                data = json.loads(resp.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = self._parse_json(content)
            if not isinstance(result, dict):
                log.warning("Segunda pasada: respuesta no es dict, ignorando")
                return {}
            return result
        except Exception as exc:
            log.warning("Segunda pasada fallida (chunk ignorado): %s", exc)
            return {}

    def _parse_json(self, content: str) -> dict:
        content = content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}


# ── Validación semántica (Fase 10) ────────────────────────────────────────────
# Conjuntos de tipos para reglas semánticas.
_SEM_PERSON_LIKE = {"Character", "Creature", "NonHuman", "Spirit", "Demon", "Beast"}
_SEM_PLACE_LIKE = {"Location", "Region"}
_SEM_GROUP_LIKE = {"Faction", "Clan", "Family", "School", "Group"}
_SEM_EVENT_LIKE = {"Event", "Encounter", "Combat"}

# Relaciones "de lugar" cuyo target debería ser un lugar
_SEM_PLACE_TARGET_RELS = {
    "FOUGHT_AT", "DEFEATED_AT", "KILLED_AT", "ESCAPED_FROM", "SEEN_IN",
    "ENCOUNTERED_AT", "FOUND_IN", "HIDDEN_IN", "TRAVELS_TO", "COMES_FROM",
    "DISAPPEARED_NEAR", "OCCURS_IN", "LOCATED_IN",
}


def _check_relation_semantics(rel, chunk_entities: list, warnings_path):
    """Detecta relaciones con semántica dudosa/ inválida.

    Devuelve (verdict, warning):
    - verdict == "ok": la relación es plausible → escribir normal.
    - verdict == "dubious": escribir pero marcar manual_review_required=true.
    - verdict == "invalid": no escribir (descartar), registrar en review.
    warning es un string informativo o None.
    """
    type_map: dict[str, str] = {e.canonical_name: e.entity_type for e in chunk_entities}
    target_type = type_map.get(rel.target_canonical, "")
    source_type = type_map.get(rel.source_canonical, "")
    rt = rel.relation_type

    verdict = "ok"
    problem: str | None = None

    # ── INVÁLIDAS (descartar antes de escribir) ───────────────────────────────
    # Una localización no puede estar "dentro de" un personaje.
    if rt == "LOCATED_IN" and target_type in _SEM_PERSON_LIKE:
        verdict, problem = "invalid", (
            f"LOCATED_IN con target {target_type}: '{rel.source_canonical}' "
            f"({source_type}) LOCATED_IN '{rel.target_canonical}' — un lugar no "
            f"puede estar dentro de un ser"
        )
    # Un objeto/lugar no puede ser cónyuge de un personaje.
    elif rt == "SPOUSE_OF" and source_type in ({"Object", "Artifact"} | _SEM_PLACE_LIKE):
        verdict, problem = "invalid", (
            f"SPOUSE_OF con source {source_type}: '{rel.source_canonical}' no puede "
            f"ser cónyuge de '{rel.target_canonical}'"
        )
    # Un lugar no combate en otro lugar (source de combate debe ser un ser).
    elif rt in ("FOUGHT_AT", "ATTACKED") and source_type in _SEM_PLACE_LIKE:
        verdict, problem = "invalid", (
            f"{rt} con source {source_type}: '{rel.source_canonical}' — un lugar no "
            f"combate/ataca"
        )

    # ── DUDOSAS (escribir con manual_review_required) ─────────────────────────
    if verdict == "ok":
        # Character FOUGHT_AT Character → dudoso (debería ser lugar)
        if rt in _SEM_PLACE_TARGET_RELS and target_type in _SEM_PERSON_LIKE:
            verdict, problem = "dubious", (
                f"{rt} con target {target_type}: '{rel.source_canonical}' {rt} "
                f"'{rel.target_canonical}' — se esperaba un lugar como destino"
            )
        # ATTACKED/HELPED/TALKED_TO con target lugar → dudoso
        elif rt in ("ATTACKED", "HELPED", "TALKED_TO", "SPOUSE_OF", "FRIEND_OF",
                    "ALLY_OF", "RIVAL_OF", "MENTOR_OF", "STUDENT_OF") \
                and target_type in _SEM_PLACE_LIKE:
            verdict, problem = "dubious", (
                f"{rt} con target {target_type}: '{rel.source_canonical}' {rt} "
                f"'{rel.target_canonical}' — se esperaba un ser/grupo como destino"
            )
        # LOCATED_IN Character→Character (heredado): dudoso
        elif rt == "LOCATED_IN" and source_type == "Character" and target_type == "Character":
            verdict, problem = "dubious", (
                f"LOCATED_IN Character→Character: '{rel.source_canonical}' → "
                f"'{rel.target_canonical}' — usar MEETS/KNOWS"
            )

    if problem:
        _write_semantic_warning(warnings_path, rel, f"[{verdict}] {problem}")
        return verdict, f"[semantic:{verdict}] {problem}"

    return "ok", None


def _write_semantic_warning(warnings_path, rel, reason: str) -> None:
    """Añade una entrada al archivo de revisión semántica."""
    import os
    try:
        path = warnings_path
        os.makedirs(os.path.dirname(str(path)), exist_ok=True)
        entry = (
            f"\n## {rel.source_canonical} {rel.relation_type} {rel.target_canonical}\n\n"
            f"- Motivo: {reason}\n"
            f"- Evidencia: {rel.evidence[:200] if rel.evidence else 'n/a'}\n"
            f"- Fuente: {rel.source_document}\n"
            f"- Páginas: {rel.source_pages}\n"
            f"- Acción sugerida: revisar manualmente\n"
        )
        header_needed = not os.path.exists(str(path))
        with open(str(path), "a", encoding="utf-8") as f:
            if header_needed:
                f.write("# Relaciones para revisar\n\n")
            f.write(entry)
    except Exception as e:
        log.warning("No se pudo escribir semantic warning: %s", e)


# ── Neo4j writer ──────────────────────────────────────────────────────────────
class Neo4jWriter:
    LABEL_MAP = {
        # Personajes y seres
        "Character": "Character",
        "Creature": "Creature",
        "NonHuman": "NonHuman",
        "Spirit": "Spirit",
        "Demon": "Demon",
        "Beast": "Beast",
        # Lugares
        "Location": "Location",
        "Region": "Region",
        # Grupos y organizaciones
        "Faction": "Faction",
        "Clan": "Clan",
        "Family": "Family",
        "School": "School",
        "Group": "Group",
        # Objetos y saber
        "Object": "Object",
        "Artifact": "Artifact",
        "Spell": "Spell",
        "Rule": "Rule",
        "Concept": "Concept",
        # Acontecimientos
        "Event": "Event",
        "Encounter": "Encounter",
        "Combat": "Combat",
        "Task": "Task",
        # Estructura de campaña y fuentes
        "Session": "Session",
        "Document": "Document",
        "Chapter": "Chapter",
        "Transcript": "Transcript",
        "Image": "Image",
    }

    def __init__(self, config: dict):
        try:
            from neo4j import GraphDatabase
        except ImportError:
            log.error("Driver neo4j no disponible")
            sys.exit(EXIT_NEO4J_ERROR)

        neo4j_cfg = config["neo4j"]
        password = read_password(neo4j_cfg["password_file"])
        self.driver = GraphDatabase.driver(
            neo4j_cfg["uri"],
            auth=(neo4j_cfg["username"], password),
        )
        self.driver.verify_connectivity()
        log.info("Neo4j conectado")
        self._doc_ctx: dict = {}

    def set_doc_context(self, *, source_id: str, source_kind: str,
                        source_document: str, source_path: str,
                        source_hash: str, workspace: str,
                        extractor_version: str = "ingest_rpg",
                        prompt_version: str = "1.3.0",
                        knowledge_layer: str = "",
                        visibility: str = "",
                        source_url: str = "",
                        source_title: str = "",
                        source_author: str = "",
                        source_date: str = "",
                        session_number: Optional[int] = None,
                        session_title: str = "",
                        session_date: str = "",
                        campaign_arc: str = "") -> None:
        """Guarda contexto de documento para adjuntarlo a nodos y relaciones."""
        self._doc_ctx = {
            "source_id": source_id,
            "source_kind": source_kind,
            "source_document": source_document,
            "source_path": source_path,
            "source_hash": source_hash,
            "workspace": workspace,
            "extractor_version": extractor_version,
            "prompt_version": prompt_version,
            # Fase 7: capa de conocimiento y visibilidad por defecto del documento
            "knowledge_layer": knowledge_layer,
            "visibility": visibility,
            # Fase (fuentes externas): trazabilidad de URL/título/autor
            "source_url": source_url,
            "source_title": source_title,
            "source_author": source_author,
            "source_date": source_date,
            # Fase 8: metadatos de sesión
            "session_number": session_number,
            "session_title": session_title,
            "session_date": session_date,
            "campaign_arc": campaign_arc,
        }
        if not source_id:
            log.warning("[doc_ctx] source_id está vacío — relaciones y nodos quedarán sin trazabilidad")
        if not source_kind:
            log.warning("[doc_ctx] source_kind está vacío — nodos y relaciones quedarán sin clasificar")

    # Campos opcionales que el writer sabe persistir (Fase 2/7/8/9/11).
    _OPTIONAL_FIELDS = (
        "subtype", "species", "role",
        "attitude", "status", "danger_level", "is_human", "is_unique",
        "visibility", "knowledge_layer",
        "first_seen_session", "first_seen_date",
        "last_seen_session", "last_seen_date",
        "source_session", "source_date", "chronology_order",
        "session_number", "session_title", "session_date",
        "campaign_arc", "summary",
        "image_path", "thumbnail_path", "media_source",
        "review_status", "manual_review_required",
        "requires_metadata", "created_from_relation",
        # conocimiento por personaje (Fase conocimiento)
        "known_by_scope", "known_by_characters", "known_by_users",
        "known_by_party", "known_publicly", "known_from_session",
        "known_from_date", "knowledge_quality", "knowledge_confidence",
        "shared_from_character", "shared_to_character", "shared_at_session",
    )

    def write_entity(self, entity) -> bool:
        label = self.LABEL_MAP.get(entity.entity_type, "Concept")
        ctx = self._doc_ctx
        params = entity.to_neo4j_params()
        params["updated_at"] = datetime.now(timezone.utc).isoformat()
        params.setdefault("source_id", ctx.get("source_id", ""))
        params.setdefault("source_kind", ctx.get("source_kind", "unknown"))
        params.setdefault("source_path", ctx.get("source_path", ""))
        params.setdefault("source_hash", ctx.get("source_hash", ""))
        params["extractor_version"] = ctx.get("extractor_version", "ingest_rpg")
        params["prompt_version"] = ctx.get("prompt_version", "1.3.0")
        params["source_url"] = ctx.get("source_url", "")
        params["source_title"] = ctx.get("source_title", "")
        params["source_author"] = ctx.get("source_author", "")

        # SET base (siempre presente)
        set_lines = [
            "n.display_name = $display_name",
            "n.aliases = $aliases",
            "n.description = $description",
            "n.entity_type = $entity_type",
            "n.source_document = $source_document",
            "n.source_pages = $source_pages",
            "n.confidence = $confidence",
            "n.source_id = $source_id",
            "n.source_kind = $source_kind",
            "n.source_path = $source_path",
            "n.source_hash = $source_hash",
            "n.extractor_version = $extractor_version",
            "n.prompt_version = $prompt_version",
            "n.source_url = $source_url",
            "n.source_title = $source_title",
            "n.source_author = $source_author",
            "n.updated_at = $updated_at",
        ]
        # SET dinámico: solo campos opcionales presentes (no null-sobrescribir)
        for f in self._OPTIONAL_FIELDS:
            if f in params and params[f] is not None:
                set_lines.append(f"n.{f} = ${f}")

        query = (
            f"MERGE (n:Entity:{label} {{workspace: $workspace, canonical_name: $canonical_name}}) "
            "ON CREATE SET n.created_at = $updated_at "
            "SET " + ", ".join(set_lines) + " "
            "RETURN n.canonical_name AS name"
        )
        if not params["source_id"]:
            log.warning("[write_entity] source_id vacío para nodo '%s'", entity.canonical_name)
        try:
            with self.driver.session() as session:
                session.run(query, **params)
            return True
        except Exception as e:
            log.error("Error escribiendo entidad %s: %s", entity.canonical_name, e)
            return False

    def _ensure_node(self, session, workspace: str, canonical_name: str,
                    source_document: str, source_pages: list) -> bool:
        """Verifica si existe el nodo; si no, lo crea como Concept minimo.
        Retorna True si fue creado, False si ya existia."""
        check_query = (
            "MATCH (n:Entity {workspace: $workspace, canonical_name: $canonical_name}) "
            "RETURN n.canonical_name AS name LIMIT 1"
        )
        result = session.run(check_query, workspace=workspace, canonical_name=canonical_name)
        if result.single():
            return False  # ya existia

        # Crear nodo minimo
        ctx = self._doc_ctx
        create_query = (
            "MERGE (n:Entity:Concept {workspace: $workspace, canonical_name: $canonical_name}) "
            "ON CREATE SET n.created_at = $updated_at "
            "SET n.display_name = $canonical_name, "
            "    n.aliases = [], "
            "    n.description = '', "
            "    n.entity_type = 'Concept', "
            "    n.source_document = $source_document, "
            "    n.source_pages = $source_pages, "
            "    n.confidence = 0.5, "
            "    n.created_from_relation = true, "
            "    n.review_status = 'auto_extracted', "
            "    n.manual_review_required = true, "
            "    n.source_id = $source_id, "
            "    n.source_kind = $source_kind, "
            "    n.source_path = $source_path, "
            "    n.source_hash = $source_hash, "
            "    n.knowledge_layer = $knowledge_layer, "
            "    n.visibility = $visibility, "
            "    n.extractor_version = $extractor_version, "
            "    n.prompt_version = $prompt_version, "
            "    n.updated_at = $updated_at "
            "RETURN n.canonical_name AS name"
        )
        session.run(create_query,
                    workspace=workspace,
                    canonical_name=canonical_name,
                    source_document=source_document,
                    source_pages=source_pages,
                    source_id=ctx.get("source_id", ""),
                    source_kind=ctx.get("source_kind", "unknown"),
                    source_path=ctx.get("source_path", ""),
                    source_hash=ctx.get("source_hash", ""),
                    knowledge_layer=ctx.get("knowledge_layer", "") or "inferred",
                    visibility=ctx.get("visibility", "") or "narrator",
                    extractor_version=ctx.get("extractor_version", "ingest_rpg"),
                    prompt_version=ctx.get("prompt_version", "1.3.0"),
                    updated_at=datetime.now(timezone.utc).isoformat())
        log.info("  Nodo destino creado automaticamente: %s (Concept, created_from_relation=True, review=needs)",
                 canonical_name)
        return True  # fue creado

    def write_relationship(self, rel, workspace: str,
                           manual_review_required: bool = False) -> tuple:
        """Escribe relacion en Neo4j.
        Retorna (rel_written: bool, target_created: bool).
        Si el nodo destino no existe, lo crea automaticamente como Concept.
        Si manual_review_required=True (relación semánticamente dudosa), se marca
        review_status='needs_review' y manual_review_required=true en la relación.
        """
        rel_type = rel.relation_type
        params = rel.to_neo4j_params()
        params["workspace"] = workspace
        params["updated_at"] = datetime.now(timezone.utc).isoformat()
        params["manual_review_required"] = bool(manual_review_required)
        params["review_status"] = "needs_review" if manual_review_required else "auto_extracted"

        try:
            with self.driver.session() as session:
                # Asegurar que el nodo destino existe (crearlo si no)
                target_created = self._ensure_node(
                    session, workspace,
                    rel.target_canonical,
                    rel.source_document,
                    rel.source_pages,
                )
                # Escribir la relacion
                ctx = self._doc_ctx
                params["source_id"] = ctx.get("source_id", "")
                params["source_kind"] = ctx.get("source_kind", "unknown")
                params["source_path"] = ctx.get("source_path", "")
                params["source_hash"] = ctx.get("source_hash", "")
                params["extractor_version"] = ctx.get("extractor_version", "ingest_rpg")
                params["prompt_version"] = ctx.get("prompt_version", "1.3.0")
                params["knowledge_layer"] = ctx.get("knowledge_layer", "") or "inferred"
                params["visibility"] = ctx.get("visibility", "") or "narrator"

                rel_set_lines = [
                    "r.evidence = $evidence",
                    "r.source_document = $source_document",
                    "r.source_pages = $source_pages",
                    "r.confidence = $confidence",
                    "r.relation_label_es = $relation_label_es",
                    "r.workspace = $workspace",
                    "r.source_id = $source_id",
                    "r.source_kind = $source_kind",
                    "r.source_path = $source_path",
                    "r.source_hash = $source_hash",
                    "r.extractor_version = $extractor_version",
                    "r.prompt_version = $prompt_version",
                    "r.knowledge_layer = $knowledge_layer",
                    "r.visibility = $visibility",
                    "r.review_status = $review_status",
                    "r.manual_review_required = $manual_review_required",
                    "r.updated_at = $updated_at",
                ]
                # SET dinámico: campos opcionales de conocimiento presentes en la relación
                for f in ("known_by_scope", "knowledge_quality", "known_from_session",
                          "known_from_date", "shared_from_character",
                          "shared_to_character", "shared_at_session"):
                    if f in params and params[f] is not None:
                        rel_set_lines.append(f"r.{f} = ${f}")

                query = (
                    "MATCH (a:Entity {workspace: $workspace, canonical_name: $source_canonical}) "
                    "MATCH (b:Entity {workspace: $workspace, canonical_name: $target_canonical}) "
                    f"MERGE (a)-[r:{rel_type}]->(b) "
                    "ON CREATE SET r.created_at = $updated_at "
                    "SET " + ", ".join(rel_set_lines) + " "
                    "RETURN type(r) AS rel_type"
                )
                if not params["source_id"]:
                    log.warning("[write_relationship] source_id vacío para relación %s->%s",
                                rel.source_canonical, rel.target_canonical)
                result = session.run(query, **params)
                record = result.single()
                if record is None:
                    log.warning("  Relacion no creada (nodo origen ausente?): %s->%s",
                                rel.source_canonical, rel.target_canonical)
                    return False, target_created
            return True, target_created
        except Exception as e:
            log.warning("Error escribiendo relacion %s->%s: %s",
                        rel.source_canonical, rel.target_canonical, e)
            return False, False

    def query_entities(self, workspace: str, limit: int = 25) -> list:
        query = (
            "MATCH (n {workspace: $workspace}) "
            "RETURN labels(n) AS labels, n.canonical_name AS name, "
            "       n.source_pages AS pages "
            "LIMIT $limit"
        )
        with self.driver.session() as session:
            result = session.run(query, workspace=workspace, limit=limit)
            return [dict(r) for r in result]

    def close(self):
        self.driver.close()


# ── State management ──────────────────────────────────────────────────────────
def safe_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]', '_', name)[:100]


# ── Detección de imágenes locales (Fase 9) ────────────────────────────────────
import unicodedata as _unicodedata

_MEDIA_CATEGORY_BY_TYPE = {
    "Character": "personajes", "NonHuman": "personajes",
    "Creature": "criaturas", "Spirit": "criaturas",
    "Demon": "criaturas", "Beast": "criaturas",
    "Location": "lugares", "Region": "lugares",
    "Object": "objetos", "Artifact": "objetos",
}
_MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _media_slug(name: str) -> str:
    """Convierte 'Oni de la Montaña Negra' → 'oni_de_la_montana_negra'."""
    s = "".join(c for c in _unicodedata.normalize("NFD", name)
                if _unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def detect_image_for_entity(entity, workspace: str,
                            media_base: str = NEXTCLOUD_BASE) -> Optional[str]:
    """Busca una imagen local asociada a la entidad por convención de nombre.

    Ruta: <media_base>/<workspace>/_media/<categoria>/<slug>.<ext>
    NO busca en internet, NO genera imágenes. Devuelve la ruta si existe, o None.
    Mantiene Nextcloud en solo lectura (solo comprueba existencia).
    """
    category = _MEDIA_CATEGORY_BY_TYPE.get(getattr(entity, "entity_type", ""), None)
    if not category:
        return None
    slug = _media_slug(entity.canonical_name)
    if not slug:
        return None
    media_dir = Path(media_base) / workspace / "_media" / category
    if not media_dir.is_dir():
        return None
    for ext in _MEDIA_EXTENSIONS:
        candidate = media_dir / f"{slug}{ext}"
        if candidate.exists():
            return str(candidate)
    return None


def load_state(state_dir: str, workspace: str, pdf_name: str) -> dict:
    state_file = Path(state_dir) / f"{workspace}_{safe_name(pdf_name)}.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state_dir: str, workspace: str, pdf_name: str, data: dict):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    state_file = Path(state_dir) / f"{workspace}_{safe_name(pdf_name)}.json"
    with open(state_file, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_chunk_state(state_dir: str, workspace: str, pdf_name: str,
                     chunk_idx: int, page_start: int, page_end: int,
                     status: str, n_entities: int, n_rels: int,
                     error: str = "", model: str = "",
                     prompt_version: str = "1.0.0",
                     schema_version: str = "1.0.0",
                     relations_normalized: int = 0,
                     unmapped_relation_types: list | None = None,
                     entity_refs_resolved: int = 0,
                     entity_refs_unresolved: int = 0,
                     entity_refs_ambiguous: int = 0,
                     collective_entities_created: int = 0,
                     relations_skipped_unresolved_source: int = 0) -> None:
    """Guarda estado por chunk de forma incremental."""
    chunk_dir = Path(state_dir) / f"{workspace}_{safe_name(pdf_name)}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_file = chunk_dir / f"chunk_{chunk_idx:04d}.json"
    with open(chunk_file, "w") as f:
        json.dump({
            "pdf": pdf_name,
            "workspace": workspace,
            "chunk_index": chunk_idx,
            "page_start": page_start,
            "page_end": page_end,
            "model": model,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "status": status,
            "entities": n_entities,
            "relationships": n_rels,
            "relations_normalized": relations_normalized,
            "unmapped_relation_types": unmapped_relation_types or [],
            "entity_refs_resolved": entity_refs_resolved,
            "entity_refs_unresolved": entity_refs_unresolved,
            "entity_refs_ambiguous": entity_refs_ambiguous,
            "collective_entities_created": collective_entities_created,
            "relations_skipped_unresolved_source": relations_skipped_unresolved_source,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)


# ── Markdown export ───────────────────────────────────────────────────────────
def export_to_markdown(entities, relationships, workspace: str,
                       source_document: str, spaces_dir: str):
    base = Path(spaces_dir) / "Grafo"
    base.mkdir(parents=True, exist_ok=True)

    type_map = {
        "Character": "Personajes",
        "NonHuman": "Personajes",
        "Location": "Lugares",
        "Region": "Lugares",
        "Faction": "Facciones",
        "Clan": "Facciones",
        "Family": "Facciones",
        "School": "Facciones",
        "Group": "Facciones",
        "Rule": "Reglas",
        "Event": "Eventos",
        "Encounter": "Eventos",
        "Combat": "Eventos",
        "Creature": "Criaturas",
        "Spirit": "Criaturas",
        "Demon": "Criaturas",
        "Beast": "Criaturas",
        "Object": "Objetos",
        "Artifact": "Objetos",
        "Spell": "Magia",
        "Concept": "Conceptos",
        "Chapter": "Documentos",
        "Document": "Documentos",
        "Transcript": "Documentos",
        "Image": "Documentos",
        "Session": "Sesiones",
        "Task": "Tareas",
    }

    rel_map = {}
    for r in relationships:
        rel_map.setdefault(r.source_canonical, []).append(r)

    for entity in entities:
        folder_name = type_map.get(entity.entity_type, "Varios")
        entity_dir = Path(spaces_dir) / folder_name
        entity_dir.mkdir(parents=True, exist_ok=True)

        note_path = entity_dir / f"{safe_name(entity.canonical_name)}.md"
        if note_path.exists():
            content = note_path.read_text()
            if "manual: true" in content or "generated_by" not in content:
                pending = base / "Pendientes"
                pending.mkdir(parents=True, exist_ok=True)
                proposal = pending / f"{safe_name(entity.canonical_name)}.md"
                log.info("Conflicto: %s ya existe como nota manual -> %s", entity.canonical_name, proposal)
                note_path = proposal

        rels_text = ""
        for r in rel_map.get(entity.canonical_name, []):
            label = getattr(r, "relation_label_es", "") or r.relation_type.lower().replace("_", " ")
            ev_short = r.evidence[:100] if r.evidence else ""
            rels_text += f"- [[{entity.canonical_name}]] {label} [[{r.target_canonical}]]"
            if ev_short:
                rels_text += f" <!-- {r.relation_type} --> _{ev_short}_"
            rels_text += "\n"

        note_content = f"""---
generated_by: llamaindex-property-graph
workspace: {workspace}
entity_type: {entity.entity_type}
source_documents:
  - {source_document}
source_pages: {entity.source_pages}
confidence: {entity.confidence}
---

# {entity.display_name}

{entity.description}

{"**Aliases:** " + ", ".join(entity.aliases) if entity.aliases else ""}

## Relaciones

{rels_text if rels_text else "_Sin relaciones registradas_"}
"""
        note_path.write_text(note_content)
        log.info("Nota creada: %s", note_path)


# ── Profile management ────────────────────────────────────────────────────────
def apply_profile(args, config: dict) -> dict:
    """Aplica el perfil seleccionado al config efectivo."""
    profiles = config.get("profiles", {})
    profile = profiles.get(getattr(args, 'profile', 'short'), {})
    effective = dict(config)
    processing = dict(config.get("processing", {}))
    for key in ("chunk_pages", "chunk_chars", "overlap_chars", "request_timeout"):
        if key in profile:
            processing[key] = profile[key]
    effective["processing"] = processing
    effective["_profile"] = profile
    if profile.get("export_markdown") and not getattr(args, 'export_markdown', False):
        args.export_markdown = True
    if profile.get("export_json") and not getattr(args, 'export_json', False):
        args.export_json = True
    if getattr(args, 'chunk_pages', None):
        effective["processing"]["chunk_pages"] = args.chunk_pages
    if getattr(args, 'chunk_chars', None):
        effective["processing"]["chunk_chars"] = args.chunk_chars
    return effective


# ── Image handler ─────────────────────────────────────────────────────────────
def handle_image_file(path: Path, config: dict, args) -> int:
    """Marca imagen como requires_ocr y guarda estado. Retorna EXIT_REQUIRES_OCR."""
    import shutil as _shutil
    has_tesseract = _shutil.which("tesseract") is not None
    state_dir = config.get("state", {}).get("base_dir",
        "/opt/knowledge-services/property-graph/state")
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    state_file = Path(state_dir) / f"{args.workspace}_{safe_name(path.name)}.json"
    status_data = {
        "path": str(path), "workspace": args.workspace,
        "type": "image", "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "status": "requires_ocr",
        "ocr_available": has_tesseract,
        "tesseract": has_tesseract,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "note": "Instala tesseract-ocr para procesar imágenes." if not has_tesseract
                else "OCR disponible pero no implementado todavía.",
    }
    with open(state_file, "w") as f:
        json.dump(status_data, f, indent=2)
    log.warning("Imagen marcada como requires_ocr: %s (tesseract=%s)", path.name, has_tesseract)
    return EXIT_REQUIRES_OCR


# ── Pydantic validation helpers (Opción B) ────────────────────────────────────
def validate_extraction_result_partial(
    raw: dict,
    chunk_idx: int,
    workspace: str,
    pages: list | None = None,
) -> tuple:
    """
    Valida entidades y relaciones individualmente (Opción B).
    Aplica normalización de tipos de relación antes de validar.
    Descarta las que fallen sin abortar el chunk.
    Retorna (valid_entities, valid_rels, warnings, stats).
    stats = {relations_normalized, unmapped_relation_types}
    """
    from schemas.rpg_schema import (
        EntityBase, RelationshipBase, normalize_relation_type_full,
        add_auto_aliases, COLLECTIVE_ENTITY_REFS, make_collective_entity,
    )

    pages = pages or []
    valid_entities = []
    valid_rels = []
    warnings = list(raw.get("warnings", []))
    stats = {
        "relations_normalized": 0,
        "relations_dropped_unmappable": 0,
        "relations_dropped_invalid_after_normalization": 0,
        "unmapped_relation_types": [],
        "entity_refs_resolved": 0,
        "entity_refs_unresolved": 0,
        "entity_refs_ambiguous": 0,
        "collective_entities_created": 0,
        "relations_skipped_unresolved_source": 0,
        "relations_skipped_unresolved_target": 0,
    }

    # Validar entidades una a una
    has_collective = False
    for i, e_data in enumerate(raw.get("entities", [])):
        e_data.setdefault("workspace", workspace)
        try:
            entity = EntityBase(**e_data)
            # Cambio 2: alias automático para Characters multi-palabra
            entity = add_auto_aliases(entity)
            valid_entities.append(entity)
        except Exception as exc:
            msg = f"Chunk {chunk_idx+1}: entidad[{i}] descartada ({exc})"
            log.warning("  %s", msg)
            warnings.append(msg)

    # Validar relaciones una a una, con normalización previa
    for i, r_data in enumerate(raw.get("relationships", [])):
        raw_type = r_data.get("relation_type", "")

        # Intentar normalización completa con contexto antes de pasar a Pydantic
        normalized_type, norm_warn = normalize_relation_type_full(
            raw_relation_type=raw_type,
            source=r_data.get("source_canonical", ""),
            target=r_data.get("target_canonical", ""),
            evidence=r_data.get("evidence", ""),
            chunk_id=chunk_idx + 1,
            pages=pages,
        )

        if normalized_type is None:
            # No mapeado: descartar
            stats["relations_dropped_unmappable"] += 1
            stats["unmapped_relation_types"].append(raw_type)
            msg = (
                f"Chunk {chunk_idx+1}: relación[{i}] DESCARTADA (no mapeada): "
                f"tipo='{raw_type}' src='{r_data.get('source_canonical','')}' "
                f"tgt='{r_data.get('target_canonical','')}'"
            )
            log.warning("  %s", msg)
            warnings.append(msg)
            if norm_warn:
                warnings.append(norm_warn)
            continue

        # Sustituir el tipo con el normalizado
        was_normalized = (normalized_type != raw_type)
        r_data_copy = dict(r_data)
        r_data_copy["relation_type"] = normalized_type

        try:
            rel = RelationshipBase(**r_data_copy)
            valid_rels.append(rel)
            if was_normalized:
                stats["relations_normalized"] += 1
                log.info(
                    "  [normalizer] relación[%d] '%s' → '%s' (%s → %s)",
                    i, raw_type, normalized_type,
                    r_data.get("source_canonical", "?"),
                    r_data.get("target_canonical", "?"),
                )
                if norm_warn:
                    warnings.append(norm_warn)
        except Exception as exc:
            stats["relations_dropped_invalid_after_normalization"] += 1
            msg = (
                f"Chunk {chunk_idx+1}: relación[{i}] descartada tras normalizar "
                f"(tipo='{normalized_type}', original='{raw_type}'): {exc}"
            )
            log.warning("  %s", msg)
            warnings.append(msg)

    return valid_entities, valid_rels, warnings, stats


# ── Main ──────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Ingesta de PDFs/texto/imágenes RPG en Property Graph")
    p.add_argument("--workspace", required=True)

    input_group = p.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--pdf", metavar="PATH")
    input_group.add_argument("--text", metavar="PATH")
    input_group.add_argument("--image", metavar="PATH")

    p.add_argument("--pages", help="Rango de páginas, ej: 1-20")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--keep-staging", action="store_true")
    p.add_argument("--model")
    p.add_argument("--no-neo4j", action="store_true")
    p.add_argument("--export-json", action="store_true")
    p.add_argument("--export-markdown", action="store_true")
    p.add_argument("--profile", choices=["short", "transcript", "book", "image-text"],
                   default="short")
    p.add_argument("--chunk-pages", type=int, default=None,
                   help="Páginas por chunk (override del config)")
    p.add_argument("--chunk-chars", type=int, default=None,
                   help="Caracteres por chunk para --text (override del config)")
    p.add_argument("--config",
                   default="/opt/knowledge-services/property-graph/config/settings.yaml")
    p.add_argument(
        "--source-id",
        default=None,
        help="Identificador estable del documento (ej: l5a_game_masters_guide_2da). "
             "Si no se provee, se deriva del nombre del archivo.",
    )
    p.add_argument(
        "--source-kind",
        default=None,
        choices=["book", "pdf", "audio", "transcript", "text", "image",
                 "youtube", "web", "manual_note", "reference", "test", "unknown"],
        help="Tipo de fuente. Por defecto se infiere del perfil activo.",
    )
    # ── Fase 7: capa de conocimiento y visibilidad ────────────────────────────
    p.add_argument("--knowledge-layer", default=None,
                   choices=["campaign", "book", "transcript", "manual",
                            "inferred", "reviewed", "test"],
                   help="Capa de conocimiento. Por defecto se infiere de source_kind.")
    p.add_argument("--visibility", default=None,
                   choices=["player", "narrator", "secret", "reference"],
                   help="Visibilidad por defecto de las entidades. Por defecto según source_kind.")
    # ── Fase 8: metadatos de sesión ───────────────────────────────────────────
    p.add_argument("--session-number", type=int, default=None,
                   help="Número de sesión (crea nodo Session y sella entidades).")
    p.add_argument("--session-title", default=None, help="Título de la sesión.")
    p.add_argument("--session-date", default=None, help="Fecha de la sesión (YYYY-MM-DD).")
    p.add_argument("--campaign-arc", default=None, help="Arco de campaña.")
    # ── Fuentes externas: trazabilidad de URL/título/autor ────────────────────
    p.add_argument("--source-url", default=None, help="URL original (youtube/web).")
    p.add_argument("--source-title", default=None, help="Título de la fuente.")
    p.add_argument("--source-author", default=None, help="Autor/canal de la fuente.")
    return p.parse_args()


def main():
    args = parse_args()

    config = load_config(args.config)

    # Aplicar perfil (modifica config efectivo y potencialmente args.export_*)
    config = apply_profile(args, config)

    state_dir = config.get("state", {}).get("base_dir",
        "/opt/knowledge-services/property-graph/state")
    staging_dir = config.get("staging", {}).get("base_dir",
        "/opt/knowledge-services/property-graph/staging")
    lock_file = config.get("staging", {}).get("lock_file",
        "/tmp/property-graph-process.lock")
    output_dir = config.get("output", {}).get("base_dir",
        "/opt/knowledge-services/property-graph/output")
    spaces = config.get("spaces", {})
    chunk_size = config.get("processing", {}).get("chunk_size", 3000)
    chunk_overlap = config.get("processing", {}).get("chunk_overlap", 300)
    PAGE_CHUNK = args.chunk_pages or config.get("processing", {}).get("chunk_pages", 3)

    allowed_workspaces = config.get("workspaces", [])
    if args.workspace not in allowed_workspaces:
        log.error("Workspace '%s' no permitido. Permitidos: %s", args.workspace, allowed_workspaces)
        sys.exit(EXIT_PDF_READ_ERROR)

    # ── Detectar tipo de input ────────────────────────────────────────────────
    if args.image:
        return handle_image_file(Path(args.image), config, args)

    if args.text:
        input_path = Path(args.text)
        if not input_path.exists():
            log.error("Archivo no encontrado: %s", args.text)
            sys.exit(EXIT_PDF_READ_ERROR)
        input_type = "text"
        doc_name = input_path.name
        pdf_hash = sha256_file(input_path)

        # Chunking por caracteres
        raw_text = input_path.read_text(encoding="utf-8", errors="replace")
        CHAR_CHUNK = config.get("processing", {}).get("chunk_chars", 6000)
        OVERLAP = config.get("processing", {}).get("overlap_chars", 500)
        chunks = []
        start = 0
        idx = 0
        while start < len(raw_text):
            end = min(start + CHAR_CHUNK, len(raw_text))
            text = raw_text[start:end]
            if text.strip():
                chunks.append({"text": text, "page_start": idx + 1, "page_end": idx + 1})
            idx += 1
            if end >= len(raw_text):
                break
            start = end - OVERLAP
        num_pages = len(chunks)
        staging_pdf = None
        log.info("Texto '%s': %d chunks (chunk_chars=%d)", doc_name, num_pages, CHAR_CHUNK)
    else:
        # ── Flujo PDF (existente) ─────────────────────────────────────────────
        input_type = "pdf"
        pdf_path = validate_pdf_path(args.pdf)
        doc_name = pdf_path.name
        pdf_hash = sha256_file(pdf_path)
        staging_pdf = None  # se asigna más abajo

    # ── Lock ─────────────────────────────────────────────────────────────────
    lock_fd = open(lock_file, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Otra instancia en ejecución (lock: %s)", lock_file)
        sys.exit(EXIT_LOCKED)

    state = load_state(state_dir, args.workspace, doc_name)
    if not args.force and state.get("sha256") == pdf_hash and state.get("status") == "ok":
        log.info("Sin cambios en %s (hash idéntico, estado ok). Usa --force para reprocesar.", doc_name)
        sys.exit(EXIT_OK)

    try:
        if input_type == "pdf":
            page_range = None
            if args.pages:
                m = re.match(r"(\d+)-(\d+)", args.pages)
                if m:
                    page_range = (int(m.group(1)), int(m.group(2)))

            size_bytes = pdf_path.stat().st_size
            size_mb = size_bytes // (1024 * 1024)
            stat = os.statvfs(staging_dir if Path(staging_dir).exists() else "/opt")
            avail_bytes = stat.f_bavail * stat.f_frsize
            if avail_bytes < size_bytes * 3:
                log.error("Espacio insuficiente: disponible=%dMB, necesario=%dMB",
                          avail_bytes // (1024 * 1024), size_mb * 3)
                sys.exit(EXIT_NO_SPACE)

            Path(staging_dir).mkdir(parents=True, exist_ok=True)
            import shutil
            staging_pdf = Path(staging_dir) / safe_name(doc_name)
            try:
                shutil.copy2(str(pdf_path), str(staging_pdf))
            except OSError:
                shutil.copy(str(pdf_path), str(staging_pdf))
            log.info("PDF copiado a staging: %s (%d MB)", staging_pdf, size_mb)

            num_pages = get_page_count(staging_pdf)
            log.info("Páginas totales: %d", num_pages)

            pages = extract_text_by_page(staging_pdf, page_range)
            empty_pages = [p for p, t in pages.items() if not t.strip()]
            if empty_pages:
                log.warning("Páginas sin texto: %s", empty_pages[:10])
            text_pages = {p: t for p, t in pages.items() if t.strip()}
            if not text_pages:
                log.error("Ninguna página con texto extraíble")
                save_state(state_dir, args.workspace, doc_name, {
                    "sha256": pdf_hash, "status": "no_text",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
                sys.exit(EXIT_NO_TEXT_PAGES)

            log.info("Páginas con texto: %d/%d", len(text_pages), len(pages))
            chunks = chunk_pages(text_pages, PAGE_CHUNK, 1)
            log.info("Chunks generados: %d (chunk_pages=%d)", len(chunks), PAGE_CHUNK)

        extractor = OllamaExtractor(config, args.model, profile=getattr(args, 'profile', 'short'))

        writer = None
        if not args.no_neo4j and not args.dry_run:
            try:
                writer = Neo4jWriter(config)
            except SystemExit:
                raise
            except Exception as e:
                log.error("No se puede conectar a Neo4j: %s", e)
                save_state(state_dir, args.workspace, doc_name, {
                    "sha256": pdf_hash, "status": "neo4j_error",
                    "error": str(e),
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
                sys.exit(EXIT_NEO4J_ERROR)

        # ── Derivar source_id y source_kind ────────────────────────────────────
        if args.source_id:
            _source_id = args.source_id
        else:
            _base = re.sub(r'^[0-9]+\s+', '', doc_name)  # quitar prefijo numérico
            _base = re.sub(r'\.[^.]+$', '', _base)        # quitar extensión
            _source_id = re.sub(r'[^a-z0-9]+', '_', _base.lower()).strip('_')
            log.warning("[doc_ctx] source_id no especificado, usando derivado: '%s' — "
                        "pasa --source-id para valor exacto", _source_id)

        # Derivar source_kind del perfil o del argumento
        _profile_kind_map = {
            "book": "book",
            "transcript": "transcript",
            "short": "transcript",
            "image-text": "book",
        }
        _active_profile = getattr(args, 'profile', None) or ""
        if args.source_kind:
            _source_kind = args.source_kind
        else:
            _source_kind = _profile_kind_map.get(_active_profile, "unknown")
            if _source_kind == "unknown":
                log.warning("[doc_ctx] source_kind no determinado (perfil='%s') — usa --source-kind",
                            _active_profile)

        _source_path = str(args.pdf) if hasattr(args, 'pdf') and args.pdf else \
                       str(args.text) if hasattr(args, 'text') and args.text else ""

        # ── Fase 7: derivar knowledge_layer y visibility por defecto ───────────
        # Reglas: libro/manual → book + reference; transcripción/audio/youtube/web
        # → campaña con visibilidad narrator; test → test + narrator.
        _KL_MAP = {
            "book": ("book", "reference"),
            "reference": ("book", "reference"),
            "pdf": ("book", "reference"),
            "image": ("book", "reference"),
            "transcript": ("transcript", "narrator"),
            "audio": ("transcript", "narrator"),
            "youtube": ("transcript", "narrator"),
            "web": ("book", "reference"),
            "text": ("transcript", "narrator"),
            "manual_note": ("manual", "narrator"),
            "test": ("test", "narrator"),
        }
        if getattr(args, "knowledge_layer", None):
            _knowledge_layer = args.knowledge_layer
            _visibility = getattr(args, "visibility", None) or "narrator"
        else:
            _knowledge_layer, _default_vis = _KL_MAP.get(_source_kind, ("inferred", "narrator"))
            _visibility = getattr(args, "visibility", None) or _default_vis

        # ── Fase 8: metadatos de sesión (CLI) ──────────────────────────────────
        _session_number = getattr(args, "session_number", None)
        _session_title = getattr(args, "session_title", None) or ""
        _session_date = getattr(args, "session_date", None) or ""
        _campaign_arc = getattr(args, "campaign_arc", None) or ""
        _source_date = _session_date  # por ahora la fecha de sesión es la fecha fuente

        if writer:
            writer.set_doc_context(
                source_id=_source_id,
                source_kind=_source_kind,
                source_document=doc_name,
                source_path=_source_path,
                source_hash=pdf_hash,
                workspace=args.workspace,
                extractor_version="ingest_rpg",
                prompt_version="1.3.0",
                knowledge_layer=_knowledge_layer,
                visibility=_visibility,
                source_url=getattr(args, "source_url", None) or "",
                source_title=getattr(args, "source_title", None) or "",
                source_author=getattr(args, "source_author", None) or "",
                source_date=_source_date,
                session_number=_session_number,
                session_title=_session_title,
                session_date=_session_date,
                campaign_arc=_campaign_arc,
            )

        # ── Fase 8: crear nodo Session si se han dado metadatos de sesión ───────
        _session_canon = None
        if writer and _session_number is not None:
            try:
                from schemas.rpg_schema import EntityBase as _EB
                _session_canon = _session_title or f"Sesión {_session_number}"
                _sess_entity = _EB(
                    canonical_name=_session_canon,
                    display_name=_session_canon,
                    entity_type="Session",
                    workspace=args.workspace,
                    description=_session_title or f"Sesión {_session_number}",
                    source_document=doc_name,
                    confidence=1.0,
                    session_number=_session_number,
                    session_title=_session_title or None,
                    session_date=_session_date or None,
                    campaign_arc=_campaign_arc or None,
                    knowledge_layer=_knowledge_layer,
                    visibility=_visibility,
                    review_status="auto_extracted",
                )
                writer.write_entity(_sess_entity)
                log.info("[session] Nodo Session creado: '%s' (nº %s)",
                         _session_canon, _session_number)
            except Exception as _exc:
                log.warning("[session] no se pudo crear nodo Session: %s", _exc)
                _session_canon = None

        all_entities = []
        all_relationships = []
        all_warnings = []
        chunk_statuses = []
        # Acumuladores para auditoría ampliada (Fase 13)
        audit = {
            "nodes_created_or_updated": 0,
            "auto_created_nodes": 0,
            "relationships_written": 0,
            "relations_normalized": 0,
            "relations_dropped_unmappable": 0,
            "relations_dropped_invalid_semantic": 0,
            "manual_review_required": 0,
            "semantic_warnings": 0,
        }
        semantic_warnings_path = Path(output_dir) / "review" / "semantic_warnings.md"

        for idx, chunk in enumerate(chunks):
            log.info("Procesando chunk %d/%d (páginas %d-%d)...",
                     idx + 1, len(chunks), chunk["page_start"], chunk["page_end"])
            chunk_status = "empty"
            chunk_entities = []
            chunk_rels = []
            chunk_error = ""
            chunk_stats = {
                "relations_normalized": 0,
                "relations_dropped_unmappable": 0,
                "relations_dropped_invalid_after_normalization": 0,
                "unmapped_relation_types": [],
                "entity_refs_resolved": 0,
                "entity_refs_unresolved": 0,
                "entity_refs_ambiguous": 0,
                "collective_entities_created": 0,
                "relations_skipped_unresolved_source": 0,
                "relations_skipped_unresolved_target": 0,
            }

            if args.dry_run:
                log.info("  [dry-run] omitiendo llamada al modelo")
                chunk_status = "dry_run"
            else:
                raw = extractor.extract(
                    text=chunk["text"],
                    workspace=args.workspace,
                    source_document=doc_name,
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                )

                if not raw:
                    log.warning("  Chunk %d: respuesta vacía, reintentando...", idx + 1)
                    raw = extractor.extract(
                        text=chunk["text"],
                        workspace=args.workspace,
                        source_document=doc_name,
                        page_start=chunk["page_start"],
                        page_end=chunk["page_end"],
                    )

                if not raw:
                    chunk_error = "Respuesta vacía tras reintento"
                    chunk_status = "model_error"
                    all_warnings.append(f"Chunk {idx+1} (pp.{chunk['page_start']}-{chunk['page_end']}): {chunk_error}")
                else:
                    try:
                        # ── Validación individual con normalización ───────────
                        chunk_entities, chunk_rels, partial_warnings, chunk_stats = \
                            validate_extraction_result_partial(
                                raw, idx, args.workspace,
                                pages=[chunk["page_start"], chunk["page_end"]],
                            )
                        all_warnings.extend(partial_warnings)

                        # chunk = success si hay entidades válidas, aunque fallen relaciones
                        if chunk_entities:
                            chunk_status = "success"
                        elif chunk_rels:
                            chunk_status = "success"
                        else:
                            chunk_status = "empty"

                        log.info(
                            "  -> %d entidades, %d relaciones "
                            "(%d normalizadas, %d descartadas sin mapeo)",
                            len(chunk_entities), len(chunk_rels),
                            chunk_stats["relations_normalized"],
                            chunk_stats["relations_dropped_unmappable"],
                        )

                        # ── Segunda pasada: Events y relaciones (solo transcript) ──
                        if getattr(extractor, "profile", "") == "transcript":
                            entity_names = [e.canonical_name for e in chunk_entities]
                            raw2 = extractor.extract_events_and_relations(
                                text=chunk["text"],
                                entity_names=entity_names,
                                workspace=args.workspace,
                                source_document=doc_name,
                                page_start=chunk["page_start"],
                            )
                            if raw2:
                                from schemas.rpg_schema import EntityBase, RelationshipBase
                                # Validar eventos de segunda pasada
                                for ev_data in raw2.get("events", []):
                                    ev_data.setdefault("workspace", args.workspace)
                                    try:
                                        ev = EntityBase(**ev_data)
                                        chunk_entities.append(ev)
                                    except Exception as exc:
                                        log.warning("  Segunda pasada: evento descartado: %s", exc)
                                # Validar relaciones de segunda pasada con normalización
                                sp_rels_raw = raw2.get("relations", [])
                                if sp_rels_raw:
                                    # Reusar validate para normalizar también la segunda pasada
                                    raw2_wrapped = {"entities": [], "relationships": sp_rels_raw}
                                    _, sp_rels, sp_warns, sp_stats = validate_extraction_result_partial(
                                        raw2_wrapped, idx, args.workspace,
                                        pages=[chunk["page_start"], chunk["page_end"]],
                                    )
                                    chunk_rels.extend(sp_rels)
                                    all_warnings.extend(sp_warns)
                                    chunk_stats["relations_normalized"] += sp_stats["relations_normalized"]
                                    chunk_stats["relations_dropped_unmappable"] += sp_stats["relations_dropped_unmappable"]
                                    chunk_stats["unmapped_relation_types"].extend(sp_stats["unmapped_relation_types"])
                                    log.info(
                                        "  Segunda pasada: +%d eventos, +%d relaciones "
                                        "(%d norm, %d descartadas)",
                                        len(raw2.get("events", [])),
                                        len(sp_rels),
                                        sp_stats["relations_normalized"],
                                        sp_stats["relations_dropped_unmappable"],
                                    )

                        # ── Cambio 3: entidad colectiva "Grupo de la sesión" ──
                        from schemas.rpg_schema import (
                            COLLECTIVE_ENTITY_REFS, make_collective_entity,
                            resolve_entity_ref, _normalize_key,
                        )
                        collective_canon = "Grupo de la sesión"
                        entity_canonical_names = {e.canonical_name for e in chunk_entities}
                        needs_collective = any(
                            _normalize_key(r.source_canonical) in COLLECTIVE_ENTITY_REFS or
                            _normalize_key(r.target_canonical) in COLLECTIVE_ENTITY_REFS
                            for r in chunk_rels
                        )
                        if needs_collective and collective_canon not in entity_canonical_names:
                            coll_entity = make_collective_entity(
                                args.workspace, doc_name,
                                [chunk["page_start"]]
                            )
                            chunk_entities.append(coll_entity)
                            entity_canonical_names.add(collective_canon)
                            chunk_stats["collective_entities_created"] += 1
                            log.info("  [resolver] Entidad colectiva creada: '%s'", collective_canon)

                        # ── Cambio 4: resolver source/target de relaciones ──
                        resolved_rels = []
                        for r in chunk_rels:
                            src_raw = r.source_canonical
                            tgt_raw = r.target_canonical

                            # Resolver source
                            if src_raw in entity_canonical_names:
                                src_resolved = src_raw
                                src_warn = None
                            elif _normalize_key(src_raw) in COLLECTIVE_ENTITY_REFS:
                                src_resolved = collective_canon
                                src_warn = f"[resolver] '{src_raw}' → '{collective_canon}' (colectivo)"
                                log.info("  %s", src_warn)
                            else:
                                src_resolved, src_warn = resolve_entity_ref(
                                    src_raw, chunk_entities, args.workspace,
                                    chunk_id=idx + 1,
                                    pages=[chunk["page_start"], chunk["page_end"]],
                                )

                            if src_resolved is None:
                                chunk_stats["relations_skipped_unresolved_source"] += 1
                                if src_warn and "AMBIGUO" in src_warn:
                                    chunk_stats["entity_refs_ambiguous"] += 1
                                else:
                                    chunk_stats["entity_refs_unresolved"] += 1
                                msg = (
                                    f"[resolver] relación DESCARTADA: source '{src_raw}' "
                                    f"no resuelto (tipo={r.relation_type}, tgt={tgt_raw})"
                                )
                                log.warning("  %s", msg)
                                all_warnings.append(msg)
                                if src_warn:
                                    all_warnings.append(src_warn)
                                continue
                            if src_resolved != src_raw:
                                chunk_stats["entity_refs_resolved"] += 1
                                if src_warn:
                                    all_warnings.append(src_warn)

                            # Resolver target
                            if tgt_raw in entity_canonical_names:
                                tgt_resolved = tgt_raw
                                tgt_warn = None
                            elif _normalize_key(tgt_raw) in COLLECTIVE_ENTITY_REFS:
                                tgt_resolved = collective_canon
                                tgt_warn = f"[resolver] '{tgt_raw}' → '{collective_canon}' (colectivo)"
                                log.info("  %s", tgt_warn)
                            else:
                                tgt_resolved, tgt_warn = resolve_entity_ref(
                                    tgt_raw, chunk_entities, args.workspace,
                                    chunk_id=idx + 1,
                                    pages=[chunk["page_start"], chunk["page_end"]],
                                )

                            if tgt_resolved is None:
                                # Target no resuelto: aceptable, lo crea _ensure_node
                                # Solo loguear warning informativo
                                chunk_stats["entity_refs_unresolved"] += 1
                                msg = (
                                    f"[resolver] target '{tgt_raw}' no resuelto en chunk "
                                    f"(tipo={r.relation_type}, src={src_resolved}) — "
                                    f"Neo4j lo creará si es necesario"
                                )
                                log.info("  %s", msg)
                                tgt_resolved = tgt_raw  # dejar pasar, _ensure_node lo gestiona
                            elif tgt_resolved != tgt_raw:
                                chunk_stats["entity_refs_resolved"] += 1
                                if tgt_warn:
                                    all_warnings.append(tgt_warn)

                            # Reconstruir relación con nombres resueltos si cambiaron
                            if src_resolved != src_raw or tgt_resolved != tgt_raw:
                                from schemas.rpg_schema import RelationshipBase as RB
                                try:
                                    r_resolved = RB(
                                        source_canonical=src_resolved,
                                        relation_type=r.relation_type,
                                        target_canonical=tgt_resolved,
                                        evidence=r.evidence,
                                        source_document=r.source_document,
                                        source_pages=r.source_pages,
                                        confidence=r.confidence,
                                    )
                                    resolved_rels.append(r_resolved)
                                    log.info(
                                        "  [resolver] relación resuelta: '%s' → '%s' --[%s]--> '%s' → '%s'",
                                        src_raw, src_resolved, r.relation_type, tgt_raw, tgt_resolved,
                                    )
                                except Exception as exc:
                                    log.warning("  [resolver] error al reconstruir relación: %s", exc)
                                    all_warnings.append(f"[resolver] relación descartada tras resolución: {exc}")
                            else:
                                resolved_rels.append(r)

                        chunk_rels = resolved_rels

                        # ── Fase 7/9: sellar metadatos temporales, visibilidad
                        #    e imágenes en cada entidad antes de escribir ──────────
                        for _e in chunk_entities:
                            if getattr(_e, "knowledge_layer", None) is None:
                                object.__setattr__(_e, "knowledge_layer", _knowledge_layer)
                            if getattr(_e, "visibility", None) is None:
                                object.__setattr__(_e, "visibility", _visibility)
                            if _session_number is not None:
                                if getattr(_e, "source_session", None) is None:
                                    object.__setattr__(_e, "source_session", _session_number)
                                if getattr(_e, "first_seen_session", None) is None \
                                        and _e.entity_type != "Session":
                                    object.__setattr__(_e, "first_seen_session", _session_number)
                            if _source_date and getattr(_e, "source_date", None) is None:
                                object.__setattr__(_e, "source_date", _source_date)
                            if getattr(_e, "review_status", None) is None:
                                object.__setattr__(_e, "review_status", "auto_extracted")
                            # Imagen local por convención de nombre (Fase 9)
                            if getattr(_e, "image_path", None) is None:
                                _img = detect_image_for_entity(_e, args.workspace)
                                if _img:
                                    object.__setattr__(_e, "image_path", _img)
                                    object.__setattr__(_e, "media_source", "nextcloud_media")
                                    log.info("  [media] imagen asociada a '%s': %s",
                                             _e.canonical_name, _img)

                        # Escribir en Neo4j inmediatamente
                        if writer and chunk_entities:
                            n_ok = sum(1 for e in chunk_entities if writer.write_entity(e))
                            r_ok = 0
                            r_target_created = 0
                            r_invalid = 0
                            r_dubious = 0
                            kept_rels = []
                            for r in chunk_rels:
                                # Validación semántica (Fase 10): ok / dubious / invalid
                                verdict, _sem_warn = _check_relation_semantics(
                                    r, chunk_entities,
                                    semantic_warnings_path,
                                )
                                if _sem_warn:
                                    all_warnings.append(_sem_warn)
                                if verdict == "invalid":
                                    r_invalid += 1
                                    chunk_stats["relations_dropped_invalid_semantic"] = \
                                        chunk_stats.get("relations_dropped_invalid_semantic", 0) + 1
                                    continue  # no escribir relación inválida
                                needs_review = (verdict == "dubious")
                                if needs_review:
                                    r_dubious += 1
                                    chunk_stats["manual_review_required"] = \
                                        chunk_stats.get("manual_review_required", 0) + 1
                                written, created = writer.write_relationship(
                                    r, args.workspace,
                                    manual_review_required=needs_review,
                                )
                                if written:
                                    r_ok += 1
                                    kept_rels.append(r)
                                if created:
                                    r_target_created += 1
                            # chunk_rels solo conserva las realmente escritas (para export/audit)
                            chunk_rels = kept_rels
                            audit["nodes_created_or_updated"] += n_ok
                            audit["auto_created_nodes"] += r_target_created
                            audit["relationships_written"] += r_ok
                            audit["relations_dropped_invalid_semantic"] += r_invalid
                            audit["manual_review_required"] += r_dubious
                            audit["relations_normalized"] += chunk_stats.get("relations_normalized", 0)
                            audit["relations_dropped_unmappable"] += chunk_stats.get("relations_dropped_unmappable", 0)
                            log.info(
                                "  Neo4j: %d/%d entidades | %d relaciones en grafo | "
                                "%d nodos destino creados | %d dudosas (review) | %d inválidas descartadas",
                                n_ok, len(chunk_entities),
                                r_ok, r_target_created, r_dubious, r_invalid,
                            )

                        all_entities.extend(chunk_entities)
                        all_relationships.extend(chunk_rels)

                        # Exportar JSON parcial acumulado
                        if args.export_json:
                            out = Path(output_dir) / args.workspace / safe_name(doc_name)
                            out.mkdir(parents=True, exist_ok=True)
                            with open(out / "entities.json", "w") as f:
                                json.dump({
                                    "entities": [e.model_dump() for e in all_entities],
                                    "relationships": [r.model_dump() for r in all_relationships],
                                    "warnings": all_warnings,
                                    "chunks_processed": idx + 1,
                                    "chunks_total": len(chunks),
                                }, f, indent=2, default=str)

                    except Exception as e:
                        chunk_error = str(e)
                        chunk_status = "invalid_json"
                        log.warning("  Chunk %d: validación fallida: %s", idx + 1, e)
                        all_warnings.append(f"Chunk {idx+1}: {e}")

            chunk_statuses.append(chunk_status)
            save_chunk_state(
                state_dir, args.workspace, doc_name,
                chunk_idx=idx,
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                status=chunk_status,
                n_entities=len(chunk_entities),
                n_rels=len(chunk_rels),
                error=chunk_error,
                model=config["ollama"]["model"],
                relations_normalized=chunk_stats.get("relations_normalized", 0),
                unmapped_relation_types=chunk_stats.get("unmapped_relation_types", []),
                entity_refs_resolved=chunk_stats.get("entity_refs_resolved", 0),
                entity_refs_unresolved=chunk_stats.get("entity_refs_unresolved", 0),
                entity_refs_ambiguous=chunk_stats.get("entity_refs_ambiguous", 0),
                collective_entities_created=chunk_stats.get("collective_entities_created", 0),
                relations_skipped_unresolved_source=chunk_stats.get("relations_skipped_unresolved_source", 0),
            )

        # ── Fase 8: enlazar entidades con la Session (APPEARS_IN) ──────────────
        if writer and _session_canon:
            try:
                from schemas.rpg_schema import RelationshipBase as _RB
                _linked = set()
                for _e in all_entities:
                    cn = _e.canonical_name
                    if cn == _session_canon or cn in _linked:
                        continue
                    if _e.entity_type == "Session":
                        continue
                    _linked.add(cn)
                    _rel = _RB(
                        source_canonical=cn,
                        relation_type="APPEARS_IN",
                        target_canonical=_session_canon,
                        evidence=f"Aparece en la sesión {_session_number}",
                        source_document=doc_name,
                    )
                    writer.write_relationship(_rel, args.workspace)
                log.info("[session] %d entidades enlazadas APPEARS_IN '%s'",
                         len(_linked), _session_canon)
                audit["relationships_written"] += len(_linked)
            except Exception as _exc:
                log.warning("[session] error enlazando APPEARS_IN: %s", _exc)

        if writer:
            writer.close()

        log.info("Total: %d entidades, %d relaciones, %d advertencias",
                 len(all_entities), len(all_relationships), len(all_warnings))

        # ── Auditoría post-run ampliada (Fase 13) ──────────────────────────────
        _type_counts: dict[str, int] = {}
        for _e in all_entities:
            _type_counts[_e.entity_type] = _type_counts.get(_e.entity_type, 0) + 1
        _creature_like = ("Creature", "NonHuman", "Spirit", "Demon", "Beast")
        _nodes_missing_sid = sum(1 for _e in all_entities
                                 if not getattr(_e, "source_id", None) and not _source_id)
        audit["semantic_warnings"] = sum(1 for w in all_warnings if "[semantic" in w)

        log.info(
            "[AUDIT] Resumen: %d entidades extraídas | %d relaciones extraídas | %d warnings",
            len(all_entities), len(all_relationships), len(all_warnings),
        )
        log.info(
            "[AUDIT] Grafo: nodes_created/updated=%d | auto_created_nodes=%d | "
            "relationships_written=%d",
            audit["nodes_created_or_updated"], audit["auto_created_nodes"],
            audit["relationships_written"],
        )
        log.info(
            "[AUDIT] Relaciones: normalizadas=%d | descartadas_sin_mapeo=%d | "
            "descartadas_inválidas_semántica=%d | dudosas_manual_review=%d | "
            "semantic_warnings=%d",
            audit["relations_normalized"], audit["relations_dropped_unmappable"],
            audit["relations_dropped_invalid_semantic"], audit["manual_review_required"],
            audit["semantic_warnings"],
        )
        log.info(
            "[AUDIT] Entidades por tipo: characters=%d | creatures=%d | locations=%d | "
            "events=%d | tasks=%d | sessions=%d | combats=%d",
            _type_counts.get("Character", 0),
            sum(_type_counts.get(t, 0) for t in _creature_like),
            _type_counts.get("Location", 0) + _type_counts.get("Region", 0),
            _type_counts.get("Event", 0) + _type_counts.get("Encounter", 0),
            _type_counts.get("Task", 0),
            _type_counts.get("Session", 0),
            _type_counts.get("Combat", 0),
        )
        log.info("[AUDIT] Detalle tipos: %s",
                 ", ".join(f"{k}={v}" for k, v in sorted(_type_counts.items())))
        log.info(
            "[AUDIT] Trazabilidad: source_id='%s' | source_kind='%s' | "
            "knowledge_layer='%s' | visibility='%s' | source_hash='%s...' | workspace='%s'",
            _source_id, _source_kind, _knowledge_layer, _visibility,
            pdf_hash[:12], args.workspace,
        )
        if _nodes_missing_sid:
            log.warning("[AUDIT] ⚠ %d nodos podrían quedar sin source_id", _nodes_missing_sid)
        if not _source_id:
            log.warning("[AUDIT] ⚠ ALERTA: source_id vacío — "
                        "nodos y relaciones escritos SIN identificador de documento")
        if _source_kind == "unknown":
            log.warning("[AUDIT] ⚠ ALERTA: source_kind='unknown' — "
                        "usa --source-kind o --profile para clasificar correctamente")

        # Determinar estado final del documento
        success_chunks = chunk_statuses.count("success")
        failed_chunks = sum(1 for s in chunk_statuses if s in ("model_error", "invalid_json"))

        if failed_chunks == 0 and success_chunks > 0:
            doc_status = "complete"
        elif failed_chunks == 0 and success_chunks == 0:
            doc_status = "no_entities"
        elif success_chunks > 0 and failed_chunks > 0:
            doc_status = "partial_success"
        else:
            doc_status = "failed"

        log.info("Estado del documento: %s (%d/%d chunks ok)",
                 doc_status, success_chunks, len(chunks))

        if not all_entities and not args.dry_run:
            log.warning("Sin entidades extraídas")
            save_state(state_dir, args.workspace, doc_name, {
                "sha256": pdf_hash, "status": doc_status,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "warnings": all_warnings,
                "chunks": chunk_statuses,
            })
            sys.exit(EXIT_NO_ENTITIES)

        # Export Markdown (al final, con todas las entidades acumuladas)
        if args.export_markdown and not args.dry_run:
            spaces_dir = spaces.get(args.workspace,
                f"/opt/knowledge-services/spaces/{args.workspace}")
            export_to_markdown(
                all_entities, all_relationships,
                args.workspace, doc_name, spaces_dir,
            )

        # Estado final
        save_state(state_dir, args.workspace, doc_name, {
            "sha256": pdf_hash,
            "status": doc_status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "pages": num_pages,
            "page_range": f"{page_range[0]}-{page_range[1]}" if input_type == "pdf" and args.pages and page_range else "all",
            "entities": len(all_entities),
            "relationships": len(all_relationships),
            "warnings": len(all_warnings),
            "chunks": chunk_statuses,
            "model": config["ollama"]["model"],
            "input_type": input_type,
        })

        # Limpiar staging solo si exito completo (solo para PDF)
        if staging_pdf and doc_status == "complete" and not args.keep_staging and not args.dry_run:
            staging_pdf.unlink(missing_ok=True)
            log.info("Staging eliminado")
        elif staging_pdf and doc_status != "complete":
            log.info("Staging conservado (estado: %s)", doc_status)

        log.info("Completado: %d entidades, %d relaciones [%s]",
                 len(all_entities), len(all_relationships), doc_status)

        if doc_status == "complete":
            return EXIT_OK
        elif doc_status == "partial_success":
            return EXIT_NO_ENTITIES  # parcial: código 10
        else:
            return EXIT_NO_ENTITIES

    except SystemExit:
        raise
    except Exception as e:
        log.exception("Error inesperado: %s", e)
        return EXIT_PDF_READ_ERROR
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
