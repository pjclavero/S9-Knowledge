# -*- coding: utf-8 -*-
"""Plantillas de prompt RPG versionadas para extraccion de relaciones.

Este subpaquete NO llama a ningun modelo (ni Ollama, ni NVIDIA, ni red). Solo
define plantillas versionadas, su renderizado determinista y la validacion de
la salida esperada contra el contrato `relation-candidate/internal-v1`.

Reutiliza/referencia el estilo y la version de `external_ai.prompts` sin
duplicarlo.
"""
from __future__ import annotations

from relations.prompts.templates import (
    ALL_TEMPLATE_IDS,
    DEFAULT_SUITE,
    EXTERNAL_AI_PROMPT_VERSION,
    INPUT_CLOSE,
    INPUT_OPEN,
    KNOWN_PREDICATES,
    PROMPT_SUITE_VERSION,
    SUITES,
    TEMPLATE_VERSION,
    TEMPLATES,
    TEMPLATES_BY_ID,
    PromptSuite,
    RelationPromptTemplate,
    build_relation_block,
    build_system_prompt,
    detect_injection,
    get_suite,
    get_template,
    list_templates,
    relation_json_schema_text,
    render,
    sanitize_document,
    validate_expected_output,
)

__all__ = [
    "ALL_TEMPLATE_IDS",
    "DEFAULT_SUITE",
    "EXTERNAL_AI_PROMPT_VERSION",
    "INPUT_CLOSE",
    "INPUT_OPEN",
    "KNOWN_PREDICATES",
    "PROMPT_SUITE_VERSION",
    "SUITES",
    "TEMPLATE_VERSION",
    "TEMPLATES",
    "TEMPLATES_BY_ID",
    "PromptSuite",
    "RelationPromptTemplate",
    "build_relation_block",
    "build_system_prompt",
    "detect_injection",
    "get_suite",
    "get_template",
    "list_templates",
    "relation_json_schema_text",
    "render",
    "sanitize_document",
    "validate_expected_output",
]
