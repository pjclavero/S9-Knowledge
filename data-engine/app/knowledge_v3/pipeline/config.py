# -*- coding: utf-8 -*-
"""Configuracion EXPLICITA de una corrida de la cadena.

Todo lo que cambia el comportamiento de la cadena se declara aqui y viaja al
informe. No hay lectura de entorno, no hay valores adivinados y no hay un
"modo por defecto razonable" escondido en el codigo: si algo no esta en este
objeto, no influye en la corrida.

Dos reglas duras:

1. **Dry-run por defecto** (`apply=False`). Escribir de verdad exige ademas un
   driver inyectado y las dos declaraciones que el gate del writer pide.
2. **Ningun proveedor esta encendido por defecto.** Ni Ollama ni el externo.
   Encenderlos requiere pasar el cliente/puerto correspondiente; no basta con
   poner un booleano, porque un booleano sin transporte seria una promesa.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional, Sequence

from ..benchmarks.ablations import Ablation, resolve as resolve_ablation
from ..contracts.game_profile import GameProfile
from ..engine.config import DEFAULT_CONFIG as ENGINE_DEFAULT, EngineConfig
from ..extraction.lexicon import Lexicon
from ..resolution.catalog import EntityCatalog
from ..resolution.config import DEFAULT_CONFIG as RESOLUTION_DEFAULT, ResolutionConfig
from ..resolution.glossary import GlossarySource
from .errors import PipelineError

#: Modos de proveedor, identicos a `benchmarks.ablations.PROVIDER_MODES`.
LOCAL_ONLY = "local_only"
EXTERNAL_ONLY = "external_only"
LOCAL_PLUS_EXTERNAL = "local_plus_external"
NO_OLLAMA = "no_ollama"


@dataclass(frozen=True)
class PipelineConfig:
    """Que subsistemas participan, con que piezas y sobre que workspace."""

    # -- identidad de la corrida -------------------------------------------
    workspace: str
    collection_id: str
    profile: GameProfile
    #: Instante inyectado. La cadena no llama al reloj en ningun punto.
    now: str
    ingested_at: str

    # -- proveedores --------------------------------------------------------
    #: Uno de LOCAL_ONLY / EXTERNAL_ONLY / LOCAL_PLUS_EXTERNAL / NO_OLLAMA.
    providers: str = NO_OLLAMA
    #: `OllamaClient` ya construido (con su `transport`) o un `ProviderPort` ya
    #: hecho. El orquestador lo envuelve en `OllamaProviderPort` y se lo entrega
    #: al extractor SEMANTICO. Sin el, no hay carril Ollama.
    ollama_client: Any = None
    #: `ProviderPort` del carril externo (`NvidiaProviderPort` en produccion, un
    #: doble guionizado en pruebas). Antes era un `ExternalProposalPort`: ese
    #: puerto solo servia al extractor LEGACY, que la cadena V3 ya no monta.
    external_port: Any = None
    #: `VisualProvider` para IMAGE/HANDWRITING/MAP/DIAGRAM. Sin el, esos
    #: adaptadores son stubs declarados y no producen evidencia.
    visual_provider: Any = None

    # -- extraccion ---------------------------------------------------------
    with_temporal: bool = True
    with_coreference: bool = True
    #: `None` = corrida SIN glosario (ablacion `without_glossary`).
    lexicon: Optional[Lexicon] = None

    # -- resolucion ---------------------------------------------------------
    catalog: Optional[EntityCatalog] = None
    glossary: Optional[GlossarySource] = None
    resolution_config: ResolutionConfig = RESOLUTION_DEFAULT

    # -- motor --------------------------------------------------------------
    engine_config: EngineConfig = ENGINE_DEFAULT

    # -- entradas sustituidas (ablaciones) ----------------------------------
    #: "real" = lo que produce el resolutor; "gold" = resoluciones inyectadas.
    entity_source: str = "real"
    #: "real" = lo que produce el extractor; "gold" = claims inyectados.
    claim_source: str = "real"

    # -- ledger -------------------------------------------------------------
    #: `LedgerStore` a usar. `None` = `InMemoryLedgerStore`.
    ledger_store: Any = None
    #: Registrar en el ledger lo que el motor aprobo.
    record_approved: bool = True

    # -- writer -------------------------------------------------------------
    #: DRY-RUN POR DEFECTO. `True` exige driver, operador y entorno.
    apply: bool = False
    operator_id: str = "s9k.pipeline"
    writer_driver: Any = None
    writer_env: dict = field(default_factory=dict)
    writer_clock: Optional[Callable[[], Any]] = None
    max_operations: int = 200
    #: Si `False`, el writer no se invoca en absoluto.
    with_writer: bool = True

    # -- etiqueta -----------------------------------------------------------
    ablation: str = "unspecified"

    def __post_init__(self) -> None:
        if self.providers not in (LOCAL_ONLY, EXTERNAL_ONLY, LOCAL_PLUS_EXTERNAL, NO_OLLAMA):
            raise PipelineError("config", f"modo de proveedor desconocido: {self.providers!r}")
        if self.entity_source not in ("gold", "real"):
            raise PipelineError("config", f"entity_source desconocido: {self.entity_source!r}")
        if self.claim_source not in ("gold", "real"):
            raise PipelineError("config", f"claim_source desconocido: {self.claim_source!r}")
        if self.profile.workspace != self.workspace:
            raise PipelineError(
                "config",
                f"el perfil es del workspace {self.profile.workspace!r} y la corrida "
                f"de {self.workspace!r}; el motor lo rechazaria de todos modos, "
                "pero fallar aqui dice donde esta el error",
            )
        if self.apply and self.writer_driver is None:
            raise PipelineError(
                "config",
                "apply=True sin driver inyectado: la cadena no abre conexiones por "
                "su cuenta. Pasa `writer_driver`",
            )

    # -- que extractores participan ----------------------------------------
    @property
    def wants_local_extractors(self) -> bool:
        return self.providers != EXTERNAL_ONLY

    @property
    def wants_ollama(self) -> bool:
        """Ollama participa solo en `local_plus_external`, y con cliente."""
        return self.providers == LOCAL_PLUS_EXTERNAL and self.ollama_client is not None

    @property
    def wants_external(self) -> bool:
        return (
            self.providers in (EXTERNAL_ONLY, LOCAL_PLUS_EXTERNAL, NO_OLLAMA)
            and self.external_port is not None
        )

    def declared(self) -> dict[str, Any]:
        """Lo que hay que poder leer en el informe para reproducir la corrida."""
        return {
            "workspace": self.workspace,
            "collection_id": self.collection_id,
            "profile_id": self.profile.profile_id,
            "ablation": self.ablation,
            "providers": self.providers,
            "ollama_bound": self.ollama_client is not None,
            "ollama_active": self.wants_ollama,
            "external_bound": self.external_port is not None,
            "external_active": self.wants_external,
            #: Que extractor cubre el carril de proveedor. Va al informe porque
            #: dos corridas con extractores distintos NO son comparables.
            "provider_extractor": "semantic",
            "visual_provider_bound": self.visual_provider is not None,
            "with_temporal": self.with_temporal,
            "with_coreference": self.with_coreference,
            "glossary": "with_glossary" if self.lexicon is not None else "without_glossary",
            "entity_source": self.entity_source,
            "claim_source": self.claim_source,
            "record_approved": self.record_approved,
            "with_writer": self.with_writer,
            "writer_mode": "APPLY" if self.apply else "DRY_RUN",
            "now": self.now,
        }

    def for_ablation(self, label: str, *, profiles: Optional[dict] = None) -> "PipelineConfig":
        """Copia de esta configuracion con la ablacion `label` aplicada.

        La ablacion manda sobre `providers`, `glossary`, `entity_source`,
        `claim_source` y `profile_id`; todo lo demas (clientes, catalogo,
        driver) se conserva, porque una ablacion cambia la ENTRADA, no las
        piezas. Una etiqueta desconocida falla: `ablations.resolve` ya lo hace.
        """
        ab: Ablation = resolve_ablation(label)
        profile = self.profile
        if ab.profile_id != profile.profile_id:
            if not profiles or ab.profile_id not in profiles:
                raise PipelineError(
                    "config",
                    f"la ablacion {label!r} pide el perfil {ab.profile_id!r} y no se "
                    "ha entregado. Pasa `profiles={id: GameProfile}`",
                )
            profile = profiles[ab.profile_id]
        return replace(
            self,
            ablation=ab.label,
            providers=ab.providers,
            entity_source=ab.entity_source,
            claim_source=ab.claim_source,
            lexicon=self.lexicon if ab.glossary == "with_glossary" else None,
            glossary=self.glossary if ab.glossary == "with_glossary" else None,
            profile=profile,
        )


@dataclass(frozen=True)
class GoldInjection:
    """Documentos gold que sustituyen la salida real en una ablacion.

    El orquestador NUNCA los lee por su cuenta ni sabe de donde salen: quien
    corre la ablacion los entrega. Asi la cadena no tiene acceso al gold salvo
    cuando la ablacion lo pide explicitamente, y jamas al held-out.
    """

    resolutions: Sequence[Any] = ()
    claims: Sequence[Any] = ()


__all__ = [
    "EXTERNAL_ONLY",
    "GoldInjection",
    "LOCAL_ONLY",
    "LOCAL_PLUS_EXTERNAL",
    "NO_OLLAMA",
    "PipelineConfig",
]
