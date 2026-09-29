# -*- coding: utf-8 -*-
"""CONTRATO MÍNIMO DEL MANIFIESTO DE PARTIDA — CORTE 6B-2(b).

## POR QUÉ ESTE CONTRATO EXISTE, Y POR QUÉ ES PEQUEÑO A PROPÓSITO

La decisión del operador (C2) prohíbe un escritor de partida sin contrato ni
parser: no se puede mutar `<juego>/partidas/<p>/manifiesto-partida.json` "a
pelo". Este módulo es ese contrato — deliberadamente MÍNIMO, no una entrada
nueva en la familia `*/v3-internal-v1`
(``data-engine/app/knowledge_v3/contracts``).

``vault_writer.py`` (6B-2a) ya diagnosticó por qué: esa familia es maquinaria
pensada para documentos de EXTRACCIÓN (``GameProfile``, ``SourceAsset``,
``Claim``...), con su propio ``.schema.json`` congelado en
``contracts/knowledge-v3/v1/``, registrado en ``CONTRACT_CLASSES`` y validado
por un módulo compartido motor+visor. Meter ahí un documento de PRESENTACIÓN
puramente humano (una etiqueta, nada más) sería la "decisión de modelo nueva"
que 6B-2a dejó explícitamente fuera de su alcance. Este contrato vive donde
vive su único lector/escritor real hoy (``viewer/app``: primero
``presentacion_etiquetas.py`` que solo lee, ahora también ``vault_writer.py``
que escribe), sin tocar el registro V3 ni su validador compartido.

## LA IDENTIDAD NO VIVE AQUÍ

Este documento NUNCA declara ``workspace`` ni ``partida_id`` dentro de sí
mismo: la identidad de una partida es la CARPETA que la descubre
(``sources_catalog.partidas_descubiertas_en_boveda`` /
``vault_scope.clasificar``), no un campo dentro de este fichero. Un documento
que declarase su propia identidad sería una SEGUNDA autoridad capaz de
divergir de la carpeta que lo contiene — la misma clase de defecto que el
Corte 6A cerró para ``partida_access``. Por eso el contrato ni admite ni
exige esos campos, y por eso "conceder es crear" (la decisión que gobierna
este corte) sigue intacta: escribir este fichero nunca hace existir una
partida que la bóveda no clasificara ya.

## QUÉ CLAVES ACEPTA — CONTRATO CERRADO EN EL PRIMER NIVEL

Solo ``metadata`` (objeto JSON abierto: la MISMA excepción de lista blanca
que ya tiene ``perfil-operador.json`` / ``GameProfile.metadata``, documentada
en ``sources_catalog._NO_SON_FUENTES`` y en ``presentacion_etiquetas.py``).
Cualquier otra clave de primer nivel deja el documento LEGIBLE_NO_CONFORME:
este contrato no inventa un esquema más amplio del que el fichero necesita
HOY (un nombre humano en ``metadata.label``); ampliarlo para representar más
cosas de una partida es una decisión explícita futura, no un efecto
colateral de este escritor.

``metadata``, cuando está presente, tiene que ser un objeto JSON. Sus claves
son libres (igual que en ``GameProfile.metadata``) SALVO ``label``, que es el
campo que este contrato existe para llevar y que por tanto SÍ está tipado
(D2 de la revisión independiente de PR #259: ``{"metadata": {"label": 42}}``
salía CONFORME y el POST devolvía 302; un contrato que no tipa su campo
principal no está contratando nada):

* ``label`` ausente → CONFORME (la partida todavía no tiene nombre humano).
* ``label`` cadena de texto → CONFORME.
* ``label`` cadena vacía (o sólo espacios) → CONFORME, y significa
  EXACTAMENTE lo mismo que ausente. Es la semántica que ya tiene el
  escritor: ``vault_writer._label_declarado`` normaliza el blanco a ``""``, y
  ``escribir_label_*`` trata el valor vacío como BORRADO (hace
  ``metadata.pop("label")``). Rechazar aquí lo que el escritor considera "sin
  nombre" haría no editable un documento que el propio escritor podría dejar
  así.
* ``label`` número, lista, objeto o booleano → ``LEGIBLE_NO_CONFORME``, y el
  documento NO es editable hasta que se corrija a mano. No se coacciona a
  texto: eso reescribiría en silencio lo que declaró otra autoridad.

El contrato de ENTRADA del propio valor de ``label`` (longitud, caracteres de
control) lo sigue imponiendo ``vault_writer._label_entrada_invalida`` — la
misma autoridad que ya usa el escritor de workspace — no una segunda regla
aquí: lo que este módulo decide es el TIPO, no la forma del texto.

``metadata`` declarado con ``null`` NO es lo mismo que ``metadata`` ausente
(D3 de la misma revisión). El docstring de esta clase siempre afirmó que
``None`` significa «el documento no declara el bloque» y que se distingue de
``{}``; hasta ahora no se distinguía, porque ``datos.get("metadata")``
devuelve ``None`` en los dos casos, y el escritor recibía un ``null`` donde
espera un mapping. Un ``metadata: null`` explícito es ahora
``LEGIBLE_NO_CONFORME``.

## EL PARSER ES LA ÚNICA VÍA DE ENTRADA/SALIDA

``ManifiestoPartida.from_dict`` es el único punto que decide si un dict
recién parseado de disco cumple el contrato (entrada), y se vuelve a llamar
sobre el dict mutado antes de escribir (salida) — mismo patrón de doble
validación que ``vault_writer._game_profile_from_dict`` para el perfil de
workspace.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Identificador de este contrato PROPIO, fuera de la familia
#: `*/v3-internal-v1`. No se registra en `CONTRACT_CLASSES`: no es un
#: documento de extracción, es un documento de presentación humana.
CONTRACT_ID = "partida-manifiesto/s9k-v1"

#: Únicas claves admitidas en el primer nivel del documento.
CLAVES_ADMITIDAS = frozenset({"metadata"})


class ManifiestoPartidaInvalidoError(Exception):
    """El documento no cumple el contrato mínimo del manifiesto de partida."""


#: ÚNICA ancla que decide los tipos del bloque `metadata`. La llaman tanto
#: `from_dict` (entrada, dict recién parseado de disco) como `validate`
#: (salida, justo antes de escribir): una sola regla, dos puertas, nunca dos
#: autoridades que puedan divergir.
def _revisar_bloque_metadata(metadata: object) -> None:
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise ManifiestoPartidaInvalidoError(
            "'metadata' del manifiesto de partida tiene que ser un objeto JSON"
        )
    if "label" in metadata and not isinstance(metadata["label"], str):
        # `bool` no es `str`, así que `true`/`false` caen aquí sin regla extra.
        raise ManifiestoPartidaInvalidoError(
            "'metadata.label' del manifiesto de partida tiene que ser una "
            "cadena de texto (el nombre humano de la partida); se declaró "
            f"{type(metadata['label']).__name__}"
        )


@dataclass(frozen=True)
class ManifiestoPartida:
    """El contenido mínimo válido de un `manifiesto-partida.json`.

    `metadata` es `None` cuando el documento no declara ese bloque en
    absoluto (fichero `{}`) — se distingue de `{}` para que quien escribe
    pueda decidir si crea el bloque o no sin perder esa distinción.
    """

    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"metadata": self.metadata} if self.metadata is not None else {}

    def validate(self) -> "ManifiestoPartida":
        _revisar_bloque_metadata(self.metadata)
        return self

    @classmethod
    def from_dict(cls, datos: object, *, validate: bool = True) -> "ManifiestoPartida":
        """Reconstruye desde un dict ya parseado. Contrato CERRADO: cualquier
        clave de primer nivel fuera de `CLAVES_ADMITIDAS` se rechaza -- no se
        ignora en silencio, porque una clave desconocida silenciada hoy es
        una migración de esquema invisible mañana."""
        if not isinstance(datos, dict):
            raise ManifiestoPartidaInvalidoError(
                "el manifiesto de partida no es un objeto JSON"
            )
        claves_desconocidas = set(datos) - CLAVES_ADMITIDAS
        if claves_desconocidas:
            raise ManifiestoPartidaInvalidoError(
                "el manifiesto de partida declara claves fuera del contrato "
                f"minimo (solo {sorted(CLAVES_ADMITIDAS)} es valido): "
                f"{sorted(claves_desconocidas)}"
            )
        # D3: ausente y `null` NO son lo mismo. Sin esta guarda, `.get()`
        # devuelve `None` en ambos casos y el `null` explícito se cuela como
        # "el documento no declara el bloque", que es justo la distinción que
        # el docstring de esta clase promete conservar.
        if "metadata" in datos and datos["metadata"] is None:
            raise ManifiestoPartidaInvalidoError(
                "el manifiesto de partida declara 'metadata' con null: null no "
                "es un objeto JSON, y no equivale a no declarar el bloque "
                "(ausente = la partida no tiene metadata; null = alguien "
                "escribió algo que no es un objeto)"
            )
        metadata = datos.get("metadata")
        _revisar_bloque_metadata(metadata)
        instancia = cls(metadata=metadata)
        if validate:
            instancia.validate()
        return instancia
