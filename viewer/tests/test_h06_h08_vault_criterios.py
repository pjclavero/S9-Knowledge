# -*- coding: utf-8 -*-
"""H-06/H-08 · CRITERIOS DE ACEPTACION DEL OPERADOR para la boveda externa (2026-11-15).

Decision CERRADA: EXTERNAL OPERATOR CONTENT. Este modulo fija lo que faltaba de los criterios:

  4  `S9K_VAULT_ROOT` declarada pero INEXISTENTE -> comportamiento explicito (404 nombrado del
     endpoint, catalogo sin fuentes de boveda, salud VAULT UNAVAILABLE) y NO se crea ningun arbol.
  7  diagnostico: componente de salud `vault` (AVAILABLE / READ_ONLY / UNAVAILABLE) independiente
     de `state_validation` (STATE OK / FAIL); dependencia OPCIONAL: nunca UNHEALTHY; solo lectura.
  8  control negativo POR EFECTO de chmod/chown/root: tras cada caso (escribible, perfil de solo
     lectura, carpeta de solo lectura, perfil 0400) dueño/grupo/modo/inodo de la boveda identicos,
     y el escritor no tiene camino hacia root (AST).

Los criterios 5 y 6 (state root borrado/restaurado; el backup no afirma contener la boveda) viven
en deploy/tests/test_h06_h08_vault_state.py (necesitan la migracion y los textos de despliegue).
"""
from __future__ import annotations

import ast
import os
import stat
from pathlib import Path

import pytest

from test_admin_label_6b2 import WS, _cliente, _csrf, _perfil_path, entorno  # noqa: F401

EUID = os.geteuid()
RAIZ = Path(__file__).resolve().parents[2]


def _post(c, tok, fp, label="Nombre nuevo"):
    return c.post("/admin/partidas/label", data={
        "workspace": WS, "label": label, "fingerprint": fp, "csrf_token": tok})


def _arbol(raiz: Path) -> dict:
    """Todo lo que hay bajo `raiz` (incluida): ruta -> (inodo, uid, gid, modo, tipo)."""
    out = {}
    for p in [raiz, *raiz.rglob("*")]:
        st = os.lstat(p)
        out[p.relative_to(raiz.parent).as_posix()] = (
            st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), stat.S_IFMT(st.st_mode))
    return out


# ---------------------------------------------------------------------------
# Criterio 4 · S9K_VAULT_ROOT inexistente
# ---------------------------------------------------------------------------

def test_V4_vault_root_inexistente_404_nombrado_y_no_se_crea_ningun_arbol(entorno, monkeypatch, tmp_path):  # noqa: F811
    """Declarada pero inexistente: el endpoint responde 404 «No se encontró la bóveda…», el
    catalogo no da fuentes de boveda (rechazo nombrado) y NADA nuevo aparece: ni la ruta declarada,
    ni sus padres, ni un sustituto bajo el state ni en ningun otro sitio del arbol de la prueba."""
    from app import sources_catalog

    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    inexistente = tmp_path / "no-existe" / "bovedas"
    antes = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    monkeypatch.setenv("S9K_VAULT_ROOT", str(inexistente))
    r = _post(c, tok, fp)
    assert r.status_code == 404 and "No se encontró la bóveda" in r.text, (r.status_code, r.text[:300])
    # el catalogo declara la AUSENCIA (excepcion nombrada), nunca «lista vacia» de fuentes
    with pytest.raises(sources_catalog.CatalogoNoDisponible, match="PATH_MISSING"):
        sources_catalog.listar_fuentes_boveda(
            {"S9K_VAULT_ROOT": str(inexistente), "S9K_VAULT_REQUIRE_MOUNT": "0"})
    despues = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    nuevos = [x for x in despues if x not in antes and "auth.db" not in x]
    assert nuevos == [], "V4: SE CREO UN ARBOL: %s" % nuevos
    assert not inexistente.parent.exists(), "V4: SE CREO LA RUTA DECLARADA"


def test_V4_la_salud_dice_UNAVAILABLE_con_el_motivo_y_no_crea_la_ruta(tmp_path):
    from app.health import checks
    from app.health.models import HealthStatus

    inexistente = tmp_path / "no-existe"
    r = checks.check_vault(str(inexistente), "0")
    assert r.details["vault"] == checks.VAULT_UNAVAILABLE and "PATH_MISSING" in r.message, r.message
    assert r.status == HealthStatus.DEGRADED
    assert not inexistente.exists()


# ---------------------------------------------------------------------------
# Criterio 7 · VAULT AVAILABLE / READ_ONLY / UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.fixture
def boveda(tmp_path):
    """Boveda minima: raiz/<juego>/perfil-operador.json, todo del usuario de la prueba."""
    raiz = tmp_path / "bovedas"
    juego = raiz / "l5r"
    juego.mkdir(parents=True)
    (juego / "perfil-operador.json").write_text('{"workspace": "leyenda"}', encoding="utf-8")
    return raiz


def _vault(raiz, montaje="0"):
    from app.health import checks

    return checks.check_vault(str(raiz) if raiz is not None else None, montaje)


def test_V7_AVAILABLE_perfil_y_carpeta_escribibles(boveda):
    from app.health import checks
    from app.health.models import HealthStatus

    r = _vault(boveda)
    assert r.component == "vault" and r.details["vault"] == checks.VAULT_AVAILABLE, r.message
    assert r.status == HealthStatus.HEALTHY and r.message.startswith("VAULT AVAILABLE")


def test_V7_AVAILABLE_carpeta_de_juego_sin_perfil_aun_pero_escribible(boveda):
    from app.health import checks

    (boveda / "l5r" / "perfil-operador.json").unlink()
    assert _vault(boveda).details["vault"] == checks.VAULT_AVAILABLE


@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos: el caso real va a VM112 (H)")
@pytest.mark.parametrize("que", ["perfil", "carpeta"])
def test_V7_READ_ONLY_existe_y_legible_pero_no_escribible(boveda, que):
    from app.health import checks
    from app.health.models import HealthStatus

    objetivo = boveda / "l5r" / ("perfil-operador.json" if que == "perfil" else "")
    modo = stat.S_IMODE(objetivo.stat().st_mode)
    objetivo.chmod(0o444 if que == "perfil" else 0o555)
    try:
        r = _vault(boveda)
    finally:
        objetivo.chmod(modo)
    assert r.details["vault"] == checks.VAULT_READ_ONLY, "V7: READ_ONLY REPORTADO COMO %s" % r.details["vault"]
    assert r.status == HealthStatus.DEGRADED and "no es escribible" in r.message, r.message


@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos: el caso real va a VM112 (H)")
def test_V7_UNAVAILABLE_raiz_ilegible(boveda):
    from app.health import checks

    boveda.chmod(0o000)
    try:
        r = _vault(boveda)
    finally:
        boveda.chmod(0o755)
    assert r.details["vault"] == checks.VAULT_UNAVAILABLE and "MOUNT_UNREADABLE" in r.message, r.message


def test_V7_UNAVAILABLE_no_configurada_es_informativo_HEALTHY(tmp_path):
    from app.health import checks
    from app.health.models import HealthStatus

    r = _vault(None)
    assert r.details["vault"] == checks.VAULT_UNAVAILABLE and r.details["configurada"] is False
    assert r.status == HealthStatus.HEALTHY and "no configurada" in r.message


def test_V7_UNAVAILABLE_sin_montaje_exigido(boveda):
    from app.health import checks

    r = _vault(boveda, montaje="1")   # tmp_path no es un punto de montaje
    assert r.details["vault"] == checks.VAULT_UNAVAILABLE and "MOUNT_MISSING" in r.message, r.message


@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos: el caso real va a VM112 (H)")
@pytest.mark.parametrize("caso", ["no_configurada", "inexistente", "read_only"])
def test_V7_la_boveda_no_pone_UNHEALTHY_la_salud_global(boveda, caso, tmp_path):
    """Dependencia OPCIONAL: READ_ONLY/UNAVAILABLE nunca hacen UNHEALTHY el informe global."""
    from app.health import runner
    from app.health.models import HealthStatus

    raiz = {"no_configurada": None, "inexistente": str(tmp_path / "no-existe"),
            "read_only": str(boveda)}[caso]
    perfil = boveda / "l5r" / "perfil-operador.json"
    if caso == "read_only":
        perfil.chmod(0o444)
    try:
        cfg = {"vault": {"vault_root": raiz, "require_mount": "0"}, "external_ai": {"enabled": False}}
        rep = runner.run_report(config=cfg, only=["vault", "external_ai"])
    finally:
        perfil.chmod(0o644)
    v = [c for c in rep.components if c.component == "vault"][0]
    assert v.status != HealthStatus.UNHEALTHY, "V7: LA BOVEDA TUMBA LA SALUD GLOBAL (%s)" % v.status
    assert rep.overall != HealthStatus.UNHEALTHY, "V7: LA BOVEDA TUMBA LA SALUD GLOBAL (%s)" % rep.overall


def test_V7_el_componente_vault_esta_registrado_y_lee_la_configuracion_gobernada(monkeypatch, boveda):
    from app.health import runner

    assert "vault" in runner.COMPONENT_NAMES and "state_validation" in runner.COMPONENT_NAMES
    monkeypatch.setenv("S9K_VAULT_ROOT", str(boveda))
    monkeypatch.setenv("S9K_VAULT_REQUIRE_MOUNT", "0")
    assert runner.build_default_config()["vault"] == {"vault_root": str(boveda), "require_mount": "0"}
    assert runner.run_component("vault").details["vault"] == "AVAILABLE"


def _estado_ok_o_fail(monkeypatch, fail: bool):
    """`check_state_validation` con systemctl simulado (sin la excepcion en las unidades)."""
    from test_h06_h08_estado_privado import _systemctl_falso

    monkeypatch.delenv("S9K_STATE_VALIDATION", raising=False)
    checks = _systemctl_falso(monkeypatch, "A=1\n")
    if fail:
        monkeypatch.setenv("S9K_STATE_VALIDATION", "disabled-explicit-for-tests")
    return checks.check_state_validation(["s9-knowledge-viewer.service"])


@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos: el caso real va a VM112 (H)")
@pytest.mark.parametrize("state_fail,vault_ro", [(True, False), (False, True), (True, True), (False, False)])
def test_V7_STATE_y_VAULT_son_independientes(monkeypatch, boveda, state_fail, vault_ro):
    from app.health import checks
    from app.health.models import HealthStatus

    perfil = boveda / "l5r" / "perfil-operador.json"
    if vault_ro:
        perfil.chmod(0o444)
    try:
        s = _estado_ok_o_fail(monkeypatch, state_fail)
        v = checks.check_vault(str(boveda), "0")
    finally:
        perfil.chmod(0o644)
    assert s.details["state"] == ("FAIL" if state_fail else "OK"), s.message
    assert s.message.startswith("STATE FAIL" if state_fail else "STATE OK"), s.message
    assert s.status == (HealthStatus.UNHEALTHY if state_fail else HealthStatus.HEALTHY)
    assert v.details["vault"] == ("READ_ONLY" if vault_ro else "AVAILABLE"), v.message


def test_V7_la_comprobacion_de_la_boveda_es_de_solo_lectura(boveda):
    """Ni ficheros de sonda ni cambios: el arbol (inodos, modos, mtime de cada directorio) es el
    mismo antes y despues; y por AST, `check_vault` y su ayudante no abren, crean ni cambian nada."""
    from app.health import checks

    antes = _arbol(boveda)
    mtimes = {p: p.stat().st_mtime_ns for p in [boveda, *boveda.rglob("*")]}
    checks.check_vault(str(boveda), "0")
    assert _arbol(boveda) == antes
    assert {p: p.stat().st_mtime_ns for p in [boveda, *boveda.rglob("*")]} == mtimes
    arbol = ast.parse((RAIZ / "viewer" / "app" / "health" / "checks.py").read_text(encoding="utf-8"))
    prohibidas = {"open", "write_text", "write_bytes", "mkdir", "makedirs", "touch", "chmod", "chown",
                  "lchown", "fchmod", "fchown", "mkstemp", "NamedTemporaryFile", "unlink", "remove",
                  "rename", "replace", "rmdir", "utime", "symlink", "link"}
    vistas = []
    for fn in ast.walk(arbol):
        if isinstance(fn, ast.FunctionDef) and fn.name in {"check_vault", "_estado_carpeta_de_juego", "_acceso"}:
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    nombre = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                    if nombre in prohibidas:
                        vistas.append((fn.name, nombre))
    assert vistas == [], vistas


# ---------------------------------------------------------------------------
# Criterio 8 · control negativo POR EFECTO de chmod/chown/root
# ---------------------------------------------------------------------------

@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos: el caso real va a VM112 (H)")
@pytest.mark.parametrize("caso", ["escribible", "perfil_0444", "carpeta_0555", "perfil_0400"])
def test_V8_tras_cada_caso_la_boveda_conserva_dueno_grupo_modo_e_inodo(entorno, caso):  # noqa: F811
    """La aplicacion jamas hace chmod/chown de la boveda (ni de la raiz, ni de la carpeta, ni del
    perfil). Se mira el EFECTO, no el codigo: tras la peticion, cada directorio de la boveda
    conserva (inodo, uid, gid, modo) y el perfil conserva (uid, gid, modo); en los casos que fallan
    tambien su inodo y su contenido."""
    db_path, auth_db, app, boveda = entorno
    c = _cliente(auth_db, db_path, app)
    tok, fp = _csrf(c)
    perfil = _perfil_path(boveda)
    carpeta = perfil.parent
    m_carpeta, m_perfil = stat.S_IMODE(carpeta.stat().st_mode), stat.S_IMODE(perfil.stat().st_mode)
    if caso == "perfil_0444":
        perfil.chmod(0o444)
    elif caso == "perfil_0400":
        perfil.chmod(0o400)
    elif caso == "carpeta_0555":
        carpeta.chmod(0o555)
    antes = _arbol(boveda)
    contenido = perfil.read_bytes()
    try:
        r = _post(c, tok, fp, "Nombre V8")
        despues = _arbol(boveda)
        contenido_despues = perfil.read_bytes()
    finally:
        carpeta.chmod(m_carpeta)
        perfil.chmod(m_perfil)
    clave_perfil = perfil.relative_to(boveda.parent).as_posix()
    if caso == "escribible":
        assert r.status_code == 302, (r.status_code, r.text[:300])
        # el perfil PROPIO se reemplaza atomicamente (otro inodo) pero conserva dueño/grupo/modo
        assert despues[clave_perfil][1:] == antes[clave_perfil][1:], "V8: PERFIL CAMBIO DE DUEÑO/MODO"
        otros = {k for k in antes if k != clave_perfil}
    else:
        assert r.status_code == 409, (r.status_code, r.text[:300])
        assert contenido_despues == contenido
        otros = set(antes)
    assert {k: despues.get(k) for k in otros} == {k: antes[k] for k in otros}, \
        "V8: LA APLICACION CAMBIO PERMISOS/DUEÑO/INODO DE LA BOVEDA"


def test_V8_el_escritor_de_la_boveda_no_tiene_camino_hacia_root():
    """Control negativo de «root»: el escritor no lanza procesos (sudo/su/runuser), no cambia de
    identidad (setuid/seteuid/setgid…) y no importa subprocess. El caso con root:root real
    (fichero no escribible por s9knowledge) va a VM112 (escenario H, caso 2)."""
    fuente = (RAIZ / "viewer" / "app" / "vault_writer.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = {a.name.split(".")[0] for n in ast.walk(arbol) if isinstance(n, (ast.Import, ast.ImportFrom))
                  for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert "subprocess" not in importados, importados
    llamadas = {n.func.attr for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    identidad = {"setuid", "seteuid", "setgid", "setegid", "setreuid", "setresuid", "setgroups",
                 "system", "popen", "execv", "execvp", "spawnv", "chown", "lchown", "chmod", "lchmod"}
    assert not (llamadas & identidad), llamadas & identidad
    for palabra in ("sudo", "runuser", "pkexec"):
        assert palabra not in fuente, palabra


# ---------------------------------------------------------------------------
# B-1 (revision acotada n.º 3): el healthcheck periodico mide desde un SANDBOX
# ---------------------------------------------------------------------------
UNIDADES = RAIZ / "viewer" / "systemd"
U_SALUD = UNIDADES / "s9-knowledge-healthcheck.service"
U_VISOR = UNIDADES / "s9-knowledge-viewer.service"


def _servicio(unidad: Path) -> list:
    """Pares (clave, valor) de la seccion [Service], en orden y con repeticiones."""
    pares, en_servicio = [], False
    for linea in unidad.read_text(encoding="utf-8").splitlines():
        s = linea.strip()
        if s.startswith("["):
            en_servicio = s == "[Service]"
            continue
        if en_servicio and s and not s.startswith(("#", ";")) and "=" in s:
            k, v = s.split("=", 1)
            pares.append((k.strip(), v.strip()))
    return pares


def _con_sandbox_de_ficheros(pares) -> list:
    """Directivas que cambian lo que el proceso VE del sistema de ficheros."""
    vistas = []
    for k, v in pares:
        if k == "ProtectSystem" and v.lower() not in ("", "no", "false", "0"):
            vistas.append("%s=%s" % (k, v))
        elif k == "ProtectHome" and v.lower() not in ("", "no", "false", "0"):
            vistas.append("%s=%s" % (k, v))
        elif k in ("ReadOnlyPaths", "InaccessiblePaths", "TemporaryFileSystem", "BindReadOnlyPaths") and v:
            vistas.append("%s=%s" % (k, v))
    return vistas


@pytest.mark.parametrize("como", ["perfil_0444", "inexistente", "sana"])
def test_B1_con_la_declaracion_del_sandbox_NUNCA_afirma_READ_ONLY_ni_UNAVAILABLE(boveda, monkeypatch, tmp_path, como):
    """Dentro del sandbox del healthcheck la boveda se ve read-only aunque el visor la escriba:
    con la declaracion de la unidad el check NO mide, lo dice y no degrada."""
    from app.health import checks
    from app.health.models import HealthStatus

    monkeypatch.setenv(checks.VAULT_MEDICION_ENV, checks.VAULT_MEDICION_SANDBOX)
    perfil = boveda / "l5r" / "perfil-operador.json"
    raiz = str(tmp_path / "no-existe") if como == "inexistente" else str(boveda)
    if como == "perfil_0444":
        perfil.chmod(0o444)
    antes = _arbol(boveda)
    try:
        r = checks.check_vault(raiz, "0")
        despues = _arbol(boveda)
    finally:
        perfil.chmod(0o644)
    assert r.details["vault"] == checks.VAULT_NO_MEDIBLE, "B-1: FALSO %s DESDE EL SANDBOX" % r.details["vault"]
    assert r.status == HealthStatus.HEALTHY and "/admin/health" in r.message, r.message
    assert despues == antes


@pytest.mark.skipif(EUID == 0, reason="root ignora los permisos")
def test_B1_sin_la_declaracion_un_READ_ONLY_real_sigue_siendo_READ_ONLY(boveda, monkeypatch):
    """El visor (panel admin) NO lleva la declaracion: ahi un READ_ONLY legitimo se informa."""
    from app.health import checks

    monkeypatch.delenv(checks.VAULT_MEDICION_ENV, raising=False)
    perfil = boveda / "l5r" / "perfil-operador.json"
    perfil.chmod(0o444)
    try:
        r = checks.check_vault(str(boveda), "0")
    finally:
        perfil.chmod(0o644)
    assert r.details["vault"] == checks.VAULT_READ_ONLY, r.message


def test_B1_la_declaracion_va_atada_al_sandbox_de_la_unidad_canonica_y_el_visor_no_la_hereda():
    """Gate: si la unidad del healthcheck cambia lo que ve del FS, DEBE declarar que la boveda no
    es medible; y si no lo cambia, no debe declararlo. El visor no tiene ese sandbox (asi el
    panel admin mide de verdad) ni la declaracion; ninguna plantilla de .env la lleva."""
    from app.health import checks

    declaracion = "%s=%s" % (checks.VAULT_MEDICION_ENV, checks.VAULT_MEDICION_SANDBOX)
    salud = _servicio(U_SALUD)
    sandbox = _con_sandbox_de_ficheros(salud)
    declarada = [v for k, v in salud if k == "Environment" and checks.VAULT_MEDICION_ENV in v]
    if sandbox:
        assert declarada == [declaracion], "B-1: SANDBOX %s SIN DECLARAR (%s)" % (sandbox, declarada)
    else:
        assert declarada == [], "B-1: DECLARADO SIN SANDBOX"
    visor = _servicio(U_VISOR)
    assert _con_sandbox_de_ficheros(visor) == [], "el visor no puede medir la boveda con sandbox"
    assert checks.VAULT_MEDICION_ENV not in U_VISOR.read_text(encoding="utf-8")
    for plantilla in (RAIZ / "viewer" / ".env.example", RAIZ / "deploy" / "config" / "viewer.env.example",
                      RAIZ / "deploy" / "config" / "worker.env.example"):
        if plantilla.exists():
            assert checks.VAULT_MEDICION_ENV not in plantilla.read_text(encoding="utf-8"), plantilla
