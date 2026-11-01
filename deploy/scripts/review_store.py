#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_store.py — EL DESPLIEGUE decide y prepara el almacen de revision.

C1 (USABLE-V1) · H-04 + H-18. Contrato del operador:

  * DEPLOY ES LA AUTORIDAD sobre `review.sqlite3` (decisiones humanas). El
    runtime (visor y motor) lo CONSUME y lo VERIFICA; no lo crea.
  * FRESH (`--modo fresh`, ya validado por `detect_state.decision=PROCEED`):
    se crea el almacen canonico (schema, permisos, propietario) y se VERIFICA
    POR EFECTO: existe, abre, tiene `human_decisions`, es escribible por el
    usuario del servicio. Un fresh sobre un almacen con DECISIONES BLOQUEA
    (con decisiones lo que procede es `upgrade`).
  * UPGRADE: exige un almacen valido ya existente y lo PRESERVA (vacio != ausente:
    schema correcto sin filas es VERDE). UPGRADE SIN ALMACEN -> STOP.
  * Excepcion explicita `--autorizar-creacion-review-db`: solo si el almacen
    esta realmente AUSENTE; queda ANOTADA en la salida (y por tanto en el log del
    despliegue). NO es un --force: nunca sustituye ni sobrescribe una base
    corrupta, un directorio, un schema invalido, permisos erroneos ni un legacy
    ambiguo (si una candidata legacy tiene decisiones y la ruta declarada esta
    ausente -> STOP aunque este autorizada).

No migra nada: una BD legacy con decisiones se MIGRA POR OTRA VIA (decision del
operador), no aqui. Nunca borra ni mueve ficheros.

Uso:
    review_store.py preparar --modo fresh|upgrade --db <ruta> \\
        [--usuario U --grupo G] [--candidata RUTA ...] \\
        [--autorizar-creacion-review-db] [--solo-lectura]

Salida: lineas `DECISION:` / `ANOTACION:` / `STOP:` legibles por una persona.
Codigos: 0 = preparado/preservado (o, con --solo-lectura, se podria seguir);
3 = STOP / BLOQUEO.
"""
from __future__ import annotations

import argparse
import grp
import importlib.util
import os
import pwd
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cargar(nombre: str, ruta: Path):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(str(ruta))
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _review_paths(raiz: Path = REPO_ROOT):
    # MISMO nombre que usa preflight_ensayo_rc: una sola instancia.
    return _cargar("_s9k_review_paths",
                   raiz / "data-engine" / "app" / "knowledge_v3" / "review_paths.py")


def _store_del_visor(raiz: Path = REPO_ROOT):
    """El almacen canonico del visor (solo stdlib), cargado por ruta."""
    return _cargar("_s9k_v3_review_store",
                   raiz / "viewer" / "app" / "services" / "v3_review_store.py")


@dataclass
class Resultado:
    rc: int = 0
    accion: str = ""          # CREADO | PRESERVADO | STOP | BLOQUEO | PLAN_*
    lineas: list = field(default_factory=list)

    def decir(self, prefijo: str, texto: str) -> None:
        self.lineas.append(f"{prefijo}: {texto}")

    def parar(self, texto: str, accion: str = "STOP") -> "Resultado":
        self.rc = 3
        self.accion = accion
        self.decir("STOP" if accion == "STOP" else "BLOQUEO", texto)
        return self


def _como(usuario: Optional[str], grupo: Optional[str]):
    """(uid, gids) del usuario del servicio, o None si no se declara."""
    if not usuario:
        return None
    if usuario.isdigit():
        uid = int(usuario)
    else:
        uid = pwd.getpwnam(usuario).pw_uid
    gids = set()
    if grupo:
        gids.add(int(grupo) if grupo.isdigit() else grp.getgrnam(grupo).gr_gid)
    try:
        gids.add(pwd.getpwuid(uid).pw_gid)
        gids.update(g.gr_gid for g in grp.getgrall() if pwd.getpwuid(uid).pw_name in g.gr_mem)
    except KeyError:
        pass
    return uid, frozenset(gids)


def _candidata_con_decisiones(rp, candidatas) -> Optional[str]:
    """Texto del problema si alguna candidata legacy impide crear; si no, None.

    * existe, valida y con decisiones  -> hay decisiones humanas fuera de la ruta
      declarada: crear una BD vacia las dejaria huerfanas;
    * existe y NO se puede interpretar -> legacy AMBIGUO: no se decide a ciegas;
    * ausente, o valida y vacia        -> no impide nada.
    """
    for crudo in candidatas:
        if not crudo:
            continue
        ruta = Path(crudo)
        ins = rp.inspect_review_db(ruta)
        if ins.causa == rp.CAUSA_NO_EXISTE:
            continue
        if ins.valido and ins.decisiones == 0:
            continue
        if ins.valido:
            return ("hay una candidata legacy con %d decision(es) humana(s) "
                    "(%s) y la ruta declarada esta ausente: crear un almacen "
                    "vacio las dejaria huerfanas. Migrar es una decision del "
                    "operador, no de este guion" % (ins.decisiones, ruta))
        return ("la candidata legacy %s existe pero no se puede interpretar "
                "(%s): legacy ambiguo" % (ruta, ins.causa))
    return None


def _crear(rp, db: Path, usuario, grupo, res: Resultado) -> bool:
    """Crea directorio y almacen con el schema del PRODUCTO. Verifica por efecto."""
    try:
        db.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    except OSError as exc:
        res.parar("no se pudo crear el directorio del almacen (%s)" % exc.strerror)
        return False
    uid = gid = -1
    if usuario:
        try:
            uid = int(usuario) if usuario.isdigit() else pwd.getpwnam(usuario).pw_uid
            if grupo:
                gid = int(grupo) if grupo.isdigit() else grp.getgrnam(grupo).gr_gid
        except KeyError as exc:
            res.parar("usuario/grupo del servicio inexistente: %s" % exc)
            return False
    # El directorio TAMBIEN pasa al usuario del servicio: SQLite necesita crear
    # los ficheros -wal/-shm junto a la base.
    try:
        if uid != -1 or gid != -1:
            os.chown(db.parent, uid, gid)
    except OSError as exc:
        res.parar("no se pudo dar el directorio al usuario del servicio (%s)"
                  % exc.strerror)
        return False
    previo = os.umask(0o007)
    try:
        almacen = _store_del_visor().SQLiteReviewStore(db, crear=True)
        del almacen
    except Exception as exc:  # noqa: BLE001 - se informa, no se traga
        res.parar("no se pudo crear el almacen: %s" % type(exc).__name__)
        return False
    finally:
        os.umask(previo)
    try:
        os.chmod(db, 0o660)
        if uid != -1 or gid != -1:
            os.chown(db, uid, gid)
            for sufijo in ("-wal", "-shm"):
                extra = Path(str(db) + sufijo)
                if extra.exists():
                    os.chown(extra, uid, gid)
    except OSError as exc:
        res.parar("no se pudo fijar propietario/permisos del almacen (%s)"
                  % exc.strerror)
        return False
    return True


def _verificar(rp, db: Path, usuario, grupo, res: Resultado) -> bool:
    """VERIFICACION POR EFECTO: existe, abre, tiene la tabla, escribible por el servicio."""
    como = _como(usuario, grupo)
    ins = rp.inspect_review_db(db, escritura=True, como=como)
    if not ins.valido:
        res.parar("el almacen NO verifica tras prepararlo: %s (%s)"
                  % (ins.detalle, ins.causa))
        return False
    res.decir("VERIFICADO", "almacen existe, abre, tiene human_decisions y es "
              "escribible por %s (%d decision(es))"
              % (usuario or "el proceso actual", ins.decisiones))
    return True


def preparar(modo: str, db_crudo: Optional[str], *, usuario: Optional[str] = None,
             grupo: Optional[str] = None, candidatas=(), autorizar: bool = False,
             solo_lectura: bool = False, raiz: Path = REPO_ROOT) -> Resultado:
    res = Resultado()
    rp = _review_paths(raiz)
    if modo not in ("fresh", "upgrade"):
        return res.parar("modo invalido: %r" % modo)
    # 1. La DECLARACION: vacia / espacios / relativa / directorio -> causa real.
    try:
        db = rp.validar_declaracion(db_crudo)
    except rp.ReviewDbConfigError as exc:
        return res.parar("%s (%s)" % (exc, exc.causa))
    ins = rp.inspect_review_db(db)
    res.decir("ESTADO", "modo=%s almacen=%s decisiones=%s"
              % (modo, ins.causa or "VALIDO", ins.decisiones if ins.valido else "-"))

    # 2. Existe y es valido.
    if ins.valido:
        if modo == "fresh" and ins.decisiones > 0:
            return res.parar(
                "--mode fresh sobre un almacen con %d decision(es) humana(s): "
                "fresh es solo para maquina limpia; con estado existente use "
                "--mode upgrade" % ins.decisiones, accion="BLOQUEO")
        if autorizar:
            res.decir("ANOTACION", "--autorizar-creacion-review-db IGNORADA: el "
                      "almacen ya existe (la autorizacion solo vale para AUSENCIA "
                      "real; no es un --force)")
        res.accion = "PRESERVADO"
        res.decir("DECISION", "almacen existente y valido: se PRESERVA (no se "
                  "crea, no se toca)")
        if solo_lectura:
            return res
        # Se PRESERVA sin tocar propietario ni modo (pertenece a la instalacion
        # existente): aqui solo se comprueba que ES un almacen valido. La
        # escritura del usuario del servicio se verifica DESPUES de
        # `preparar_estado_del_worker` (subcomando `verificar`, paso 13).
        return res

    # 3. Cualquier causa distinta de AUSENCIA: nunca se sustituye ni se repara.
    if ins.causa != rp.CAUSA_NO_EXISTE:
        return res.parar(
            "%s [%s]. NO se sobrescribe ni se repara (autorizacion o no): "
            "restaure una copia o corrija la causa" % (ins.detalle, ins.causa))

    # 4. AUSENTE.
    impide = _candidata_con_decisiones(rp, candidatas)
    if impide:
        return res.parar(impide)
    if modo == "upgrade":
        if not autorizar:
            return res.parar(
                "UPGRADE sin almacen de revision en la ruta declarada. Un "
                "upgrade conserva decisiones humanas y aqui no hay ninguna que "
                "conservar: ¿cambio de ruta o estado perdido? Si es una "
                "instalacion que NUNCA abrio la revision, repita con "
                "--autorizar-creacion-review-db")
        res.decir("ANOTACION", "--autorizar-creacion-review-db: el almacen de "
                  "revision estaba AUSENTE en un upgrade y se crea por "
                  "autorizacion explicita del operador (sin candidata legacy con "
                  "decisiones)")
    if solo_lectura:
        res.accion = "PLAN_CREAR"
        res.decir("DECISION", "se CREARIA el almacen (modo %s)" % modo)
        return res
    if not _crear(rp, db, usuario, grupo, res):
        return res
    res.accion = "CREADO"
    res.decir("DECISION", "almacen CREADO por el despliegue (modo %s)" % modo)
    _verificar(rp, db, usuario, grupo, res)
    return res


def verificar(db_crudo: Optional[str], *, usuario: Optional[str] = None,
              grupo: Optional[str] = None, raiz: Path = REPO_ROOT) -> Resultado:
    """Solo mira: el almacen declarado existe, abre, tiene la tabla y lo escribe el servicio."""
    res = Resultado()
    rp = _review_paths(raiz)
    try:
        db = rp.validar_declaracion(db_crudo)
    except rp.ReviewDbConfigError as exc:
        return res.parar("%s (%s)" % (exc, exc.causa))
    _verificar(rp, db, usuario, grupo, res)
    return res


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--modo", required=True, choices=["fresh", "upgrade"])
    p.add_argument("--db", default=None,
                   help="valor DECLARADO de S9K_V3_REVIEW_DATABASE_PATH")
    p.add_argument("--usuario", default=None, help="usuario del servicio (worker)")
    p.add_argument("--grupo", default=None)
    p.add_argument("--candidata", action="append", default=[],
                   help="ruta de un posible review.sqlite3 legacy (repetible)")
    p.add_argument("--autorizar-creacion-review-db", action="store_true",
                   dest="autorizar")
    p.add_argument("--solo-lectura", action="store_true")
    v = sub.add_parser("verificar")
    v.add_argument("--db", default=None)
    v.add_argument("--usuario", default=None)
    v.add_argument("--grupo", default=None)
    args = ap.parse_args(argv)
    if args.orden == "verificar":
        res = verificar(args.db, usuario=args.usuario, grupo=args.grupo)
        for linea in res.lineas:
            print(linea, file=sys.stderr if res.rc else sys.stdout)
        return res.rc
    res = preparar(args.modo, args.db, usuario=args.usuario, grupo=args.grupo,
                   candidatas=args.candidata, autorizar=args.autorizar,
                   solo_lectura=args.solo_lectura)
    for linea in res.lineas:
        print(linea, file=sys.stderr if res.rc else sys.stdout)
    return res.rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
