# -*- coding: utf-8 -*-
"""CARRIL 7 — reproduccion y verificacion sobre el PRODUCTO REAL (no maqueta).

Sigue el dato:  texto -> mention -> normalized_surfaces -> candidatos
                      -> score/motivo -> decision -> entity_id

Se ejecuta IGUAL con el arreglo y sin el (`git stash`). Los tres casos declaran
su expectativa; el script devuelve rc!=0 si alguna no se cumple, de modo que el
control negativo no depende de leer la salida a ojo.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "data-engine" / "app"
sys.path.insert(0, str(APP))

from knowledge_v3.contracts.mention import EntityMention  # noqa: E402
from knowledge_v3.resolution import (  # noqa: E402
    CatalogEntity,
    EntityResolver,
    InMemoryEntityCatalog,
    ResolutionRequest,
    TrigramJaccardSimilarity,
    normalize_surface,
)
from knowledge_v3.resolution.cascade import run_cascade  # noqa: E402
from knowledge_v3.resolution.config import DEFAULT_CONFIG  # noqa: E402
from knowledge_v3.resolution.resolver import _build_context, _read_envelope  # noqa: E402

WS = "leyenda"
ASSET = "asset:carril7"
SH = {"algorithm": "sha256", "value": hashlib.sha256(ASSET.encode()).hexdigest()}
PARTIDA_A = "partida:alpha"

FALLOS: list[str] = []


def mention(mid, surface, *, mtype="Faction", conf=0.92, partida=None):
    return EntityMention(
        contract_version="3.0.0", workspace=WS, source_asset_id=ASSET, source_hash=SH,
        provider_trace=[{"step": "ner.deterministic", "provider": "local",
                         "model": "s9k.ner", "model_version": "3.0.0",
                         "inputs": ["surface"]}],
        produced_by_step="ner.deterministic", mention_id=mid,
        episode_id="episode:carril7:p1", surface=surface,
        normalized_surface=normalize_surface(surface), start=0, end=len(surface),
        bbox=None, time_start=None, time_end=None,
        type_candidates=[{"type": mtype, "confidence": 0.92}],
        confidence=conf, coreference_candidates=[],
        evidence_fragment_ids=["fragment:p1:0"], partida_id=partida,
    )


# -- Catalogos ---------------------------------------------------------------
# CASO 1: la entidad existente del diferencial del supervisor.
MAREA_NEGRA = CatalogEntity(
    entity_id="entity:faction:marea-negra", workspace=WS, entity_type="Faction",
    canonical_name="Marea Negra", aliases=("la Marea",),
)
# CASO 3: rival GENUINAMENTE plausible — comparte el MISMO alias exacto.
MAREA_ROJA_AMBIGUA = CatalogEntity(
    entity_id="entity:faction:marea-roja", workspace=WS, entity_type="Faction",
    canonical_name="Marea Roja", aliases=("la Marea",),
)
# CASO 2: los objetos existentes del escenario multipartida (capa juego, lore).
COFRADIA = CatalogEntity(
    entity_id="entity:cofradia-ambar", workspace=WS, entity_type="Faction",
    canonical_name="Cofradia de Ambar", aliases=(), partida_id=None,
)
CONSEJO = CatalogEntity(
    entity_id="entity:consejo-umbra", workspace=WS, entity_type="Faction",
    canonical_name="Consejo de Umbra", aliases=(), partida_id=None,
)
SELA = CatalogEntity(
    entity_id="entity:sela-marrec", workspace=WS, entity_type="Character",
    canonical_name="Sela Marrec", aliases=(), partida_id=None,
)


def trace(nombre, surface, entities, *, partida=None, mtype="Faction",
          espera_action=None, espera_entity="__sin_comprobar__", prohibe=()):
    cat = InMemoryEntityCatalog(entities)
    res = EntityResolver(catalog=cat, similarity=TrigramJaccardSimilarity())
    req = ResolutionRequest.of(
        mention("mention:" + nombre, surface, mtype=mtype, partida=partida)
    )
    env = _read_envelope(req.mentions)
    ctx = _build_context(req, env)
    ctx.entities = tuple(cat.entities(WS, partida_scope=env.partida_id))
    casc = run_cascade(ctx, DEFAULT_CONFIG, similarity=TrigramJaccardSimilarity())
    out = res.resolve(req)
    d = out.resolution

    print("\n=== %s ===" % nombre)
    print("  superficie            : %r   (partida_scope=%s)" % (surface, partida))
    print("  normalized_surfaces   : %s          <-- ESLABON" % (ctx.normalized_surfaces,))
    print("  candidatos:")
    for c in casc.candidates:
        print("     %-34s raw=%.4f  score=%.4f  %s"
              % (c.entity_id, c.raw_score, c.score, list(c.reason_codes)))
    if not casc.candidates:
        print("     (ninguno)")
    print("  ACTION                : %s" % out.action)
    print("  entity_id             : %s" % out.entity_id)
    print("  confidence            : %s" % d.confidence)
    print("  reason_codes          : %s" % (d.reason_codes,))

    if espera_action is not None:
        esperados = espera_action if isinstance(espera_action, tuple) else (espera_action,)
        ok_a = out.action in esperados
        print("  ESPERADO action       : %s -> %s" % (espera_action, "OK" if ok_a else "FALLA"))
        if not ok_a:
            FALLOS.append("%s: action=%s, esperado %s" % (nombre, out.action, espera_action))
    if espera_entity != "__sin_comprobar__":
        ok_e = out.entity_id == espera_entity
        print("  ESPERADO entity_id    : %s -> %s" % (espera_entity, "OK" if ok_e else "FALLA"))
        if not ok_e:
            FALLOS.append("%s: entity_id=%s, esperado %s"
                          % (nombre, out.entity_id, espera_entity))
    if prohibe:
        ok_p = out.entity_id not in prohibe
        print("  NO debe enlazar con   : %s -> %s" % (list(prohibe), "OK" if ok_p else "FALLA"))
        if not ok_p:
            FALLOS.append("%s: enlazo con %s pese a ser ambiguo"
                          % (nombre, out.entity_id))
    return out


if __name__ == "__main__":
    print("#" * 74)
    print("# CASO 1 - el articulo (diferencial del supervisor independiente)")
    print("#" * 74)
    trace("c1-sin-articulo", "Marea Negra", [MAREA_NEGRA],
          espera_action="LINK_EXISTING", espera_entity="entity:faction:marea-negra")
    trace("c1-con-articulo", "la Marea Negra", [MAREA_NEGRA],
          espera_action="LINK_EXISTING", espera_entity="entity:faction:marea-negra")

    print("\n" + "#" * 74)
    print("# CASO 2 - objetos EXISTENTES del escenario multipartida")
    print("#   superficies literales del escenario de tanda6, en ambito de partida")
    print("#" * 74)
    LORE = [SELA, COFRADIA, CONSEJO]
    trace("c2-cofradia", "la Cofradia de Ambar", LORE, partida=PARTIDA_A,
          espera_action="LINK_EXISTING", espera_entity="entity:cofradia-ambar")
    trace("c2-consejo", "del Consejo de Umbra", LORE, partida=PARTIDA_A,
          espera_action="LINK_EXISTING", espera_entity="entity:consejo-umbra")
    trace("c2-sujeto", "Sela Marrec", LORE, partida=PARTIDA_A, mtype="Character",
          espera_action="LINK_EXISTING", espera_entity="entity:sela-marrec")

    print("\n" + "#" * 74)
    print("# CASO 3 - ambiguedad GENUINA: DEBE seguir degradando")
    print("#   dos entidades comparten el MISMO alias exacto 'la Marea'")
    print("#" * 74)
    trace("c3-ambiguo", "la Marea", [MAREA_NEGRA, MAREA_ROJA_AMBIGUA],
          espera_action=("REVIEW", "CREATE_PROVISIONAL"),
          prohibe=("entity:faction:marea-negra", "entity:faction:marea-roja"))
    trace("c3-ambiguo-sin-articulo", "Marea", [MAREA_NEGRA, MAREA_ROJA_AMBIGUA],
          espera_action=("REVIEW", "CREATE_PROVISIONAL"),
          prohibe=("entity:faction:marea-negra", "entity:faction:marea-roja"))

    print("\n" + "=" * 74)
    if FALLOS:
        print("RESULTADO: %d expectativa(s) INCUMPLIDA(S)" % len(FALLOS))
        for f in FALLOS:
            print("   - " + f)
        sys.exit(1)
    print("RESULTADO: todas las expectativas se cumplen")
