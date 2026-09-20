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

Y AHORA HAY UNA SEGUNDA SUPERFICIE. DECLARADA, NO DESCUBIERTA.
--------------------------------------------------------------
Desde el Corte de altas de entidad, la misma decision se puede tomar desde el
producto (`/panel/operations/altas`), y ALLI la autoridad es el almacen de
revision del visor --la misma base que sostiene las decisiones de propuesta y
los planes sellados--, no este fichero de decisiones.

Las dos NO se hablan, y eso es DEUDA, no diseño:

  * el camino WEB (cola de trabajos -> revision -> sellado -> apply) no lee ni
    escribe `--decisiones`: emite `CREATE_ENTITY` unicamente para lo aprobado
    en el almacen de revision;
  * este camino CLI no lee la tabla del visor, y sigue usando su fichero.

Mientras cada camino consuma SOLO su propia autoridad no hay dos verdades
sobre un mismo plan --un plan lo sella uno de los dos, nunca los dos-- pero sí
hay dos sitios donde mirar quien aprobo que. Unificarlas exige que el motor
pueda leer el almacen del visor, y hoy la dependencia solo va en el otro
sentido (visor -> motor): es un carril aparte, no un apaño dentro de este.

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
from ..engine import promotion as promo
from ..review_paths import default_proposals_dir
from ..writer.apply import ProvenanceBundle

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


def merge_catalogo(graph_rows: Sequence[dict], declaradas: Sequence[dict]) -> list[dict]:
    """El mundo: lo OBSERVADO en el grafo, mas lo DECLARADO que aun no existe.

    El grafo manda cuando el mismo `entity_id` esta en los dos: su fila trae la
    `version` y el `state_hash` observados, y una fila de fichero los inventaria.

    EQUIPO 8A. Existe como funcion propia porque ahora tiene DOS consumidores:
    `run_ingest`, que construye con ella el catalogo del resolutor, y `main`,
    que necesita el mismo mundo para decirle a `reconcile` COMO SE LLAMAN las
    entidades. Copiar la fusion en el segundo sitio habria creado justo lo que
    este fichero ya advierte en `reconcile`: una segunda ruta que se desvia de
    la primera sin que nada lo note.
    """
    observados = {f["entity_id"] for f in graph_rows}
    return list(graph_rows) + [
        e for e in declaradas if e["entity_id"] not in observados
    ]


def identidades_por_entidad(entities: Sequence[dict]) -> dict[str, dict]:
    """`entity_id -> {name, aliases}`: el nombre CANONICO y sus alias.

    Es lo que `reconcile` necesita para no volver a nombrar una entidad con la
    superficie que la menciono. Solo se incluyen las entradas que traen nombre:
    una fila sin `name` no aporta nada y dejarla entrar haria que un `name`
    vacio del catalogo pisara la superficie, que es peor que la superficie.
    """
    salida: dict[str, dict] = {}
    for e in entities:
        entity_id = e.get("entity_id")
        nombre = e.get("name")
        if not entity_id or not nombre:
            continue
        salida[str(entity_id)] = {
            "name": str(nombre),
            "aliases": [str(a) for a in (e.get("aliases") or ()) if str(a).strip()],
        }
    return salida


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
    promotions: Sequence[Any] = (),
    apply: bool = False,
    operator_id: Optional[str] = None,
    writer_env: Optional[dict] = None,
    review_proposals_dir: Optional[Path] = None,
    job_id: Optional[str] = None,
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
        entities = merge_catalogo(graph_rows, declaradas)
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
        promotions=tuple(promotions),
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
    # LA COLA DE REVISION SE ESCRIBE AQUI, Y POR ESO EXISTE.
    #
    # Hasta el Corte 3 esta llamada no pasaba `review_proposals_dir` y el
    # exportador de propuestas quedaba SIN LLAMADOR en el camino del producto:
    # el informe decia `REVIEW=2`, el job quedaba `complete` y `/panel/review`
    # decia «Sin propuestas visibles». El operador daba por buena una ingesta
    # cuyas ambiguedades no habia visto nunca.
    #
    # La ruta NO se deriva aqui: se pide al unico resolvedor del producto
    # (`knowledge_v3.review_paths`), que es el mismo que usa el visor para
    # leerlas. Si este modulo derivara la suya, escritor y lector podrian
    # apuntar a almacenes distintos sin un solo error.
    proposals_dir = (
        review_proposals_dir
        if review_proposals_dir is not None
        else default_proposals_dir()
    )
    # ATRIBUCION DE LA CORRIDA (Corte 4). `job_id` viene de la cola, no se
    # deriva aqui: es la MISMA identidad que el operador ve en `/panel/
    # operations`, y por eso el enlace desde el acuse a su revision puede
    # existir. Sin `job_id` (CLI a mano) no se atribuye nada y el paquete
    # conserva su forma anterior.
    review_run = {
        "job_id": job_id,
        "source_id": case.source_id,
        "exported_at": _utc_now(),
    } if job_id else None
    result = KnowledgePipeline(config).run(
        [case],
        catalog_entities=snapshot_entities,
        review_proposals_dir=proposals_dir,
        review_run=review_run,
    )
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
    # EL PAQUETE DE PROCEDENCIA, PUBLICADO. Es lo unico que el fichero de plan
    # no puede contener y sin lo cual el conocimiento se escribe con las
    # referencias de evidencia colgando. Publicarlo es lo que permite que el
    # mando de bajo nivel (`writer.cli --procedencia`) llegue al MISMO grafo:
    # la diferencia entre las dos rutas son datos, no dos implementaciones.
    # LO PROMOVIBLE Y LO PROMOVIDO, EN EL INFORME. Antes, revisar era leer:
    # el motor mandaba una relacion a REVIEW y no habia mando para promoverla.
    if run.engine_result is not None:
        report["revision"] = {
            "pendientes": promo.pending_rows(run.engine_result.decisions),
            "promociones": [dict(e) for e in run.engine_result.promotion_report],
        }
    # LA COLA DE REVISION DE ESTA CORRIDA, PUBLICADA EN EL INFORME.
    #
    # `None` cuando no se exporto: "no se exporto" y "se exporto y no habia
    # nada" son hechos distintos y el resumen del panel los dice distinto. La
    # ruta del paquete NO entra: es del servidor. Entra el NOMBRE del fichero,
    # que es content-addressed y no revela donde vive.
    exportacion = getattr(result, "review_export", None)
    report["cola_de_revision"] = None if exportacion is None else {
        "job_id": exportacion.job_id,
        "propuestas": exportacion.count,
        "proposal_ids": list(exportacion.proposal_ids),
        "paquete": exportacion.path.name,
        "workspace": exportacion.workspace,
    }
    report["procedencia_paquete"] = ProvenanceBundle.of(
        source_asset=run.asset.to_dict() if run.asset else None,
        episodes=[e.to_dict() for e in run.episodes],
        fragments=[f.to_dict() for f in run.fragments],
    ).to_dict()
    # IDENTIDAD DEL APPLY, PUBLICADA Y DESGLOSADA. Un equipo anterior afirmo
    # que `apply_id` era "la misma cadena en cualquier base y tras un restore".
    # Es cierto A IGUALDAD DE PLAN -- y `plan_hash` cubre `created_at`, que sale
    # del reloj de pared. Sin `--ahora`, cada ejecucion produce un plan nuevo y
    # por tanto un `apply_id` nuevo. Aqui se dice, con las piezas a la vista,
    # en vez de dejarlo para que alguien lo descubra comparando.
    report["apply_identity"] = {
        "apply_id": run.apply_id,
        "plan_id": (run.plan.plan_id if run.plan else None),
        "plan_hash": (run.plan.plan_hash["value"] if run.plan else None),
        "snapshot_id": (run.plan.snapshot_id if run.plan else None),
        "workspace": ws,
        "partida_id": (run.plan.partida_id if run.plan else None),
        "created_at": (run.plan.created_at if run.plan else None),
        "reloj_fijado": now is not None,
        "carencia": (
            None if now is not None else
            "SIN --ahora: `created_at` sale del reloj de pared, entra en "
            "`plan_hash` y por tanto en `apply_id`. Repetir esta misma orden "
            "produce OTRO apply_id. La identidad LOGICA estable del plan es "
            "`plan_id` (no depende del reloj), pero el contrato congelado la "
            "declara NO FIRMADA, asi que no puede sostener una decision de "
            "escritura. Fija --ahora para que el apply_id sea reproducible."
        ),
    }
    if escritura is not None:
        report["write"] = {
            "outcome": escritura.outcome,
            "mode": escritura.mode,
            "codes": list(escritura.codes),
            "applied_operations": escritura.applied_operations,
            "noop_operations": escritura.noop_operations,
            # IDENTIDAD DURABLE, NO `elementId`. `created_ids` devolvia al
            # operador el `elementId` crudo de cada arista creada
            # (`cypher.create_relation` termina en `RETURN elementId(r)`),
            # mezclado con los `entity_id`/`assertion_id` de los nodos y sin
            # forma de distinguirlos. El `elementId` se regenera al restaurar
            # un dump: no identifica nada durable, y publicarlo como "id
            # creado" invita a usarlo como si lo fuera.
            "created": _creado_durable(escritura),
            # Se conserva el nombre historico, pero SOLO con ids durables: los
            # `elementId` de arista salen de aqui y viven en `created`, bajo
            # `element_id_at_write`.
            "created_ids": [
                c["identidad_durable"]["id"]
                for c in _creado_durable(escritura)
                if c["kind"] == "NODE" and c["identidad_durable"].get("id")
            ],
        }
        if escritura.rollback is not None:
            report["rollback"] = escritura.rollback.to_dict()
    if run.apply_outcome is not None:
        salida = run.apply_outcome
        report["apply"] = {
            "notes": [dict(n) for n in salida.notes],
            "dangling_fragment_ids": list(salida.dangling_fragment_ids),
        }
    if run.provenance_result is not None:
        report["provenance"] = run.provenance_result.to_dict()
    return report


def _creado_durable(escritura: Any) -> list:
    """Lo que el APPLY creo, con IDENTIDAD DURABLE y no con `elementId`.

    DEFECTO CERRADO. `write.created_ids` publicaba al operador la lista cruda
    de `WriteResult.created_ids`, que para las ARISTAS es el `elementId(r)` que
    devuelve `cypher.create_relation`. Tres cosas mal a la vez:

    * el `elementId` se regenera al restaurar un dump -- deja de identificar
      justo durante una recuperacion, que es cuando hace falta;
    * iba mezclado con los `entity_id`/`assertion_id` de los nodos, sin ninguna
      marca que permitiera distinguir cual era cual;
    * publicado como "id creado", invita a usarlo como identidad durable, que
      es exactamente lo que el proyecto tiene escrito que NO es.

    La identidad de producto es `(workspace, entity_id)`; la de una arista, la
    tripleta `(sujeto, predicado, objeto)` dentro de su ambito. Eso es lo que
    se publica. El `elementId` se conserva bajo el nombre que le corresponde
    --`element_id_at_write`, el mismo que ya usa el documento de rollback-- y
    solo para las aristas, que es donde existe.
    """
    salida: list = []
    if escritura.rollback is None:
        return salida
    for instr in escritura.rollback.instructions:
        det = dict(instr.detail or {})
        if instr.action == "DELETE_RELATIONSHIP":
            salida.append({
                "operation_id": instr.operation_id,
                "kind": "RELATIONSHIP",
                "identidad_durable": {
                    "workspace": det.get("workspace"),
                    "subject_id": det.get("subject"),
                    "predicate": det.get("predicate"),
                    "object_id": det.get("object"),
                    "partida_id": det.get("partida_id"),
                },
                # Se conserva con el nombre que dice lo que es: dato del
                # momento de la escritura, NUNCA identidad durable.
                "element_id_at_write": det.get("element_id_at_write"),
            })
        elif instr.action == "DELETE_NODE":
            salida.append({
                "operation_id": instr.operation_id,
                "kind": "NODE",
                "identidad_durable": {
                    "workspace": det.get("workspace"),
                    "id": det.get("created_id") or instr.target_id,
                    "label": det.get("label"),
                    "partida_id": det.get("partida_id"),
                },
            })
    return salida


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


def _volcar(ruta: Path, doc: Any) -> None:
    """Un documento JSON del operador, determinista y sin rutas de nadie."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
        help="documento de decisiones de identidad. SE ESCRIBE solo cuando la "
             "corrida abrio el grafo (--desde-grafo o --apply): el documento "
             "se reconcilia contra lo que el grafo tiene, y sin grafo no hay "
             "con que reconciliar. En una ingesta OFFLINE esta ruta no se "
             "escribe y el mando lo dice, en vez de ignorarla en silencio. "
             "Se LEE en --revisar y en el APPLY",
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
                        help="quien aprueba las altas o promueve revisiones. "
                             "Obligatorio con --revisar")
    parser.add_argument(
        "--promociones", type=Path, default=None, metavar="RUTA",
        help="documento de PROMOCIONES de revision. Se ESCRIBE en cada "
             "ingesta con lo que el motor mando a REVIEW (para que el revisor "
             "no tenga que abrir el informe.json), se edita con "
             "--revisar --promover, y se LEE en la ingesta siguiente. "
             "Con --out-dir se escribe ademas en DIR/promociones.json",
    )
    parser.add_argument(
        "--promover", action="append", default=[], dest="promover",
        metavar="CLAIM_ID",
        help="MODO REVISION: promueve ESE claim de REVIEW asumiendo sus "
             "motivos actuales. Repetible. No existe 'promover todo': cada "
             "promocion es una firma sobre unos motivos concretos, y si esos "
             "motivos cambian la firma caduca y no se aplica",
    )
    parser.add_argument(
        "--nota-promocion", default=None, dest="nota_promocion",
        help="por que se promueve. Queda en el documento y en la explicacion "
             "de la decision",
    )

    # -- escritura real ------------------------------------------------------
    parser.add_argument(
        "--apply", action="store_true",
        help="ESCRITURA REAL. Exige ademas el gate del writer: "
             "S9K_ALLOW_REAL_INGEST=1, S9K_WRITER_WORKSPACE y --operador",
    )
    parser.add_argument(
        "--rollback-out", type=Path, default=None, metavar="RUTA",
        help="donde guardar el DOCUMENTO DE ROLLBACK del apply: la poliza que "
             "`knowledge_v3.writer.cli_rollback` ejecuta para deshacerlo. Sin "
             "--out-dir, este mando no emitia ninguna y el operador tenia que "
             "extraer el plan del informe.json a mano. Con --out-dir se "
             "escribe ademas en DIR/rollback.json",
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


def _promociones_path(args: argparse.Namespace) -> Path:
    if args.promociones is not None:
        return args.promociones
    if args.out_dir is not None:
        return args.out_dir / "promociones.json"
    raise PipelineError(
        "config",
        "no se dijo donde vive el documento de promociones: usa "
        "--promociones o --out-dir",
    )


def _leer_promociones(ruta: Path) -> promo.PromotionLedger:
    return promo.PromotionLedger.from_dict(
        json.loads(ruta.read_text(encoding="utf-8"))
    )


def _promover(args: argparse.Namespace) -> int:
    """Firma la promocion de unos claims en REVIEW. No abre ninguna conexion.

    La firma se ata a los motivos que el documento registro cuando la corrida
    los produjo. Aqui no se juzga nada: se comprueba que el claim esta en la
    lista de pendientes y se copian SUS motivos a la firma. Que la firma siga
    valiendo en la ingesta siguiente lo decide `engine.promotion`, comparando
    contra lo que el motor produzca entonces.
    """
    ruta = _promociones_path(args)
    if not ruta.exists():
        print(f"ERROR: no hay documento de promociones en {ruta}. Corre "
              "primero la ingesta con --out-dir o --promociones para que se "
              "genere con lo que el motor mando a REVIEW", file=sys.stderr)
        return exit_codes.EXIT_USAGE
    doc = _leer_promociones(ruta)
    pendientes = {p["claim_id"]: p for p in doc.pending}
    ya = doc.by_claim()
    incompletos = sorted(
        c for c in args.promover
        if c in pendientes and not pendientes[c].get("promovible", True)
    )
    if incompletos:
        for c in incompletos:
            print(f"ERROR: {c} no es promovible: le falta "
                  f"{pendientes[c]['no_promovible_por']}. Un ACCEPT sobre un "
                  "claim incompleto no valida contra el contrato congelado",
                  file=sys.stderr)
        return exit_codes.EXIT_USAGE
    desconocidos = sorted(set(args.promover) - set(pendientes))
    if desconocidos:
        print(f"ERROR: estos claims no estan pendientes de revision en "
              f"{ruta}: {desconocidos}. Pendientes: {sorted(pendientes)}",
              file=sys.stderr)
        return exit_codes.EXIT_USAGE
    ahora = _utc_now()
    nuevas = []
    for claim_id in sorted(set(args.promover)):
        if claim_id in ya:
            continue
        nuevas.append(promo.ClaimPromotion(
            claim_id=claim_id,
            reason_codes=tuple(pendientes[claim_id]["reason_codes"]),
            promoted_by=args.revisor,
            promoted_at=ahora,
            note=args.nota_promocion or "",
        ))
    doc.promotions = list(doc.promotions) + nuevas
    _volcar(ruta, doc.to_dict())
    print(json.dumps({
        "documento": str(ruta),
        "revisor": args.revisor,
        "promovidas_ahora": [p.claim_id for p in nuevas],
        "ya_promovidas": sorted(set(args.promover) & set(ya)),
        "pendientes_sin_promover": sorted(set(pendientes) - {p.claim_id for p in doc.promotions}),
        "totals": doc.to_dict()["totals"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
    # PROMOCION DE REVISIONES. Es la salida que `REVIEW` no tenia: hasta
    # ahora `--aprobar-alta` solo aprobaba altas de ENTIDAD y una relacion en
    # revision no tenia ningun mando que la moviera.
    if args.promover:
        return _promover(args)
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

        promociones: list = []
        if args.promociones is not None and args.promociones.exists():
            promociones = list(_leer_promociones(args.promociones).promotions)

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
            promotions=promociones,
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
                # EQUIPO 8A. La superficie de la mencion ya no basta para
                # nombrar una entidad: cuando el mundo (grafo + `--catalogo`)
                # conoce esa identidad, el nombre y los alias salen de ahi.
                catalog_by_entity=identidades_por_entidad(
                    merge_catalogo(filas, load_catalog(args.catalogo))
                ),
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
        # EL PLAN SELLADO, COMO FICHERO. El unico mando que emitia poliza
        # (`writer.cli --rollback-out`) exige un fichero de plan que NADIE
        # producia: un supervisor tuvo que extraerlo del informe.json a mano.
        # Ahora sale solo, y es el mismo documento que el writer verifica.
        if report.get("plan") is not None:
            _volcar(args.out_dir / "plan.json", report["plan"])
            print(f"plan:    {args.out_dir / 'plan.json'}")
        # EL PAQUETE DE PROCEDENCIA. Es lo que el plan no puede llevar dentro y
        # lo que hace que `writer.cli --procedencia` alcance el MISMO grafo.
        if report.get("procedencia_paquete") is not None:
            _volcar(args.out_dir / "procedencia.json",
                    report["procedencia_paquete"])
            print(f"procedencia: {args.out_dir / 'procedencia.json'}")
    # EL DOCUMENTO DE PROMOCIONES, SIEMPRE. Es lo que hace que revisar deje de
    # ser leer: sale con los claims que el motor mando a REVIEW y sus motivos,
    # listo para `--revisar --promover`. No hace falta grafo: la revision de
    # claims es una decision sobre lo que el motor dijo, no sobre el grafo.
    revision = report.get("revision") or {}
    destinos_promo: list = []
    if args.promociones is not None:
        destinos_promo.append(args.promociones)
    if args.out_dir is not None and args.promociones is None:
        destinos_promo.append(args.out_dir / "promociones.json")
    for destino in destinos_promo:
        previas = []
        if destino.exists():
            try:
                previas = list(_leer_promociones(destino).promotions)
            except (ValueError, json.JSONDecodeError) as exc:
                # Falla CERRADO: no se pisa un documento que no se entiende.
                print(f"ERROR [promociones]: {destino} ilegible: {exc}",
                      file=sys.stderr)
                return exit_codes.EXIT_USAGE
        doc = promo.PromotionLedger(
            workspace=report["run"]["workspace"],
            partida_id=args.partida_id,
            source_path=str(args.fichero),
            generated_at=report["run"]["now"],
            promotions=previas,
            pending=revision.get("pendientes") or [],
        )
        _volcar(destino, doc.to_dict())
        print(f"promociones: {destino} "
              f"({len(doc.pending)} en REVIEW, {len(doc.promotions)} promovidas)")
    for entrada in revision.get("promociones") or []:
        print(f"promocion[{entrada['code']}] {entrada['claim_id']}: "
              f"{entrada['detail']}")
    for fila in revision.get("pendientes") or []:
        marca = "" if fila.get("promovible", True) else \
            f" [NO PROMOVIBLE: falta {','.join(fila['no_promovible_por'])}]"
        print(f"  REVISION PENDIENTE {fila['claim_id']} "
              f"({fila['predicate']} conf={fila['confidence']:.3f}) "
              f"{','.join(fila['reason_codes'])}{marca}")

    if ledger is None and args.decisiones is not None:
        # Antes esto no se decia: el operador pasaba --decisiones RUTA en una
        # ingesta offline, el fichero no aparecia nunca y la ayuda afirmaba
        # que "se escribe en la ingesta".
        print(f"decisiones: NO SE ESCRIBE {args.decisiones}: esta corrida no "
              "abrio el grafo (hace falta --desde-grafo o --apply para poder "
              "reconciliar las decisiones contra lo que el grafo tiene)",
              file=sys.stderr)
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
    # LA POLIZA DEL APPLY. Un apply que escribe y no publica como deshacerlo
    # deja al operador con conocimiento en el grafo y sin documento de
    # reversion -- que es justo lo que la ruta de operador existe para evitar.
    destinos_rollback = []
    if args.rollback_out is not None:
        destinos_rollback.append(args.rollback_out)
    if args.out_dir is not None:
        destinos_rollback.append(args.out_dir / "rollback.json")
    doc_rollback = report.get("rollback")
    for destino in destinos_rollback:
        if doc_rollback is None:
            print(f"rollback: SIN DOCUMENTO ({destino} no se escribe): "
                  "esta corrida no aplico nada", file=sys.stderr)
            continue
        # NUNCA se pisa una poliza existente con un documento SIN
        # instrucciones: repetir un apply es un no-op idempotente y su
        # documento va vacio; escribirlo encima borraria la unica forma de
        # deshacer lo que se aplico la primera vez. Misma regla que
        # `writer.cli.save_rollback`, y por la misma razon.
        if destino.exists() and not (doc_rollback.get("instructions") or []):
            print(f"rollback: SE CONSERVA la poliza previa en {destino} (el "
                  "documento nuevo no trae instrucciones)")
            continue
        _volcar(destino, doc_rollback)
        print(f"rollback: {destino} "
              f"({len(doc_rollback.get('instructions') or [])} instrucciones)")
    if args.apply and report.get("apply_identity"):
        print("apply_identity: " + json.dumps(
            report["apply_identity"], ensure_ascii=False, sort_keys=True))
    if args.apply and report.get("apply"):
        for nota in report["apply"]["notes"]:
            print(f"apply[{nota['code']}] {nota['detail']}")
        if report["apply"]["dangling_fragment_ids"]:
            print("apply: REFERENCIAS COLGANTES -> "
                  + ", ".join(report["apply"]["dangling_fragment_ids"]),
                  file=sys.stderr)
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
