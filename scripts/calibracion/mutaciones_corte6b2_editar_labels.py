#!/usr/bin/env python3
"""CORTE 6B-2(a) — editar el nombre humano del workspace desde la web.

Arnes de calibracion: aplica mutaciones de una en una sobre el arbol
COMMITEADO, corre los testigos, y comprueba (1) que se ponen ROJOS, (2) QUE
pruebas fallan, (3) que el mensaje del rojo dice la causa esperada. Despues
restaura y comprueba la restauracion POR EFECTO (arbol tracked limpio y suite
verde otra vez).

Cubre las formas de romper la propiedad de este corte:

  M1 — el escritor deja de comprobar la CONCURRENCIA: escribe aunque la
       huella no coincida (last-write-wins silencioso).
  M2 — el escritor deja de VALIDAR el perfil como CONFORME antes de editarlo:
       un perfil con claves fuera de contrato se edita igual (C1 roto).
  M3 — el escritor usa `GameProfile.to_json()` en vez de mutar el dict
       original: reflowea el documento del operador.
  M4 — el predicado de destino seguro deja de EJERCERSE: siempre dice que si,
       sin correr la sonda real.
  M5 — C3 colapsa: `can_edit_context_label` deja de ser una capacidad propia
       y se convierte en un alias de `can_manage_access` (el negativo deja de
       poder existir).
  M6 — (D1, revisión independiente de PR #258) la guarda que rechaza un
       label idéntico al identificador canónico se desactiva: el
       identificador vuelve a poder escribirse como nombre humano.
  M7 — (R1, segunda ronda) el escritor deja de detectar el NO-OP: reescribe
       o reflowea el documento del operador aunque el efecto neto sea cero.
  M8 — (R2, segunda ronda) la guarda D1 vuelve a comparar `casefold()`
       crudo: un homóglifo Unicode sortea el rechazo.
  M9 — (R3, segunda ronda) el filtro de control se encoge de categoría
       Unicode a sólo C0+DEL: C1, formato invisible y separadores de línea/
       párrafo vuelven a colarse.
  M10 — (reglas precisas del operador, R2) el comparador NFKC+casefold deja
       de ser sólo comparador y se usa también para transformar lo que se
       almacena: el label guardado deja de ser el que escribió el usuario.

Uso: python3 scripts/calibracion/mutaciones_corte6b2_editar_labels.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, mutar_unico  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGOS = [
    "viewer/tests/test_vault_writer_6b2.py",
    "viewer/tests/test_admin_label_6b2.py",
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
    """Nombres de los testigos en rojo, SIN el sufijo de parametrización.

    `pytest` nombra un caso parametrizado `test_x[compacto]`. Sin recortar el
    `[...]`, un testigo parametrizado NUNCA coincide con el nombre declarado en
    la tabla y el caso sale NO CALIBRADA aunque el rojo sea exactamente el
    esperado -- medido con N1, que corre sobre tres formatos.
    """
    return sorted({
        linea.split("::")[-1].split(" ")[0].split("[")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


MUTACIONES = [
    (
        "M1 — la huella deja de comparar CONTENIDO: `coincide_contenido` "
        "siempre dice que sí (last-write-wins silencioso, en las DOS "
        "revalidaciones a la vez)",
        "viewer/app/vault_writer.py",
        "        return self.sha256 == otra.sha256",
        "        return True",
        [
            "test_409_si_el_perfil_cambio_desde_que_se_leyo",
            "test_revalidacion_justo_antes_de_escribir_tambien_detecta_el_cambio",
            "test_409_si_la_huella_enviada_no_coincide",
        ],
        "assert",
    ),
    (
        "M2 — el escritor deja de exigir CONFORME (C1) A LA ENTRADA: un "
        "perfil inválido o no conforme llega a mutarse en vez de rechazarse "
        "limpio (el fallo dejar de ser controlado es la propia violación)",
        "viewer/app/vault_writer.py",
        "    lectura = leer_estado_perfil(ruta_perfil)\n"
        "    if lectura.estado != EstadoPerfil.CONFORME:\n"
        "        raise EscrituraRechazadaError(lectura.estado, lectura.causa or \"perfil no editable\")",
        "    lectura = leer_estado_perfil(ruta_perfil)",
        [
            "test_c1_escritor_rechaza_editar_un_perfil_invalido",
            "test_nunca_crea_el_directorio_del_juego",
        ],
        "AttributeError",
    ),
    (
        # N1 — POLARIDAD REDEFINIDA, NO SÓLO RENOMBRADA. El testigo anterior
        # (`test_la_escritura_no_reflowea_...`) se ponía rojo por un ACCIDENTE
        # DEL FORMATO DEL FIXTURE: comparaba líneas contra un fixture fabricado
        # con `indent=2`, el mismo formato que produce el escritor. Al pasar el
        # fixture al formato real (compacto, una línea) la comparación se
        # volvía vacua y ESTE MUTANTE PASABA. Además, la propiedad que decía
        # defender («no reflowea») el producto ya NO la promete: su docstring
        # declara que un cambio real reserializa el documento entero.
        #
        # El testigo nuevo protege lo que `to_json()` rompe de verdad y que NO
        # depende del formato: (a) `OMIT_IF_NONE` borra `learned_adapter: null`
        # —una clave del operador DESAPARECE—, y (b) se impone el orden de
        # claves del dataclass en vez del del documento del operador. Está
        # parametrizado sobre TRES serializaciones (compacta, indent=2,
        # indent=4) y las tres dan la MISMA polaridad: medido, 3 verdes sobre
        # el producto correcto y 3 rojas con este mutante, con el mismo
        # mensaje. El fragmento esperado abajo es DISCRIMINANTE (no un `assert`
        # genérico): nombra el efecto concreto.
        "M3 — el escritor reconstruye el documento desde el dataclass "
        "(`GameProfile.to_json()`) en vez de mutar el dict original: pierde "
        "claves del operador e impone su propio orden",
        "viewer/app/vault_writer.py",
        "    _escribir_atomico(ruta_perfil, datos)\n"
        "    return leer_estado_perfil(ruta_perfil)",
        "    ruta_perfil.write_text(_perfil_salida.to_json(), encoding=\"utf-8\")\n"
        "    return leer_estado_perfil(ruta_perfil)",
        ["test_un_cambio_real_conserva_el_documento_del_operador_clave_por_clave"],
        "PERDIÓ claves del documento del operador",
    ),
    (
        "M4 — el escritor deja de ejercer el predicado de destino seguro: "
        "siempre dice que SI sin correr la sonda",
        "viewer/app/vault_writer.py",
        "def destino_admite_escritura_segura(directorio: Path, *, forzar: bool = False) -> tuple[bool, str]:\n"
        "    \"\"\"`(True, \"\")` si el destino soporta reemplazo atómico seguro, si no\n"
        "    `(False, motivo)`. Cacheado por directorio tras el primer intento.\"\"\"\n"
        "    clave = str(directorio)",
        "def destino_admite_escritura_segura(directorio: Path, *, forzar: bool = False) -> tuple[bool, str]:\n"
        "    return (True, \"\")\n"
        "    clave = str(directorio)",
        ["test_predicado_de_destino_dice_que_no_en_un_directorio_de_solo_lectura"],
        "assert",
    ),
    (
        "M5 — C3 colapsa: `can_edit_context_label` se convierte en un alias "
        "de `can_manage_access` (el negativo deja de poder existir)",
        "viewer/app/auth/models.py",
        "    def can_edit_context_label(self) -> bool:\n"
        "        \"\"\"Editar `metadata.label` de un workspace/partida (Corte 6B-2).\"\"\"\n"
        "        overridden = self._overridden(\"can_edit_context_label\")\n"
        "        return self.is_admin() if overridden is None else overridden",
        "    def can_edit_context_label(self) -> bool:\n"
        "        return self.can_manage_access()",
        ["test_c3_gestiona_accesos_pero_no_puede_editar_el_label"],
        "403",
    ),
    (
        "M6 — (D1, revisión independiente de PR #258) la guarda que impide "
        "escribir el nombre humano igual al identificador canónico se "
        "desactiva: el identificador vuelve a poder colarse como label",
        "viewer/app/routers/admin.py",
        "    if label and _normalizado_para_comparacion(label) == _normalizado_para_comparacion(workspace):",
        "    if False:",
        ["test_post_rechaza_label_igual_al_identificador"],
        "assert",
    ),
    (
        "M7 — (R1, segunda ronda de revisión de PR #258) el escritor deja de "
        "detectar el NO-OP y reescribe/reflowea el documento aunque el "
        "efecto neto sea cero",
        # ANCLA AMBIGUA DESTAPADA POR EL BARRIDO DE ESTE CARRIL. La guarda del
        # NO-OP existe DOS veces en el fichero, una por escritor:
        # `escribir_label_workspace` (6B-2a) y `escribir_label_partida` (6B-2b).
        # El `replace(..., 1)` mutaba la PRIMERA, que resultaba ser la correcta
        # por pura casualidad del orden de definición: si 6B-2(b) se hubiera
        # escrito arriba, M7 habría mutado el escritor de PARTIDA y los testigos
        # de WORKSPACE habrían seguido verdes con la garantía rota. Se acota por
        # estructura al escritor que estos testigos ejercen.
        "viewer/app/vault_writer.py",
        lambda texto: mutar_en_funcion(
            texto,
            "escribir_label_workspace",
            "    if valor_normalizado == lectura.label_actual:",
            "    if False:",
        ),
        None,
        [
            "test_no_op_de_borrado_sobre_perfil_compacto_no_reescribe_nada",
            "test_no_op_guardando_el_mismo_label_sobre_perfil_compacto_no_reescribe_nada",
        ],
        "assert",
    ),
    (
        "M8 — (R2, segunda ronda de revisión de PR #258) la guarda D1 vuelve "
        "a comparar `casefold()` crudo: un homóglifo Unicode (fullwidth, u "
        "otra letra que se ve igual) vuelve a colarse",
        "viewer/app/routers/admin.py",
        "    if label and _normalizado_para_comparacion(label) == _normalizado_para_comparacion(workspace):",
        "    if label and label.casefold() == workspace.casefold():",
        [
            "test_post_rechaza_homoglifos_del_identificador[fullwidth]",
            "test_post_rechaza_homoglifos_del_identificador[otro_bloque_u217c]",
        ],
        "assert",
    ),
    (
        "M9 — (R3, segunda ronda de revisión de PR #258) el filtro de "
        "control se encoge de categoría Unicode a sólo C0+DEL: C1, formato "
        "invisible y separadores de línea/párrafo vuelven a colarse crudos",
        "viewer/app/vault_writer.py",
        "    if any(unicodedata.category(c) in _CATEGORIAS_DE_CONTROL_PROHIBIDAS for c in texto):",
        "    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in texto):",
        [
            "test_servidor_rechaza_controles_ampliados[c1_u0080]",
            "test_servidor_rechaza_controles_ampliados[c1_u009f]",
            "test_servidor_rechaza_controles_ampliados[sep_linea_u2028]",
            "test_servidor_rechaza_controles_ampliados[sep_parrafo_u2029]",
            "test_servidor_rechaza_controles_ampliados[nel_u0085]",
            "test_servidor_rechaza_controles_ampliados[cero_ancho_u200b]",
            "test_servidor_rechaza_controles_ampliados[bidi_rlo_u202e]",
            "test_servidor_rechaza_controles_ampliados[bidi_lri_u2066]",
            "test_servidor_rechaza_controles_ampliados[bidi_pdi_u2069]",
        ],
        "DID NOT RAISE",
    ),
    (
        "M10 — (reglas precisas del operador para R2) NFKC+casefold deja de "
        "ser SÓLO el comparador y se usa también para transformar lo que se "
        "ALMACENA: el label guardado deja de ser el que escribió el usuario",
        "viewer/app/routers/admin.py",
        "        vault_writer.escribir_label_workspace(carpeta, label, huella_cliente)",
        "        vault_writer.escribir_label_workspace(carpeta, _normalizado_para_comparacion(label), huella_cliente)",
        [
            "test_admin_puede_editar_el_label_del_workspace",
            "test_el_label_almacenado_es_el_que_escribio_el_usuario_no_el_normalizado",
        ],
        "assert",
    ),
]


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
    for nombre, rel, viejo, nuevo, esperadas, fragmento in MUTACIONES:
        f = RAIZ / rel
        original = f.read_text(encoding="utf-8")
        # NO `replace(viejo, nuevo, 1)`: ese `1` elige la PRIMERA aparición en
        # todo el fichero, y convierte la POSICIÓN —que cualquier carril mueve
        # sin darse cuenta— en parte de la garantía. Es el defecto que ya se
        # cobró a M6 de Corte 1 (ver `corte1_existencia_partida.py`): un bloque
        # legítimo nuevo apareció antes, la mutación cayó en él y el arnés
        # siguió verde con la garantía real intacta. `mutar_unico` exige que el
        # ancla sea ÚNICA y, si no lo es, da DETECTOR ROTO en vez de mutar el
        # sitio equivocado en silencio.
        # `viejo` puede ser un texto literal o un LOCALIZADOR ESTRUCTURAL
        # (callable texto -> texto|None), igual que en Corte 1. Un localizador
        # que devuelve None es DETECTOR ROTO, nunca un verde silencioso.
        if callable(viejo):
            mutado = viejo(original)
            motivo_estructural = (
                "el localizador estructural no pudo acotar el sitio "
                "(función ausente, duplicada, o ancla no única dentro de ella)"
            )
        else:
            mutado = mutar_unico(original, viejo, nuevo)
            motivo_estructural = None
        if mutado is None:
            if motivo_estructural is not None:
                motivo = motivo_estructural
            else:
                veces = original.count(viejo)
                motivo = ("el texto a mutar no está" if veces == 0 else
                          f"el ancla aparece {veces} veces (AMBIGUA: no identifica un sitio)")
            print(f"### {nombre}\n  DETECTOR ROTO: {motivo} en {rel}. "
                  f"La mutación no se aplicó: un verde aquí sería FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

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
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre.splitlines()[0]}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
