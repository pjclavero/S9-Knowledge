#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrar_estado.py — migracion AUTOMATICA del estado al usuario de servicio.

H-06 + H-08 (USABLE-V1, Fase C). Es el cuerpo, en Python y por tanto
comprobable, de los pasos 6-11 de la migracion del contrato (§8):

    6  inspeccionar el state root            (STOP si symlink, tipo raro,
                                              ilegible, journal pendiente,
                                              fichero abierto por un proceso)
    7  mover fuera de la release el estado mutable legacy
                                             (copia + hash + SOLO ENTONCES se
                                              retira el original)
    8  corregir el propietario               (s9knowledge:s9knowledge)
    9  corregir los modos                    (dirs 0700, ficheros 0600)
    10 verificar el resultado con la MISMA funcion canonica que usan el visor y
       el worker al arrancar (``service_state.inspect_state``)

Los pasos 1-5 (parar visor y worker y comprobar que estan parados) y 12-14
(arrancar, salud, funcionalidad minima) son de ``deploy.sh``/``lib.sh``: aqui
se SUPONE que nadie tiene los ficheros abiertos y se COMPRUEBA (paso 6).

GARANTIAS
---------
* NUNCA se borra un original antes de verificar el destino: la copia se hace a
  un temporal 0600 en el directorio destino, se fsync-ea, se compara el
  SHA-256 y se publica con ``link`` (que no pisa un destino existente); el
  original se RENOMBRA a ``<nombre>.migrado-<release>`` (atomico, mismo FS),
  no se borra.
* IDEMPOTENTE: un segundo pase con el destino ya identico solo retira el
  original que quedara; sin nada que hacer no toca nada.
* Si destino y origen EXISTEN y DIFIEREN: STOP [CONFLICTO_DE_ESTADO]; se
  conservan los dos. Nunca se elige en silencio.
* Cualquier fallo de ``chown``/``chmod``/copia: STOP con la ruta y el errno;
  el servicio NO arranca (el llamador no activa la release ni declara exito).
* Como root, NO se abre ninguna base SQLite (abrir una base WAL como root crea
  ``-wal``/``-shm`` de root: el defecto N14). La integridad se comprueba por
  hash de las copias; la lectura real la hace el usuario de servicio.

SALIDA: lineas ``PASO n``/``MOVIDO``/``OK`` y, si se para, ``STOP[CODIGO]``.
CODIGOS: 0 = migrado/verificado; 3 = STOP.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

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


def _service_state(raiz: Path = REPO_ROOT):
    # MISMO nombre de modulo que review_store/preflight: una sola instancia.
    return _cargar("_s9k_service_state",
                   raiz / "data-engine" / "app" / "knowledge_v3" / "service_state.py")


def _ss():
    """La AUTORIDAD (modos, propietario): aqui no se escribe ninguna cifra."""
    return _service_state()


#: Estado mutable que el codigo antiguo dejaba DENTRO de la release
#: (``viewer/output/reviews-v3``) y su clave en ``effective_paths``.
LEGACY_EN_RELEASE = (
    ("viewer/output/reviews-v3/decisions.jsonl", "decisions", "file"),
    ("viewer/output/reviews-v3/audit.jsonl", "audit", "file"),
    ("viewer/output/reviews-v3/glossary-candidates", "glossary", "dir"),
    ("viewer/output/reviews-v3/proposals", "proposals", "dir"),
)


@dataclass
class Resultado:
    rc: int = 0
    lineas: list = field(default_factory=list)

    def decir(self, prefijo: str, texto: str) -> None:
        self.lineas.append("%s: %s" % (prefijo, texto))

    def parar(self, codigo: str, texto: str) -> "Resultado":
        self.rc = 3
        self.lineas.append("STOP[%s]: %s" % (codigo, texto))
        return self


class Parada(Exception):
    """Interrumpe la migracion con un STOP ya formulado."""

    def __init__(self, codigo: str, texto: str):
        self.codigo, self.texto = codigo, texto
        super().__init__("%s: %s" % (codigo, texto))


# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------
def _sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _errno(exc: OSError) -> str:
    return exc.strerror or type(exc).__name__


def _fsync_dir(ruta: str) -> None:
    fd = os.open(ruta, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def procesos_con_abiertos(prefijo: str, ignorar: Iterable[int] = ()) -> list:
    """(pid, comando, ruta) de procesos con un fichero abierto bajo ``prefijo``.

    Lee ``/proc/<pid>/fd`` (necesita ser root para ver procesos ajenos; como
    root del despliegue lo es). Ignora los PID dados y el propio proceso.
    """
    prefijo = os.path.normpath(prefijo)
    propio = {os.getpid(), *ignorar}
    hallados = []
    try:
        pids = [int(d) for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return hallados
    for pid in pids:
        if pid in propio:
            continue
        base = "/proc/%d/fd" % pid
        try:
            fds = os.listdir(base)
        except OSError:
            continue
        for fd in fds:
            try:
                destino = os.readlink("%s/%s" % (base, fd))
            except OSError:
                continue
            if destino == prefijo or destino.startswith(prefijo + "/"):
                try:
                    with open("/proc/%d/comm" % pid, encoding="utf-8") as fh:
                        cmd = fh.read().strip()
                except OSError:
                    cmd = "?"
                hallados.append((pid, cmd, destino))
                break
    return hallados


def _backups_legacy(state_root: str, res: Resultado) -> None:
    """§10 · el BACKUP no vive dentro del estado vivo. ``<state>/backups`` (que creaba
    Ansible, vacio) se retira si esta vacio; con contenido se PARA: moverlo es una
    decision del operador (son copias, quizas root:root, y no se mezclan con el estado)."""
    ruta = os.path.join(state_root, "backups")
    if os.path.islink(ruta):
        raise Parada("SYMLINK", "%s es un enlace simbolico" % ruta)
    if not os.path.isdir(ruta):
        return
    try:
        contenido = os.listdir(ruta)
    except OSError as exc:
        raise Parada("ILEGIBLE", "%s ilegible (%s)" % (ruta, _errno(exc)))
    if contenido:
        raise Parada("BACKUP_EN_STATE", "%s contiene %d elemento(s): los backups viven FUERA del "
                     "state root (raiz de backups separada, root:%s 0750). Muevalos a mano a esa "
                     "raiz y repita; el despliegue no mezcla copias con estado vivo"
                     % (ruta, len(contenido), _ss().SERVICE_GROUP))
    try:
        os.rmdir(ruta)
    except OSError as exc:
        raise Parada("SIN_PERMISOS", "no se pudo retirar el directorio vacio %s (%s)" % (ruta, _errno(exc)))
    res.decir("PASO 6", "directorio vacio %s retirado (el backup vive fuera del state root)" % ruta)


# --------------------------------------------------------------------------
# paso 6: inspeccion
# --------------------------------------------------------------------------
def _precondiciones(raiz: str, crear: bool, uid: int, gid: int, res: Resultado) -> None:
    if os.path.islink(raiz):
        raise Parada("SYMLINK", "el state root %s es un enlace simbolico" % raiz)
    if not os.path.exists(raiz):
        if not crear:
            raise Parada("STATE_ROOT_AUSENTE", "el state root %s no existe" % raiz)
        try:
            os.makedirs(raiz, mode=_ss().DIR_MODE)
            os.chown(raiz, uid, gid)
            os.chmod(raiz, _ss().DIR_MODE)
        except OSError as exc:
            raise Parada("SIN_PERMISOS", "no se pudo crear el state root %s (%s)"
                         % (raiz, _errno(exc)))
        res.decir("PASO 2", "state root creado 0700 (%s)" % raiz)
    if not os.path.isdir(raiz):
        raise Parada("TIPO", "el state root %s no es un directorio" % raiz)
    try:
        vfs = os.statvfs(raiz)
    except OSError as exc:
        raise Parada("SIN_PERMISOS", "no se puede inspeccionar %s (%s)" % (raiz, _errno(exc)))
    if vfs.f_flag & os.ST_RDONLY:
        raise Parada("FS_SOLO_LECTURA", "el sistema de ficheros de %s es de solo lectura" % raiz)


def _inspeccionar(raiz: str, skip: Sequence[str], res: Resultado,
                  ignorar_pids: Iterable[int]) -> None:
    saltar = {os.path.join(raiz, s) for s in skip}
    n = 0
    pila = [raiz]
    while pila:
        actual = pila.pop()
        try:
            with os.scandir(actual) as it:
                entradas = list(it)
        except OSError as exc:
            raise Parada("ILEGIBLE", "directorio ilegible/inaccesible %s (%s)"
                         % (actual, _errno(exc)))
        for e in entradas:
            if e.path in saltar:
                continue
            n += 1
            try:
                st = e.stat(follow_symlinks=False)
            except OSError as exc:
                raise Parada("ILEGIBLE", "no se puede inspeccionar %s (%s)" % (e.path, _errno(exc)))
            if stat.S_ISLNK(st.st_mode):
                raise Parada("SYMLINK", "enlace simbolico inesperado en el estado: %s" % e.path)
            if stat.S_ISDIR(st.st_mode):
                pila.append(e.path)
            elif not stat.S_ISREG(st.st_mode):
                raise Parada("TIPO", "entrada que no es fichero ni directorio: %s" % e.path)
            elif e.name.endswith("-journal") and st.st_size > 0:
                raise Parada("JOURNAL_PENDIENTE", "journal SQLite no vacio %s: la base no se "
                             "cerro limpia; no se toca (restaure o revise a mano)" % e.path)
    res.decir("PASO 6", "state root inspeccionado: %d entradas, sin symlinks ni tipos raros" % n)
    abiertos = procesos_con_abiertos(raiz, ignorar_pids)
    if abiertos:
        pid, cmd, ruta = abiertos[0]
        raise Parada("BASE_ABIERTA", "el proceso %d (%s) tiene abierto %s: los servicios no "
                     "estan parados; no se migra con ficheros en uso" % (pid, cmd, ruta))
    res.decir("PASO 6", "ningun proceso tiene ficheros del state root abiertos")


# --------------------------------------------------------------------------
# paso 7: mover el estado mutable legacy fuera de la release
# --------------------------------------------------------------------------
def _copiar_verificado(origen: str, destino: str, uid: int, gid: int,
                       solo_si_ausente: bool = False) -> str:
    """Copia ``origen`` -> ``destino`` SIN pisar. Devuelve ``COPIADO``/``IGUAL``.

    Levanta ``Parada`` en conflicto o ante cualquier fallo; el origen no se toca.
    ``solo_si_ausente`` (arbol legacy, que NUNCA se retira): si el destino ya
    existe se respeta sin comparar, porque el estado vivo ha podido seguir
    creciendo desde la primera copia y compararlo bloquearia cada despliegue.
    """
    if solo_si_ausente and os.path.lexists(destino):
        return "YA_EXISTE"
    sha_origen = _sha256(origen)
    if os.path.lexists(destino):
        if os.path.islink(destino) or not os.path.isfile(destino):
            raise Parada("SYMLINK" if os.path.islink(destino) else "TIPO",
                         "el destino %s existe y no es un fichero regular" % destino)
        if _sha256(destino) == sha_origen:
            return "IGUAL"
        raise Parada("CONFLICTO_DE_ESTADO",
                     "%s y %s existen y DIFIEREN; se conservan los dos y no se elige en "
                     "silencio (decision del operador)" % (origen, destino))
    carpeta = os.path.dirname(destino)
    tmp = os.path.join(carpeta, ".migrando-%d-%s" % (os.getpid(), os.path.basename(destino)))
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _ss().FILE_MODE)
    except OSError as exc:
        raise Parada("SIN_PERMISOS", "no se pudo crear el temporal %s (%s)" % (tmp, _errno(exc)))
    try:
        with os.fdopen(fd, "wb") as out, open(origen, "rb") as src:
            for bloque in iter(lambda: src.read(1 << 20), b""):
                out.write(bloque)
            out.flush()
            os.fsync(out.fileno())
        os.chown(tmp, uid, gid)
        os.chmod(tmp, _ss().FILE_MODE)
        if _sha256(tmp) != sha_origen:
            raise Parada("COPIA_NO_VERIFICA", "el hash de la copia de %s no coincide" % origen)
        try:
            os.link(tmp, destino)
        except FileExistsError:
            raise Parada("CONFLICTO_DE_ESTADO", "el destino %s aparecio durante la copia" % destino)
        _fsync_dir(carpeta)
    except OSError as exc:
        raise Parada("MOVIMIENTO_PARCIAL", "fallo copiando %s -> %s (%s); el original sigue "
                     "intacto" % (origen, destino, _errno(exc)))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if _sha256(destino) != sha_origen:
        raise Parada("COPIA_NO_VERIFICA", "el destino %s no verifica tras publicarse" % destino)
    return "COPIADO"


def _asegurar_dir(ruta: str, uid: int, gid: int) -> None:
    if os.path.islink(ruta):
        raise Parada("SYMLINK", "%s es un enlace simbolico" % ruta)
    if not os.path.isdir(ruta):
        try:
            os.makedirs(ruta, mode=_ss().DIR_MODE, exist_ok=True)
        except OSError as exc:
            raise Parada("SIN_PERMISOS", "no se pudo crear %s (%s)" % (ruta, _errno(exc)))
    try:
        os.chown(ruta, uid, gid)
        os.chmod(ruta, _ss().DIR_MODE)
    except OSError as exc:
        raise Parada("SIN_PERMISOS", "no se pudo fijar propietario/modo de %s (%s)" % (ruta, _errno(exc)))


def _retirar(ruta: str, release_id: str) -> str:
    """Renombra (no borra) el original ya verificado. Devuelve el nuevo nombre."""
    base = "%s.migrado-%s" % (ruta, release_id)
    nuevo, k = base, 1
    while os.path.lexists(nuevo):
        k += 1
        nuevo = "%s.%d" % (base, k)
    try:
        os.rename(ruta, nuevo)
    except OSError as exc:
        raise Parada("MOVIMIENTO_PARCIAL", "copiado y verificado, pero no se pudo retirar el "
                     "original %s (%s)" % (ruta, _errno(exc)))
    return nuevo


def _mover_fichero(origen: str, destino: str, uid: int, gid: int, release_id: str,
                   retirar: bool, res: Resultado) -> None:
    if os.path.islink(origen):
        raise Parada("SYMLINK", "el origen legacy %s es un enlace simbolico" % origen)
    _asegurar_dir(os.path.dirname(destino), uid, gid)
    como = _copiar_verificado(origen, destino, uid, gid, solo_si_ausente=not retirar)
    if retirar:
        nuevo = _retirar(origen, release_id)
        res.decir("MOVIDO", "%s -> %s (%s; original conservado como %s)"
                  % (origen, destino, como, os.path.basename(nuevo)))
    else:
        res.decir("COPIADO", "%s -> %s (%s; origen legacy intacto)" % (origen, destino, como))


def _mover_directorio(origen: str, destino: str, uid: int, gid: int, release_id: str,
                      retirar: bool, res: Resultado) -> None:
    if os.path.islink(origen):
        raise Parada("SYMLINK", "el origen legacy %s es un enlace simbolico" % origen)
    _asegurar_dir(destino, uid, gid)
    n = 0
    for carpeta, subdirs, ficheros in os.walk(origen, followlinks=False):
        for d in list(subdirs):
            p = os.path.join(carpeta, d)
            if os.path.islink(p):
                raise Parada("SYMLINK", "enlace simbolico dentro del origen legacy: %s" % p)
            _asegurar_dir(os.path.join(destino, os.path.relpath(p, origen)), uid, gid)
        for f in ficheros:
            p = os.path.join(carpeta, f)
            if os.path.islink(p) or not os.path.isfile(p):
                raise Parada("SYMLINK" if os.path.islink(p) else "TIPO",
                             "entrada no regular dentro del origen legacy: %s" % p)
            _copiar_verificado(p, os.path.join(destino, os.path.relpath(p, origen)), uid, gid,
                               solo_si_ausente=not retirar)
            n += 1
    if retirar:
        nuevo = _retirar(origen, release_id)
        res.decir("MOVIDO", "%s -> %s (%d fichero(s); original conservado como %s)"
                  % (origen, destino, n, os.path.basename(nuevo)))
    else:
        res.decir("COPIADO", "%s -> %s (%d fichero(s); origen legacy intacto)" % (origen, destino, n))


def _mover_legacy(rutas: dict, releases: Sequence[str], legacy_root: Optional[str],
                  uid: int, gid: int, release_id: str, res: Resultado) -> None:
    fuentes = [(r, True) for r in releases]
    if legacy_root:
        fuentes.append((legacy_root, False))
    movidos = 0
    total = 0
    for base, _retirar_ in fuentes:
        for rel, _clave, _tipo in LEGACY_EN_RELEASE:
            origen = os.path.join(base, rel)
            if os.path.isfile(origen):
                total += os.path.getsize(origen)
            elif os.path.isdir(origen):
                for carpeta, _d, ficheros in os.walk(origen):
                    total += sum(os.path.getsize(os.path.join(carpeta, f))
                                 for f in ficheros if os.path.isfile(os.path.join(carpeta, f)))
    if total:
        destino_fs = next(iter(rutas.values()), None)
        if destino_fs is not None:
            vfs = os.statvfs(os.path.dirname(str(destino_fs)) if os.path.isdir(
                os.path.dirname(str(destino_fs))) else "/")
            libre = vfs.f_bavail * vfs.f_frsize
            if libre < total * 2 + (1 << 20):
                raise Parada("ESPACIO_INSUFICIENTE", "se necesitan ~%d bytes para copiar el "
                             "estado legacy y hay %d libres" % (total * 2, libre))
    for base, retirar in fuentes:
        for rel, clave, tipo in LEGACY_EN_RELEASE:
            origen = os.path.join(base, rel)
            if not os.path.lexists(origen):
                continue
            destino = rutas.get(clave)
            if destino is None:
                raise Parada("RUTA_INCORRECTA", "hay estado legacy en %s pero el entorno no "
                             "declara dónde va (%s)" % (origen, clave))
            destino = str(destino)
            if os.path.normpath(destino) == os.path.normpath(origen):
                raise Parada("RUTA_INCORRECTA", "el destino %s es el propio origen: el estado "
                             "sigue DENTRO de la release" % destino)
            if tipo == "file":
                _mover_fichero(origen, destino, uid, gid, release_id, retirar, res)
            else:
                _mover_directorio(origen, destino, uid, gid, release_id, retirar, res)
            movidos += 1
    res.decir("PASO 7", "estado mutable legacy fuera de la release: %d elemento(s) movido(s)" % movidos)


# --------------------------------------------------------------------------
# pasos 8 y 9: propietario y modos
# --------------------------------------------------------------------------
def _corregir(raiz: str, skip: Sequence[str], dirs_requeridos: Iterable[str],
              uid: int, gid: int, res: Resultado) -> None:
    saltar = {os.path.join(raiz, s) for s in skip}
    for d in dirs_requeridos:
        _asegurar_dir(d, uid, gid)
    cambios = 0

    def arreglar(ruta: str, es_dir: bool) -> None:
        nonlocal cambios
        try:
            st = os.lstat(ruta)
            if st.st_uid != uid or st.st_gid != gid:
                os.lchown(ruta, uid, gid)
                cambios += 1
            modo = _ss().DIR_MODE if es_dir else _ss().FILE_MODE
            if stat.S_IMODE(st.st_mode) != modo:
                os.chmod(ruta, modo)
                cambios += 1
        except OSError as exc:
            raise Parada("SIN_PERMISOS", "no se pudo fijar propietario/modo de %s (%s)"
                         % (ruta, _errno(exc)))

    arreglar(raiz, True)
    pila = [raiz]
    while pila:
        actual = pila.pop()
        with os.scandir(actual) as it:
            entradas = list(it)
        for e in entradas:
            if e.path in saltar:
                continue
            es_dir = e.is_dir(follow_symlinks=False)
            arreglar(e.path, es_dir)
            if es_dir:
                pila.append(e.path)
    res.decir("PASO 8-9", "propietario %d:%d y modos 0700/0600 aplicados (%d cambio(s); 0 = ya estaba)"
              % (uid, gid, cambios))


# --------------------------------------------------------------------------
# orquestacion
# --------------------------------------------------------------------------
def aplicar(state_root: str, env: dict, *, releases: Sequence[str] = (),
            legacy_root: Optional[str] = None, release_id: str = "sin-id",
            role: str = "viewer", uid: Optional[int] = None, gid: Optional[int] = None,
            crear_state_root: bool = True, ignorar_pids: Iterable[int] = (),
            raiz_repo: Path = REPO_ROOT) -> Resultado:
    res = Resultado()
    ss = _service_state(raiz_repo)
    try:
        if uid is None or gid is None:
            real_uid, real_gid = ss.expected_ids()
            uid = real_uid if uid is None else uid
            gid = real_gid if gid is None else gid
        if uid is None or gid is None:
            raise Parada("IDENTIDAD", "el usuario/grupo %s:%s no existe; crearlo es parte "
                         "del despliegue (asegurar_identidad_de_servicio)"
                         % (ss.SERVICE_USER, ss.SERVICE_GROUP))
        state_root = os.path.normpath(state_root)
        env = dict(env)
        # El state root efectivo es UNO (config explicita o default de la autoridad); si el
        # entorno declara otro distinto del que se migra, no se determina de forma inequivoca.
        declarada = (env.get(ss.STATE_ROOT_ENV) or "").strip()
        if declarada and os.path.normpath(declarada) != state_root:
            raise Parada("STATE_ROOT_AMBIGUO", "el entorno declara S9K_STATE_ROOT=%s pero se migra %s"
                         % (declarada, state_root))
        env[ss.STATE_ROOT_ENV] = state_root
        rutas, faltan = ss.effective_paths(env, role=role)
        if faltan:
            raise Parada("RUTA_INCORRECTA", "; ".join(v.message() for v in faltan))
        declaradas = []
        for clave, ruta in sorted(rutas.items()):
            viol: list = []
            ss._revisar_declarada(clave, ruta, Path(state_root), ss.RELEASE_PREFIXES, viol)
            declaradas += viol
        if declaradas:
            raise Parada("RUTA_INCORRECTA", "; ".join(v.message() for v in declaradas))
        res.decir("PASO 1", "estado real: state_root=%s servicio=%s:%s (uid %d gid %d) rutas=%d"
                  % (state_root, ss.SERVICE_USER, ss.SERVICE_GROUP, uid, gid, len(rutas)))
        _precondiciones(state_root, crear_state_root, uid, gid, res)
        res.decir("PASO 2", "precondiciones: state root real, escribible, sistema de ficheros rw")
        _backups_legacy(state_root, res)
        _inspeccionar(state_root, ss.ADMIN_SUBTREES, res, ignorar_pids)
        _mover_legacy(rutas, releases, legacy_root, uid, gid, release_id, res)
        tipos = {clave: tipo for (tipo, clave) in ss.STATE_PATH_VARS.values()}
        tipos["audit"] = "file"
        requeridos = [os.path.join(state_root, s) for s in ss.SERVICE_SUBDIRS]
        for clave, ruta in rutas.items():
            requeridos.append(str(ruta if tipos.get(clave) == "dir" else ruta.parent))
        requeridos = sorted({r for r in requeridos if r.startswith(state_root + "/")},
                            key=lambda p: p.count("/"))
        _corregir(state_root, ss.ADMIN_SUBTREES, requeridos, uid, gid, res)
        # Paso 10: LA MISMA funcion que el arranque del servicio.
        viol = ss.inspect_state(state_root, uid=uid, gid=gid, declared=rutas)
        if viol:
            for v in viol:
                res.decir("RESIDUAL", v.message())
            raise Parada("NO_VERIFICA", "el estado sigue sin cumplir el contrato tras migrar "
                         "(%d hallazgo(s) arriba)" % len(viol))
        res.decir("PASO 10", "inspect_state (la comprobacion de arranque del servicio): sin hallazgos")
    except Parada as p:
        return res.parar(p.codigo, p.texto)
    except OSError as exc:
        # Cualquier fallo de E/S no previsto (fichero ilegible, EIO...) es un STOP
        # con la ruta y la causa, no un traceback ni un falso exito.
        return res.parar("ILEGIBLE" if isinstance(exc, PermissionError) else "ERROR_DE_E_S",
                         "%s (%s)" % (exc.filename or "ruta desconocida", _errno(exc)))
    res.decir("OK", "estado migrado y verificado; falta la verificacion por efecto como %s "
              "(deploy.sh, runuser)" % ss.SERVICE_USER)
    return res


def _leer_env(ruta: str) -> dict:
    ss = _service_state()
    return ss._leer_env_file(ruta)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("aplicar", help="migra y verifica (servicios YA parados)")
    a.add_argument("--state-root", required=True)
    a.add_argument("--env-file", required=True, help="viewer.env (rutas efectivas)")
    a.add_argument("--worker-env-file", default=None)
    a.add_argument("--release-dir", action="append", default=[],
                   help="release (activa) cuyo estado mutable legacy se mueve (repetible)")
    a.add_argument("--legacy-root", default=None, help="arbol legacy: solo se COPIA")
    a.add_argument("--release-id", default="sin-id")
    a.add_argument("--role", default="viewer", choices=["viewer", "worker"])
    a.add_argument("--uid", type=int, default=None)
    a.add_argument("--gid", type=int, default=None)
    args = ap.parse_args(argv)
    env = _leer_env(args.env_file)
    res = aplicar(args.state_root, env, releases=args.release_dir,
                  legacy_root=args.legacy_root, release_id=args.release_id,
                  role=args.role, uid=args.uid, gid=args.gid)
    for linea in res.lineas:
        print(linea, file=sys.stderr if res.rc else sys.stdout)
    return res.rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
