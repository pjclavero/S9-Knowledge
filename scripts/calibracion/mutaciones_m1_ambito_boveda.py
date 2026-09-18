#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración del Carril B · M1 — controles negativos con su MENSAJE.

QUÉ ES ESTO Y POR QUÉ EXISTE
----------------------------
Una afirmación no cuenta hasta que hay una prueba capaz de ponerse ROJA **por la
causa correcta**. Este arnés revierte, una a una, cada garantía de M1 DENTRO DEL
PRODUCTO, corre la prueba que debería protegerla y exige:

  1. que se ponga roja, y
  2. que se ponga roja POR SU CAUSA — se comprueba el MENSAJE, no el color.

LAS MUTACIONES OBLIGATORIAS DEL ENCARGO, Y DÓNDE ESTÁ CADA UNA
--------------------------------------------------------------
  1. **recursión sin clasificación**  -> nº 1 y nº 2. La nº 1 es la importante:
     reproduce EXACTAMENTE el error que el invariante prohíbe —recorrer en
     profundidad asignando a todo el ámbito único de la raíz— y exige que la
     suite lo vea. Si pasara, «hacerlo recursivo» sería una regresión invisible.
  2. **ruta desconocida**             -> nº 3 y nº 4 (no ingiere, Y con
     diagnóstico: se comprueban las dos mitades por separado, porque una ruta
     rechazada con el motivo equivocado se lee igual que una bien rechazada).
  3. **montaje ausente vs vacío**     -> nº 5 y nº 6. La nº 6 va EN SENTIDO
     CONTRARIO: comprueba que «arreglar» el montaje ausente a lo bruto —tratando
     también el vacío legítimo como no utilizable— también pone rojo. Sin ella,
     la forma fácil de aprobar la nº 5 sería declarar todo inutilizable.
  4. **partida que no llega al alta** -> nº 7 y nº 8 (payload y motor).

Y una más, que no está en la lista pero sí en el encargo:

  9. **BORRAR LA PANTALLA**. En esta sesión un carril añadió una cabecera y
     borrarla entera dejó la suite igual de verde. Aquí se borra la tabla de
     ámbito del panel y se exige que la suite se entere: si una garantía es
     visible, el testigo tiene que PEDIR LA PANTALLA.

USO
---
    python3 scripts/calibracion/mutaciones_m1_ambito_boveda.py

Requiere árbol limpio en lo TRACKED: las mutaciones se revierten con
`git checkout --`, que se lleva por delante cualquier cambio sin commitear del
fichero mutado.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CATALOGO = "viewer/app/sources_catalog.py"
SCOPE = "viewer/app/vault_scope.py"
MONTAJE = "viewer/app/vault_mount.py"
ROUTER = "viewer/app/routers/chassis_operations.py"
HANDLER = "data-engine/app/jobs/handlers/ingest_v3.py"
PLANTILLA = "viewer/app/templates/chassis/operations.html"

SUITE = "viewer/tests/test_vault_descubrimiento_ambito.py"
SUITE_ALTA = "viewer/tests/test_panel_operations_alta_fuente.py"


class Mutacion:
    """Una garantía revertida, y la prueba que tiene que verlo."""

    def __init__(self, nombre, fichero, viejo, nuevo, prueba, esperado):
        self.nombre = nombre
        self.fichero = fichero
        self.viejo = viejo
        self.nuevo = nuevo
        self.prueba = prueba
        #: Fragmento que TIENE que aparecer en el fallo. Es lo que distingue
        #: «rojo por su causa» de «rojo por cualquier cosa».
        self.esperado = esperado


MUTACIONES = [
    # =================================================================
    # 1 y 2. RECURSIÓN SIN CLASIFICACIÓN — el invariante duro
    # =================================================================
    Mutacion(
        nombre="EL DEFECTO PROHIBIDO: recorrer en profundidad dando a TODO el "
               "ambito unico de la raiz",
        fichero=CATALOGO,
        # Se sustituye la clasificación real por un ámbito fijo, que es
        # literalmente lo que haría un `rglob` a secas: `reservado/`,
        # `secretos/` y `compartido/` entrarían todos iguales y sin partida.
        viejo="""            try:
                ambito = clasificar(relativa)
            except NoIngerible as exc:
                rechazos.append(exc.para_pantalla())
                continue""",
        nuevo="""            ambito = Ambito(carpeta_juego=relativa.split("/")[0],
                            partida_id=None, visibility="player",
                            regla="ambito-unico-de-la-raiz")""",
        prueba=f"{SUITE}::test_la_recursion_ve_los_niveles_profundos_Y_cada_uno_con_SU_ambito",
        esperado="es el sintoma del ambito uniforme de la raiz",
    ),
    Mutacion(
        nombre="degradar `ambito` a campo OPCIONAL (se puede construir una "
               "fuente sin clasificar)",
        fichero=CATALOGO,
        viejo="    ambito: Ambito\n    perfil: Path",
        nuevo="    ambito: Ambito = AMBITO_PLANO\n    perfil: Path = Path(\".\")",
        prueba=f"{SUITE}::test_no_existe_forma_de_construir_una_fuente_sin_ambito",
        esperado="se puede construir una fuente sin clasificar",
    ),

    # =================================================================
    # 3 y 4. RUTA DESCONOCIDA / INCOHERENTE — falla cerrado, y lo dice
    # =================================================================
    Mutacion(
        nombre="ruta desconocida ADIVINADA en vez de rechazada",
        fichero=SCOPE,
        viejo="""    if seccion != _RAIZ_PARTIDAS:
        raise _no(MOTIVO_DESCONOCIDA, partes,""",
        nuevo="""    if seccion != _RAIZ_PARTIDAS:
        return Ambito(carpeta_juego=juego, partida_id=None,
                      visibility="player", regla="adivinada")
    if False:
        raise _no(MOTIVO_DESCONOCIDA, partes,""",
        prueba=f"{SUITE}::test_no_se_devuelve_nunca_un_ambito_por_defecto",
        esperado="DID NOT RAISE",
    ),
    Mutacion(
        nombre="colapsar INCOHERENTE en DESCONOCIDA (rechaza, pero con el "
               "diagnostico equivocado)",
        fichero=SCOPE,
        # Rechaza igual: el fichero NO entra. Lo único que cambia es el motivo.
        # Si la suite no lo viera, «no ingiere» taparía que el operador no puede
        # saber si colocó mal el fichero o si lo nombró mal.
        viejo="""            raise _no(MOTIVO_INCOHERENTE, partes,
                      f"el buzon `{buzon}` no corresponde a la partida """,
        nuevo="""            raise _no(MOTIVO_DESCONOCIDA, partes,
                      f"el buzon `{buzon}` no corresponde a la partida """,
        prueba=f"{SUITE}::test_aportacion_de_otra_partida_es_INCOHERENTE_no_desconocida",
        esperado="no puede confundirse con una ruta desconocida",
    ),

    # =================================================================
    # 5 y 6. MONTAJE AUSENTE vs MONTAJE VACÍO
    # =================================================================
    Mutacion(
        nombre="EL CASO TRAICIONERO: no verificar el montaje (un mountpoint sin "
               "montaje parece un directorio vacio)",
        fichero=MONTAJE,
        viejo="""        if not montado:
            return Montaje(
                EstadoMontaje.MONTAJE_AUSENTE, p,""",
        nuevo="""        if False:
            return Montaje(
                EstadoMontaje.MONTAJE_AUSENTE, p,""",
        prueba=f"{SUITE}::test_montaje_ausente_y_montaje_vacio_son_ESTADOS_DISTINTOS",
        esperado="no se declaro MONTAJE_AUSENTE",
    ),
    Mutacion(
        nombre="EN SENTIDO CONTRARIO: declarar inutilizable tambien el vacio "
               "LEGITIMO (arreglo a lo bruto)",
        fichero=MONTAJE,
        viejo="""_NO_ENUMERABLES = frozenset({
    EstadoMontaje.MONTAJE_AUSENTE,""",
        nuevo="""_NO_ENUMERABLES = frozenset({
    EstadoMontaje.MONTAJE_VACIO,
    EstadoMontaje.MONTAJE_AUSENTE,""",
        prueba=f"{SUITE}::test_una_boveda_realmente_vacia_da_lista_vacia_sin_levantar",
        esperado="CatalogoNoDisponible: MOUNT_AVAILABLE_EMPTY",
    ),

    # =================================================================
    # 7 y 8. LA PARTIDA NO LLEGA
    # =================================================================
    Mutacion(
        nombre="la partida NO llega al alta (payload sin dimension de partida)",
        fichero=ROUTER,
        viejo='                "partida_id": ambito.partida_id,',
        nuevo='                "partida_id": None,',
        prueba=f"{SUITE_ALTA}::test_la_partida_viaja_EXPLICITA_hasta_el_trabajo",
        esperado="la partida NO llegó al alta",
    ),
    Mutacion(
        nombre="la partida llega al alta pero NO al motor (se degrada a capa "
               "juego EN SILENCIO)",
        fichero=HANDLER,
        viejo="            partida_id=partida_id,\n",
        nuevo="",
        prueba=f"{SUITE_ALTA}::test_la_partida_llega_hasta_EL_MOTOR_y_alli_falla_cerrado",
        esperado="el motor no vio la partida, o la degradó a capa juego",
    ),

    # =================================================================
    # 10. LA TERCERA SALIDA MUDA (la que se le escapo a la primera entrega)
    # -----------------------------------------------------------------
    # `if nombre in _NO_SON_FUENTES: continue` descartaba EN SILENCIO, a
    # cualquier profundidad: un `README.md` con contenido real dentro de
    # `compartido/lore/` salia ni fuente ni rechazo. Es el defecto de este
    # corte en forma residual, y el docstring afirmaba que no existia.
    #
    # Lo encontro un revisor independiente, no esta suite: el testigo
    # construia el universo esperado con la MISMA constante del sujeto que
    # causaba el descarte, asi que no podia verlo. Los dos —producto y
    # testigo— estan corregidos; esta mutacion es lo que lo mantiene asi.
    # =================================================================
    Mutacion(
        nombre="devolver la TERCERA SALIDA MUDA: auxiliar descartado en "
               "silencio a cualquier profundidad",
        fichero=CATALOGO,
        viejo='''                rechazos.append({
                    "motivo": MOTIVO_AUXILIAR,''',
        nuevo='''                continue
                rechazos.append({
                    "motivo": MOTIVO_AUXILIAR,''',
        prueba=f"{SUITE}::test_un_auxiliar_ANIDADO_se_declara_en_vez_de_desaparecer",
        esperado="se fue en silencio",
    ),

    # =================================================================
    # 11. CRUZAR LA FRONTERA: convertir ORIGEN en REVELACION
    # -----------------------------------------------------------------
    # La linea que el operador ha marcado y este carril no cruza:
    #
    #     ruta: sesiones/sesion-05/...  NO IMPLICA  known_from_session = 5
    #
    # Aqui se cruza a proposito —derivando el entero de la carpeta, que es
    # justo lo que alguien haria «por comodidad»— y se exige que la guarda
    # por AST lo vea. Sin esta mutacion, esa guarda seria prosa.
    # =================================================================
    Mutacion(
        nombre="CRUZAR LA FRONTERA: derivar known_from_session de la carpeta "
               "sesion-NN",
        fichero=SCOPE,
        viejo="        origen = sesion\n",
        nuevo=("        origen = sesion\n"
               "        known_from_session = int(sesion.split('-')[1])\n"),
        prueba=f"{SUITE}::test_el_modulo_de_ambito_no_nombra_la_revelacion_en_su_codigo",
        esperado="la carpeta no concede conocimiento",
    ),

    # =================================================================
    # 9. BORRAR LA PANTALLA
    # =================================================================
    Mutacion(
        nombre="BORRAR LA PANTALLA: quitar la tabla de ambito del panel",
        fichero=PLANTILLA,
        viejo='      <table data-role="ambito-de-fuentes">',
        nuevo='      <table data-role="otra-cosa-cualquiera">',
        prueba=f"{SUITE_ALTA}::test_la_pantalla_ensena_el_ambito_de_cada_fuente",
        esperado="no se pinta el ámbito de las fuentes",
    ),
]


def _git_limpio() -> bool:
    """¿Hay cambios TRACKED sin commitear? Esos son los que importan.

    La mutación se revierte con `git checkout --`, que sólo toca ficheros
    seguidos: un cambio tracked sin commitear se perdería, y por eso aborta. Un
    fichero SIN SEGUIR no corre ese riesgo, así que se ignora — pero se AVISA:
    un intruso en el árbol es dato, no ruido.
    """
    salida = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO,
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    tracked = [l for l in salida if not l.startswith("??")]
    ajenos = [l for l in salida if l.startswith("??")]
    if ajenos:
        print("AVISO, ficheros sin seguir en el arbol (ignorados, NO son mios):")
        for l in ajenos:
            print("   " + l)
    if tracked:
        print("ARBOL SUCIO (cambios sin commitear), no se calibra:")
        for l in tracked:
            print("   " + l)
        return False
    return True


def _aplicar(m: Mutacion) -> None:
    ruta = REPO / m.fichero
    texto = ruta.read_text(encoding="utf-8")
    apariciones = texto.count(m.viejo)
    if apariciones != 1:
        raise SystemExit(
            f"[{m.nombre}] el fragmento a mutar aparece {apariciones} veces en "
            f"{m.fichero}; una mutacion que no se aplica produce un VERDE "
            f"enganoso, asi que se para aqui."
        )
    ruta.write_text(texto.replace(m.viejo, m.nuevo), encoding="utf-8")


def _revertir(m: Mutacion) -> None:
    """Restaura el fichero Y TIRA EL BYTECODE. Lo segundo no es precaución.

    MEDIDO EN ESTE MISMO ARNÉS, y casi cuesta una entrega falsa: la mutación nº 4
    cambia `MOTIVO_INCOHERENTE` por `MOTIVO_DESCONOCIDA`, que tiene EXACTAMENTE
    la misma longitud. Python invalida el `.pyc` comparando **mtime y tamaño**
    del fuente; si el `git checkout` cae en el mismo segundo que la escritura de
    la mutación, los dos coinciden y el intérprete sigue ejecutando **el bytecode
    del código mutado** — indefinidamente.

    El resultado es un árbol que `git status` declara limpio, un fuente que al
    leerlo es correcto, y un producto que al EJECUTARSE es el mutado. Es
    exactamente «medir sobre un árbol contaminado», pero por debajo del nivel en
    el que se suele mirar: el diff no lo ve porque no hay diff.

    Así que se borra el `.pyc` del fichero revertido. Y no se confía en que
    baste: `main()` vuelve a correr la prueba SIN mutación al final y exige que
    esté verde, que es la comprobación por EFECTO y no por intención.
    """
    subprocess.run(["git", "checkout", "--", m.fichero], cwd=REPO, check=True)
    fuente = REPO / m.fichero
    cache = fuente.parent / "__pycache__"
    if cache.is_dir():
        for pyc in cache.glob(fuente.stem + ".*.pyc"):
            pyc.unlink()


def main() -> int:
    if not _git_limpio():
        return 2

    fallos = []
    for m in MUTACIONES:
        print(f"\n{'=' * 72}\nMUTACION: {m.nombre}\n  fichero: {m.fichero}\n"
              f"  prueba : {m.prueba}")
        _aplicar(m)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", m.prueba],
                cwd=REPO, capture_output=True, text=True,
            )
        finally:
            _revertir(m)

        salida = proc.stdout + proc.stderr
        rojo = proc.returncode != 0
        por_su_causa = m.esperado in salida

        print(f"  PYTEST_RC = {proc.returncode}  -> {'ROJO' if rojo else 'VERDE'}")
        if not rojo:
            fallos.append(f"{m.nombre}: la prueba NO se puso roja (PYTEST_RC=0)")
            continue
        if not por_su_causa:
            fallos.append(
                f"{m.nombre}: roja, pero NO por su causa. Se esperaba "
                f"{m.esperado!r} en el fallo."
            )
            print("  ATRIBUCION: NO -- se esperaba: " + repr(m.esperado))
            continue
        for linea in salida.splitlines():
            if m.esperado in linea:
                print("  MENSAJE   : " + linea.strip()[:200])
                break
        print("  ATRIBUCION: SI")

    print("\n" + "=" * 72)
    if not _git_limpio():
        print("RESULTADO: el arbol NO quedo limpio tras revertir las mutaciones")
        return 2
    print("arbol limpio tras revertir todas las mutaciones")

    # RESTAURACION COMPROBADA POR EFECTO, NO POR INTENCION.
    #
    # `git status` limpio NO demuestra que el producto ejecutado sea el de la
    # rama: un `.pyc` del codigo mutado puede sobrevivir al revert (ver
    # `_revertir`). La unica prueba es volver a correr las suites y verlas
    # verdes DESPUES de deshacerlo todo.
    print("\ncomprobando POR EFECTO que el arbol quedo restaurado...")
    verificacion = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", SUITE, SUITE_ALTA],
        cwd=REPO, capture_output=True, text=True,
    )
    print(f"  PYTEST_RC = {verificacion.returncode}")
    if verificacion.returncode != 0:
        print("RESULTADO: el arbol dice estar limpio pero NO se comporta como "
              "limpio. Alguna mutacion sigue viva (bytecode rancio?).")
        print(verificacion.stdout[-3000:])
        return 2
    print("  las suites vuelven a estar verdes: la restauracion es REAL")
    if fallos:
        print("RESULTADO: CALIBRACION FALLIDA")
        for f in fallos:
            print("  - " + f)
        return 1
    print(f"RESULTADO: {len(MUTACIONES)}/{len(MUTACIONES)} controles negativos "
          "rojos POR SU CAUSA, con el mensaje comprobado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
