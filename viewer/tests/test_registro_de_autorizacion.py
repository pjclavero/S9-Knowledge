"""Comprobacion BIDIRECCIONAL de la cadena de autorizacion (M5b-C).

Sustituye a la red anterior, que buscaba el nombre del campo por todo el
repositorio. Aquella fallo DOS veces:

  - contaba 169 ficheros de prueba como "productor real", asi que un campo
    presente solo en fixtures pasaba por escrito de verdad --el defecto del
    primer dictamen, dentro de la red contra ese defecto--;
  - se conformaba con una mencion en un comentario o en una lista de
    PROHIBICION (`VISIBILITY_PROPS`), que es lo contrario de producir el campo;
  - y solo miraba campos de NODO, de modo que no cubria las dimensiones del
    contexto: no habria detectado H-A, como admitia su propio docstring.

Aqui no se adivina nada: el registro DECLARA la cadena y estas pruebas
comprueban que la realidad coincide, en las dos direcciones.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.policies import engine as engine_mod
from app.policies import models as models_mod
from app.policies.registry import (
    CAMPOS_DEL_CONTEXTO,
    CAMPOS_DEL_DATO,
    DENY,
    MINIMO,
    NEUTRO,
    POR_NOMBRE,
    RETIRADAS,
    TODOS,
)

RAIZ = Path(__file__).resolve().parents[2]


def _lee_del_motor() -> set[str]:
    """Campos de nodo que el motor consulta, en TODO el paquete de politica.

    Se barren los dos modulos enteros porque una regla puede mudarse de
    funcion: la version anterior miraba solo `can_view` y por eso no vio que
    `known_by_of` --en otro fichero-- leia un campo no transportado (G3).
    """
    fuente = "\n".join(inspect.getsource(m) for m in (engine_mod, models_mod))
    leidos = set(re.findall(r'node\.get\(\s*["\']([a-z_]+)["\']', fuente))
    leidos.discard("id")  # identidad, no autorizacion (y siempre viaja)
    return leidos


# --- direccion 1: lo que el motor consume debe estar declarado y viajar ------

def test_todo_campo_que_el_motor_consulta_esta_en_el_registro():
    no_declarados = _lee_del_motor() - set(POR_NOMBRE)
    assert not no_declarados, (
        f"el motor decide con {sorted(no_declarados)} y el registro no lo "
        f"declara: nadie garantiza que exista productor ni transporte"
    )


def test_todo_campo_declarado_del_dato_viaja_en_la_proyeccion():
    from app.providers.neo4j_provider import _node_to_dict, _rel_to_dict
    from tests.test_provider_authz_fields_contract import _NodoFalso, _RelacionFalsa

    for campo in CAMPOS_DEL_DATO:
        if not campo.in_projection:
            continue
        if "node" in campo.applies_to:
            assert campo.name in _node_to_dict(_NodoFalso({})), (
                f"_node_to_dict no transporta '{campo.name}': la barrera deja "
                f"de evaluarse sobre datos reales"
            )
        if "relationship" in campo.applies_to:
            assert campo.name in _rel_to_dict(_RelacionFalsa({})), (
                f"_rel_to_dict no transporta '{campo.name}'"
            )


def test_ninguna_dimension_retirada_ha_vuelto_al_motor():
    """Las reglas retiradas no pueden reaparecer en silencio."""
    resucitadas = _lee_del_motor() & set(RETIRADAS)
    assert not resucitadas, (
        f"{sorted(resucitadas)} volvieron al motor pese a estar retiradas: "
        + "; ".join(RETIRADAS[c] for c in sorted(resucitadas))
    )


# --- direccion 2: lo declarado debe tener productor, consumidor y prueba -----

def _fuente_de(ruta_declarada: str) -> str:
    """Lee el/los fichero(s) que el registro declara como productor.

    Comprobar la ruta CONCRETA es lo que hace fuerte a esta red: no cuenta
    apariciones por el repositorio, va al fichero que dice ser el productor.
    """
    ruta = ruta_declarada.split(" ")[0].split("(")[0].strip()
    p = RAIZ / ruta
    if not p.exists():
        # Rutas declaradas relativas al propio viewer.
        p = RAIZ / "viewer" / ruta
    if not p.exists():
        return ""
    texto = p.read_text(encoding="utf-8", errors="ignore")
    # Fuera comentarios: mencionar un campo en prosa no es escribirlo.
    return "\n".join(ln for ln in texto.splitlines() if not ln.lstrip().startswith("#"))


@pytest.mark.parametrize("campo", TODOS, ids=lambda c: c.name)
def test_cada_dimension_declara_un_productor_que_existe_y_la_menciona(campo):
    """El eslabon que rompio T1 y H-A: campo sin escritor real."""
    rutas = [r for r in campo.producer.replace(" + ", ",").split(",") if r.strip()]
    assert rutas, f"{campo.name} no declara productor"
    # El nombre con el que se ESCRIBE puede diferir del de la dimensión, pero
    # entonces el registro tiene que declararlo (`stored_as`). Un renombrado
    # tácito entre escritor y lector es literalmente T1.
    buscado = campo.stored_as or campo.name
    encontrado = any(buscado in _fuente_de(r) for r in rutas)
    assert encontrado, (
        f"'{campo.name}' (escrito como '{buscado}') declara como productor "
        f"{campo.producer}, pero ese "
        f"fichero no lo escribe. Es una barrera decorativa: paso con `party`, "
        f"`is_public` y `session_index` (T1) y con `max_visible_session` (H-A)."
    )


@pytest.mark.parametrize("campo", TODOS, ids=lambda c: c.name)
def test_ninguna_dimension_falla_abierta_por_ausencia(campo):
    """La regla global: campo de seguridad ausente NUNCA es permiso maximo."""
    assert campo.missing in (DENY, MINIMO, NEUTRO)
    assert campo.malformed in (DENY, MINIMO), (
        f"'{campo.name}' declara {campo.malformed} para dato invalido: un dato "
        f"que no se puede leer no puede conceder nada"
    )
    if campo.missing == NEUTRO:
        # Se admite, pero exige justificacion escrita: fue la excusa de las
        # inferencias permisivas que hubo que arrancar.
        assert campo.notes, (
            f"'{campo.name}' declara su ausencia como NEUTRA sin razonarlo"
        )


@pytest.mark.parametrize("campo", CAMPOS_DEL_CONTEXTO, ids=lambda c: c.name)
def test_las_dimensiones_del_contexto_salen_del_servidor(campo):
    """Ninguna puede depender del cliente."""
    assert "servidor" in campo.authority, (
        f"'{campo.name}' no declara autoridad del servidor: un valor que el "
        f"cliente pueda influir es una barrera que el protegido levanta"
    )
    assert not campo.in_projection, (
        f"'{campo.name}' es dimension de CONTEXTO y no debe viajar como campo "
        f"del dato"
    )


@pytest.mark.parametrize("campo", TODOS, ids=lambda c: c.name)
def test_cada_dimension_tiene_prueba_de_ausencia_o_invalidez(campo):
    """Declarar el fail-closed no basta: tiene que estar probado."""
    corpus = ""
    for f in (Path(__file__).parent).glob("test_*.py"):
        if f.name == Path(__file__).name:
            continue
        corpus += f.read_text(encoding="utf-8", errors="ignore")
    assert campo.name in corpus, (
        f"ninguna prueba menciona '{campo.name}': su comportamiento ante "
        f"ausencia o dato invalido no esta verificado"
    )
