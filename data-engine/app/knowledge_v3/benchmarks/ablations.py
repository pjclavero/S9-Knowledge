# -*- coding: utf-8 -*-
"""Ablaciones: configuraciones etiquetadas de una corrida (dosier 8).

El arnes no ejecuta el pipeline — eso llega en integracion —, pero SI define
que configuraciones existen, que significa cada una y como se etiqueta su
resultado. Sin esto, cada equipo inventaria su propio nombre para "sin
glosario" y ninguna tabla del informe final seria comparable.

Una ablacion cambia la ENTRADA del subsistema, no la forma de medirlo: el
mismo arnes puntua todas, y el informe lleva siempre la etiqueta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: De donde salen las entidades que ve el motor.
ENTITY_SOURCES = ("gold", "real", "none")
#: De donde salen los claims que ve el motor.
CLAIM_SOURCES = ("gold", "real")
#: Que proveedores participan.
PROVIDER_MODES = ("local_only", "external_only", "local_plus_external", "no_ollama")
#: Si el glosario/perfil de alias esta activo.
GLOSSARY_MODES = ("with_glossary", "without_glossary")


@dataclass(frozen=True)
class Ablation:
    """Una configuracion etiquetada."""

    label: str
    description: str
    entity_source: str = "real"
    claim_source: str = "real"
    providers: str = "local_plus_external"
    glossary: str = "with_glossary"
    profile_id: str = "generic"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entity_source not in ENTITY_SOURCES:
            raise ValueError(f"entity_source desconocido: {self.entity_source!r}")
        if self.claim_source not in CLAIM_SOURCES:
            raise ValueError(f"claim_source desconocido: {self.claim_source!r}")
        if self.providers not in PROVIDER_MODES:
            raise ValueError(f"providers desconocido: {self.providers!r}")
        if self.glossary not in GLOSSARY_MODES:
            raise ValueError(f"glossary desconocido: {self.glossary!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "entity_source": self.entity_source,
            "claim_source": self.claim_source,
            "providers": self.providers,
            "glossary": self.glossary,
            "profile_id": self.profile_id,
            "extra": dict(self.extra),
        }


def _a(label: str, description: str, **kw: Any) -> Ablation:
    return Ablation(label=label, description=description, **kw)


#: Las diez ablaciones del dosier 8, mas la corrida nominal.
ABLATIONS: dict[str, Ablation] = {
    a.label: a
    for a in (
        _a("nominal", "Corrida de referencia: todo real, perfil correcto, con glosario."),
        _a(
            "gold_identity",
            "Prueba de cordura del arnes: el gold medido contra si mismo. No es "
            "una corrida del sistema y no debe aparecer en ninguna tabla de "
            "resultados; solo demuestra que el arnes sabe reconocer un acierto.",
            entity_source="gold",
            claim_source="gold",
        ),
        _a(
            "gold_entities_to_engine",
            "El motor recibe las entidades GOLD. Aisla el motor de los errores del resolutor.",
            entity_source="gold",
        ),
        _a(
            "real_entities_to_engine",
            "El motor recibe las entidades del resolutor real. Es el caso de produccion.",
            entity_source="real",
        ),
        _a(
            "gold_claims_to_engine",
            "El motor recibe los claims GOLD. Aisla el motor de los errores del extractor.",
            claim_source="gold",
        ),
        _a("local_only", "Solo codigo local determinista: ni Ollama ni externo.", providers="local_only"),
        _a("external_only", "Solo proveedor externo. Cota superior, no configuracion de produccion.", providers="external_only"),
        _a("local_plus_external", "Local y externo combinados.", providers="local_plus_external"),
        _a("no_ollama", "Sin el LLM local. Mide cuanto aporta Ollama de verdad.", providers="no_ollama"),
        _a("without_glossary", "Sin glosario ni alias del perfil.", glossary="without_glossary"),
        _a("with_glossary", "Con glosario y alias del perfil.", glossary="with_glossary"),
        _a("generic_profile", "Perfil de juego correcto ('generic').", profile_id="generic"),
        _a(
            "wrong_profile",
            "Perfil DELIBERADAMENTE incompleto ('bench-narrow'): faltan LEADS, "
            "RIVAL_OF y SIBLING_OF. Se espera abstencion o revision, no un "
            "predicado parecido inventado.",
            profile_id="bench-narrow",
        ),
    )
}

#: Etiqueta usada cuando quien corre el arnes no declara ninguna.
UNSPECIFIED = "unspecified"


def resolve(label: str) -> Ablation:
    """Devuelve la ablacion etiquetada. Falla si no existe: una etiqueta libre
    en el informe es una etiqueta que nadie podra comparar despues."""
    if label == UNSPECIFIED:
        return Ablation(
            label=UNSPECIFIED,
            description="Corrida sin ablacion declarada. El informe lo hace constar.",
        )
    try:
        return ABLATIONS[label]
    except KeyError as exc:
        raise KeyError(
            f"ablacion desconocida: {label!r}. Conocidas: {sorted(ABLATIONS)}"
        ) from exc


def labels() -> list[str]:
    return sorted(ABLATIONS)


__all__ = [
    "ABLATIONS",
    "Ablation",
    "CLAIM_SOURCES",
    "ENTITY_SOURCES",
    "GLOSSARY_MODES",
    "PROVIDER_MODES",
    "UNSPECIFIED",
    "labels",
    "resolve",
]
