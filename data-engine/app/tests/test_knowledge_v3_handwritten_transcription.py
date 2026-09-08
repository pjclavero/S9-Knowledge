# -*- coding: utf-8 -*-
"""Criterios de aceptacion del carril TRANSCRIBED_TEXT (encargo V3/29)."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Checkpoint vigente de los contratos congelados. Lo avanza QUIEN INTEGRA, no
#: un carril, y siempre registrando el valor viejo y el nuevo (ver el comentario
#: de `test_19_contratos_congelados_mantienen_su_hash`).
FROZEN_CONTRACTS_REF = "v3-contracts-frozen-1.0.0-int11"

#: Raices congeladas byte a byte por el gate de contratos.
_FROZEN_ROOTS = (
    "contracts/knowledge-v3/v1",
    "data-engine/app/knowledge_v3/contracts",
)


def _no_es_ruido(partes) -> bool:
    return not any(p in ("__pycache__", "tests", "examples") for p in partes)


def _frozen_tree_files() -> list[Path]:
    """Los ficheros de contrato del ARBOL DE TRABAJO, en orden estable."""
    return sorted(
        path
        for root in _FROZEN_ROOTS
        for path in (_REPO_ROOT / root).rglob("*")
        if path.is_file() and _no_es_ruido(path.parts)
    )


def _frozen_ref_paths(ref: str) -> list[str]:
    """Las rutas que ese checkpoint congelo."""
    salida = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", *_FROZEN_ROOTS],
        cwd=_REPO_ROOT,
        text=True,
    ).splitlines()
    return [p for p in salida if _no_es_ruido(p.split("/"))]


def _frozen_digest(pares) -> str:
    """Digest de (ruta, contenido).

    UNA sola definicion a proposito: el gate y su control negativo comparten
    exactamente este calculo. Si el control usase una copia, demostraria que
    muerde la copia, no el gate.
    """
    result = hashlib.sha256()
    for relative_path, content in pares:
        result.update(relative_path.encode())
        result.update(b"\0")
        result.update(content.replace(b"\r\n", b"\n"))
    return result.hexdigest()


def _digest_del_checkpoint(ref: str, rutas: list[str]) -> str:
    return _frozen_digest(
        (
            r,
            subprocess.check_output(["git", "show", f"{ref}:{r}"], cwd=_REPO_ROOT),
        )
        for r in rutas
    )
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from knowledge_v3.multimodal import IngestOptions, normalize_bytes  # noqa: E402
from knowledge_v3.multimodal.registry import default_registry  # noqa: E402
from knowledge_v3.multimodal.transcription import (  # noqa: E402
    COHERENCE_PROMPT,
    TRANSCRIPTION_FAMILY,
    TRANSCRIPTION_PROMPT,
    CoherenceRequest,
    NvidiaCoherenceReviewer,
    NvidiaVisionTranscriber,
    TranscriptionCascade,
    TranscriptionReading,
    literal_diff,
    risk_spans,
)

IMAGE = b"\x89PNG\r\n\x1a\nmanuscrito-real-simulado-en-el-puerto"
BASE_GLOSSARY = {
    "la", "puerta", "sigue", "cerrada", "el", "grupo", "llega", "al",
    "amanecer", "linea", "sin", "duda", "ve", "a", "en", "norte",
    "es", "aliada", "hoy", "nota", "dice", "que", "sale",
}


class ScriptedVLM:
    def __init__(self, model: str, *texts: str) -> None:
        self.model = model
        self.texts = list(texts)
        self.requests = []

    def transcribe(self, request):
        self.requests.append(request)
        text = self.texts[min(len(self.requests) - 1, len(self.texts) - 1)]
        return TranscriptionReading(
            text=text,
            model=self.model,
            provider="external",
            name="scripted-vlm",
            version="test",
        )


class ScriptedCoherence:
    model = "text-coherence-model"

    def __init__(self, coherent: bool) -> None:
        self.coherent = coherent
        self.requests: list[CoherenceRequest] = []

    def review(self, request: CoherenceRequest) -> bool:
        self.requests.append(request)
        return self.coherent


def cascade(
    first: str,
    second: str | None = None,
    *,
    coherent: bool = True,
    glossary=BASE_GLOSSARY,
):
    primary = ScriptedVLM("vision-primary", first)
    secondary = ScriptedVLM("vision-secondary", second if second is not None else first)
    reviewer = ScriptedCoherence(coherent)
    built = TranscriptionCascade(
        primary, secondary, reviewer, glossary=frozenset(glossary)
    )
    return built, primary, secondary, reviewer


def options(**overrides):
    values = {
        "workspace": "transcription-tests",
        "collection_id": "notes",
        "ingested_at": "2026-07-29T12:00:00Z",
        "privacy_class": "INTERNAL",
        "allow_external_providers": True,
        "language_hint": "es",
    }
    values.update(overrides)
    return IngestOptions(**values)


def normalize(provider, *, payload=None, ingest_options=None):
    return normalize_bytes(
        IMAGE,
        original_name="sesion-12-pj.png",
        original_location="file:///notas/sesion-12-pj.png",
        source_kind="HANDWRITING",
        mime_type="image/png",
        payload={"ingested_by": "pj", **(payload or {})},
        options=ingest_options or options(),
        registry=default_registry(visual_provider=provider),
    )


def review_fragments(result):
    return [f for f in result.fragments if (f.metadata or {}).get("review_required")]


def test_01_imprenta_limpia_no_escala_y_revision_cero():
    provider, _, secondary, _ = cascade("la puerta sigue cerrada")
    result = normalize(provider)
    assert not secondary.requests
    assert not review_fragments(result)
    assert result.report["transcription_metrics"]["s9_transcription_review_fraction"] == 0


def test_02_incoherencia_escala_una_palabra_emborronada():
    provider, _, secondary, _ = cascade(
        "la puerta [ilegible] cerrada", coherent=False
    )
    normalize(provider)
    assert len(secondary.requests) == 1


def test_03_nombre_propio_coherente_escala_por_riesgo():
    provider, _, secondary, _ = cascade(
        "el grupo ve a Narek", glossary=BASE_GLOSSARY | {"narek"}
    )
    normalize(provider)
    assert len(secondary.requests) == 1


@pytest.mark.parametrize("text", ["el grupo llega en 1247", "el grupo llega 12/03/1247"])
def test_04_numero_o_fecha_siempre_escala(text):
    provider, _, secondary, _ = cascade(text)
    normalize(provider)
    assert len(secondary.requests) == 1


def test_05_termino_fuera_del_glosario_escala():
    provider, _, secondary, _ = cascade("la puerta zharakai")
    normalize(provider)
    assert len(secondary.requests) == 1


def test_06_dos_lecturas_identicas_aceptan_sin_revision():
    provider, _, _, _ = cascade("el grupo ve a Narek")
    result = normalize(provider)
    assert not review_fragments(result)
    assert result.report["transcription_metrics"]["s9_transcription_disagreed_total"] == 0


def test_07_dos_lecturas_distintas_marcan_solo_la_palabra():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    result = normalize(provider)
    marked = review_fragments(result)
    assert [item.literal_text for item in marked] == ["Narek"]
    assert any(not (f.metadata or {}).get("review_required") for f in result.fragments)
    assert not result.episodes[0].metadata.get("review_required")


def test_08_cuarenta_lineas_dos_dudas_dejan_38_lineas_limpias():
    lines = [f"linea sin duda {i}" for i in range(1, 41)]
    first = "\n".join(lines)
    second_lines = list(lines)
    second_lines[9] = "linea sin duda diez"
    second_lines[29] = "linea sin duda treinta"
    provider, _, _, _ = cascade(first, "\n".join(second_lines))
    result = normalize(provider)
    marked_lines = {(f.metadata or {}).get("line") for f in review_fragments(result)}
    clean_lines = {
        (f.metadata or {}).get("line")
        for f in result.fragments
        if not (f.metadata or {}).get("review_required")
    }
    assert marked_lines == {10, 30}
    assert len(clean_lines - marked_lines) == 38


def test_09_tramo_dudoso_no_bloquea_ingesta():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    result = normalize(provider)
    assert result.episodes[0].text == "el grupo ve a Narek"
    assert review_fragments(result)[0].confidence == 0.5
    result.validate()


def test_10_ilegible_se_conserva_y_no_se_adivina():
    provider, _, _, _ = cascade("la puerta [ilegible] cerrada")
    result = normalize(provider)
    assert "[ilegible]" in result.episodes[0].text
    assert "plausible" not in result.episodes[0].text


def test_11_prompt_prohibe_normalizar_y_exige_preservacion_literal():
    lower = TRANSCRIPTION_PROMPT.lower()
    assert all(word in lower for word in ("no interpretes", "no resumas", "no normalices"))
    assert "no completes" in lower and "[ilegible]" in lower
    assert all(word in lower for word in ("ortografia", "mayusculas", "puntuacion"))


def test_12_diff_literal_no_invoca_ningun_modelo():
    assert literal_diff("Narek llega", "Narok llega")[0].start == 0


def test_13_codigo_no_contiene_validacion_contra_grafo():
    source = (_APP_DIR / "knowledge_v3/multimodal/transcription.py").read_text("utf-8")
    assert "neo4j" not in source.casefold()
    assert "graph" not in source.casefold()
    assert "resolution" not in source.casefold()


def test_14_nombre_conocido_no_aumenta_confianza():
    known, _, _, _ = cascade(
        "el grupo ve a Narek", "el grupo ve a Narok", glossary=BASE_GLOSSARY | {"narek"}
    )
    unknown, _, _, _ = cascade(
        "el grupo ve a Narek", "el grupo ve a Narok", glossary=BASE_GLOSSARY
    )
    assert review_fragments(normalize(known))[0].confidence == 0.5
    assert review_fragments(normalize(unknown))[0].confidence == 0.5


def test_15_peticion_vlm_no_tiene_bboxes_ni_coordenadas():
    provider, primary, _, _ = cascade("la puerta sigue cerrada")
    normalize(provider)
    request = primary.requests[0]
    assert not hasattr(request, "bbox")
    assert "coordenadas" in request.prompt.lower()
    assert "devuelvas coordenadas" in request.prompt.lower()


def test_16_offsets_son_de_transcripcion_y_hash_es_propio_del_episodio():
    text = "el grupo ve a Narek"
    provider, _, _, _ = cascade(text, "el grupo ve a Narok")
    result = normalize(provider)
    episode = result.episodes[0]
    for fragment in result.fragments:
        assert episode.text[fragment.start:fragment.end] == fragment.literal_text
        assert fragment.bbox is None
        assert fragment.metadata["anchor"] == "transcription_offsets"
    assert episode.content_hash["value"] != result.asset.content_hash["value"]


def test_17_metadata_funciona_sin_campos_opcionales():
    provider, _, _, _ = cascade("la puerta sigue cerrada")
    metadata = normalize(provider).episodes[0].metadata
    assert metadata["source_file"] == "sesion-12-pj.png"
    assert metadata["ingested_by"] == "pj"
    assert not any(
        key in metadata
        for key in ("author_hint", "perspective_hint", "session_id", "in_game_date")
    )


def test_18_autor_y_perspectiva_se_conservan_separados():
    provider, _, _, _ = cascade("la puerta sigue cerrada")
    metadata = normalize(
        provider,
        payload={"author_hint": "master", "perspective_hint": "Elara"},
    ).episodes[0].metadata
    assert metadata["author_hint"] == "master"
    assert metadata["perspective_hint"] == "Elara"


def test_19_contratos_congelados_mantienen_su_hash():
    # M0 (docs/v3/49-multipartida-diseno.md §8): `partida_id`/`scope` se
    # anadieron de forma aditiva a los contratos v1 (SourceAsset,
    # ClaimProposal, GraphMutationPlan). El tag `v3-contracts-frozen-1.0.0`
    # sigue existiendo e intacto para quien ancle contra el estado previo;
    # M0 avanzo al checkpoint `v3-contracts-frozen-1.0.0-m0`.
    #
    # M2 (docs/v3/49-multipartida-diseno.md, "Politica de version de
    # contratos v1 del programa"): `partida_id` opcional, mismo criterio
    # aditivo, ahora tambien en EntityMention/EntityResolution (el resolutor
    # necesitaba el campo para acotar el ambito visible). Nuevo checkpoint:
    # `v3-contracts-frozen-1.0.0-m2`.
    #
    # M3 (docs/v3/49-multipartida-diseno.md SS11 "M3 implementado"): sin
    # cambios de ESQUEMA (M3 no toco JSON Schema ni dataclasses de
    # contratos) -- el freeze avanza solo porque `validator.py`
    # (DECISION_HASH_FIELDS/IDEMPOTENCY_KEY_FIELDS) y `mutation_plan.py`
    # ganaron comentarios que documentan, con verificacion, por que esos dos
    # huecos heredados de M0 se dejan abiertos en M3 (writer/admission.py ya
    # consume partida_id/scope, pero ningun dataset congelado lo declara
    # hoy). Nuevo checkpoint: `v3-contracts-frozen-1.0.0-m3`.
    #
    # M4 (docs/v3/49-multipartida-diseno.md SS12 "M4 implementado"):
    # `FactAssertion` gana `local_override_of` (aditivo, opcional, mismo
    # patron que M0/M2) en `contracts/assertion.py` y en
    # `fact-assertion-v3.schema.json`, mas un chequeo semantico de
    # autoreferencia en `validator.py`. Nuevo checkpoint:
    # `v3-contracts-frozen-1.0.0-m4`.
    #
    # GATE4-03 (carril A, docs/v3/53-ingesta-real-vertical-slice.md SS2): la
    # correccion del defecto real de `SourceEpisode.from_dict` toca
    # `contracts/episode.py`, que este gate congela BYTE A BYTE. El cambio es
    # ADITIVO y no altera la serializacion (`speaker`/`turn`/`table` ganan
    # `default=None` pero NO entran en `OMIT_IF_NONE`, porque el schema los
    # declara nullable), asi que `to_dict()` sigue emitiendolos con `null`.
    # Aun asi el digest cambia, y CAMBIAR ESTA CONSTANTE NO ES DECISION DEL
    # CARRIL: el checkpoint lo avanza quien integra, creando el tag nuevo sobre
    # el arbol ya revisado —igual que se hizo en M0, M2, M3 y M4— y poniendolo
    # aqui.
    #
    # INTEGRACION tanda 3: hecho. El checkpoint avanza a
    # `v3-contracts-frozen-1.0.0-gate4-03`, creado sobre el arbol integrado y
    # ya revisado. Los dos valores quedan registrados para que el avance sea
    # auditable y no un borron:
    #
    #   digest anterior (m4)    51cb491e727cf7d92d7e429a057f67d46aa1ad6ee3d09c57fd72e1d1d89e18e7
    #   digest nuevo (gate4-03) b36fbb3e2d1353c6ab230f21368966b587b6a573b903e6e9f323086a5e611216
    #
    # Unico cambio de contrato entre ambos: el `episode.py` de arriba. Las 23
    # rutas congeladas son las mismas en los dos checkpoints.
    #
    # EQUIPO 5A (ambito de partida + ruta de esquema): ESTE TEST ESTA ROJO A
    # PROPOSITO EN LA RAMA DEL EQUIPO, Y NO SE TOCA LA CONSTANTE.
    #
    # El carril cambia UNA de las 23 rutas congeladas:
    # `contracts/knowledge-v3/v1/validator.py`. VERIFICADO con
    # `git diff --name-only v3-contracts-frozen-1.0.0-gate4-03 HEAD --
    # contracts/ .../knowledge_v3/contracts/`, que devuelve ese fichero y
    # ninguno mas. Las 23 rutas siguen siendo las mismas.
    #
    #   digest anterior (gate4-03) b36fbb3e2d1353c6ab230f21368966b587b6a573b903e6e9f323086a5e611216
    #   digest de esta rama        9e7ce73a2ee0aaba462921a3af1efcfdd5fbec1a249c7385fd7e722938f8e96b
    #
    # QUE CAMBIA Y POR QUE NO ES UN BORRON: `compute_idempotency_key` mete
    # `partida_id` en el cuerpo de la clave SOLO cuando no es nulo. No se
    # toca `IDEMPOTENCY_KEY_FIELDS` ni `DECISION_HASH_FIELDS` --las dos
    # tuplas que M0/M3 declararon intocables--, no cambia ningun JSON Schema
    # y no cambia ninguna dataclass. Un plan que no declara ambito produce el
    # cuerpo IDENTICO de antes y, por tanto, la MISMA clave.
    #
    # MEDIDO, no supuesto: recomputando `compute_idempotency_key` sobre los
    # 21 documentos de plan sellados del repo, los unicos dos que cambian son
    # `contracts/knowledge-v3/v1/examples/invalid/plan_invented_idempotency_
    # key.json` y `plan_workspace_changed.json`, fixtures cuyo proposito ES
    # tener la clave mal. Cero documentos validos afectados; cero datasets
    # que regenerar.
    #
    # AVANZAR EL CHECKPOINT NO ES DECISION DE ESTE CARRIL, por la misma regla
    # que dejo escrita GATE4-03 unas lineas mas arriba: el tag nuevo lo crea
    # QUIEN INTEGRA, sobre el arbol ya revisado, y pone aqui el digest. Se
    # deja el rojo como la senal que es.
    #
    # INTEGRACION tanda 5: hecho. El carril 5A dejo este test ROJO A PROPOSITO
    # --pudiendo haberlo puesto verde solo-- porque `validator.py` es una de
    # las 23 rutas congeladas y la regla escrita aqui dice que el checkpoint lo
    # avanza QUIEN INTEGRA, sobre el arbol ya revisado. Se avanza a
    # `v3-contracts-frozen-1.0.0-int5`, y los dos valores quedan registrados
    # para que el avance sea auditable y no un borron:
    #
    #   digest anterior (gate4-03) b36fbb3e2d1353c6ab230f21368966b587b6a573b903e6e9f323086a5e611216
    #   digest nuevo    (int5)     9e7ce73a2ee0aaba462921a3af1efcfdd5fbec1a249c7385fd7e722938f8e96b
    #
    # QUE CAMBIA, VERIFICADO POR EL INTEGRADOR Y NO ACEPTADO DE PALABRA
    # -----------------------------------------------------------------
    # `git diff --name-only` entre los dos tags, restringido a las dos raices
    # congeladas, devuelve `contracts/knowledge-v3/v1/validator.py` y NADA MAS.
    # Y comparando el AST de las dos versiones de ese fichero, las 14
    # constantes de modulo son IDENTICAS: `IDEMPOTENCY_KEY_FIELDS`,
    # `DECISION_HASH_FIELDS` y las demas no se tocan. El cambio es una insercion
    # limpia de 32 lineas en `compute_idempotency_key` que anade `partida_id` al
    # cuerpo SOLO cuando no es nulo, de modo que ningun plan sin ambito --que
    # son todos los de los datasets sellados-- cambia de clave. Ningun JSON
    # Schema y ninguna dataclass se tocan. Las 23 rutas congeladas son las
    # mismas en los dos checkpoints.
    #
    # Que el gate SIGUE MORDIENDO despues de avanzarlo no se presume: lo
    # demuestra `test_19b_control_negativo_...`, que inyecta un cambio
    # contractual real y comprueba que la comparacion se pone roja. Ese control
    # se CONSERVA intacto al avanzar --sigue mutando `episode.py`, que esta
    # congelado y que esta integracion no toca--, asi que sigue siendo una
    # prueba capaz de ponerse roja y no una copia del gate que siempre pasa.
    # INTEGRACION tanda 11: hecho. El equipo 11A dejo este test ROJO A PROPOSITO
    # --pudiendo haberlo puesto verde solo-- porque `validator.py` es una de las
    # 23 rutas congeladas y la regla escrita arriba dice que el checkpoint lo
    # avanza QUIEN INTEGRA, sobre el arbol ya revisado. Se avanza a
    # `v3-contracts-frozen-1.0.0-int11`, y los dos valores quedan registrados
    # para que el avance sea auditable y no un borron:
    #
    #   digest anterior (int5)  9e7ce73a2ee0aaba462921a3af1efcfdd5fbec1a249c7385fd7e722938f8e96b
    #   digest nuevo    (int11) 5676f7475159634c135a8df8543da5be6f2e8cc4562d22ba252583ba43bc3813
    #
    # QUE CAMBIA, VERIFICADO POR EL INTEGRADOR Y NO ACEPTADO DE PALABRA
    # -----------------------------------------------------------------
    # El diff de nombres entre int5 y HEAD, restringido a las dos raices
    # congeladas, devuelve `contracts/knowledge-v3/v1/validator.py` y NADA MAS.
    # Comparando el AST de las dos versiones de ese fichero: las 14 constantes
    # de modulo son IDENTICAS --`DECISION_HASH_FIELDS` e `IDEMPOTENCY_KEY_FIELDS`
    # incluidas--, no hay funciones nuevas ni eliminadas, y la UNICA funcion
    # modificada es `_check_plan`. Las 23 rutas congeladas son las mismas en los
    # dos checkpoints (comparadas ruta a ruta, no por recuento).
    #
    # QUE HACE EL CAMBIO Y POR QUE NO AFLOJA EL CONTRATO: una `PROJECT_RELATION`
    # con `expected_state=WOULD_CREATE` cuyo extremo lo da de alta ESE MISMO
    # plan cuenta como creacion, y por tanto puede traer `expected_version` y
    # `expected_hash` nulos. No es aflojar la regla "modificar algo existente
    # exige version y hash": es que ahi no hay nada existente todavia, y el
    # propio validador EXIGE que el `CREATE_ENTITY` del extremo este de verdad
    # en el plan. Sin esa alta, la operacion vuelve a necesitar version y hash.
    #
    # Que el gate SIGUE MORDIENDO despues de avanzarlo no se presume: lo
    # demuestra `test_19b_control_negativo_...`, que se CONSERVA intacto --sigue
    # mutando `episode.py`, congelado y que esta integracion no toca-- y que
    # esta integracion ha verificado que se pone rojo al mutar.
    frozen_ref = FROZEN_CONTRACTS_REF
    files = _frozen_tree_files()
    relative_paths = [path.relative_to(_REPO_ROOT).as_posix() for path in files]
    frozen_paths = _frozen_ref_paths(frozen_ref)

    assert len(files) == 23
    assert relative_paths == frozen_paths
    current_digest = _frozen_digest(
        (r, path.read_bytes()) for r, path in zip(relative_paths, files, strict=True)
    )
    frozen_digest = _digest_del_checkpoint(frozen_ref, frozen_paths)
    assert current_digest == frozen_digest



def test_19b_control_negativo_un_cambio_contractual_real_sigue_poniendolo_rojo():
    """El gate de contratos SIGUE MORDIENDO despues de avanzar el checkpoint.

    Avanzar un freeze es exactamente el momento en que se puede desactivar sin
    querer: basta con que el nuevo sujeto se calcule de una forma que ya no
    dependa del contenido, y el gate pasa a estar verde para siempre sin que
    nadie lo note. Esto lo impide midiendolo.

    NO es un gate nuevo ni un meta-gate: no bloquea nada por su cuenta y no
    congela nada que no estuviese congelado. Es el control negativo del gate
    que ya existe -- la prueba de que puede ponerse rojo.

    El cambio inyectado es CONTRACTUAL DE VERDAD, no un byte al azar: se le
    quita a `SourceEpisode` el `default=None` de `speaker` que GATE4-03 acaba
    de anadir. Es exactamente la clase de cambio que el freeze existe para
    interceptar. Y se inyecta EN MEMORIA: el arbol de trabajo no se toca.
    """
    frozen_paths = _frozen_ref_paths(FROZEN_CONTRACTS_REF)
    files = _frozen_tree_files()
    relative_paths = [path.relative_to(_REPO_ROOT).as_posix() for path in files]
    assert relative_paths == frozen_paths

    objetivo = "data-engine/app/knowledge_v3/contracts/episode.py"
    assert objetivo in relative_paths, "el fichero mutado tiene que estar congelado"

    contenidos = {r: f.read_bytes() for r, f in zip(relative_paths, files, strict=True)}

    # Control POSITIVO primero: sin mutar, el gate esta verde. Sin esto, un
    # rojo del control negativo podria venir de cualquier otra cosa.
    limpio = _frozen_digest((r, contenidos[r]) for r in relative_paths)
    congelado = _digest_del_checkpoint(FROZEN_CONTRACTS_REF, frozen_paths)
    assert limpio == congelado, (
        "el control negativo no vale si el arbol ya diverge del checkpoint"
    )

    original = contenidos[objetivo]
    mutado = original.replace(b"speaker: Optional[dict] = None", b"speaker: Optional[dict]")
    assert mutado != original, (
        "la mutacion no se aplico: el texto que se esperaba mutar ya no esta en "
        f"{objetivo}, asi que este control no estaria probando nada"
    )
    contenidos[objetivo] = mutado

    sucio = _frozen_digest((r, contenidos[r]) for r in relative_paths)
    assert sucio != congelado, (
        "el gate de contratos NO muerde: un cambio contractual real deja el "
        "digest igual. El freeze estaria desactivado."
    )

def test_20_determinismo_en_diez_pasadas():
    outputs = []
    for _ in range(10):
        provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
        result = normalize(provider)
        outputs.append(
            (
                [episode.to_json() for episode in result.episodes],
                [fragment.to_json() for fragment in result.fragments],
            )
        )
    assert all(output == outputs[0] for output in outputs)


def test_familia_y_modelos_distintos_quedan_declarados():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    metadata = normalize(provider).episodes[0].metadata
    assert metadata["family"] == TRANSCRIPTION_FAMILY
    assert metadata["transcription_models"] == ["vision-primary", "vision-secondary"]


def test_no_se_permiten_dos_lecturas_del_mismo_modelo():
    with pytest.raises(ValueError, match="modelos distintos"):
        TranscriptionCascade(
            ScriptedVLM("same", "texto"),
            ScriptedVLM("same", "texto"),
            ScriptedCoherence(True),
        )


def test_revision_de_coherencia_solo_recibe_texto():
    provider, _, _, reviewer = cascade("la puerta sigue cerrada")
    normalize(provider)
    request = reviewer.requests[0]
    assert request.text == "la puerta sigue cerrada"
    assert not hasattr(request, "data")
    assert "conocimiento externo" in COHERENCE_PROMPT.lower()


def test_contenido_privado_se_bloquea_antes_del_primer_vlm():
    provider, primary, _, _ = cascade("la puerta sigue cerrada")
    with pytest.raises(Exception, match="privacy_class=PERSONAL_DATA"):
        normalize(
            provider,
            ingest_options=options(
                privacy_class="PERSONAL_DATA", allow_external_providers=True
            ),
        )
    assert not primary.requests


def test_metricas_obligatorias_estan_expuestas():
    provider, _, _, _ = cascade("el grupo ve a Narek", "el grupo ve a Narok")
    metrics = normalize(provider).report["transcription_metrics"]
    assert set(metrics) == {
        "s9_transcription_pages_total",
        "s9_transcription_spans_total",
        "s9_transcription_escalated_total",
        "s9_transcription_disagreed_total",
        "s9_transcription_to_review_total",
        "s9_transcription_review_fraction",
        's9_stage_duration_seconds{stage="transcription"}',
    }
    assert metrics["s9_transcription_review_fraction"] == pytest.approx(1 / 5)


class FakeNvidiaClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.guarded = []
        self.messages = []

    def _assert_safe_to_send(self, payload):
        self.guarded.append(payload)

    def chat_json(self, messages, *, model, max_tokens):
        self.messages.append((messages, model, max_tokens))
        return self.responses.pop(0)


def test_adaptadores_nvidia_usan_guarda_y_no_mandan_imagen_al_revisor():
    client = FakeNvidiaClient(
        [
            {"parsed": {"transcription": "Texto literal"}, "model": "vision"},
            {"parsed": {"coherent": True}, "model": "text"},
        ]
    )
    reading = NvidiaVisionTranscriber(client, model="vision").transcribe(
        type("R", (), {
            "data": IMAGE,
            "mime_type": "image/png",
            "language_hint": "es",
            "prompt": TRANSCRIPTION_PROMPT,
        })()
    )
    coherent = NvidiaCoherenceReviewer(client, model="text").review(
        CoherenceRequest(reading.text)
    )
    assert coherent is True
    assert "data:image/png;base64," in str(client.messages[0][0])
    assert "data:image" not in str(client.messages[1][0])
    assert len(client.guarded) == 2
