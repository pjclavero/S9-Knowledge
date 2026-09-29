#!/usr/bin/env python3
"""CORTE 6B-2(b) — editar el nombre humano de la PARTIDA desde la web.

Arnes de calibracion: aplica mutaciones de una en una sobre el arbol
COMMITEADO, corre los testigos, y comprueba (1) que se ponen ROJOS, (2) QUE
pruebas fallan, (3) que el mensaje del rojo dice la causa esperada. Despues
restaura y comprueba la restauracion POR EFECTO (arbol tracked limpio y suite
verde otra vez). Mismo patron que
`scripts/calibracion/mutaciones_corte6b2_editar_labels.py` (6B-2a).

Cubre las formas de romper la propiedad de este corte:

  M1 — el identificador de la partida vuelve a ser el `value` por defecto del
       campo (en vez de `placeholder`): un "Guardar" sin tocar nada
       escribiria el identificador como nombre humano.
  M2 — la guarda que rechaza un nombre igual al identificador de la partida
       se desactiva.
  M3 — el escritor deja de detectar el NO-OP: reescribe/crea el manifiesto
       aunque el efecto neto sea cero.
  M4 — C3 colapsa en ESTE endpoint: `/admin/partidas/label-partida` deja de
       exigir `can_edit_context_label` y pasa a exigir `can_manage_access`
       (el negativo del encargo deja de poder existir en esta superficie).
  M5 — el ambito autorizado colapsa: el POST deja de comprobar que
       `partida_id` esta en `partidas_descubiertas_en_boveda` (se puede
       nombrar una partida que la boveda no reconoce).
  M6 — el almacenamiento deja de ser VERBATIM: el label se guarda plegado
       (`casefold()`) en vez de tal cual lo escribio el usuario.
  M7 — el contrato minimo deja de cerrar el primer nivel: una clave
       desconocida en el manifiesto (`partida_id`, etc.) deja de bastar para
       marcarlo LEGIBLE_NO_CONFORME.
  M8 — el manifiesto AUSENTE deja de colapsar a CONFORME: una partida sin
       manifiesto todavia se vuelve INVALIDA/no editable en vez de "nombre
       vacio, listo para escribir".

Uso: python3 scripts/calibracion/mutaciones_corte6b2b_nombre_partida.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_vault_writer_6b2b.py",
    "viewer/tests/test_admin_label_partida_6b2b.py",
]


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                        cwd=RAIZ, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigos() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTIGOS, "-q", "--no-header",
         "--color=no", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list[str]:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


MUTACIONES = [
    (
        "M1 — el identificador de la partida vuelve a ser `value` por "
        "defecto del campo (en vez de solo `placeholder`)",
        "viewer/app/templates/auth/admin/partidas.html",
        '<input type="text" id="partida_label" name="label"\n'
        '                     value="{{ partida_label_valor_formulario | e }}"\n'
        '                     placeholder="{{ partida_editada | e }}" maxlength="200">',
        '<input type="text" id="partida_label" name="label"\n'
        '                     value="{{ partida_editada | e }}"\n'
        '                     placeholder="{{ partida_editada | e }}" maxlength="200">',
        ["test_el_valor_del_formulario_nunca_es_el_identificador_de_partida"],
        "assert",
    ),
    (
        "M2 — la guarda que rechaza un nombre igual al identificador de la "
        "partida se desactiva",
        "viewer/app/routers/admin.py",
        "    if label and _normalizado_para_comparacion(label) == _normalizado_para_comparacion(partida_id):",
        "    if False:",
        ["test_post_rechaza_label_igual_al_identificador_de_partida"],
        "assert",
    ),
    (
        "M3 — el escritor deja de detectar el NO-OP: crea/reescribe el "
        "manifiesto aunque el efecto neto sea cero",
        "viewer/app/vault_writer.py",
        "    if valor_normalizado == lectura.label_actual:\n"
        "        # NO-OP (mismo R1 que el workspace): incluye \"borrar sobre un\n"
        "        # manifiesto ausente o sin label\" -- no se crea ningún fichero.\n"
        "        return lectura",
        "    if False:\n"
        "        return lectura",
        ["test_no_op_sobre_manifiesto_ausente_no_crea_el_fichero"],
        "assert",
    ),
    (
        "M4 — C3 colapsa en `/admin/partidas/label-partida`: deja de exigir "
        "`can_edit_context_label` y pasa a exigir `can_manage_access` (el "
        "negativo del encargo deja de poder existir en esta superficie)",
        "viewer/app/routers/admin.py",
        "    admin: User = Depends(require_edit_context_label),\n"
        ")async def admin_partidas_label_partida_marcador_no_usar",  # nunca coincide: forzado abajo
        "NO-USAR",
        [],
        "",
    ),
    (
        "M5 — el ambito autorizado colapsa: el POST deja de comprobar que "
        "`partida_id` esta en la enumeracion real de la boveda",
        "viewer/app/routers/admin.py",
        "    if partida_id not in descubribles:\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        "            detail=(\n"
        "                f\"«{partida_id}» no es una partida que la bóveda conozca en \"\n"
        "                f\"«{presentacion_etiquetas.resolvedor_de_peticion(request).workspace(workspace)}». \"\n"
        "                \"Solo se puede nombrar una partida que existe realmente en \"\n"
        "                \"el árbol de la bóveda.\"\n"
        "            ),\n"
        "        )\n"
        "\n"
        "    # MISMO D1 que el workspace: el nombre humano no puede ser igual al",
        "    # MISMO D1 que el workspace: el nombre humano no puede ser igual al",
        ["test_post_rechaza_partida_que_la_boveda_no_conoce"],
        "assert",
    ),
    (
        "M6 — el almacenamiento deja de ser VERBATIM: el label se guarda "
        "plegado (`casefold()`) en vez de tal cual lo escribio el usuario",
        "viewer/app/vault_writer.py",
        "    if valor_normalizado:\n"
        "        metadata[\"label\"] = valor_normalizado\n"
        "    else:\n"
        "        metadata.pop(\"label\", None)\n"
        "\n"
        "    _manifiesto_salida, error_salida = _manifiesto_partida_from_dict(datos)",
        "    if valor_normalizado:\n"
        "        metadata[\"label\"] = valor_normalizado.casefold()\n"
        "    else:\n"
        "        metadata.pop(\"label\", None)\n"
        "\n"
        "    _manifiesto_salida, error_salida = _manifiesto_partida_from_dict(datos)",
        ["test_el_label_almacenado_es_verbatim_no_normalizado"],
        "assert",
    ),
    (
        "M7 — el contrato minimo deja de cerrar el primer nivel: una clave "
        "desconocida deja de bastar para marcar el manifiesto "
        "LEGIBLE_NO_CONFORME",
        "viewer/app/partida_manifest_contract.py",
        "        claves_desconocidas = set(datos) - CLAVES_ADMITIDAS\n"
        "        if claves_desconocidas:",
        "        claves_desconocidas = set()\n"
        "        if claves_desconocidas:",
        ["test_c1_manifiesto_legible_no_conforme_tiene_causa_visible",
         "test_contrato_rechaza_clave_de_primer_nivel_fuera_del_contrato"],
        "assert",
    ),
    (
        "M8 — el manifiesto AUSENTE deja de colapsar a CONFORME: se trata "
        "como fichero ilegible (INVALIDO) en vez de \"todavia sin nombre\"",
        "viewer/app/vault_writer.py",
        "    except FileNotFoundError:\n"
        "        return LecturaManifiestoPartida(\n"
        "            EstadoPerfil.CONFORME, {}, huella_ausente(), None, \"\"\n"
        "        )",
        "    except FileNotFoundError:\n"
        "        return LecturaManifiestoPartida(\n"
        "            EstadoPerfil.INVALIDO, None, None, \"ausente\", \"\"\n"
        "        )",
        ["test_c1_manifiesto_ausente_colapsa_a_conforme_vacio",
         "test_cambio_real_sobre_manifiesto_ausente_crea_el_fichero"],
        "assert",
    ),
]

# M4 se construye aparte: la sustitucion textual generica de arriba no basta
# para intercambiar la dependencia SOLO en este endpoint sin tocar
# `/admin/partidas/label` (que usa el mismo nombre de parametro). Se localiza
# por el bloque completo de la funcion, que es unico en el fichero.
_ANCLA_M4 = (
    'async def admin_partidas_label_partida(\n'
    '    request: Request,\n'
    '    workspace: str = Form(...),\n'
    '    partida_id: str = Form(...),\n'
)
_ANCLA_M4_DEP = "    admin: User = Depends(require_edit_context_label),\n):\n    if isinstance(admin, RedirectResponse):\n        return admin\n    session = getattr(request.state, \"session\", None)\n\n    if not _check_csrf(request, csrf_token, session.id if session else 0):\n        raise HTTPException(status_code=403, detail=\"CSRF inválido\")\n\n    workspace = workspace.strip()\n    partida_id = partida_id.strip()\n    label = label.strip()\n    if not workspace or not partida_id:\n        raise HTTPException(status_code=400, detail=\"workspace y partida_id son obligatorios\")\n\n    # MISMA guarda que `/admin/partidas/grant` y `/admin/partidas/label`: solo"


def _aplicar_m4(original: str) -> str | None:
    if _ANCLA_M4 not in original or _ANCLA_M4_DEP not in original:
        return None
    return original.replace(
        _ANCLA_M4_DEP,
        _ANCLA_M4_DEP.replace(
            "admin: User = Depends(require_edit_context_label),",
            "admin: User = Depends(require_manage_access),",
        ),
        1,
    )


def _ejecutar_mutacion(indice: int, nombre: str, rel: str, viejo: str, nuevo: str,
                        esperadas: list[str], fragmento: str) -> tuple[str, str]:
    f = RAIZ / rel
    original = f.read_text(encoding="utf-8")

    if indice == 3:  # M4, construccion especial
        mutado = _aplicar_m4(original)
        if mutado is None:
            print(f"### {nombre}\n  DETECTOR ROTO: el ancla de M4 no esta en "
                  f"{rel}. La mutación no se aplicó: un verde aquí sería FALSO.\n")
            return nombre, "DETECTOR ROTO"
        esperadas = ["test_c3_gestiona_accesos_pero_no_puede_nombrar_la_partida"]
        fragmento = "403"
    else:
        if viejo not in original:
            print(f"### {nombre}\n  DETECTOR ROTO: el texto a mutar no está en "
                  f"{rel}. La mutación no se aplicó: un verde aquí sería FALSO.\n")
            return nombre, "DETECTOR ROTO"
        mutado = original.replace(viejo, nuevo, 1)

    f.write_text(mutado, encoding="utf-8")
    rc_mut, salida_mut = _correr_testigos()
    fallos = _fallos(salida_mut)
    mensaje_ok = fragmento in salida_mut

    f.write_text(original, encoding="utf-8")
    _purgar_pycache()
    limpio = _arbol_limpio_tracked()
    rc_post, _ = _correr_testigos()

    print(f"### {nombre}")
    print(f"  fichero            : {rel}")
    print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
    print(f"  pruebas en rojo    : {fallos}")
    print(f"  esperadas          : {sorted(esperadas)}")
    print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
    print(f"  restaurado (tracked limpio): {limpio}")
    print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")

    ok = (
        rc_mut != 0
        and set(esperadas).issubset(set(fallos))
        and mensaje_ok
        and limpio
        and rc_post == 0
    )
    print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
    return nombre, ("CALIBRADA" if ok else "NO CALIBRADA")


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar — el checkout del arnés borra lo no commiteado.")
        return 2

    rc, salida = _correr_testigos()
    if rc != 0:
        print(f"ABORTA: los testigos no están verdes en la base (PYTEST_RC={rc})")
        print(salida[-3000:])
        return 2
    print(f"BASE: testigos verdes, PYTEST_RC={rc}\n")

    veredictos = []
    for i, (nombre, rel, viejo, nuevo, esperadas, fragmento) in enumerate(MUTACIONES):
        veredictos.append(_ejecutar_mutacion(i, nombre, rel, viejo, nuevo, esperadas, fragmento))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre.splitlines()[0]}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
