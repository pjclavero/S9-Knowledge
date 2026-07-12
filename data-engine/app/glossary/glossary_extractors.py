"""Extractores de términos para el glosario L5A.

Tres extractores:
- ManualSeedExtractor: semillas hardcoded L5A (Rokugán, Toshi Ranbo, etc.)
- Neo4jGlossaryExtractor: lee entidades del grafo Neo4j (solo lectura)
- MarkdownGlossaryExtractor: extrae términos de docs/*.md y transcripciones

Todos implementan extract() → list[GlossaryTerm].
Si un extractor falla (ej. Neo4j no disponible), degrada con warning.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from glossary.glossary_models import GlossaryTerm
from glossary.glossary_store import normalize_term

log = logging.getLogger("glossary.extractors")

# Raíz del repo (parents[3] desde data-engine/app/glossary/)
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ── ManualSeedExtractor ───────────────────────────────────────────────────────

# Semillas L5A: (canonical, type, aliases, spoken_forms, error_forms)
_L5A_SEEDS: list[dict] = [
    {
        "canonical": "Rokugán",
        "type": "lugar",
        "aliases": ["Rokugan"],
        "spoken_forms": ["Rokugán", "Rokugan"],
        "error_forms": [],
    },
    {
        "canonical": "Toshi Ranbo",
        "type": "lugar",
        "aliases": ["Ciudad Toshi Ranbo"],
        "spoken_forms": ["Toshi Ranbo"],
        "error_forms": ["Tosi Rambo", "Toshi Rambo", "Tosi Ranbo"],
    },
    {
        "canonical": "Clan Grulla",
        "type": "clan",
        "aliases": ["Grulla"],
        "spoken_forms": ["Clan Grulla", "Grulla"],
        "error_forms": ["Clan Gruya", "Clan Grulla"],
    },
    {
        "canonical": "Clan León",
        "type": "clan",
        "aliases": ["León"],
        "spoken_forms": ["Clan León", "León"],
        "error_forms": [],
    },
    {
        "canonical": "Clan Dragón",
        "type": "clan",
        "aliases": ["Dragón"],
        "spoken_forms": ["Clan Dragón", "Dragón"],
        "error_forms": [],
    },
    {
        "canonical": "Clan Escorpión",
        "type": "clan",
        "aliases": ["Escorpión"],
        "spoken_forms": ["Clan Escorpión", "Escorpión"],
        "error_forms": [],
    },
    {
        "canonical": "Clan Cangrejo",
        "type": "clan",
        "aliases": ["Cangrejo"],
        "spoken_forms": ["Clan Cangrejo", "Cangrejo"],
        "error_forms": [],
    },
    {
        "canonical": "Magistrado Esmeralda",
        "type": "titulo",
        "aliases": ["Magistrados Esmeralda"],
        "spoken_forms": ["Magistrado Esmeralda"],
        "error_forms": ["magistrados en medaldas", "magistrados en medallas", "magistrado en medalla"],
    },
    {
        "canonical": "Campeona Rubí",
        "type": "titulo",
        "aliases": ["Campeon Ruby", "Campeón Rubí"],
        "spoken_forms": ["Campeona Rubí"],
        "error_forms": ["campeona ruby", "campeon ruby"],
    },
    {
        "canonical": "wakizashi",
        "type": "arma",
        "aliases": [],
        "spoken_forms": ["wakizashi"],
        "error_forms": ["guacizasi", "wacizasi", "guacisasi"],
    },
    {
        "canonical": "katana",
        "type": "arma",
        "aliases": [],
        "spoken_forms": ["katana"],
        "error_forms": [],
    },
    {
        "canonical": "iaijutsu",
        "type": "habilidad",
        "aliases": ["iai"],
        "spoken_forms": ["iaijutsu"],
        "error_forms": [],
    },
    {
        "canonical": "kami",
        "type": "criatura",
        "aliases": [],
        "spoken_forms": ["kami"],
        "error_forms": [],
    },
    {
        "canonical": "oni",
        "type": "criatura",
        "aliases": [],
        "spoken_forms": ["oni"],
        "error_forms": [],
    },
    {
        "canonical": "Mirumoto Seiyuro",
        "type": "personaje",
        "aliases": ["Seiyuro", "Mirumoto"],
        "spoken_forms": ["Mirumoto Seiyuro", "Seiyuro"],
        "error_forms": ["Se Lloro", "Se Yuro", "Seiyuro"],
    },
    {
        # DISCREPANCIA Seiyuro/Seijuro:
        # El audio real (benchmark Agente A) dice "Seijuro", no "Seiyuro".
        # canonical = "Seijuro" (forma del audio real)
        # alias "Seiyuro" = forma del manual del juego
        "canonical": "Seijuro",
        "type": "personaje",
        "aliases": ["Seiyuro", "Mirumoto Seijuro"],
        "spoken_forms": ["Seijuro", "Seiyuro"],
        "error_forms": ["Se Lloro", "Se Yuro", "Se Juro", "Seijurou"],
    },
    {
        "canonical": "Kitsugi Kaji",
        "type": "personaje",
        "aliases": ["Kaji"],
        "spoken_forms": ["Kitsugi Kaji", "Kaji"],
        "error_forms": ["Kitsuji Kaji", "Kitsuki Kaji"],
    },
]


class ManualSeedExtractor:
    """Extrae semillas manuales hardcoded del ambientación L5A."""

    def extract(self, workspace: str) -> list[GlossaryTerm]:
        terms: list[GlossaryTerm] = []
        for seed in _L5A_SEEDS:
            t = GlossaryTerm(
                workspace=workspace,
                canonical_term=seed["canonical"],
                normalized_term=normalize_term(seed["canonical"]),
                term_type=seed["type"],
                aliases=seed["aliases"],
                spoken_forms=seed["spoken_forms"],
                error_forms=seed["error_forms"],
                source_id='seed',
                source_kind="manual_seed",
                source_document=None,
                confidence=0.99,
                frequency=1,
                language="es",
            )
            terms.append(t)
        log.info("ManualSeedExtractor: %d semillas extraídas", len(terms))
        return terms


# ── Neo4jGlossaryExtractor ────────────────────────────────────────────────────

class Neo4jGlossaryExtractor:
    """Lee entidades del grafo Neo4j para el workspace indicado. SOLO LECTURA.

    Carga credenciales desde el fichero viewer/.env del repo.
    Si no puede conectar, degrada con warning sin propagar la excepción.
    """

    def __init__(self, uri: str | None = None, user: str | None = None, password: str | None = None):
        self._uri = uri
        self._user = user
        self._password = password

    def _load_credentials(self) -> tuple[str, str, str]:
        """Lee viewer/.env; fallback a env vars."""
        uri = self._uri
        user = self._user
        password = self._password

        env_file = _REPO_ROOT / "viewer" / ".env"
        env_vars: dict[str, str] = {}
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()

        # Leer contraseña desde fichero si hay S9K_NEO4J_PASSWORD_FILE
        password_file = env_vars.get("S9K_NEO4J_PASSWORD_FILE", "")
        if password_file and Path(password_file).exists():
            pw = Path(password_file).read_text(encoding="utf-8").strip()
        else:
            pw = env_vars.get("S9K_NEO4J_PASSWORD", "")

        uri = uri or env_vars.get("S9K_NEO4J_URI", "bolt://127.0.0.1:7687")
        user = user or env_vars.get("S9K_NEO4J_USER", "neo4j")
        password = password or pw or os.environ.get("S9K_NEO4J_PASSWORD", "")

        return uri, user, password

    def _type_from_entity_type(self, entity_type: str | None) -> str | None:
        """Mapea entity_type del grafo a term_type del glosario."""
        if not entity_type:
            return None
        mapping = {
            "Personaje": "personaje",
            "Lugar": "lugar",
            "Organizacion": "organizacion",
            "Clan": "clan",
            "Arma": "arma",
            "Habilidad": "habilidad",
            "Concepto": "concepto",
            "Objeto": "objeto",
            "Criatura": "criatura",
            "Deidad": "deidad",
            "Titulo": "titulo",
        }
        return mapping.get(entity_type, "general")

    def extract(self, workspace: str) -> list[GlossaryTerm]:
        try:
            from neo4j import GraphDatabase  # import perezoso
        except ImportError:
            log.warning("Neo4jGlossaryExtractor: neo4j no instalado; saltando")
            return []

        try:
            uri, user, password = self._load_credentials()
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
        except Exception as exc:
            log.warning("Neo4jGlossaryExtractor: no se puede conectar a Neo4j (%s); saltando", exc)
            return []

        terms: list[GlossaryTerm] = []
        query = """
        MATCH (n:Entity {workspace: $workspace})
        RETURN
            n.canonical_name AS canonical_name,
            n.display_name AS display_name,
            n.aliases AS aliases,
            n.entity_type AS entity_type,
            n.workspace AS workspace,
            n.source_document AS source_document,
            n.confidence AS confidence,
            n.source_id AS source_id,
            n.source_kind AS source_kind,
            n.source_pages AS source_pages
        ORDER BY n.canonical_name
        """
        try:
            with driver.session() as session:
                records = session.run(query, workspace=workspace)
                for rec in records:
                    canonical = rec["canonical_name"] or rec["display_name"] or ""
                    if not canonical:
                        continue
                    aliases_raw = rec["aliases"] or []
                    if isinstance(aliases_raw, str):
                        aliases_raw = [aliases_raw]
                    # display_name como alias si difiere del canonical
                    display = rec["display_name"] or ""
                    if display and display != canonical and display not in aliases_raw:
                        aliases_raw = list(aliases_raw) + [display]

                    source_pages_raw = rec["source_pages"] or []
                    if isinstance(source_pages_raw, str):
                        source_pages_raw = [source_pages_raw]
                    source_pages_str = [str(p) for p in source_pages_raw]

                    t = GlossaryTerm(
                        workspace=workspace,
                        canonical_term=canonical,
                        normalized_term=normalize_term(canonical),
                        term_type=self._type_from_entity_type(rec["entity_type"]),
                        aliases=list(aliases_raw),
                        spoken_forms=[],
                        error_forms=[],
                        source_id=rec["source_id"],
                        source_kind=rec["source_kind"] or "neo4j",
                        source_document=rec["source_document"],
                        source_pages=source_pages_str,
                        confidence=float(rec["confidence"] or 0.7),
                        frequency=1,
                        language="es",
                    )
                    terms.append(t)
        except Exception as exc:
            log.warning("Neo4jGlossaryExtractor: error en consulta (%s)", exc)
        finally:
            try:
                driver.close()
            except Exception:
                pass

        log.info("Neo4jGlossaryExtractor: %d términos extraídos de Neo4j (workspace=%s)", len(terms), workspace)
        return terms


# ── MarkdownGlossaryExtractor ─────────────────────────────────────────────────

# Patrones para extraer términos de Markdown
_RE_HEADING = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_CLAN = re.compile(r"\b(Clan|Familia)\s+([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñA-ZÁÉÍÓÚÜÑ]+)", re.UNICODE)
_RE_PROPER_NOUN = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{2,}(?:\s+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{2,}){0,3})\b",
    re.UNICODE,
)
# Palabras comunes a ignorar (stopwords de inicio de frase)
_STOPWORDS: set[str] = {
    "El", "La", "Los", "Las", "Un", "Una", "Unos", "Unas",
    "En", "De", "Del", "Con", "Por", "Para", "Sin", "Sobre",
    "Ante", "Bajo", "Cabe", "Contra", "Desde", "Durante",
    "Entre", "Hacia", "Hasta", "Mediante", "Según", "Tras",
    "También", "Este", "Esta", "Estos", "Estas", "Ese", "Esa",
    "Todo", "Todos", "Toda", "Todas", "Cada", "Mismo", "Misma",
    "Aquí", "Allí", "Donde", "Como", "Cuando", "Que", "Qué",
    "Hay", "Era", "Son", "Sus", "Muy", "Más", "Ser", "Fue",
    "Han", "Has", "Hemos", "Habría", "Había", "Habrá",
    "Transcripción", "Metadatos", "Resumen", "Fuente", "Archivo",
    "Motor", "Modelo", "Idioma", "Estado", "Duración", "Fecha",
    "Pendiente", "Preparado",
}


class MarkdownGlossaryExtractor:
    """Extrae candidatos a términos de ficheros Markdown.

    Busca en:
    - docs/*.md (raíz del repo)
    - output/transcriptions/**/*.md

    Estrategias:
    1. Encabezados H1-H4
    2. Texto en **negrita**
    3. Patrones "Clan X" / "Familia X"
    4. Sustantivos propios con mayúscula inicial (filtrados por stopwords)
    """

    def __init__(self, extra_paths: list[Path] | None = None):
        self.extra_paths = extra_paths or []

    def _markdown_files(self) -> list[Path]:
        files: list[Path] = []
        # docs/*.md
        docs_dir = _REPO_ROOT / "docs"
        if docs_dir.is_dir():
            files.extend(docs_dir.glob("*.md"))
        # output/transcriptions/**/*.md
        trans_dir = _REPO_ROOT / "output" / "transcriptions"
        if trans_dir.is_dir():
            files.extend(trans_dir.rglob("*.md"))
        # data-engine/tests/data/*.md
        tests_data = _REPO_ROOT / "data-engine" / "tests" / "data"
        if tests_data.is_dir():
            files.extend(tests_data.glob("*.md"))
        # rutas adicionales
        files.extend(self.extra_paths)
        return files

    def _extract_from_text(self, text: str) -> set[str]:
        candidates: set[str] = set()

        # 1. Encabezados
        for m in _RE_HEADING.finditer(text):
            h = m.group(1).strip().strip("*_`").strip()
            if 2 < len(h) < 80 and h not in _STOPWORDS:
                candidates.add(h)

        # 2. Negritas
        for m in _RE_BOLD.finditer(text):
            b = m.group(1).strip()
            if 2 < len(b) < 80 and b not in _STOPWORDS:
                candidates.add(b)

        # 3. Clan / Familia X
        for m in _RE_CLAN.finditer(text):
            candidates.add(m.group(0).strip())

        # 4. Nombres propios (con mayúscula inicial)
        for m in _RE_PROPER_NOUN.finditer(text):
            term = m.group(1).strip()
            # Al menos una palabra de >3 chars no en stopwords
            words = term.split()
            if any(w not in _STOPWORDS and len(w) > 3 for w in words):
                if len(term) > 3 and len(term) < 60:
                    candidates.add(term)

        return candidates

    def extract(self, workspace: str) -> list[GlossaryTerm]:
        files = self._markdown_files()
        all_candidates: dict[str, dict] = {}  # canonical → {count, source_doc}

        for md_file in files:
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("MarkdownGlossaryExtractor: no se puede leer %s (%s)", md_file, exc)
                continue

            candidates = self._extract_from_text(text)
            for cand in candidates:
                if cand in all_candidates:
                    all_candidates[cand]["count"] += 1
                else:
                    all_candidates[cand] = {"count": 1, "source_doc": md_file.name}

        terms: list[GlossaryTerm] = []
        for canonical, meta in all_candidates.items():
            t = GlossaryTerm(
                workspace=workspace,
                canonical_term=canonical,
                normalized_term=normalize_term(canonical),
                term_type="general",
                aliases=[],
                spoken_forms=[],
                error_forms=[],
                source_id=None,
                source_kind="markdown",
                source_document=meta["source_doc"],
                confidence=0.4,
                frequency=meta["count"],
                language="es",
            )
            terms.append(t)

        log.info(
            "MarkdownGlossaryExtractor: %d candidatos de %d ficheros",
            len(terms), len(files)
        )
        return terms
