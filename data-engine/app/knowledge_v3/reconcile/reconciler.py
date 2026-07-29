# -*- coding: utf-8 -*-
"""Implementacion pura del ProposalReconciler."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from ..contracts import ClaimProposal, EntityMention
from ..extraction.base import Diagnostic, ExtractionOutput
from .canonical import (
    RECONCILIATION_METADATA_KEY,
    canonical_trace,
    claim_key,
    claim_sort_key,
    mention_key,
    mention_sort_key,
    sort_alternatives,
    sort_direction_candidates,
    sort_predicate_candidates,
    sort_type_candidates,
    stable_unique,
    without_reconciliation_metadata,
)
from .config import DEFAULT_RECONCILER_CONFIG, ReconcilerConfig
from .families import Origin
from .models import ReconcileResult, ReconcileStats

RECONCILE_STEP = "reconcile.proposals"


class ProposalReconciler:
    """Alinea propuestas que apuntan a la misma aparicion textual.

    No resuelve identidades ni decide hechos: solo reescribe IDs equivalentes,
    combina candidatos contractuales y conserva la procedencia en metadata.
    """

    def __init__(self, config: ReconcilerConfig = DEFAULT_RECONCILER_CONFIG) -> None:
        self.config = config

    def reconcile(self, output: ExtractionOutput) -> ExtractionOutput:
        return self.run(output).output

    def run(self, output: ExtractionOutput) -> ReconcileResult:
        started = time.perf_counter()
        self._check_single_workspace(output)

        mention_groups = self._group_mentions(output.mentions)
        mention_merge_keys = {
            key for key, group in mention_groups.items() if len({m.mention_id for m in group}) > 1
        }
        mention_map = self._mention_id_map(mention_groups, mention_merge_keys)

        preliminary_claims, orphan_diagnostics, rewritten_unknowns = self._rewrite_claims(
            output.claims, mention_map, set(mention_map.values()) or {m.mention_id for m in output.mentions}
        )
        claim_groups = self._group_claims(preliminary_claims)
        claim_merge_keys = {
            key for key, group in claim_groups.items() if len({c.claim_id for c in group}) > 1
        }

        duration = (time.perf_counter() - started) * 1000.0
        if not mention_merge_keys and not claim_merge_keys and not orphan_diagnostics:
            return ReconcileResult(
                output=output,
                stats=ReconcileStats(
                    input_mentions=len(output.mentions),
                    output_mentions=len(output.mentions),
                    input_claims=len(output.claims),
                    output_claims=len(output.claims),
                    duration_ms=duration,
                ),
            )

        diagnostics = list(output.diagnostics)
        diagnostics.extend(orphan_diagnostics)
        unknown_families = rewritten_unknowns

        merged_mentions: list[EntityMention] = []
        for key, group in sorted(mention_groups.items()):
            if key in mention_merge_keys:
                mention, unknown = self._merge_mentions(key, group, mention_map)
                unknown_families += unknown
                diagnostics.append(
                    Diagnostic(
                        "RECONCILE_MENTION_MERGED",
                        RECONCILE_STEP,
                        mention.episode_id,
                        ",".join(sorted(m.mention_id for m in group)),
                    )
                )
                merged_mentions.append(mention)
            else:
                for mention in group:
                    if mention.coreference_candidates:
                        mention = self._rewrite_mention_coreferences(mention, mention_map)
                    merged_mentions.append(mention)

        final_claim_groups = self._group_claims(preliminary_claims)
        merged_claims: list[ClaimProposal] = []
        for key, group in sorted(final_claim_groups.items()):
            if key in claim_merge_keys:
                claim, unknown = self._merge_claims(key, group)
                unknown_families += unknown
                diagnostics.append(
                    Diagnostic(
                        "RECONCILE_CLAIM_MERGED",
                        RECONCILE_STEP,
                        claim.episode_id,
                        ",".join(sorted(c.claim_id for c in group)),
                    )
                )
                merged_claims.append(claim)
            else:
                merged_claims.extend(group)

        if unknown_families:
            diagnostics.append(
                Diagnostic(
                    "RECONCILE_UNKNOWN_INDEPENDENCE_FAMILY",
                    RECONCILE_STEP,
                    "",
                    str(unknown_families),
                )
            )

        merged_mentions.sort(key=mention_sort_key)
        merged_claims.sort(key=claim_sort_key)
        if self.config.validate_output:
            for doc in (*merged_mentions, *merged_claims):
                doc.validate()

        duration = (time.perf_counter() - started) * 1000.0
        result = ExtractionOutput(
            mentions=merged_mentions,
            claims=merged_claims,
            diagnostics=diagnostics,
        )
        return ReconcileResult(
            output=result,
            stats=ReconcileStats(
                input_mentions=len(output.mentions),
                output_mentions=len(merged_mentions),
                input_claims=len(output.claims),
                output_claims=len(merged_claims),
                mention_groups=len(mention_merge_keys),
                claim_groups=len(claim_merge_keys),
                mentions_merged=len(output.mentions) - len(merged_mentions),
                claims_merged=len(output.claims) - len(merged_claims),
                preserved_ambiguous=0,
                unknown_families=unknown_families,
                duration_ms=duration,
            ),
        )

    @staticmethod
    def _check_single_workspace(output: ExtractionOutput) -> None:
        workspaces = {d.workspace for d in (*output.mentions, *output.claims)}
        if len(workspaces) > 1:
            raise ValueError(f"reconciliacion con multiples workspaces: {sorted(workspaces)}")

    @staticmethod
    def _group_mentions(mentions: Iterable[EntityMention]) -> dict:
        groups: dict = defaultdict(list)
        for mention in mentions:
            groups[mention_key(mention)].append(mention)
        for group in groups.values():
            group.sort(key=mention_sort_key)
        return groups

    def _mention_id_map(self, groups: dict, merge_keys: set) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, group in groups.items():
            canonical_id = key.hash_id(self.config.canonical_mention_prefix)
            for mention in group:
                out[mention.mention_id] = canonical_id if key in merge_keys else mention.mention_id
        return out

    @staticmethod
    def _group_claims(claims: Iterable[ClaimProposal]) -> dict:
        groups: dict = defaultdict(list)
        for claim in claims:
            groups[claim_key(claim)].append(claim)
        for group in groups.values():
            group.sort(key=claim_sort_key)
        return groups

    def _rewrite_mention_coreferences(
        self, mention: EntityMention, mention_map: dict[str, str]
    ) -> EntityMention:
        rewritten = stable_unique(
            mention_map.get(candidate, candidate) for candidate in mention.coreference_candidates
        )
        filtered = [candidate for candidate in rewritten if candidate != mention.mention_id]
        if list(mention.coreference_candidates) == filtered:
            return mention
        return replace(mention, coreference_candidates=filtered)

    def _rewrite_claims(
        self,
        claims: Iterable[ClaimProposal],
        mention_map: dict[str, str],
        known_mentions: set[str],
    ) -> tuple[list[ClaimProposal], list[Diagnostic], int]:
        out: list[ClaimProposal] = []
        diagnostics: list[Diagnostic] = []
        unknown = 0
        for claim in claims:
            subject = list(stable_unique(mention_map.get(mid, mid) for mid in claim.subject_mentions))
            obj = list(stable_unique(mention_map.get(mid, mid) for mid in claim.object_mentions))
            missing = sorted((set(subject) | set(obj)) - known_mentions)
            if missing:
                diagnostics.append(
                    Diagnostic(
                        "RECONCILE_ORPHAN_CLAIM_REFERENCE",
                        RECONCILE_STEP,
                        claim.episode_id,
                        f"{claim.claim_id}: {missing}",
                    )
                )
            if subject == claim.subject_mentions and obj == claim.object_mentions:
                out.append(claim)
                continue
            metadata, metadata_unknown = self._merged_metadata_with_unknowns((claim,), claim_id_getter)
            unknown += metadata_unknown
            rewritten = replace(
                claim,
                claim_id=claim_key(replace(claim, subject_mentions=subject, object_mentions=obj)).hash_id(
                    self.config.canonical_claim_prefix
                ),
                subject_mentions=subject,
                object_mentions=obj,
                metadata=metadata,
            )
            if self.config.validate_output:
                rewritten.validate()
            out.append(rewritten)
        return out, diagnostics, unknown

    def _merge_mentions(
        self,
        key,
        group: list[EntityMention],
        mention_map: dict[str, str],
    ) -> tuple[EntityMention, int]:
        base = group[0]
        metadata, unknown = self._merged_metadata_with_unknowns(group, mention_id_getter)
        canonical_id = key.hash_id(self.config.canonical_mention_prefix)
        coref = stable_unique(
            mention_map.get(candidate, candidate)
            for mention in group
            for candidate in mention.coreference_candidates
            if candidate not in {m.mention_id for m in group}
        )
        merged = replace(
            base,
            provider_trace=canonical_trace(entry for m in group for entry in m.provider_trace),
            produced_by_step=base.produced_by_step,
            mention_id=canonical_id,
            type_candidates=sort_type_candidates(c for m in group for c in m.type_candidates),
            confidence=max(float(m.confidence) for m in group),
            coreference_candidates=[c for c in coref if c != canonical_id],
            evidence_fragment_ids=list(stable_unique(f for m in group for f in m.evidence_fragment_ids)),
            metadata=metadata,
        )
        if self.config.validate_output:
            merged.validate()
        return merged, unknown

    def _merge_claims(self, key, group: list[ClaimProposal]) -> tuple[ClaimProposal, int]:
        base = group[0]
        metadata, unknown = self._merged_metadata_with_unknowns(group, claim_id_getter)
        metadata[RECONCILIATION_METADATA_KEY]["predicate_candidate_origins"] = (
            self._candidate_origins(group, "predicate_candidates", "predicate", claim_id_getter)
        )
        metadata[RECONCILIATION_METADATA_KEY]["direction_candidate_origins"] = (
            self._candidate_origins(group, "direction_candidates", "direction", claim_id_getter)
        )
        confidence = 0.0 if base.abstained else max(float(c.confidence) for c in group)
        merged = replace(
            base,
            provider_trace=canonical_trace(entry for c in group for entry in c.provider_trace),
            produced_by_step=base.produced_by_step,
            claim_id=key.hash_id(self.config.canonical_claim_prefix),
            subject_mentions=list(stable_unique(mid for c in group for mid in c.subject_mentions)),
            object_mentions=list(stable_unique(mid for c in group for mid in c.object_mentions)),
            predicate_candidates=(
                [] if base.abstained else sort_predicate_candidates(
                    candidate for c in group for candidate in c.predicate_candidates
                )
            ),
            direction_candidates=sort_direction_candidates(
                candidate for c in group for candidate in c.direction_candidates
            ),
            confidence=confidence,
            alternatives=sort_alternatives(candidate for c in group for candidate in c.alternatives),
            metadata=metadata,
        )
        if self.config.validate_output:
            merged.validate()
        return merged, unknown

    def _merged_metadata_with_unknowns(self, docs: Iterable, id_getter) -> tuple[dict, int]:
        docs = tuple(docs)
        metadata = self._merged_metadata(docs, id_getter)
        unknown = sum(1 for doc in docs if not self.config.independence_registry.origin_for(doc)[1])
        return metadata, unknown

    def _merged_metadata(self, docs: Iterable, id_getter) -> dict:
        docs = tuple(docs)
        base_metadata = without_reconciliation_metadata(docs[0].metadata)
        origins: list[Origin] = []
        original_ids: set[str] = set()
        for doc in docs:
            meta = dict(doc.metadata or {})
            prior = meta.get(RECONCILIATION_METADATA_KEY) or {}
            original_ids.update(str(x) for x in prior.get("original_ids") or ())
            original_ids.add(id_getter(doc))
            origin, _known = self.config.independence_registry.origin_for(doc)
            origins.append(origin)
        providers = {origin.provider_key for origin in origins}
        families = {origin.family for origin in origins}
        base_metadata[RECONCILIATION_METADATA_KEY] = {
            "version": self.config.version,
            "independence_registry_version": self.config.independence_registry.version,
            "original_ids": sorted(original_ids),
            "support": {
                "proposals": len(docs),
                "providers": len(providers),
                "independent_families": len(families),
            },
            "origins": sorted(
                (origin.to_dict() for origin in origins),
                key=lambda item: (
                    item.get("family", ""),
                    item.get("step", ""),
                    item.get("provider", ""),
                    item.get("name", ""),
                    item.get("model", ""),
                ),
            ),
        }
        return base_metadata

    def _candidate_origins(self, docs: Iterable, attr: str, key: str, id_getter) -> list[dict]:
        out: list[dict] = []
        for doc in docs:
            origin, _known = self.config.independence_registry.origin_for(doc)
            for candidate in getattr(doc, attr):
                out.append(
                    {
                        key: str(candidate.get(key) or ""),
                        "confidence": float(candidate.get("confidence", 0.0)),
                        "proposal_id": id_getter(doc),
                        "origin": origin.to_dict(),
                    }
                )
        return sorted(
            out,
            key=lambda item: (
                item.get(key, ""),
                -float(item.get("confidence", 0.0)),
                item.get("proposal_id", ""),
                item["origin"].get("family", ""),
            ),
        )


def mention_id_getter(mention: EntityMention) -> str:
    return mention.mention_id


def claim_id_getter(claim: ClaimProposal) -> str:
    return claim.claim_id


__all__ = ["ProposalReconciler", "RECONCILE_STEP"]
