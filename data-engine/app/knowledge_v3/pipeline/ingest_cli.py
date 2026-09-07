# -*- coding: utf-8 -*-
"""Ingesta V3 de una fuente REAL de operador, en dry-run.

    export PYTHONPATH=data-engine/app
    python3 -m knowledge_v3.pipeline.ingest_cli <fichero> \
        --perfil examples/ingesta-v3/perfil-operador.json \
        --catalogo examples/ingesta-v3/catalogo-workspace.json \
        --dry-run

QUE ES ESTO Y QUE NO ES
-----------------------
`pipeline.runner` corre la cadena sobre un SPLIT DEL GOLD y la puntua con el
arnes. Es medicion, no operacion: sus fuentes son documentos del dataset y sus
identificadores estan redactados a mano. Este modulo es la otra puerta, la que
faltaba: coge **bytes de un fichero del operador**, los mete por el normalizador
real y publica lo que la cadena produjo.

    fichero -> SourceInput -> SourceCase -> episodios + evidencia
            -> extraccion -> reconciliacion -> resolucion -> motor -> plan

DE DONDE SALE EL MUNDO: DEL GRAFO, NO DE UN FICHERO
---------------------------------------------------
`--catalogo` lee de un JSON que entidades existen. Ese fichero y el grafo real
eran dos afirmaciones independientes sobre el mismo mundo, sin nada que las
contrastara: el fichero decia que `entity:sela-marrec` existe, el grafo estaba
vacio, y el APPLY abortaba con `EXEC_TARGET_MISSING`. La unica salida era
sembrar las entidades a mano por Cypher.

`--desde-grafo` cierra ese hueco: el catalogo se LEE del grafo (solo lectura,
`writer.reads.list_entities`) y cada mencion sale reconciliada como
`LINK_EXISTING` o `CREATE_ENTITY_REQUIRED`.

LAS ALTAS LAS APRUEBA UNA PERSONA
---------------------------------
`LINK_EXISTING` NO es "enlaza, y si no existe creala". Un enlace sin respaldo
en el grafo se DEGRADA a alta pendiente y se para. Las altas se aprueban por
id, una a una (`--revisar --aprobar-alta <id> --revisor <quien>`); no hay
"aprobar todas".

ESCRITURA REAL
--------------
`--dry-run` sigue siendo el defecto. `--apply` existe ahora, y NO relaja nada:
el gate del writer sigue mandando (`S9K_ALLOW_REAL_INGEST=1`,
`S9K_WRITER_WORKSPACE`, `--operador`, hash de plan confirmado por la propia
cadena), la contrasena no viaja por `argv` y sin documento de decisiones
revisado no se escribe. Los tres pasos del operador:

    ...ingest_cli fuente.md --perfil P --desde-grafo --out-dir DIR \
        --neo4j-uri "$S9K_NEO4J_URI" --neo4j-user neo4j \
        --neo4j-password-file /ruta/privada/neo4j.pass

    ...ingest_cli --revisar --decisiones DIR/decisiones.json \
        --revisor pjc --aprobar-alta entity:new:...

    S9K_ALLOW_REAL_INGEST=1 S9K_WRITER_WORKSPACE=ws \
    ...ingest_cli fuente.md --perfil P --apply --operador pjc \
        --decisiones DIR/decisiones.json --neo4j-...

DE DONDE SALE EL MUNDO
----------------------
El extractor determinista no tiene reconocedor de entidades propio: sus
menciones salen del GLOSARIO (alias del perfil + nombres del catalogo) o del
patron `<titulo declarado> <Nombre Propio>` (defecto D-6, `docs/v3/11-e2e.md`).
Por eso el CLI pide un perfil y admite un catalogo, y por eso, cuando el
glosario queda vacio, lo DECLARA (`SIN_GLOSARIO`) en vez de publicar un cero
mudo.

DETERMINISMO
------------
La cadena no llama al reloj: `--ahora` y `--ingerido-en` son datos. Si no se
dan, el CLI lee el reloj UNA vez, en la frontera, y lo declara en el informe;
dentro de la cadena sigue siendo un dato inyectado.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from ..contracts.base import sha256_hash
from ..contracts.game_profile import GameProfile
from ..driver_neo4j import (
    ENV_DATABASE,
    ENV_PASSWORD_FILE,
    ENV_URI,
    ENV_USER,
    DriverConfigError,
    build_driver_factory,
    resolve_config,
)
from ..extraction.lexicon import Lexicon, LexiconEntry
from ..multimodal.base import IngestOptions, SourceInput
from ..multimodal.registry import default_registry
from ..resolution.catalog import CatalogEntity, InMemoryEntityCatalog
from .config import PipelineConfig
from . import bridge
from .errors import PipelineError
from ..writer import exit_codes
from .ingest_report import ingest_report, to_markdown
from .pipeline import KnowledgePipeline, SourceCase
from . import entity_decisions, graph_catalog
from ..writer.rollback import add_provenance_sweep

#: Extension -> `source_kind`, solo para las que este CLI declara soportar de
#: verdad. Lo demas se le deja al registro de adaptadores, que resuelve por
#: MIME y extension y falla con un mensaje claro si no sabe.
KIND_BY_EXTENSION = {
    ".md": "MARKDOWN",
    ".markdown": "MARKDOWN",
    ".txt": "TEXT",
    ".text": "TEXT",
    ".note": "NOTE",
}


def _utc_now() -> str:
    """Reloj leido UNA vez, en la frontera. Dentro de la cadena es un dato."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_profile(path: Path, *, workspace: Optional[str] = None) -> GameProfile:
    """`GameProfile` del operador, validado contra el contrato congelado."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    profile = GameProfile.from_dict(doc)
    if workspace is not None and profile.workspace != workspace:
        raise PipelineError(
            "config",
            f"el perfil {path} es del workspace {profile.workspace!r} y se pidio "
            f"{workspace!r}. No se reescribe en silencio: corrige uno de los dos",
        )
    return profile


def load_catalog(path: Optional[Path]) -> list[dict[str, Any]]:
    """Entidades declaradas del workspace. Lista vacia si no hay fichero."""
    if path is None:
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    entities = doc.get("entities") if isinstance(doc, dict) else doc
    if not isinstance(entities, list):
        raise PipelineError(
            "input", f"{path}: se esperaba una lista `entities` de entidades"
        )
    for entity in entities:
        missing = {"entity_id", "type", "name"} - set(entity)
        if missing:
            raise PipelineError(
                "input", f"{path}: entidad sin {sorted(missing)}: {entity!r}"
            )
    return entities


def build_catalog(entities: Sequence[dict], workspace: str) -> InMemoryEntityCatalog:
    """Catalogo del resolutor: SOLO lo que ya existe en el grafo.

    Las provisionales quedan fuera a proposito — mismo criterio que
    `sources.entity_catalog`: una entidad que aun no existe no puede ser
    candidata a enlace, y es justo lo que obliga al motor a proponer un alta.
    """
    return InMemoryEntityCatalog(
        [
            CatalogEntity(
                entity_id=e["entity_id"],
                workspace=workspace,
                entity_type=e["type"],
                canonical_name=e["name"],
                aliases=tuple(e.get("aliases") or ()),
            )
            for e in entities
            if not e.get("provisional")
        ]
    )


def build_lexicon(entities: Sequence[dict], profile: GameProfile) -> Lexicon:
    """Glosario: alias del perfil (sin tipo) + nombres del catalogo (con tipo).

    Las provisionales SI entran: el extractor tiene que saber leer el nombre
    aunque la entidad no exista todavia en el grafo.
    """
    catalog = [
        LexiconEntry(
            canonical=e["name"],
            entity_type=e["type"],
            variants=tuple(e.get("aliases") or ()),
            confidence=0.9,
            origin="catalog",
        )
        for e in entities
    ]
    return Lexicon.from_profile(profile).merged(Lexicon(catalog))


def build_source(path: Path, *, source_kind: Optional[str] = None) -> SourceInput:
    """Bytes REALES del fichero. Nada se reconstruye ni se rellena."""
    data = path.read_bytes()
    if not data:
        raise PipelineError("input", f"{path}: fichero vacio; no hay fuente que ingerir")
    extension = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)
    return SourceInput(
        data=data,
        original_name=path.name,
        original_location=path.resolve().as_uri(),
        mime_type=mime,
        source_kind=source_kind or KIND_BY_EXTENSION.get(extension),
    )


def supported_kinds() -> list[str]:
    """Lo que el registro de adaptadores dice soportar. Observado, no cableado."""
    return default_registry().source_kinds()


def _como_provisionales(altas: Sequence[dict]) -> list[dict]:
    """Altas aprobadas, en la forma que `build_catalog`/`build_lexicon` leen."""
    return [
        {
            "entity_id": a["entity_id"],
            "type": a["type"],
            "name": a.get("name") or a["entity_id"],
            "aliases": list(a.get("aliases") or ()),
            "provisional": True,
        }
        for a in altas
    ]


def run_ingest(
    path: Path,
    *,
    profile_path: Path,
    catalog_path: Optional[Path] = None,
    workspace: Optional[str] = None,
    collection_id: Optional[str] = None,
    now: Optional[str] = None,
    ingested_at: Optional[str] = None,
    source_kind: Optional[str] = None,
    driver: Any = None,
    partida_id: Optional[str] = None,
    known_from_session: Optional[int] = None,
    approved_altas: Sequence[dict] = (),
    apply: bool = False,
    operator_id: Optional[str] = None,
    writer_env: Optional[dict] = None,
) -> dict:
    """Corre la cadena sobre UN fichero y devuelve el informe estructurado.

    `driver` presente = el mundo sale del GRAFO, no del fichero `--catalogo`.
    Leer no es escribir: con `apply=False` el driver solo se usa para la
    consulta de solo lectura del catalogo, y el writer sigue simulando.
    """
    # EQUIPO 6C. FAIL CLOSED lo antes posible: si el ambito es de partida y no
    # hay sesion de revelacion declarada, no se abre conexion, no se extrae y
    # no se planifica. El motor volveria a rechazarlo mas abajo
    # (`PlanContext.__post_init__`), pero para entonces ya se habria gastado
    # una corrida entera —y, con `--apply`, credenciales— en un plan que el
    # writer no podia admitir. Nunca se degrada a capa juego.
    if partida_id is not None and known_from_session is None:
        raise PipelineError(
            "scope",
            "PLAN_SESION_NO_DECLARADA: --partida exige --sesion N (la sesion "
            "de REVELACION del contenido; 0 = conocido desde el inicio). Sin "
            "ella el writer aborta con EXEC_REVELACION_NO_DECLARADA, y "
            "asumirla seria conceder una revelacion que nadie declaro."
        )
    if partida_id is None and known_from_session is not None:
        raise PipelineError(
            "scope",
            "PLAN_SESION_SIN_AMBITO: --sesion solo tiene sentido con "
            "--partida. La capa juego no esta sujeta a progresion de sesion y "
            "el valor se descartaria en silencio."
        )
    profile = load_profile(profile_path, workspace=workspace)
    ws = profile.workspace
    moment = now or _utc_now()
    ingested = ingested_at or moment
    collection = collection_id or f"collection:{ws}"

    # DOS FUENTES, DOS PREGUNTAS DISTINTAS. Es el reparto que faltaba y el que
    # explica todo este carril:
    #
    #   * el CATALOGO declarado (`--catalogo`) dice COMO SE LLAMAN las cosas.
    #     Es vocabulario de identidad: sin el, el resolutor no tiene con que
    #     enlazar y todo sale provisional — y el motor manda a revision humana
    #     cualquier hecho sobre una entidad provisional (`ENTITY_PROVISIONAL`),
    #     asi que no se escribe nada. MEDIDO: con el grafo vacio y sin
    #     catalogo, 5 claims -> 3 REVIEW + 2 ABSTAIN, 0 operaciones.
    #   * el GRAFO dice QUE EXISTE de verdad, con su `version` y su
    #     `state_hash`.
    #
    # Antes solo habia la primera, tratada como si respondiera tambien a la
    # segunda. De ahi el `EXEC_TARGET_MISSING`: el fichero declaraba
    # `entity:cofradia-ambar` y el grafo no la tenia.
    #
    # Se juntan para RESOLVER, y el grafo manda cuando el mismo id esta en los
    # dos (su fila trae la version observada). Lo declarado y ausente NO entra
    # en el snapshot: sale como `CREATE_ENTITY_REQUIRED` y espera a un humano.
    declaradas = load_catalog(catalog_path)
    graph_rows: list[dict] = []
    if driver is not None:
        graph_rows = graph_catalog.catalog_rows(driver, ws, partida_id)
        observados = {f["entity_id"] for f in graph_rows}
        entities = graph_rows + [
            e for e in declaradas if e["entity_id"] not in observados
        ]
    else:
        entities = declaradas
    source = build_source(path, source_kind=source_kind)
    options = IngestOptions(
        workspace=ws,
        collection_id=collection,
        ingested_at=ingested,
        game_profile=profile.profile_id,
    )
    config = PipelineConfig(
        workspace=ws,
        collection_id=collection,
        profile=profile,
        now=moment,
        ingested_at=ingested,
        # EQUIPO 5A. `--partida` llegaba hasta aqui y se quedaba en la puerta:
        # se usaba para LEER el catalogo acotado (`catalog_rows`) y para el
        # documento de rollback, pero NUNCA entraba en la corrida, asi que el
        # plan salia sin ambito. Ese era el tramo que faltaba de la carretera.
        partida_id=partida_id,
        # EQUIPO 6C. Y con el ambito viaja su sesion de revelacion. Iban por
        # rutas distintas hasta aqui y por eso el plan de partida salia sin
        # ella: el ambito entraba en la corrida y la sesion no existia.
        known_from_session=known_from_session,
        # Las altas aprobadas NO entran aqui. Ni en el catalogo ni en el
        # glosario. MEDIDO: al meterlas, la cascada del resolutor cambiaba de
        # rama y los `entity_id` derivados pasaban de `entity:prov:...` a
        # `entity:new:...` entre la primera pasada y la segunda — es decir, el
        # operador aprobaba unos ids y se escribian otros, y la aprobacion
        # dejaba de cubrir lo que se escribia.
        #
        # La regla que queda: **aprobar un alta autoriza una creacion; no
        # cambia como se resuelve la identidad.** La resolucion es la misma
        # con aprobacion y sin ella (misma entrada, misma salida), y lo unico
        # que la aprobacion mueve es el SNAPSHOT, mas abajo.
        catalog=build_catalog(entities, ws),
        lexicon=build_lexicon(entities, profile),
        # El writer solo escribe si el operador lo pidio Y hay driver. Sin
        # `--apply` sigue siendo DRY-RUN aunque la conexion exista, porque el
        # driver tambien se usa para LEER el catalogo.
        apply=bool(apply),
        writer_driver=driver if apply else None,
        operator_id=operator_id or "s9k.pipeline",
        # El gate lee de AQUI, no de `os.environ`, si el diccionario no es
        # vacio. Pasarle `{}` seria falsificar un entorno sin
        # `S9K_ALLOW_REAL_INGEST` y hacer que el APPLY se bloquease siempre
        # con `GATE_ENV_NOT_ALLOWED` — un fallo cerrado, pero por el motivo
        # equivocado. Se le pasa el entorno REAL del proceso: la declaracion
        # sigue siendo del operador, no de este modulo.
        writer_env=dict(writer_env) if writer_env is not None else dict(os.environ),
        ablation="operator_ingest",
    )
    case = SourceCase(
        source_id=path.name, source=source, ingest_options=options
    )
    lexicon = config.lexicon
    # El snapshot del motor arranca del catalogo: sin el, NINGUNA entidad
    # existe para el motor y todo cae por `ENTITY_NOT_IN_SNAPSHOT` aunque el
    # resolutor haya enlazado con confianza 1.0. Mismo puente que usa el runner.
    #
    # Con driver, el snapshot lleva ademas la `version`/`state_hash` OBSERVADAS
    # y las altas APROBADAS marcadas `pending_creation`, que es lo que hace que
    # el planificador emita sus `CREATE_ENTITY`.
    if driver is not None:
        # SOLO lo observado + las altas aprobadas. Lo declarado y ausente se
        # queda fuera a proposito: meterlo aqui es exactamente lo que producia
        # el `EXEC_TARGET_MISSING` — un plan anclado a entidades que el grafo
        # no tiene.
        snapshot_entities = graph_catalog.snapshot_entities(
            graph_rows, altas=approved_altas
        )
    else:
        snapshot_entities = bridge.entities_from_catalog(entities)
    result = KnowledgePipeline(config).run([case], catalog_entities=snapshot_entities)
    report = ingest_report(
        result,
        source_path=path,
        input_hash=sha256_hash(source.data.decode("utf-8", errors="replace")),
        source_bytes=len(source.data),
        catalog_entities=entities,
        profile=profile,
        lexicon_entries=len(getattr(lexicon, "entries", ()) or ()),
        clock_read_at_boundary=now is None,
        # OBSERVADO, no supuesto: `--desde-grafo` abre driver para LEER el
        # catalogo aunque sea dry-run. El acta lo dira tal cual.
        driver_opened=driver is not None,
    )
    # Lo que el writer HIZO, publicado en el informe. `ingest_report` no lo
    # traia porque hasta ahora no habia escritura que contar; sin este bloque,
    # un APPLY exitoso y uno abortado producen actas indistinguibles.
    run = result.runs[0]
    escritura = run.write_result
    if escritura is not None:
        report["write"] = {
            "outcome": escritura.outcome,
            "mode": escritura.mode,
            "codes": list(escritura.codes),
            "applied_operations": escritura.applied_operations,
            "noop_operations": escritura.noop_operations,
            "created_ids": list(escritura.created_ids),
        }
        # INTEGRACION tanda 3. El carril B hizo que esta ruta emitiera
        # `CREATE_ENTITY` DE VERDAD: por primera vez el producto crea
        # entidades por aqui. Crear sin publicar como deshacerlo deja al
        # operador con conocimiento escrito y sin documento de reversion, que
        # es justo lo que la ruta de operador del writer existe para evitar.
        #
        # El documento es DESCRIPTIVO: nadie lo ejecuta por su cuenta. Se
        # publica para que exista, no para que actue.
        if escritura.rollback is not None:
            # DEFECTO MEDIDO Y CERRADO: el documento solo llevaba la
            # procedencia que las aserciones CITAN, mientras el volcado
            # persiste la de toda la corrida. Un apply de 7 evidencias / 7
            # episodios / 1 fuente producia un documento con UN `fragment_id`,
            # y revertirlo dejaba el resto huerfano en el grafo. El barrido
            # amplia el conjunto candidato; la condicion de borrado --cero
            # referencias vivas, dentro del propio DELETE-- no se toca.
            if run.provenance_result is not None:
                # EL RADIO ES EL APPLY, NO LA CORRIDA. Con `apply_id` el
                # barrido no enumera fragmentos: declara de QUIEN es lo que
                # puede borrar, y el ejecutor descubre ese conjunto en el
                # grafo. Enumerarlos aqui era fijar el radio en la corrida
                # entera, que es como revertir un apply de UNA arista se
                # llevaba 6 episodios y 6 evidencias que no habia creado.
                #
                # Sin `apply_id` (apply sin identidad completa) se conserva el
                # radio antiguo, declarado como `scope: "run"` en el propio
                # documento. No es equivalente y no se finge que lo sea.
                add_provenance_sweep(
                    escritura.rollback,
                    workspace=ws,
                    partida_id=(run.plan.partida_id if run.plan else None),
                    fragment_ids=(
                        [] if run.apply_id
                        else [f.fragment_id for f in run.fragments]
                    ),
                    apply_id=run.apply_id,
                )
            report["rollback"] = escritura.rollback.to_dict()
    if run.provenance_result is not None:
        report["provenance"] = run.provenance_result.to_dict()
    return report


def _driver_factory(args: argparse.Namespace, env: Optional[dict] = None):
    """La FABRICA de driver, con las reglas de `driver_neo4j` intactas.

    La contrasena NO viaja por `argv`: se declara el CAMINO de un fichero
    privado (modo 0o600), o `-` para leerla de la entrada estandar. Este
    modulo no la ve, no la guarda y no la imprime.
    """
    config = resolve_config(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password_file=args.neo4j_password_file,
        database=args.neo4j_database,
        env=env,
    )
    return build_driver_factory(config)


def _necesita_grafo(args: argparse.Namespace) -> bool:
    """¿Hay que abrir conexion? Leer el catalogo del grafo tambien cuenta."""
    return bool(args.desde_grafo or args.apply)


def _ledger_path(args: argparse.Namespace) -> Path:
    if args.decisiones is not None:
        return args.decisiones
    if args.out_dir is not None:
        return args.out_dir / "decisiones.json"
    raise PipelineError(
        "config",
        "no se dijo donde vive el documento de decisiones: usa --decisiones o "
        "--out-dir",
    )


def _escribir_ledger(ruta: Path, ledger: entity_decisions.DecisionLedger) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _leer_ledger(ruta: Path) -> entity_decisions.DecisionLedger:
    return entity_decisions.DecisionLedger.from_dict(
        json.loads(ruta.read_text(encoding="utf-8"))
    )


def _resoluciones(report: dict) -> list[dict]:
    """Todas las candidatas del informe, sin reagrupar.

    El criterio de reparto sigue siendo el `action` del contrato, que
    `entity_decisions.reconcile` vuelve a leer. Aqui solo se juntan las tres
    listas que `ingest_report` publico por separado.
    """
    cand = report.get("candidates") or {}
    return (
        list(cand.get("link_existing") or ())
        + list(cand.get("create_entity") or ())
        + list(cand.get("review_identity") or ())
    )


def _nombres_por_mencion(report: dict) -> dict:
    """`mention_id -> superficie`. Es el nombre que llevara un alta."""
    return {
        m["mention_id"]: m.get("surface")
        for m in (report.get("mentions") or ())
        if m.get("mention_id") and m.get("surface")
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge_v3.pipeline.ingest_cli",
        description=(
            "Mete una fuente real por la cadena V3. DRY-RUN por defecto. "
            "Con --desde-grafo el catalogo se LEE del grafo en vez de un "
            "fichero; con --apply se escribe, y entonces manda el gate del "
            "writer, no esta CLI."
        ),
    )
    parser.add_argument("fichero", type=Path, nargs="?",
                        help="fuente a ingerir (.md, .txt)")
    parser.add_argument(
        "--perfil", type=Path, default=None, help="GameProfile del workspace (JSON)"
    )
    parser.add_argument(
        "--catalogo", type=Path, default=None,
        help="entidades ya existentes (JSON). Alternativa OFFLINE a "
             "--desde-grafo; si se dan las dos, manda el grafo",
    )
    parser.add_argument("--workspace", default=None, help="debe coincidir con el perfil")
    parser.add_argument("--partida", default=None, dest="partida_id",
                        help="ambito de partida; sin el, capa juego (lore)")
    # EQUIPO 6C. La sesion de REVELACION (T2) la declara quien ingiere, igual
    # que el ambito: es un dato del mundo (en que sesion se juega/se revela lo
    # que hay en la fuente) que ningun punto del software puede deducir del
    # fichero. Obligatoria con `--partida`.
    parser.add_argument("--sesion", default=None, dest="known_from_session",
                        type=int, metavar="N",
                        help="sesion de REVELACION del contenido (T2): desde "
                             "que sesion puede revelarse. Obligatoria con "
                             "--partida; 0 = conocido desde el inicio")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--source-kind", default=None, help="fuerza el adaptador")
    parser.add_argument("--ahora", default=None, help="instante inyectado (ISO-8601 Z)")
    parser.add_argument("--ingerido-en", default=None, dest="ingerido_en")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="no escribe en el grafo. Sigue siendo el defecto",
    )
    parser.add_argument(
        "--formato", choices=("markdown", "json", "ambos"), default="markdown",
        help="markdown = acta legible; json = informe estructurado; ambos = las dos",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None,
        help="escribe acta.md, informe.json y decisiones.json ahi",
    )

    # -- reconciliacion contra el grafo real --------------------------------
    parser.add_argument(
        "--desde-grafo", action="store_true", dest="desde_grafo",
        help="el catalogo del workspace se LEE del grafo (solo lectura). Es "
             "lo que permite decidir que entidades existen de verdad",
    )
    parser.add_argument(
        "--decisiones", type=Path, default=None,
        help="documento de decisiones de identidad: se escribe en la ingesta "
             "y se lee en la revision y en el APPLY",
    )
    parser.add_argument(
        "--revisar", action="store_true",
        help="modo REVISION: no ingiere nada; aprueba altas sobre un "
             "documento de decisiones ya generado",
    )
    parser.add_argument(
        "--aprobar-alta", action="append", default=[], dest="aprobar_alta",
        metavar="ENTITY_ID",
        help="aprueba el alta de ESE entity_id. Repetible. No existe "
             "'aprobar todas': cada alta se aprueba por su id",
    )
    parser.add_argument(
        "--tipo-alta", action="append", default=[], dest="tipo_alta",
        metavar="ENTITY_ID=TIPO",
        help="declara el `entity_type` de un alta que se esta aprobando. "
             "Repetible. Hace falta cuando el resolutor no pudo inferirlo "
             "(tipico en un grafo nuevo): sin tipo, la creacion no se puede "
             "construir y el mando lo dice en vez de descartar el alta",
    )
    parser.add_argument("--revisor", default=None,
                        help="quien aprueba las altas. Obligatorio con --revisar")

    # -- escritura real ------------------------------------------------------
    parser.add_argument(
        "--apply", action="store_true",
        help="ESCRITURA REAL. Exige ademas el gate del writer: "
             "S9K_ALLOW_REAL_INGEST=1, S9K_WRITER_WORKSPACE y --operador",
    )
    parser.add_argument("--operador", default=None, dest="operator_id",
                        help="identificador del operador que autoriza el APPLY")
    parser.add_argument("--neo4j-uri", default=None, help=f"URI del servidor ({ENV_URI})")
    parser.add_argument("--neo4j-user", default=None, help=f"usuario ({ENV_USER})")
    parser.add_argument(
        "--neo4j-password-file", default=None,
        help=f"CAMINO de un fichero privado con la contrasena, o '-' para "
             f"stdin ({ENV_PASSWORD_FILE}). NUNCA se pasa por argv.",
    )
    parser.add_argument("--neo4j-database", default=None,
                        help=f"base de datos ({ENV_DATABASE})")
    return parser


def _tipos_declarados(pares: Sequence[str]) -> dict:
    """`--tipo-alta id=Tipo` -> dict. Un par mal escrito es un ERROR de uso.

    No se acepta `id=` vacio: declarar un tipo vacio es lo mismo que no
    declararlo, y tragarselo devolveria el descarte silencioso por otra via.
    """
    tipos: dict = {}
    for par in pares:
        if "=" not in par:
            raise ValueError(f"--tipo-alta espera ENTITY_ID=TIPO, no {par!r}")
        entity_id, _, tipo = par.partition("=")
        entity_id, tipo = entity_id.strip(), tipo.strip()
        if not entity_id or not tipo:
            raise ValueError(f"--tipo-alta con id o tipo vacio: {par!r}")
        if entity_id in tipos and tipos[entity_id] != tipo:
            raise ValueError(
                f"dos tipos distintos para {entity_id}: "
                f"{tipos[entity_id]!r} y {tipo!r}"
            )
        tipos[entity_id] = tipo
    return tipos


def _modo_revision(args: argparse.Namespace) -> int:
    """Aprueba altas. No abre ninguna conexion y no toca el grafo."""
    if not args.revisor:
        print("ERROR: --revisar exige --revisor: una aprobacion sin revisor no "
              "es una aprobacion", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    try:
        tipos = _tipos_declarados(args.tipo_alta)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    ruta = _ledger_path(args)
    ledger = _leer_ledger(ruta)
    try:
        nuevo = entity_decisions.approve(
            ledger, args.aprobar_alta, reviewer=args.revisor, at=_utc_now(),
            entity_types=tipos,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    # EQUIPO 5A. Se avisa AQUI, cuando el revisor todavia esta mirando, de las
    # altas que aprobo y no podran crearse por falta de tipo. Descubrirlo en
    # el apply siguiente es tarde, y descubrirlo nunca era el defecto.
    sin_tipo = sorted(
        str(d.entity_id) for d in nuevo.aprobadas
        if d.entity_id and not d.entity_type
    )
    _escribir_ledger(ruta, nuevo)
    print(json.dumps(
        {
            "documento": str(ruta),
            "revisor": args.revisor,
            "aprobadas_ahora": sorted(args.aprobar_alta),
            "aprobadas_sin_tipo": sin_tipo,
            "totals": nuevo.to_dict()["totals"],
            "pendientes": sorted(
                str(d.entity_id) for d in nuevo.pendientes
                if d.decision == entity_decisions.CREATE_ENTITY_REQUIRED
            ),
        },
        ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _rc_del_desenlace(report: dict) -> int:
    """`rc` de la corrida, derivado del DESENLACE resuelto de la corrida.

    DEFECTO CERRADO (equipo 5C). Esta funcion decia antes: "sin bloque `write`
    no hubo writer, la corrida es una ingesta que produjo su informe y eso es
    un exito (0)". Es cierto en dry-run y **falso bajo `--apply`**: un
    `--apply --operador ... --desde-grafo` cuya cadena paraba antes del writer
    (`SIN_PLAN`, `CADENA_DETENIDA`) publicaba un acta honesta que decia
    `SIN_RESULTADO_DE_ESCRITURA` ... y salia `0`, con el grafo intacto. Un
    runner desatendido no podia distinguir ese APPLY fallido de uno aplicado.

    Ahora el desenlace se RESUELVE primero -- cruzando lo que el usuario pidio
    (`run.writer_mode`, que es el modo PEDIDO, no el ejecutado) con lo que
    ocurrio -- y el `rc` sale de ese desenlace. `describe_outcome` publica la
    frase a partir de la MISMA cadena, asi que acta y `rc` no pueden divergir.

    Lo que NO se hace, a proposito: `operaciones == 0 -> error`. Un `--apply`
    repetido sobre conocimiento ya escrito da 0 operaciones y es un EXITO
    (`NOOP_IDEMPOTENT`); esa regla simplista romperia la idempotencia.
    """
    modo_pedido = (report.get("run") or {}).get("writer_mode")
    escritura = report.get("write")
    desenlace = exit_codes.resolve_run_outcome(modo_pedido, escritura)
    return exit_codes.exit_code_for_run(
        desenlace,
        (escritura or {}).get("codes") or (),
        requested_mode=modo_pedido,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.revisar:
        try:
            return _modo_revision(args)
        except (PipelineError, ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return exit_codes.EXIT_USAGE

    if args.fichero is None or args.perfil is None:
        parser.error("hace falta el fichero a ingerir y --perfil")
    # Las dos declaraciones que nadie puede poner por el operador se exigen
    # ANTES de abrir conexion: gastar credenciales y una sesion en un APPLY
    # que ya no puede autorizarse no aporta nada, y deja el fallo detras de un
    # error de red que lo tapa.
    if args.apply and not args.operator_id:
        parser.error("--apply exige --operador: el gate del writer rechaza un "
                     "APPLY sin operador identificado")
    if args.apply and (args.decisiones is None or not args.decisiones.exists()):
        parser.error(
            "--apply exige --decisiones apuntando a un documento de decisiones "
            "REVISADO. Sin el no hay constancia de que nadie haya aprobado las "
            "altas de entidad que se van a escribir"
        )

    driver = None
    ledger = None
    try:
        if _necesita_grafo(args):
            try:
                factory = _driver_factory(args)
            except DriverConfigError as exc:
                # Falla CERRADO y sin secreto en el mensaje. No se degrada a
                # dry-run offline en silencio: si el operador pidio leer el
                # grafo, seguir con un catalogo de fichero seria contestar
                # otra pregunta.
                print(f"ERROR [conexion]: {exc}", file=sys.stderr)
                return exit_codes.EXIT_USAGE
            driver = factory()

        aprobadas: list[dict] = []
        ledger_previo = None
        if args.decisiones is not None and args.decisiones.exists():
            ledger_previo = _leer_ledger(args.decisiones)
            if args.apply:
                # Falla CERRADO: con altas sin aprobar no se escribe nada.
                entity_decisions.require_reviewed(ledger_previo)
            aprobadas = entity_decisions.approved_snapshot_entities(ledger_previo)

        report = run_ingest(
            args.fichero,
            profile_path=args.perfil,
            catalog_path=args.catalogo,
            workspace=args.workspace,
            collection_id=args.collection,
            now=args.ahora,
            ingested_at=args.ingerido_en,
            source_kind=args.source_kind,
            driver=driver,
            partida_id=args.partida_id,
            known_from_session=args.known_from_session,
            approved_altas=aprobadas,
            apply=bool(args.apply),
            operator_id=args.operator_id,
        )

        if driver is not None:
            filas = graph_catalog.catalog_rows(driver, report["run"]["workspace"],
                                               args.partida_id)
            ledger = entity_decisions.reconcile(
                resolutions=_resoluciones(report),
                graph_entity_ids=graph_catalog.entity_ids(filas),
                workspace=report["run"]["workspace"],
                source_path=str(args.fichero),
                partida_id=args.partida_id,
                generated_at=report["run"]["now"],
                names_by_mention=_nombres_por_mencion(report),
            )
            # Una revision previa no se pierde al reingerir: lo aprobado sigue
            # aprobado si la decision sigue siendo la misma alta pendiente.
            if ledger_previo is not None and ledger_previo.aprobadas:
                pendientes_ahora = {p.entity_id for p in ledger.pendientes}
                # DEDUPLICADO: varias menciones distintas pueden resolver a la
                # MISMA entidad, asi que el mismo id aparece varias veces entre
                # las aprobadas. Aprobarlo dos veces fallaba con "no es un alta
                # pendiente" — la primera pasada ya lo habia dejado aprobado.
                ya = sorted({
                    d.entity_id for d in ledger_previo.aprobadas
                    if d.entity_id in pendientes_ahora
                })
                if ya:
                    quien = next(
                        (d.approved_by for d in ledger_previo.aprobadas
                         if d.entity_id in ya and d.approved_by), "revision-previa")
                    cuando = next(
                        (d.approved_at for d in ledger_previo.aprobadas
                         if d.entity_id in ya and d.approved_at), _utc_now())
                    # EQUIPO 5A. El tipo que el revisor declaro vive en el
                    # ledger ANTERIOR; la reconciliacion lo acaba de
                    # regenerar desde las resoluciones, donde vuelve a ser
                    # `None`. Sin arrastrarlo, reingerir borraba el dato que
                    # una persona habia aportado y el alta volvia a caerse.
                    tipos_previos = {
                        d.entity_id: d.entity_type
                        for d in ledger_previo.aprobadas
                        if d.entity_id in ya and d.entity_type
                    }
                    ledger = entity_decisions.approve(
                        ledger, ya, reviewer=quien, at=cuando,
                        entity_types=tipos_previos)
            report["entity_decisions"] = ledger.to_dict()
            report.setdefault("carencias", []).extend(graph_catalog.carencias(filas))

    except entity_decisions.AltaNoAprobada as exc:
        print(f"ERROR [altas]: {exc}", file=sys.stderr)
        return exit_codes.EXIT_ALTAS_NOT_APPROVED
    except entity_decisions.AltaAprobadaSinTipo as exc:
        # Mismo rc que "altas sin aprobar" y por la misma razon de producto:
        # hay altas que una persona tiene que atender antes de que se escriba
        # nada. No es un desenlace nuevo del writer; es la misma puerta.
        print(f"ERROR [altas]: {exc}", file=sys.stderr)
        return exit_codes.EXIT_ALTAS_NOT_APPROVED
    except PipelineError as exc:
        print(f"ERROR [{exc.stage}]: {exc}", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    finally:
        if driver is not None:
            driver.close()

    acta = to_markdown(report)
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "acta.md").write_text(acta, encoding="utf-8")
        (args.out_dir / "informe.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"acta:    {args.out_dir / 'acta.md'}")
        print(f"informe: {args.out_dir / 'informe.json'}")
    if ledger is not None:
        destino = _ledger_path(args)
        _escribir_ledger(destino, ledger)
        print(f"decisiones: {destino}")
        print(json.dumps(ledger.to_dict()["totals"], ensure_ascii=False,
                         sort_keys=True))
        for d in ledger.pendientes:
            if d.decision == entity_decisions.CREATE_ENTITY_REQUIRED:
                print(f"  ALTA PENDIENTE {d.entity_id} ({d.entity_type}) "
                      f"{','.join(d.reason_codes)}")
    if args.apply and report.get("write"):
        print("write: " + json.dumps(report["write"], ensure_ascii=False,
                                     sort_keys=True))

    # EL DESENLACE MANDA EL `rc`. Antes esta funcion salia 0 pasara lo que
    # pasara con la escritura: un APPLY que el gate BLOQUEO (0 operaciones,
    # grafo intacto) y uno que la admision RECHAZO salian igual que un APPLY
    # aplicado. Un runner desatendido leia exito donde no se escribio nada --
    # y la inconsistencia era interna, porque quitar `--operador` si daba 2.
    #
    # `exit_code_for_outcome` es la MISMA funcion que da la frase del acta
    # (`describe_outcome`), asi que texto y codigo no pueden divergir.
    rc = _rc_del_desenlace(report)

    if args.out_dir is not None:
        return rc

    if args.formato in ("json", "ambos"):
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.formato in ("markdown", "ambos"):
        print(acta)
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
