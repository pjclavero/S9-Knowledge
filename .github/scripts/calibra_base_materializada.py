#!/usr/bin/env python3
"""Calibracion de la RUTA QUE CI EJECUTA DE VERDAD: la base materializada.

POR QUE HACIA FALTA ESTE ARNES
==============================
`calibra_suite_inventory.py` mide SIEMPRE con `--base-fichero`, o sea con una
base ya escrita. Pero en CI el gate no usa esa bandera —esta prohibida ahi—:
DERIVA el merge-base, saca su arbol con `git archive | tar` a un temporal y
mide alli. Esa ruta no la ejercitaba ningun caso.

Y se pago. Al introducir la integridad del registro, el hijo que mide la base
empezo a morir dentro del temporal —que NO es un repositorio git, asi que no hay
commit de referencia— y ademas le faltaba un modulo que el gate habia empezado a
importar. Resultado: sin inventario de base, y el padre certificando con SIETE
controles sin ejecutar (C, C-bis, D, D2, A2, G y X-T), en verde. Sobre arbol
limpio. La calibracion no lo veia porque probaba el instrumento en una
configuracion en la que el producto no corre.

Es exactamente el fallo que este carril persigue —verde por no mirar— un nivel
mas arriba, asi que la ruta real tiene su arnes.

QUE SE COMPRUEBA
================
  1. Sobre arbol limpio y SIN `--base-fichero`: EXIT=0 y la salida tiene que
     decir `MATERIALIZADA`. Si dijera `SIN TRINQUETE`, el caso es ROJO aunque
     el gate salga 0: un verde sin trinquetes no es un verde.
  2. Con la materializacion ROTA de verdad (un `git` que falla solo en
     `archive`): EXIT=1. Antes era EXIT=0 con un aviso enterrado.
  3. Con `--sin-base` PEDIDO a proposito: EXIT=0 con aviso. Es la unica forma
     legitima de quedarse sin base, y tiene que seguir existiendo.
  4. El instrumento prestado al temporal esta COMPLETO: se comprueba que la
     medida de la base devuelve inventario y no None.

TRES VEREDICTOS, NO DOS
=======================
Un escenario que NO PUEDE MONTARSE en el contexto de la corrida no es una
violacion del gate. Contarlo como `DESVIACION` es un falso rojo, y un falso
rojo repetido acaba ensenando a ignorar la tabla. Por eso hay un tercer
estado, `NO EJERCITABLE`, que se REGISTRA con su razon y no suma desviacion.

El riesgo evidente de un tercer estado es que se convierta en una puerta de
escape: si un escenario pudiera declararse inejercitable a voluntad, cualquier
violacion futura se esconderia detras de la etiqueta. Aqui no puede:

  * la inejercitabilidad se DERIVA de una condicion estructural observable
    --¿existe en la historia de `origin/main` un commit cuyo arbol no publique
    el inventario?--, nunca de una lista de nombres, ni de una variable de
    entorno, ni del nombre de la rama;
  * la etiqueta no se le cree a quien la pone: al anotar la fila se vuelve a
    derivar la condicion desde cero, y si el escenario SI era montable la fila
    pasa a DESVIACION POR ETIQUETA INDEBIDA y suma rojo;
  * los casos 5 y 6 calibran esas dos caras en cada corrida.

Un escenario ejercitable que falla sigue siendo ROJO. Sin excepciones.

NO MUTA NINGUN FICHERO DEL REPOSITORIO. Publica igualmente el SHA-256 de lo que
podria tocar, porque "no lo toco" tambien hay que medirlo.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arnes_comun  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_suite_inventory.py"
VIGILADOS = (
    GATE,
    REPO / ".github" / "scripts" / "registro_xfail.py",
    REPO / ".github" / "scripts" / "normaliza_shell.py",
    REPO / ".github" / "suite-inventario.json",
    REPO / ".github" / "xfail-registro.txt",
)

VERDE, ROJO = "VERDE", "ROJO"
NO_EJERCITABLE = "NO EJERCITABLE"
INVENTARIO_REL = ".github/suite-inventario.json"


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def git_que_falla_en_archive() -> Path:
    """Un `git` real salvo para `archive`, que devuelve 1.

    Inyeccion QUIRURGICA: no se rompe git entero —eso tumbaria tambien la
    derivacion del merge-base y el caso no distinguiria una causa de otra—,
    solo el subcomando que materializa.
    """
    tmp = Path(tempfile.mkdtemp(prefix="git-sin-archive-"))
    shim = tmp / "git"
    real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
    shim.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "archive" ]; then\n'
        '  echo "fallo inyectado por la calibracion" >&2\n'
        "  exit 1\n"
        "fi\n"
        f'exec {real} "$@"\n',
        encoding="utf-8")
    shim.chmod(0o755)
    return tmp


def clon_con_main_en(sha: str) -> Path:
    """Un clon local del repo con `origin/main` apuntando a `sha`.

    Asi se ejercitan LAS DOS vias de `inventario_base()` sin depender de en cual
    caiga el repositorio hoy:

      * `origin/main` en un commit SIN inventario -> via de MATERIALIZACION
      * `origin/main` en un commit CON inventario -> via RAPIDA (`git show`)

    Hace falta porque el arnes se auto-invalidaba al fusionar: solo era correcto
    MIENTRAS la base no publicara `suite-inventario.json`. En cuanto esto entre
    en `main`, la via rapida seria la real, la nota dejaria de decir
    `MATERIALIZADA` y el job saldria ROJO en `main` el primer dia. Falso rojo,
    y ademas la via que quedaria en produccion se quedaba sin arnes.
    """
    tmp = Path(tempfile.mkdtemp(prefix="clon-base-"))
    destino = tmp / "repo"
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(REPO),
                    str(destino)], check=True, capture_output=True, timeout=900)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", sha],
                   cwd=destino, check=True, capture_output=True, timeout=120)
    return destino


def corre_gate_en(raiz: Path, extra: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, ".github/scripts/check_suite_inventory.py", *extra],
        cwd=raiz, capture_output=True, text=True, timeout=3600,
        env=os.environ.copy(),
    )
    return p.returncode, p.stdout + p.stderr


def corre_gate(extra: list[str], entorno: dict | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE), *extra],
        cwd=REPO, capture_output=True, text=True, timeout=3600,
        env=entorno or os.environ.copy(),
    )
    return p.returncode, p.stdout + p.stderr


def precondicion() -> list[str]:
    """Este arnes EXIGE el mismo checkout que el job donde el gate corre.

    Si no hay historia suficiente para derivar el merge-base con `origin/main`,
    los casos saldrian rojos por una razon que no es la que calibran y la tabla
    confundiria a quien la lea. Medido: colocado en un job con el checkout por
    defecto, dio `SIN TRINQUETE: no hay merge-base con origin/main` y dos
    desviaciones que parecian del producto y eran del sitio donde se le puso.
    Mejor una PRECONDICION explicita que una tabla enganosa.
    """
    problemas = []
    sucio = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if sucio:
        problemas.append(
            "PRECONDICION: el arbol tiene cambios sin commitear. Este arnes "
            "monta clones aislados para ejercitar las DOS vias de la base, y un "
            "clon solo ve lo COMMITEADO: mediria codigo distinto del que hay "
            "delante. Commitea antes de calibrar.")
    p = subprocess.run(["git", "rev-parse", "--verify", "origin/main^{commit}"],
                       cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0:
        problemas.append(
            "PRECONDICION: no existe `origin/main` en este checkout, asi que no "
            "hay merge-base que materializar. Este arnes ejercita LA RUTA REAL "
            "de la base y necesita el mismo checkout que el job donde el gate "
            "corre de verdad: `fetch-depth: 0`. Sin eso no mide el producto, "
            "mide el sitio donde se le ha puesto.")
    return problemas


def deriva_base_sin_inventario(raiz: Path = REPO) -> tuple[str | None, str]:
    """CONDICION ESTRUCTURAL de los casos 1 y 2, derivada del GRAFO DE GIT.

    Los dos casos necesitan una base que NO publique `suite-inventario.json`:
    es lo UNICO que obliga al gate a MATERIALIZAR el arbol de la base en vez de
    tomar la via rapida de `git show`. Que esa base exista o no es un hecho
    OBSERVABLE de la historia de `origin/main` --¿hay algun commit cuyo ARBOL
    no contenga el fichero?-- y se responde preguntando por el arbol de cada
    commit, uno a uno.

    NO hay lista de commits, NO hay variable de entorno y NO se mira el nombre
    de la rama: se pregunta por el CONTENIDO del arbol. Si manana alguien
    quisiera declarar inejercitable este caso, tendria que hacer que TODOS los
    commits de `origin/main` publicasen el inventario, que es precisamente la
    situacion en la que el caso de verdad no puede montarse.

    POR QUE HIZO FALTA TOCARLO. La busqueda estaba capada a los 60 commits mas
    recientes, asi que dependia del CALENDARIO y no de la estructura: al entrar
    `integracion/tanda11` en `main`, los 60 ultimos pasaron a publicar todos el
    inventario, la base desaparecio y el caso se conto como DESVIACION. Medido
    sobre la historia completa si hay bases sin inventario (610 commits, la
    primera a 103 de HEAD), asi que el caso NUNCA fue inejercitable: la ventana
    era corta. Por eso el arreglo AMPLIA la busqueda antes de contemplar
    siquiera la etiqueta.
    """
    commits = subprocess.run(
        ["git", "rev-list", "origin/main"], cwd=raiz,
        capture_output=True, text=True, timeout=600).stdout.split()
    if not commits:
        return None, "`origin/main` no tiene historia alcanzable en este checkout"
    consulta = "".join(f"{c}:{INVENTARIO_REL}\n" for c in commits)
    p = subprocess.run(["git", "cat-file", "--batch-check"], cwd=raiz,
                       input=consulta, capture_output=True, text=True,
                       timeout=600)
    for commit, linea in zip(commits, p.stdout.splitlines()):
        if linea.strip().endswith("missing"):
            return commit, (f"el arbol de {commit[:8]} no contiene "
                            f"`{INVENTARIO_REL}`")
    return None, (f"los {len(commits)} commits alcanzables desde `origin/main` "
                  f"publican TODOS `{INVENTARIO_REL}`: no existe base que "
                  f"obligue a materializar")


class Tabla:
    """Acumula filas con TRES veredictos, no dos.

    `NO EJERCITABLE` no es un `OK` disfrazado ni una `DESVIACION` disfrazada:
    es un tercer estado que se REGISTRA con su razon y no suma desviacion. Un
    escenario que no puede MONTARSE en este contexto no es una violacion del
    gate; contarlo como tal es un falso rojo, y un falso rojo repetido acaba
    ensenando a ignorar la tabla.

    Y NO es una puerta de escape, que es el riesgo evidente de tener un tercer
    estado: la etiqueta NO se le cree a quien la pone. Al anotar la fila se
    vuelve a DERIVAR la condicion estructural desde cero, y si resulta que el
    escenario SI era montable, la fila pasa a DESVIACION POR ETIQUETA INDEBIDA
    y suma rojo. O sea que marcar como inejercitable algo que si lo es sale
    MAS caro que dejarlo fallar: no hay incentivo para esconderse detras.
    """

    def __init__(self) -> None:
        self.filas: list[tuple[str, str, str, str]] = []
        self.fallos = 0
        self.inejercitables: list[tuple[str, str]] = []

    def anota(self, titulo: str, esperado: str, detalle: str, ok: bool, *,
              inejercitable: str | None = None, condicion=None) -> None:
        if inejercitable is None:
            self.fallos += 0 if ok else 1
            self.filas.append((titulo, esperado, detalle,
                               "OK" if ok else "**DESVIACION**"))
            return
        if condicion is None:
            raise AssertionError(
                "declarar NO EJERCITABLE exige la CONDICION estructural que lo "
                "demuestra; sin ella la etiqueta seria una opinion")
        base_real, razon = condicion()
        if base_real is not None:
            self.fallos += 1
            self.filas.append((
                titulo, esperado,
                f"se declaro NO EJERCITABLE y SI es ejercitable ({razon})",
                "**DESVIACION (ETIQUETA INDEBIDA)**"))
            return
        self.inejercitables.append((titulo, razon))
        self.filas.append((titulo, esperado, f"no ejercitable: {razon}",
                           NO_EJERCITABLE))


def clon_superficial(profundidad: int = 20) -> Path:
    """Un clon SUPERFICIAL: historia real, pero corta de verdad.

    Sirve para ejercitar la cara BUENA de la etiqueta sin mentir en ninguna
    parte. En un clon de profundidad 20 los unicos commits que EXISTEN son los
    20 ultimos, y todos publican el inventario: la condicion estructural sale
    genuinamente insatisfecha y el escenario es de verdad inejercitable ahi.
    Es el mismo contexto que tendria un `checkout` sin `fetch-depth: 0`.

    `file://` no es decorativo: con una ruta de disco git IGNORA `--depth` y
    haria un clon completo, con lo que el caso mediria lo contrario de lo que
    dice.

    Y el `update-ref` tampoco: un clon superficial solo trae la rama de HEAD,
    asi que SIN el `origin/main` no existiria y la condicion saldria
    insatisfecha por «no hay historia alcanzable». Saldria el veredicto
    correcto por el diagnostico equivocado --el caso pasaria aunque la regla
    que calibra estuviera rota-- y eso no es evidencia de nada. Apuntando
    `origin/main` al HEAD del propio clon, la condicion se evalua sobre
    `profundidad` commits REALES que publican todos el inventario, que es
    exactamente la situacion que el caso quiere ejercitar.
    """
    tmp = Path(tempfile.mkdtemp(prefix="clon-superficial-"))
    destino = tmp / "repo"
    subprocess.run(["git", "clone", "--quiet", "--depth", str(profundidad),
                    f"file://{REPO}", str(destino)],
                   check=True, capture_output=True, timeout=900)
    cabeza = subprocess.run(["git", "rev-parse", "HEAD"], cwd=destino,
                            check=True, capture_output=True, text=True,
                            timeout=120).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", cabeza],
                   cwd=destino, check=True, capture_output=True, timeout=120)
    return destino


def main() -> int:
    fallos_previos = precondicion()
    for e in fallos_previos:
        print(f"::error::{e}")
    if fallos_previos:
        return 1

    hashes = {f: sha(f) for f in VIGILADOS if f.exists()}
    print("SHA-256 ANTES (este arnes NO deberia tocar ninguno):")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    tabla = Tabla()
    temporales = []

    # --- 1. via de MATERIALIZACION (base SIN inventario publicado) --------
    print("\n########## 1. via de MATERIALIZACION (base sin inventario)")
    # La base se DERIVA de la estructura de la historia, no de una lista de
    # commits ni de una ventana reciente. Ver `deriva_base_sin_inventario`.
    #
    # OJO con el nombre: `sha` es la funcion de hash de este modulo. Usarla como
    # variable de bucle la convertia en local de `main()` y reventaba la primera
    # linea con `UnboundLocalError`. Lo caza la EJECUCION, no el AST: el nombre
    # existe a nivel de modulo, asi que el control de nombres definidos no tiene
    # nada que objetar. Otro recordatorio de que los arneses hay que correrlos.
    base_sin, razon_base = deriva_base_sin_inventario()
    print(f"  condicion estructural: {razon_base}")
    if base_sin is None:
        tabla.anota("1 via de MATERIALIZACION (base sin inventario)",
                    "VERDE y nota MATERIALIZADA", "", False,
                    inejercitable=razon_base,
                    condicion=deriva_base_sin_inventario)
    else:
        clon = clon_con_main_en(base_sin)
        temporales.append(clon.parent)
        rc, salida = corre_gate_en(clon, [])
        materializada = "MATERIALIZADA" in salida
        sin_trinquete = "SIN TRINQUETE" in salida
        ok = (rc == 0) and materializada and not sin_trinquete
        print(f"  base sin inventario: {base_sin[:8]}")
        print(f"  EXIT={rc}  MATERIALIZADA={materializada}  SIN TRINQUETE={sin_trinquete}")
        tabla.anota("1 via de MATERIALIZACION (base sin inventario)",
                    "VERDE y nota MATERIALIZADA",
                    f"EXIT={rc}, MATERIALIZADA={materializada}", ok)

    # --- 1b. via RAPIDA (base CON inventario publicado) -------------------
    # ESTA es la via que quedara en produccion en cuanto el carril se fusione,
    # y hasta ahora no la ejercitaba nadie.
    print("\n########## 1b. via RAPIDA (base con inventario publicado)")
    sha_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip()
    clon2 = clon_con_main_en(sha_head)
    temporales.append(clon2.parent)
    rc1b, salida1b = corre_gate_en(clon2, [])
    rapida = f"base {sha_head[:8]}" in salida1b
    sin_trinquete1b = "SIN TRINQUETE" in salida1b
    ok1b = (rc1b == 0) and rapida and not sin_trinquete1b
    print(f"  EXIT={rc1b}  via rapida={rapida}  SIN TRINQUETE={sin_trinquete1b}")
    tabla.anota("1b via RAPIDA (base con inventario) = la de post-fusion",
                "VERDE con trinquete aplicado",
                f"EXIT={rc1b}, via rapida={rapida}", ok1b)

    # --- 2. materializacion ROTA -> ROJO, no verde con aviso --------------
    #
    # EN UN CLON con la base SIN inventario, no en el repo ambiente. Medido en
    # un clon post-fusion: sobre el repo ambiente, cuando la base YA publica
    # inventario se toma la via rapida, `git archive` no llega a usarse y
    # `INSTRUMENTO ROTO` no aparece nunca. O sea que este caso solo era correcto
    # mientras la base no publicara inventario: exactamente la trampa que ya se
    # arreglo para los casos 1 y 1b, dejada a medias aqui. Al integrar los
    # carriles habria puesto «Calibracion de gates» ROJO en `main`.
    print("\n########## 2. materializacion ROTA (`git archive` falla)")
    tmp = git_que_falla_en_archive()
    temporales.append(tmp)
    entorno = os.environ.copy()
    entorno["PATH"] = f"{tmp}{os.pathsep}{entorno.get('PATH', '')}"
    if base_sin is None:
        tabla.anota("2 materializacion rota (en clon con base sin inventario)",
                    "ROJO (no verde con aviso)", "", False,
                    inejercitable=razon_base,
                    condicion=deriva_base_sin_inventario)
    else:
        clon3 = clon_con_main_en(base_sin)
        temporales.append(clon3.parent)
        p2 = subprocess.run(
            [sys.executable, ".github/scripts/check_suite_inventory.py"],
            cwd=clon3, capture_output=True, text=True, timeout=3600, env=entorno)
        rc2 = p2.returncode
        instrumento = "INSTRUMENTO ROTO" in (p2.stdout + p2.stderr)
        ok2 = (rc2 == 1) and instrumento
        print(f"  EXIT={rc2}  dice INSTRUMENTO ROTO={instrumento}")
        tabla.anota("2 materializacion rota (en clon con base sin inventario)",
                    "ROJO (no verde con aviso)",
                    f"EXIT={rc2}, INSTRUMENTO ROTO={instrumento}", ok2)

    # --- 3. `--sin-base` PEDIDO -> verde con aviso ------------------------
    #
    # "Pedido a proposito" ya no puede ser desde la LINEA DE COMANDOS: esa
    # invocacion no certifica nada y por eso es ROJO desde que el desarme se
    # cerro por propiedad. La forma legitima es la que usan los arneses: llamar
    # a `main()` dentro del propio proceso. Se comprueban las DOS caras.
    print("\n########## 3. `--sin-base` pedido a proposito (en proceso)")
    rc3, salida3 = arnes_comun.ejecuta_gate(
        "check_suite_inventory", ["--sin-base"], ablacion="", timeout=2400)
    aviso = "SIN TRINQUETE" in salida3
    ok3 = (rc3 == 0) and aviso
    print(f"  EXIT={rc3}  avisa={aviso}")
    tabla.anota("3 `--sin-base` en proceso (arnes)", "VERDE con aviso",
                f"EXIT={rc3}, avisa={aviso}", ok3)

    print("\n########## 3b. `--sin-base` desde la LINEA DE COMANDOS")
    rc3b, _ = corre_gate(["--sin-base"])
    ok3b = rc3b == 1
    print(f"  EXIT={rc3b}")
    tabla.anota("3b `--sin-base` desde linea de comandos",
                "ROJO (no certifica nada)", f"EXIT={rc3b}", ok3b)

    # --- 4. el instrumento prestado esta COMPLETO -------------------------
    print("\n########## 4. la medida de la base devuelve inventario")
    sys.path.insert(0, str(REPO / ".github" / "scripts"))
    import check_suite_inventory as G  # noqa: E402
    datos_base, nota = G.inventario_base()
    ok4 = datos_base is not None and bool(datos_base.get("modulos"))
    print(f"  nota: {nota}")
    print(f"  modulos en la base: "
          f"{len(datos_base['modulos']) if datos_base else 'NINGUNO'}")
    tabla.anota("4 instrumento prestado completo", "inventario no vacio",
                nota[:60], ok4)

    # --- 5. la etiqueta NO EJERCITABLE, por su cara MALA ------------------
    #
    # El control NEGATIVO, y el que decide si el tercer estado vale algo. Se
    # declara inejercitable un escenario CUYA CONDICION SI SE CUMPLE. Tiene que
    # salir DESVIACION POR ETIQUETA INDEBIDA: si saliera `NO EJERCITABLE`, la
    # etiqueta seria una puerta de escape y cualquier violacion futura podria
    # esconderse detras de ella.
    print("\n########## 5. NO EJERCITABLE indebido -> DESVIACION (puerta cerrada)")
    if base_sin is None:
        tabla.anota("5 etiqueta indebida (control negativo)",
                    "DESVIACION POR ETIQUETA INDEBIDA", "", False,
                    inejercitable=razon_base,
                    condicion=deriva_base_sin_inventario)
    else:
        sonda = Tabla()
        sonda.anota("sonda: escenario ejercitable declarado inejercitable",
                    "ROJO", "", True,
                    inejercitable="excusa inventada por la calibracion",
                    condicion=deriva_base_sin_inventario)
        indebida = "ETIQUETA INDEBIDA" in sonda.filas[0][3]
        ok5 = indebida and sonda.fallos == 1 and not sonda.inejercitables
        print(f"  veredicto de la sonda: {sonda.filas[0][3]}")
        print(f"  suma desviacion={sonda.fallos}  registrada como "
              f"inejercitable={bool(sonda.inejercitables)}")
        tabla.anota("5 etiqueta indebida (control negativo)",
                    "DESVIACION POR ETIQUETA INDEBIDA",
                    f"veredicto={sonda.filas[0][3]}, desviaciones="
                    f"{sonda.fallos}", ok5)

    # --- 6. la etiqueta NO EJERCITABLE, por su cara BUENA ------------------
    #
    # El positivo del 5. En un clon SUPERFICIAL la condicion estructural sale
    # genuinamente insatisfecha --los unicos commits que existen publican todos
    # el inventario-- y ahi la etiqueta SI procede: fila `NO EJERCITABLE`, cero
    # desviaciones y registro con su razon. Nada de esto se declara: se mide
    # sobre una historia real, solo que corta.
    print("\n########## 6. NO EJERCITABLE legitimo -> registrado, no rojo")
    superficial = clon_superficial()
    temporales.append(superficial.parent)
    def condicion_superficial():
        return deriva_base_sin_inventario(superficial)

    base_sup, razon_sup = condicion_superficial()
    sonda6 = Tabla()
    sonda6.anota("sonda: escenario sin base montable en historia corta",
                 "NO EJERCITABLE", "", False,
                 inejercitable=razon_sup, condicion=condicion_superficial)
    # Se exige tambien el DIAGNOSTICO, no solo el veredicto: la razon tiene
    # que ser «todos publican el inventario», nunca «no hay historia». Si no,
    # el caso saldria verde con la regla rota.
    por_la_razon_buena = "publican TODOS" in razon_sup
    ok6 = (base_sup is None and por_la_razon_buena
           and sonda6.filas[0][3] == NO_EJERCITABLE
           and sonda6.fallos == 0 and len(sonda6.inejercitables) == 1)
    print(f"  condicion en el clon superficial: {razon_sup}")
    print(f"  veredicto={sonda6.filas[0][3]}  desviaciones={sonda6.fallos}  "
          f"registrados={len(sonda6.inejercitables)}  "
          f"razon correcta={por_la_razon_buena}")
    tabla.anota("6 inejercitable legitimo (control positivo de la etiqueta)",
                "NO EJERCITABLE, registrado y sin sumar rojo",
                f"veredicto={sonda6.filas[0][3]}, desviaciones={sonda6.fallos}",
                ok6)

    for t in temporales:
        shutil.rmtree(t, ignore_errors=True)

    print("\n===== SHA-256 DESPUES =====")
    for f, esperado in hashes.items():
        real = sha(f)
        marca = "OK" if real == esperado else "**NO COINCIDE**"
        tabla.fallos += 0 if real == esperado else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")

    print("\n\n===== TABLA (ruta de la base que CI ejecuta) =====\n")
    print("| Caso | Esperado | Obtenido | Veredicto |")
    print("|---|---|---|---|")
    for fila in tabla.filas:
        print("| {} | {} | {} | {} |".format(*fila))

    # REGISTRO EXPLICITO. Un escenario que no se ha podido montar no se silencia
    # ni se cuela como OK: se dice cuantos son y POR QUE, para que quien lea la
    # tabla vea lo que NO se ha ejercitado en esta corrida.
    print(f"\n===== NO EJERCITABLES EN ESTE CONTEXTO: "
          f"{len(tabla.inejercitables)} =====")
    if not tabla.inejercitables:
        print("  (ninguno: todos los escenarios se han podido montar y evaluar)")
    for titulo, razon in tabla.inejercitables:
        print(f"  NO EJERCITABLE  {titulo}\n                  razon: {razon}")

    ejercitados = len(tabla.filas) - len(tabla.inejercitables)
    if tabla.fallos:
        print(f"\nCALIBRACION FALLIDA: {tabla.fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {ejercitados}/{ejercitados} casos "
          f"ejercitados ({len(tabla.inejercitables)} no ejercitable(s) "
          f"registrado(s)), y ningun fichero del repositorio modificado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
