# -*- coding: utf-8 -*-
"""H-06/H-08 · criterios 5 y 6 del operador para la boveda externa (EXTERNAL OPERATOR CONTENT).

  5  Borrar y restaurar (o recrear vacio) el STATE ROOT no altera la boveda externa: hash, inodo,
     dueño, grupo y modo del perfil y de cada directorio de la boveda identicos antes/despues; y la
     migracion (`migrar_estado.aplicar`), la comprobacion de arranque (`enforce`), `inspect_state`
     y el `check`/`validate-env` de la autoridad NUNCA recorren ni tocan `S9K_VAULT_ROOT`, aunque
     el operador la situe en una ruta HERMANA del state root (`/var/lib/s9-knowledge-boveda`).
  6  El backup/restore del STATE ROOT no afirma contener la boveda: la frase explicita en
     deploy/README.md, en la propuesta de backup (cabecera y metadatos de cada copia) y en su
     README; y la copia no lee `S9K_VAULT_ROOT`.

El paso real (state root borrado y restaurado con deploy.sh, boveda hermana, root:root) es el
H.7 del escenario H de VM112 (deploy/tests/lab/50_escenario_H_boveda.sh).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
RAIZ = _TESTS.parents[1]
SCRIPTS = RAIZ / "deploy" / "scripts"
SS_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"
README = RAIZ / "deploy" / "README.md"
BACKUP_SH = RAIZ / "deploy" / "propuestas" / "backup-automatico" / "backup.sh"
BACKUP_README = RAIZ / "deploy" / "propuestas" / "backup-automatico" / "README.md"
UID, GID = os.getuid(), os.getgid()

#: La frase que fija el criterio 6 (la misma en los tres documentos).
FRASE_BACKUP = "El backup/restore del STATE ROOT NO contiene la bóveda externa (`S9K_VAULT_ROOT`)"


def _cargar(nombre, ruta):
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


ss = _cargar("_s9k_service_state", SS_PY)
mg = _cargar("_s9k_migrar_estado", SCRIPTS / "migrar_estado.py")


def _causa(r) -> str:
    return " | ".join(l for l in r.lineas if l.startswith(("STOP", "RESIDUAL", "OK"))) or "sin STOP ni OK"


def _foto_boveda(raiz: Path) -> dict:
    """ruta -> (inodo, uid, gid, modo, tipo, sha256 si es fichero)."""
    out = {}
    for p in [raiz, *sorted(raiz.rglob("*"))]:
        st = os.lstat(p)
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if stat.S_ISREG(st.st_mode) else None
        out[p.relative_to(raiz.parent).as_posix()] = (
            st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), stat.S_IFMT(st.st_mode), sha)
    return out


class Instalacion:
    """State root LEGACY + boveda HERMANA del state root (la ruta que un operador podria elegir)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "var" / "lib" / "s9-knowledge"
        self.vault = tmp / "var" / "lib" / "s9-knowledge-boveda"      # HERMANA
        self.release = tmp / "opt" / "releases" / "r-ant"
        self.rv3 = self.state / "reviews-v3"
        for d in ("auth", "jobs", "reviews-v3/proposals", "health"):
            (self.state / d).mkdir(parents=True)
        self._escribe(self.state / "auth" / "auth.db", b"AUTH" * 10, 0o644)
        self._escribe(self.rv3 / "review.sqlite3", b"REVIEW" * 10, 0o660)
        self._escribe(self.release / "viewer" / "output" / "reviews-v3" / "decisions.jsonl", b'{"d":1}\n', 0o644)
        for d in [self.state, *[p for p in self.state.rglob("*") if p.is_dir()]]:
            d.chmod(0o755)
        juego = self.vault / "l5r"
        juego.mkdir(parents=True)
        self._escribe(juego / "perfil-operador.json", b'{"workspace": "leyenda"}', 0o664)
        self._escribe(juego / "Cronica.md", b"# notas del operador\n", 0o644)
        juego.chmod(0o775)
        self.vault.chmod(0o755)
        self.env = {
            "S9K_STATE_ROOT": str(self.state),
            "S9K_AUTH_DB_PATH": str(self.state / "auth" / "auth.db"),
            "S9K_JOBS_DB": str(self.state / "jobs" / "jobs.db"),
            "S9K_V3_REVIEW_DATABASE_PATH": str(self.rv3 / "review.sqlite3"),
            "S9K_V3_REVIEW_PROPOSALS_DIR": str(self.rv3 / "proposals"),
            "S9K_VAULT_ROOT": str(self.vault),
            "S9K_VAULT_REQUIRE_MOUNT": "0",
        }

    @staticmethod
    def _escribe(ruta: Path, datos: bytes, modo: int):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        ruta.chmod(modo)

    def migrar(self, **kw):
        kw.setdefault("releases", [str(self.release)])
        kw.setdefault("release_id", "r-nueva")
        return mg.aplicar(str(self.state), self.env, uid=UID, gid=GID, **kw)


@pytest.fixture
def inst(tmp_path):
    return Instalacion(tmp_path)


_VIGILADAS = ("lstat", "stat", "scandir", "listdir", "open", "access", "chmod", "chown",
              "lchown", "rename", "replace", "unlink", "rmdir", "mkdir", "utime", "walk", "readlink")


@pytest.fixture
def rutas_tocadas(monkeypatch):
    """Registra cada RUTA que pasa por las primitivas del SO (las de la autoridad y la migracion)."""
    vistas: list = []

    def envolver(nombre):
        original = getattr(os, nombre)

        def envoltura(*a, **k):
            if a and isinstance(a[0], (str, bytes, os.PathLike)):
                vistas.append(os.fsdecode(os.fspath(a[0])))
            return original(*a, **k)
        return envoltura

    for nombre in _VIGILADAS:
        monkeypatch.setattr(os, nombre, envolver(nombre))
    return vistas


def _bajo(rutas, raiz: Path):
    r = str(raiz)
    return sorted({p for p in rutas if p == r or p.startswith(r + "/")})


def test_V5_migracion_enforce_e_inspect_state_nunca_tocan_la_boveda_hermana(inst, rutas_tocadas):
    antes = _foto_boveda(inst.vault)
    del rutas_tocadas[:]          # la foto del propio test no cuenta
    r = inst.migrar()
    assert r.rc == 0, _causa(r)
    rutas, faltan = ss.effective_paths(inst.env, role="viewer")
    assert not faltan
    assert ss.inspect_state(str(inst.state), uid=UID, gid=GID, declared=rutas) == []
    ss.inspect_effective_access(str(inst.state), rutas)
    ss.inspect_dedicated_state_root(str(inst.state), rutas)
    with pytest.raises(ss.ServiceStateError):      # identidad: no corre como s9knowledge
        ss.enforce("viewer", env=inst.env, uid=UID, gid=GID)
    assert rutas_tocadas, "la vigilancia no vio ninguna ruta: el detector estaria ciego"
    assert _bajo(rutas_tocadas, inst.state), "la vigilancia no vio el state root: detector ciego"
    assert _bajo(rutas_tocadas, inst.vault) == [], "V5: LA AUTORIDAD RECORRIO LA BOVEDA: %s" % _bajo(
        rutas_tocadas, inst.vault)[:5]
    assert _foto_boveda(inst.vault) == antes, "V5: LA BOVEDA CAMBIO"


def test_V5_borrar_y_restaurar_el_state_root_no_altera_la_boveda(inst, rutas_tocadas):
    """Restore: el state root se borra entero y se restaura de una copia (lo que haria un
    operador con un backup); despues se re-ejecuta la migracion, que es el «restore canonico»."""
    assert inst.migrar().rc == 0
    antes = _foto_boveda(inst.vault)
    copia = inst.tmp / "copia-del-state"
    shutil.copytree(inst.state, copia, symlinks=True)
    shutil.rmtree(inst.state)
    shutil.copytree(copia, inst.state, symlinks=True)
    del rutas_tocadas[:]
    r = inst.migrar(release_id="r-restaurada")
    assert r.rc == 0, _causa(r)
    assert _bajo(rutas_tocadas, inst.vault) == [], "V5: LA MIGRACION RECORRIO LA BOVEDA"
    assert _foto_boveda(inst.vault) == antes, "V5: LA BOVEDA CAMBIO TRAS RESTAURAR EL STATE ROOT"


def test_V5_recrear_el_state_root_vacio_fresh_no_altera_la_boveda(inst, rutas_tocadas):
    """Fresh: el state root se borra y la migracion lo recrea VACIO (sin release legacy)."""
    antes = _foto_boveda(inst.vault)
    shutil.rmtree(inst.state)
    del rutas_tocadas[:]
    r = inst.migrar(releases=[], crear_state_root=True)
    assert r.rc == 0, _causa(r)
    assert inst.state.is_dir()
    assert _bajo(rutas_tocadas, inst.vault) == [], "V5: LA MIGRACION RECORRIO LA BOVEDA"
    assert _foto_boveda(inst.vault) == antes, "V5: LA BOVEDA CAMBIO TRAS RECREAR EL STATE ROOT"


def test_V5_check_y_validate_env_de_la_autoridad_no_miran_la_boveda(inst):
    """Las CLIs de la autoridad (las que usan bash/Ansible) con S9K_VAULT_ROOT HERMANA en el
    EnvironmentFile: la boveda no aparece en ningun hallazgo ni la tocan (foto identica)."""
    assert inst.migrar().rc == 0
    env_file = inst.tmp / "viewer.env"
    env_file.write_text("".join("%s=%s\n" % kv for kv in inst.env.items()), encoding="utf-8")
    antes = _foto_boveda(inst.vault)
    for args in (["validate-env", "--env-file", str(env_file), "--state-root", str(inst.state)],
                 ["check", "--state-root", str(inst.state), "--env-file", str(env_file)]):
        r = subprocess.run([sys.executable, str(SS_PY), *args], capture_output=True, text=True)
        assert "s9-knowledge-boveda" not in (r.stdout + r.stderr), (args[0], r.stdout + r.stderr)
    assert _foto_boveda(inst.vault) == antes


def test_V5_la_boveda_no_es_una_ruta_de_estado_de_la_autoridad():
    assert not [v for v in ss.STATE_PATH_VARS if "VAULT" in v], "V5: LA BOVEDA ES RUTA DE ESTADO"


# ---------------------------------------------------------------------------
# Criterio 6 · el backup del STATE ROOT no afirma contener la boveda
# ---------------------------------------------------------------------------

def _funcion_bash(texto: str, nombre: str) -> str:
    m = re.search(r"^%s\(\) \{\n(.*?)^\}" % re.escape(nombre), texto, re.S | re.M)
    assert m, "no se encontro la funcion %s" % nombre
    return m.group(1)


@pytest.mark.parametrize("doc", [README, BACKUP_README], ids=["deploy-README", "backup-README"])
def test_V6_la_documentacion_dice_que_el_backup_no_contiene_la_boveda(doc):
    texto = doc.read_text(encoding="utf-8")
    assert FRASE_BACKUP in texto, "V6: FALTA LA FRASE EN %s" % doc.relative_to(RAIZ)


def test_V6_la_propuesta_de_backup_lo_declara_y_no_lee_la_boveda():
    texto = BACKUP_SH.read_text(encoding="utf-8")
    cabecera = texto.split("set -Eeuo pipefail", 1)[0]
    assert "NO incluye la bóveda externa (S9K_VAULT_ROOT)" in cabecera, "V6: LA CABECERA NO LO DICE"
    copiar = _funcion_bash(texto, "copiar")
    # los metadatos de CADA copia lo declaran (lo que un restore lee para saber que contiene)
    assert 'echo "boveda_externa=NO_INCLUIDA' in copiar, "V6: LOS METADATOS DE LA COPIA NO LO DICEN"
    # y la copia no la lee: ninguna referencia a la variable fuera de esa linea declarativa
    lineas = [l for l in copiar.splitlines() if "VAULT" in l and "boveda_externa=NO_INCLUIDA" not in l]
    assert lineas == [], lineas


def test_V6_el_healthcheck_de_backups_no_afirma_contener_la_boveda():
    """`check_backups` mide conjuntos de copias del STATE: ni su mensaje ni su codigo hablan de la
    boveda (no puede «darla por respaldada»)."""
    import ast

    fuente = (RAIZ / "viewer" / "app" / "health" / "checks.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    funciones = {n.name: ast.get_source_segment(fuente, n) for n in ast.walk(arbol)
                 if isinstance(n, ast.FunctionDef)}
    for nombre in ("check_backups", "_is_backup_set", "_find_backup_sets", "_verify_checksums"):
        cuerpo = funciones[nombre].lower()
        assert "vault" not in cuerpo and "boveda" not in cuerpo and "bóveda" not in cuerpo, nombre
