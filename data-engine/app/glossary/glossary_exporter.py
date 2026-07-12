"""Genera los ficheros de export del glosario para faster-whisper.

Salidas:
- initial_prompt.txt: prompt corto para initial_prompt de Whisper
- hotwords.txt: un término por línea (palabras/frases cortas sin contexto largo)
- glossary.json: lista completa de términos con todos los campos relevantes

Límites configurables:
- max_terms: máximo de términos en el prompt/hotwords (default 250)
- max_prompt_chars: máximo de chars del initial_prompt (default 224, límite Whisper)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from glossary.glossary_models import GlossaryTerm
from glossary.glossary_store import GlossaryStore

log = logging.getLogger("glossary.exporter")

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Prompt base para el contexto de la partida
_PROMPT_CONTEXT_DEFAULT = (
    "Transcripción en español de una partida de rol de La Leyenda de los Cinco Anillos "
    "ambientada en Rokugán."
)


class GlossaryExporter:
    """Exporta el glosario a los formatos requeridos por faster-whisper."""

    def __init__(self, store: GlossaryStore):
        self.store = store

    def export(
        self,
        workspace: str,
        output_dir: Path | str,
        context: str | None = None,
        max_terms: int = 250,
        max_prompt_chars: int = 224,
    ) -> dict[str, Path]:
        """Genera los tres ficheros de export y devuelve sus rutas."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        terms = self.store.list_terms(workspace, enabled_only=True, limit=max_terms)

        initial_prompt_path = output_dir / "initial_prompt.txt"
        hotwords_path = output_dir / "hotwords.txt"
        glossary_json_path = output_dir / "glossary.json"

        self._write_initial_prompt(terms, initial_prompt_path, context, max_prompt_chars)
        self._write_hotwords(terms, hotwords_path, max_terms)
        self._write_glossary_json(terms, glossary_json_path, workspace)

        log.info(
            "Export completado: %d términos → %s",
            len(terms), output_dir
        )
        return {
            "initial_prompt": initial_prompt_path,
            "hotwords": hotwords_path,
            "glossary_json": glossary_json_path,
        }

    def _write_initial_prompt(
        self,
        terms: list[GlossaryTerm],
        path: Path,
        context: str | None,
        max_chars: int,
    ) -> None:
        """Genera un initial_prompt corto con los términos más prioritarios.

        Formato: "<contexto> Términos relevantes: T1, T2, T3. No traduzcas ni
        separes los nombres propios."
        Se trunca para no superar max_chars.
        """
        ctx = context or _PROMPT_CONTEXT_DEFAULT
        suffix = " No traduzcas ni separes los nombres propios."

        # Recoger canonical_terms únicos (sin duplicados) ordenados por priority
        term_names: list[str] = []
        seen: set[str] = set()
        for t in terms:
            if t.canonical_term not in seen:
                seen.add(t.canonical_term)
                term_names.append(t.canonical_term)

        # Construir prompt truncando términos hasta no superar max_chars
        prefix = ctx + " Términos relevantes: "
        available = max_chars - len(prefix) - len(suffix) - 2
        selected: list[str] = []
        acc = 0
        for name in term_names:
            addition = len(name) + (2 if selected else 0)  # ", " separator
            if acc + addition > available:
                break
            selected.append(name)
            acc += addition

        if selected:
            prompt = prefix + ", ".join(selected) + "." + suffix
        else:
            prompt = ctx + suffix

        path.write_text(prompt, encoding="utf-8")
        log.debug("initial_prompt.txt: %d chars, %d términos", len(prompt), len(selected))

    def _write_hotwords(self, terms: list[GlossaryTerm], path: Path, max_terms: int) -> None:
        """Genera hotwords.txt: un término por línea, sin frases muy largas."""
        lines: list[str] = []
        seen: set[str] = set()
        for t in terms:
            # Solo términos cortos (máx 4 palabras) como hotwords
            words = t.canonical_term.split()
            if len(words) <= 4 and t.canonical_term not in seen:
                seen.add(t.canonical_term)
                lines.append(t.canonical_term)
            # También añadir aliases cortos
            for alias in t.aliases:
                alias_words = alias.split()
                if len(alias_words) <= 3 and alias not in seen:
                    seen.add(alias)
                    lines.append(alias)
            if len(lines) >= max_terms:
                break

        path.write_text("\n".join(lines), encoding="utf-8")
        log.debug("hotwords.txt: %d entradas", len(lines))

    def _write_glossary_json(
        self, terms: list[GlossaryTerm], path: Path, workspace: str
    ) -> None:
        """Genera glossary.json con canonical, aliases, error_forms y priority."""
        data = {
            "workspace": workspace,
            "count": len(terms),
            "terms": [
                {
                    "canonical_term": t.canonical_term,
                    "term_type": t.term_type,
                    "aliases": t.aliases,
                    "spoken_forms": t.spoken_forms,
                    "error_forms": t.error_forms,
                    "confidence": t.confidence,
                    "priority": t.priority,
                    "source_kind": t.source_kind,
                    "language": t.language,
                }
                for t in terms
            ],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.debug("glossary.json: %d términos", len(terms))
