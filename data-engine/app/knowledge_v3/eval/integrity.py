# -*- coding: utf-8 -*-
"""Verificacion de integridad de los corpus del arnes de la puerta 4.

Un corpus gold (de desarrollo o de generalizacion) declara el hash sha256 de
cada uno de sus ficheros en un `manifest.json`. Esta comprobacion recalcula
esos hashes contra lo que hay en disco AHORA MISMO y falla en cuanto uno no
cuadra. No decide si el cambio es legitimo -- eso lo decide una persona
actualizando el manifiesto a proposito -- solo impide que un corpus se lea
como si no hubiera cambiado cuando si lo ha hecho.

Es la misma disciplina que ya usa el manifiesto de la bateria de negaciones
congelada (campo `file_hashes`, ver su script de autoria); este modulo la hace
CUMPLIR en tiempo de carga, en vez de dejarla como metadato sin consecuencias.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping


class IntegrityError(RuntimeError):
    """Un corpus del arnes no coincide con su manifiesto declarado."""


def sha256_of(path: Path) -> str:
    """Hash sha256 del contenido BYTE A BYTE del fichero (sin normalizar)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_declared_hashes(root: Path, file_hashes: Mapping[str, str]) -> list[str]:
    """Recalcula el hash de cada ruta declarada; devuelve las discrepancias.

    `root` es el directorio del que cuelgan las rutas relativas de
    `file_hashes`. Un fichero declarado que falta en disco cuenta como
    discrepancia -- no como "0 ficheros comprobados" -- porque silenciarlo
    esconderia exactamente el caso "alguien borro un caso del gold".
    """
    mismatches: list[str] = []
    for rel in sorted(file_hashes):
        expected = file_hashes[rel]
        path = root / rel
        if not path.exists():
            mismatches.append(f"{rel}: FALTA EN DISCO (se esperaba {expected})")
            continue
        actual = sha256_of(path)
        if actual != expected:
            mismatches.append(f"{rel}: hash actual {actual} != declarado {expected}")
    return mismatches


def verify_or_raise(root: Path, file_hashes: Mapping[str, str], *, label: str) -> None:
    """Como `verify_declared_hashes`, pero rompe la carga si algo no cuadra.

    Este es el punto de la disciplina: un corpus editado sin declarar el
    cambio en su manifiesto NO se deja usar silenciosamente. Quien lo edito a
    proposito solo tiene que volver a calcular el hash y ponerlo en el
    manifiesto; quien lo edito sin darse cuenta lo descubre aqui, no tres
    bloques despues con un numero que no significa lo que dice significar.
    """
    if not file_hashes:
        raise IntegrityError(
            f"integridad de {label}: el manifiesto no declara ningun `file_hashes`; "
            "un corpus sin hashes declarados no es un corpus congelado"
        )
    mismatches = verify_declared_hashes(root, file_hashes)
    if mismatches:
        detalle = "; ".join(mismatches)
        raise IntegrityError(
            f"integridad de {label} rota ({len(mismatches)} fichero(s) no "
            f"coinciden con el manifiesto): {detalle}"
        )


__all__ = ["IntegrityError", "sha256_of", "verify_declared_hashes", "verify_or_raise"]
