#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración del Corte F-2 — autoridad canónica del workspace.

QUÉ ES ESTO
-----------
Cada garantía de F-2 se revierte DENTRO DEL PRODUCTO, se corre la prueba que
debería protegerla y se exige que se ponga roja **por su causa**: se comprueba
el MENSAJE del fallo, no el color. Un rojo con un valor pelado
(`assert 'a' == 'b'`) se lee exactamente igual que un rojo sin causa.

LA MUTACIÓN QUE EL ENCARGO PIDE POR SU NOMBRE
---------------------------------------------
«Quitar la comparación del perfil → el gate debe ponerse ROJO» es la mutación 1
(en el resolvedor) y la mutación 4 (en el preflight de despliegue). Las demás
cubren los otros cuatro negativos y el SIMÉTRICO.

EL ARNÉS SE CALIBRA A SÍ MISMO, y por dos vías
----------------------------------------------
1. **Criterio**: antes de mutar nada comprueba que cada `esperado` es PROSA y
   no un identificador que pytest imprima solo al comparar. Un criterio que
   admite identificadores no distingue un rojo mudo de uno con causa.
2. **Control nulo**: la mutación 0 cambia un COMENTARIO —no puede alterar el
   comportamiento— y tiene que dejar la suite VERDE. Si esa sale roja, el
   instrumento está roto o el árbol contaminado, y NINGÚN rojo de la tabla
   significa nada. Es el control positivo de resultado conocido que toda tabla
   que mide ausencias tiene que llevar dentro.

USO
---
    python3 scripts/calibracion/f2_autoridad_workspace.py

Requiere árbol limpio: las mutaciones se revierten con `git checkout --`, que
se lleva por delante cualquier cambio sin commitear del fichero mutado.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

RESOLVEDOR = "viewer/app/authz/autoridad_workspace.py"
PREFLIGHT = "deploy/scripts/preflight_ensayo_rc.py"
PLANTILLA = "viewer/app/templates/_aviso_autoridad_workspace.html"
PLANTILLA_REVIEW = "viewer/app/templates/v3_review.html"
ROUTER_OPS = "viewer/app/routers/chassis_operations.py"
DEPENDENCIAS = "viewer/app/authz/dependencies.py"
CATALOGO = "viewer/app/sources_catalog.py"

SUITE = "viewer/tests/test_f2_autoridad_canonica_workspace.py"
SUITE_PREFLIGHT = "deploy/tests/test_preflight_ensayo_rc.py"
SUITE_PANTALLA = "viewer/tests/test_f2_divergencia_visible_desde_el_producto.py"


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: str
    viejo: str
    nuevo: str
    prueba: str
    #: Frase que TIENE que aparecer en el fallo. Para el control nulo, `None`:
    #: ahí lo que se exige es que la prueba siga VERDE.
    esperado: str | None


CONTROL_NULO = Mutacion(
    nombre="CONTROL NULO — tocar un comentario no puede cambiar nada",
    fichero=RESOLVEDOR,
    viejo="# --- Procedencias ---",
    nuevo="# --- Procedencias (comentario tocado por el calibrador) ---",
    prueba=SUITE,
    esperado=None,
)


MUTACIONES: list[Mutacion] = [
    Mutacion(
        nombre="1 · se QUITA la comparación del perfil: el resolvedor deja de "
               "mirarlo y el entorno vuelve a ser la autoridad",
        fichero=RESOLVEDOR,
        viejo="        del_perfil = declaraciones_de_perfil(env, catalogo)",
        nuevo="        del_perfil = []",
        prueba=f"{SUITE}::test_n5_el_resultado_depende_de_la_declaracion_del_perfil",
        esperado="el perfil no se esta comparando",
    ),
    Mutacion(
        nombre="2 · se repone EL DEFECTO DE LA RONDA 3: ante la divergencia "
               "se vuelve a devolver vacío, es decir, a denegar todo",
        fichero=RESOLVEDOR,
        viejo="            return Autoridad(\n                valor=unico,\n"
              "                procedencia=PROCEDENCIA_PERFIL,\n"
              "                codigo=COD_DIVERGENTE,",
        nuevo="            return Autoridad(\n                valor=\"\",\n"
              "                procedencia=PROCEDENCIA_PERFIL,\n"
              "                codigo=COD_DIVERGENTE,",
        prueba=f"{SUITE}::test_n2_divergencia_no_resuelve_y_nombra_las_dos_declaraciones",
        esperado="con perfil y entorno discrepando NO manda el perfil",
    ),
    Mutacion(
        nombre="3 · el fallback del entorno se sella como si fuera una "
               "declaración del perfil: la procedencia deja de distinguir",
        fichero=RESOLVEDOR,
        viejo="            valor=del_entorno,\n            procedencia=PROCEDENCIA_FALLBACK,",
        nuevo="            valor=del_entorno,\n            procedencia=PROCEDENCIA_PERFIL,",
        prueba=f"{SUITE}::test_n3_el_fallback_solo_se_usa_cuando_NO_hay_perfil_y_se_sella",
        esperado="no podria distinguir una declaracion de una herencia",
    ),
    Mutacion(
        nombre="4 · se QUITA la comparación del perfil en el PREFLIGHT: vuelve "
               "a comparar tres declaraciones y da por buena la cuarta",
        fichero=PREFLIGHT,
        viejo="        declaradas = autoridad.declaraciones_de_perfil(dict(ctx.env), catalogo)",
        nuevo="        declaradas = [ctx.workspace]",
        prueba=f"{SUITE_PREFLIGHT}::test_f2_el_preflight_no_re_deriva_la_lectura_del_perfil",
        esperado="ya no pregunta al resolvedor canonico del producto",
    ),
    Mutacion(
        nombre="5 · el cartel deja de avisar: el operador vuelve a ver un "
               "workspace y a recibir un 400 sin explicación",
        fichero=PLANTILLA,
        viejo='data-testid="aviso-autoridad-workspace"',
        nuevo='data-testid="aviso-desactivado-por-el-calibrador"',
        prueba=f"{SUITE_PANTALLA}::test_la_pantalla_de_partidas_avisa_de_la_divergencia",
        esperado="la pantalla NO avisa de que las dos autoridades",
    ),
    Mutacion(
        nombre="6 · SIMÉTRICO — el resolvedor llama divergencia a que el "
               "entorno DIGA LO MISMO: un gate que se queja siempre no guarda",
        fichero=RESOLVEDOR,
        viejo="        if del_entorno and del_entorno != unico:",
        nuevo="        if del_entorno:",
        prueba=f"{SUITE_PANTALLA}::test_D1_simetrico_sin_divergencia_ninguna_pantalla_avisa",
        esperado="se avisa de una divergencia que no existe en",
    ),
    # ---------------------------------------------------------------------
    # RONDA 2 · D4 — el arnés no podía ver el silencio de las otras pantallas
    # ---------------------------------------------------------------------
    # Ninguna de las seis mutaciones anteriores detectaba que `/v3/review` y el
    # panel de operaciones estuvieran MUDOS, porque el aviso nunca existió allí:
    # no había nada que quitar. Ahora que existe, se puede quitar — y duele.
    Mutacion(
        nombre="7 · se quita el aviso de /v3/review: la pantalla donde el daño "
               "es una MUTACIÓN de material ajeno vuelve al silencio",
        fichero=PLANTILLA_REVIEW,
        viejo='  {% include "_aviso_autoridad_workspace.html" %}\n',
        nuevo="",
        prueba=f"{SUITE_PANTALLA}::test_D1_la_cola_de_revision_avisa_de_la_divergencia",
        esperado="sigue MUDA ante la divergencia",
    ),
    Mutacion(
        nombre="8 · se quita el aviso del panel de operaciones: desde donde se "
               "lanza la ingesta ya no se ve la divergencia",
        fichero=ROUTER_OPS,
        viejo='    ctx["autoridad_workspace"] = autoridad_workspace.aviso_para_pantalla()',
        nuevo='    ctx["autoridad_workspace"] = None',
        prueba=f"{SUITE_PANTALLA}::test_D1_el_panel_de_operaciones_avisa_de_la_divergencia",
        esperado="el panel de operaciones sigue MUDO",
    ),
    Mutacion(
        nombre="9 · SIMÉTRICO de las anteriores — el cartel se pinta SIEMPRE, "
               "también sin divergencia, en las tres pantallas",
        fichero=RESOLVEDOR,
        viejo="    resuelta = resolver(env, catalogo)\n    if not resuelta.diverge:\n        return None",
        nuevo="    resuelta = resolver(env, catalogo)\n    if False:\n        return None",
        prueba=f"{SUITE_PANTALLA}::test_D1_simetrico_sin_divergencia_ninguna_pantalla_avisa",
        esperado="se avisa de una divergencia que no existe en",
    ),
    # ---------------------------------------------------------------------
    # RONDA 3 · EL NEGATIVO ANTI-REGRESIÓN
    # ---------------------------------------------------------------------
    # Éste es el que evita que dentro de seis meses alguien "simplifique" el
    # resolvedor y REINTRODUZCA LAS DOS AUTORIDADES mientras toda la
    # configuración de fábrica coincide. Con A == B el defecto es INVISIBLE,
    # así que la única prueba que puede cazarlo es una que mantenga la
    # divergencia puesta. Su simétrico está en `CONTROLES_VERDES`.
    Mutacion(
        nombre="10 · el ENTORNO vuelve a gobernar `allowed_workspaces`: se "
               "reintroducen las dos autoridades",
        fichero=DEPENDENCIAS,
        viejo="        default_workspace=_workspace_canonico_de_la_peticion(settings),",
        nuevo="        default_workspace=settings.S9K_DEFAULT_WORKSPACE,",
        prueba=f"{SUITE_PANTALLA}::test_R3_authz_resuelve_el_workspace_del_PERFIL_con_la_divergencia_puesta",
        esperado="la autorizacion NO resuelve el workspace del perfil",
    ),
    # ---------------------------------------------------------------------
    # RONDA 4 · LA REGLA DE LA UBICACIÓN DECLARADA, EN EL LADO DE LA INGESTA
    # ---------------------------------------------------------------------
    # La regla estaba aplicada a un solo lado. Quitar la guarda del lado de la
    # ingesta no ponía roja NINGUNA prueba de F-2: lo único que la sujetaba
    # eran ~142 rojos colaterales en pruebas ajenas, que es daño incidental,
    # no un testigo. Ahora tiene el suyo.
    Mutacion(
        nombre="11 · la INGESTA vuelve a derivar el ámbito del perfil de "
               "`examples/`: la doble autoridad, íntegra y muda",
        fichero=CATALOGO,
        viejo="        if not ubicacion_declarada(env):",
        nuevo="        if False:",
        prueba=f"{SUITE_PANTALLA}::test_R4_sin_ubicacion_declarada_NO_hay_dos_autoridades",
        esperado="sigue derivando el ambito del perfil",
    ),
    # Y el cartel, que decía lo contrario de lo que hace el producto.
    Mutacion(
        nombre="12 · el cartel vuelve a atribuir permisos y partidas al "
               "ENTORNO: señala al operador el lado equivocado",
        fichero=PLANTILLA,
        viejo="<strong>no gobierna nada</strong>",
        nuevo="<strong>gobierna los permisos</strong>",
        prueba=f"{SUITE_PANTALLA}::test_R4_el_cartel_dice_que_manda_el_PERFIL_no_el_entorno",
        esperado="el cartel no dice que la declaracion del entorno NO gobierna",
    ),
]


#: MUTACIONES QUE **NO** DEBEN PONER ROJA A SU PRUEBA.
#:
#: RONDA 3. El simétrico del negativo anti-regresión, y es la mitad que da
#: sentido a la otra: con el entorno gobernando otra vez, una configuración
#: COHERENTE (A == B) sigue funcionando. Eso es precisamente lo que hace
#: invisible al defecto — y por lo que la prueba que lo caza tiene que
#: conservar la divergencia.
CONTROLES_VERDES: list = []


def _controles_verdes():
    return [
        (
            "10-sim · con el entorno gobernando otra vez, A == B SIGUE "
            "funcionando: por eso el defecto es invisible con los valores "
            "alineados",
            MUTACIONES[-1],
            f"{SUITE_PANTALLA}::test_R3_con_perfil_y_entorno_de_acuerdo_todo_funciona",
        ),
        (
            "11-sim · con la guarda de la ubicación QUITADA, una bóveda "
            "DECLARADA sigue derivando su workspace: la guarda no es lo que "
            "hace funcionar el caso legítimo",
            MUTACIONES[-2],
            f"{SUITE_PANTALLA}::test_R4_SIMETRICO_con_ubicacion_declarada_la_ingesta_SI_deriva",
        ),
    ]


#: Lo que el producto imprime por su cuenta y por tanto NO distingue causa.
_NO_SON_CAUSA = (
    "WORKSPACE_AUTHORITY_DIVERGENT", "WORKSPACE_AUTHORITY_PROFILE",
    "WORKSPACE_AUTHORITY_ENV_FALLBACK", "WORKSPACE_AUTHORITY_UNDETERMINED",
    "PERFIL_DE_BOVEDA", "FALLBACK_ENTORNO", "SIN_AUTORIDAD",
    "S9K_DEFAULT_WORKSPACE", "ROJO", "VERDE", "True", "False", "None",
)


def _esperado_es_una_frase(esperado: str) -> str | None:
    texto = esperado.strip()
    if len(texto.split()) < 3:
        return (f"{esperado!r} no es una frase (menos de tres palabras): un "
                f"identificador lo imprime pytest solo al comparar")
    for ident in _NO_SON_CAUSA:
        if texto == ident or texto in ident:
            return (f"{esperado!r} es un identificador que el producto imprime "
                    f"por su cuenta; no distingue un rojo mudo de uno con causa")
    return None


def _purgar_pycache() -> None:
    subprocess.run(
        ["find", str(REPO), "-name", "__pycache__", "-type", "d",
         "-prune", "-exec", "rm", "-rf", "{}", "+"],
        check=False, capture_output=True,
    )


def _arbol_limpio() -> bool:
    r = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                        "--untracked-files=no"],
                       capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def _leer(ruta: str) -> str:
    return (REPO / ruta).read_text(encoding="utf-8")


def _restaurar(ruta: str, original: str) -> None:
    """Y se verifica POR EFECTO, no porque el comando dijera que lo hizo."""
    subprocess.run(["git", "-C", str(REPO), "checkout", "--", ruta], check=True)
    if _leer(ruta) != original:
        raise SystemExit(
            f"RESTAURACIÓN FALLIDA en {ruta}: el árbol ha quedado mutado. "
            f"Revísalo a mano ANTES de seguir.")


def _correr(prueba: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", prueba, "-q", "-p", "no:randomly",
         "--no-header"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _aplicar(m: Mutacion) -> tuple[str, str | None]:
    """Devuelve `(original, error)`. `error` no `None` = no se mutó nada."""
    original = _leer(m.fichero)
    if m.viejo not in original:
        return original, (f"el texto a mutar ya no está en {m.fichero}: esta "
                          f"mutación no está mutando NADA")
    (REPO / m.fichero).write_text(
        original.replace(m.viejo, m.nuevo, 1), encoding="utf-8")
    return original, None


def main() -> int:
    if not _arbol_limpio():
        print("ÁRBOL SUCIO. Commitea antes: las mutaciones se revierten con "
              "`git checkout --` y se llevarían por delante tu trabajo.")
        return 2

    # AUTOCALIBRACIÓN 1 — el criterio.
    flojos = [(i, motivo) for i, m in enumerate(MUTACIONES, 1)
              if (motivo := _esperado_es_una_frase(m.esperado or ""))]
    if flojos:
        print("CRITERIO DEMASIADO FLOJO — este arnés no puede certificar nada:")
        for i, motivo in flojos:
            print(f"  · mutación {i}: {motivo}")
        return 2

    _purgar_pycache()

    # AUTOCALIBRACIÓN 2 — el control nulo, ANTES de la tabla.
    print(f"[0] {CONTROL_NULO.nombre}")
    original, error = _aplicar(CONTROL_NULO)
    if error:
        print(f"   ANCLA PERDIDA — {error}")
        return 2
    _purgar_pycache()
    try:
        rc, salida = _correr(CONTROL_NULO.prueba)
    finally:
        _restaurar(CONTROL_NULO.fichero, original)
        _purgar_pycache()
    if rc != 0:
        print("   ROJA CON UNA MUTACIÓN INOCUA — el instrumento no sirve: "
              "ningún rojo de la tabla significaría nada.")
        print(salida[-2000:])
        return 2
    print("   verde, como tenía que ser: el instrumento distingue")

    # AUTOCALIBRACION 3 — los controles que deben seguir VERDES con la
    # mutacion puesta. Sin ellos, "se pone roja" no distingue una prueba que
    # caza el defecto de una que se rompe con cualquier cosa.
    fallos = []
    for nombre, m, prueba in _controles_verdes():
        print(f"\n[V] {nombre}")
        original, error = _aplicar(m)
        if error:
            fallos.append(f"V. {error}")
            print("   ANCLA PERDIDA")
            continue
        _purgar_pycache()
        try:
            rc, salida = _correr(prueba)
        finally:
            _restaurar(m.fichero, original)
            _purgar_pycache()
        if rc != 0:
            fallos.append(f"V. {nombre}: se puso ROJA y deberia seguir verde "
                          f"({prueba})")
            print("   ROJA — el defecto NO es invisible con A == B, asi que "
                  "la prueba que lo caza no necesitaba la divergencia")
        else:
            print("   verde con la mutacion puesta, como tenia que ser")

    for i, m in enumerate(MUTACIONES, 1):
        print(f"\n[{i}/{len(MUTACIONES)}] {m.nombre}")
        original, error = _aplicar(m)
        if error:
            fallos.append(f"{i}. {error}")
            print("   ANCLA PERDIDA — la mutación no se aplicó")
            continue
        _purgar_pycache()
        try:
            rc, salida = _correr(m.prueba)
        finally:
            _restaurar(m.fichero, original)
            _purgar_pycache()

        if rc == 0:
            fallos.append(f"{i}. la prueba SIGUIÓ VERDE con la garantía "
                          f"revertida ({m.prueba})")
            print("   VERDE CON LA MUTACIÓN PUESTA — la prueba no protege nada")
        elif m.esperado not in salida:
            fallos.append(f"{i}. roja, pero SIN su causa. Se esperaba "
                          f"{m.esperado!r} en el fallo")
            print(f"   ROJA POR OTRA RAZÓN — no aparece {m.esperado!r}")
        else:
            print("   roja, y por su causa")

    print("\n" + "=" * 74)
    if fallos:
        print(f"CALIBRACIÓN FALLIDA: {len(fallos)} de {len(MUTACIONES)}")
        for f in fallos:
            print(f"  · {f}")
        return 1
    print(f"CALIBRACIÓN OK: {len(MUTACIONES)}/{len(MUTACIONES)} rojas por su "
          f"causa, {len(_controles_verdes())} control(es) simetrico(s) verde(s) "
          f"y el control nulo verde")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
