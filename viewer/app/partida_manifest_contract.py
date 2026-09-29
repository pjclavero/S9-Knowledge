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

``metadata``, cuando está presente, solo se exige que sea un objeto JSON: el
resto de sus claves (incluida ``label``) son libres, igual que en
``GameProfile.metadata``. El contrato de ENTRADA del propio valor de
``label`` (longitud, caracteres de control) lo sigue imponiendo
``vault_writer._label_entrada_invalida`` — la misma autoridad que ya usa el
escritor de workspace — no una segunda regla aquí.

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
        if self.metadata is not None and not isinstance(self.metadata, dict):
            raise ManifiestoPartidaInvalidoError(
                "'metadata' del manifiesto de partida tiene que ser un objeto JSON"
            )
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
        metadata = datos.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ManifiestoPartidaInvalidoError(
                "'metadata' del manifiesto de partida tiene que ser un objeto JSON"
            )
        instancia = cls(metadata=metadata)
        if validate:
            instancia.validate()
        return instancia
