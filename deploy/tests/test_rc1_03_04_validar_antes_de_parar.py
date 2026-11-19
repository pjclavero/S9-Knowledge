# -*- coding: utf-8 -*-
"""RC1-03 / RC1-04 · configuracion y almacen de revision se deciden ANTES de parar (paso 2c).

Defecto (RC-E2E 1): una configuracion invalida (RC1-03), un upgrade sin almacen de revision
(RC1-04) o un BLOCK de detect_state (RC1-05) se descubrian en los pasos 4-6 de `deploy.sh`,
DESPUES de parar visor y worker (3b) y de migrar el estado (5b): servicio caido por un error
conocible al empezar.

Contrato: esos tres veredictos se aplican antes de 3b, con LAS MISMAS funciones que usan los
pasos 4 y 6 (que se conservan como segunda barrera). Nada de eso se mueve de sitio ni se relaja.

QUE SE EJECUTA: el texto REAL de `deploy.sh` entre marcas unicas (como `test_b2_fresh_install`),
ejecutado con bash sobre estados temporales. NO se ejecuta el despliegue entero (necesita root,
systemd y red): el orden global se comprueba por TEXTO (indices de marcas) y por el arnes del
paso 3-4 con `parar_y_verificar_servicios` sustituido por un testigo que deja una marca.
Los mutantes se aplican sobre COPIAS del texto de `deploy.sh`/`validate_deploy.sh`.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import review_store as rs  # noqa: E402
from test_b2_fresh_install import (  # noqa: E402
    DEPLOY_SH, LIB_SH, VALIDATE_SH, _paso6, plantilla_productiva_en)

URL = "https://s9k.example.test"
MARCA_2C_INI = "# Paso 2c "
MARCA_2C_FIN = "# --- fin del paso 2c ---"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _tramo(texto: str, ini: str, fin: str) -> str:
    for m in (ini, fin):
        assert texto.count(m) == 1, f"DETECTOR ROTO: la marca {m!r} aparece {texto.count(m)} veces"
    a = texto.index(ini)
    return texto[a:texto.index(fin, a) + len(fin)]


def _correr(cuerpo: str, validate: Path = VALIDATE_SH):
    guion = "set -Eeuo pipefail\nsource %s\nsource %s\n%s\necho TRAMO_SUPERADO\n" % (LIB_SH, validate, cuerpo)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _paso2c(env: Path, raiz: Path, *, ambiente="production", modo="upgrade", autorizar=0,
            actual: Path = None, legacy_root: Path = None, deploy_texto: str = None,
            validate: Path = VALIDATE_SH):
    tmp = env.parent
    texto = deploy_texto if deploy_texto is not None else DEPLOY_SH.read_text(encoding="utf-8")
    cuerpo = """
HERE=%s
VIEWER_ENV=%s
ENVIRONMENT=%s
S9K_STATE_ROOT=%s
S9K_CONFIG_ROOT=%s
MODE=%s
S9K_ROOT=%s
LEGACY_ROOT=%s
AUTORIZAR_CREACION_REVIEW_DB=%d
%s
""" % (_SCRIPTS, env, ambiente, raiz, tmp, modo,
       actual if actual is not None else tmp / "opt-s9k-vacio",
       legacy_root or (tmp / "legacy-no-existe"), autorizar,
       _tramo(texto, MARCA_2C_INI, MARCA_2C_FIN))
    return _correr(cuerpo, validate)


def _arbol(raiz: Path):
    out = []
    for p in sorted(raiz.rglob("*")):
        h = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "DIR"
        out.append((p.relative_to(raiz).as_posix(), h))
    return out


def _worker_env(tmp: Path) -> Path:
    return tmp / "worker.env"


def _secreto(tmp: Path) -> Path:
    return tmp / "secrets" / "neo4j_worker_password"


# ===========================================================================
# RC1-03 · configuracion validada ANTES de parar, con las mismas funciones del paso 6
# ===========================================================================
def test_RC103_C1_control_la_plantilla_productiva_pasa_el_paso_2c(tmp_path):
    """Esperado: rc 0 y TRAMO_SUPERADO (plantilla literal, upgrade, almacen existente)."""
    env, raiz = plantilla_productiva_en(tmp_path, URL)
    rc, out = _paso2c(env, raiz)
    assert rc == 0 and "TRAMO_SUPERADO" in out, out


@pytest.mark.parametrize("caso", ["url_ausente", "url_http", "password_en_worker", "secreto_vacio",
                                  "worker_env_ausente"])
def test_RC103_N1_configuracion_invalida_para_en_2c_nombrando_la_causa(tmp_path, caso):
    """Esperado: rc != 0, la causa que ya nombraba el paso 6 y la frase «NADA se ha parado»."""
    if caso == "url_ausente":
        env, raiz = plantilla_productiva_en(tmp_path, URL, quitar=("S9K_PUBLIC_BASE_URL",))
        causa = "URL_PUBLICA_NO_DECLARADA"
    elif caso == "url_http":
        env, raiz = plantilla_productiva_en(tmp_path, "http://s9k.example.test")
        causa = "ESQUEMA_NO_HTTPS"
    else:
        env, raiz = plantilla_productiva_en(tmp_path, URL)
        if caso == "password_en_worker":
            _worker_env(tmp_path).write_text(_worker_env(tmp_path).read_text() + "S9K_NEO4J_PASSWORD=x\n")
            causa = "S9K_NEO4J_PASSWORD"
        elif caso == "secreto_vacio":
            _secreto(tmp_path).write_text("")
            causa = "esta vacio"
        else:
            _worker_env(tmp_path).unlink()
            causa = "BLOCK(worker)"
    rc, out = _paso2c(env, raiz)
    assert rc != 0 and "TRAMO_SUPERADO" not in out, out
    assert causa in out, out
    assert "NADA se ha parado ni tocado" in out, out


@pytest.mark.parametrize("caso", ["url_ausente", "url_http", "password_en_worker", "secreto_vacio"])
def test_RC103_E1_2c_y_paso_6_dan_el_MISMO_veredicto(tmp_path, caso):
    """Esperado: para cada configuracion invalida, 2c y el paso 6 REAL fallan los dos (segunda
    barrera conservada; una sola autoridad de validacion)."""
    resultados = []
    for nombre, fn in (("a", _paso2c), ("b", _paso6)):
        sub = tmp_path / nombre
        sub.mkdir()
        if caso == "url_ausente":
            env, raiz = plantilla_productiva_en(sub, URL, quitar=("S9K_PUBLIC_BASE_URL",))
        elif caso == "url_http":
            env, raiz = plantilla_productiva_en(sub, "http://s9k.example.test")
        else:
            env, raiz = plantilla_productiva_en(sub, URL)
            if caso == "password_en_worker":
                _worker_env(sub).write_text(_worker_env(sub).read_text() + "S9K_NEO4J_PASSWORD=x\n")
            else:
                _secreto(sub).write_text("")
        resultados.append(fn(env, raiz)[0] != 0)
    assert resultados == [True, True], resultados


def test_RC103_P1_el_modo_del_secreto_se_difiere_a_la_segunda_barrera(tmp_path):
    """Esperado: un secreto 0644 NO bloquea en 2c (el paso 5b lo normaliza a 0640) pero SI en el
    paso 6 (que no tiene la excepcion): no se valida menos, se valida cuando ya es exigible."""
    env, raiz = plantilla_productiva_en(tmp_path, URL)
    _secreto(tmp_path).chmod(0o644)
    rc2c, out2c = _paso2c(env, raiz)
    assert rc2c == 0, out2c
    rc6, out6 = _paso6(env, raiz)
    assert rc6 != 0 and "permisos inseguros" in out6, out6


def test_RC103_L1_en_lab_http_avisa_como_en_el_paso_6(tmp_path):
    """Esperado: en `lab` una URL http no bloquea (AVISO), igual que en el paso 6."""
    env, raiz = plantilla_productiva_en(tmp_path, "http://s9k.example.test")
    rc, out = _paso2c(env, raiz, ambiente="lab")
    assert rc == 0 and "AVISO(lab)" in out, out


def test_RC103_G1_2c_llama_a_las_mismas_funciones_que_el_paso_6():
    """Esperado: cada validate_* de configuracion que llama el paso 6 aparece en
    `validar_configuracion_antes_de_parar` (guardian contra que una diverja de la otra)."""
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    paso6 = _tramo(texto, "# Paso 6: validar viewer.env", "# --- fin del paso 6 ---")
    val = VALIDATE_SH.read_text(encoding="utf-8")
    cuerpo = val[val.index("\nvalidar_configuracion_antes_de_parar() {"):]
    cuerpo = cuerpo[:cuerpo.index("\n}\n")]
    for fn in ("validate_viewer_secrets", "validate_worker_env", "validate_state_paths", "validate_https_contract"):
        assert fn in paso6, f"el paso 6 ya no llama a {fn}: actualice el guardian"
        assert fn in cuerpo, f"2c no llama a {fn}, que si llama el paso 6"
    pre = _tramo(texto, MARCA_2C_INI, MARCA_2C_FIN)
    assert "validar_configuracion_antes_de_parar" in pre


def test_RC103_G2_2c_no_toca_nada_ni_para_nada():
    """Esperado: el bloque 2c no contiene ninguna orden que cambie el sistema."""
    pre = _tramo(DEPLOY_SH.read_text(encoding="utf-8"), MARCA_2C_INI, MARCA_2C_FIN)
    codigo = "\n".join(l for l in pre.splitlines() if not l.lstrip().startswith("#"))
    for prohibido in ("systemctl", "parar_y_verificar", "migrar_estado", "chown", "chmod", "mkdir", "install ",
                      "asegurar_identidad", "rm ", "mv ", "cp "):
        assert prohibido not in codigo, f"2c contiene {prohibido!r}"
    assert "--solo-lectura" in codigo


def _orden_global_ok(texto: str) -> bool:
    """2b < 2c < 3 < (gate RC1-05) < 3b < parada < migracion del estado."""
    try:
        idx = [texto.index("# --- fin del paso 2b ---"), texto.index(MARCA_2C_INI),
               texto.index(MARCA_2C_FIN), texto.index("# Paso 3: detectar layout/estado"),
               texto.index('exigir_decision_de_estado "${STATE_JSON}"'), texto.index("# Paso 3b "),
               texto.index("parar_y_verificar_servicios ||"), texto.index('migrar_estado.py" aplicar')]
    except ValueError:
        return False
    return idx == sorted(idx) and len(set(idx)) == len(idx)


def test_RC103_O1_el_orden_global_de_deploy_sh():
    """Esperado: 2b < 2c < 3 < gate de decision < 3b < parada < migracion (5b)."""
    assert _orden_global_ok(DEPLOY_SH.read_text(encoding="utf-8")), (
        "RC1-03/04: ORDEN GLOBAL ROTO (2c debe ir antes de 3b)")


# ===========================================================================
# RC1-04 · «UPGRADE sin almacen» se decide antes de parar
# ===========================================================================
def test_RC104_U1_upgrade_sin_almacen_sin_autorizar_para_en_2c_sin_tocar_nada(tmp_path):
    """Esperado: rc != 0 con «UPGRADE sin almacen», y NI UN fichero creado/cambiado."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=False)
    antes = _arbol(tmp_path)
    rc, out = _paso2c(env, raiz, modo="upgrade")
    assert rc != 0 and "UPGRADE sin almacen" in out, out
    assert "STOP antes de parar nada" in out, out
    assert _arbol(tmp_path) == antes


def test_RC104_U2_con_autorizacion_pasa_en_2c_y_no_crea_el_almacen(tmp_path):
    """Esperado: rc 0 (la creacion es del paso 6, no de 2c); el almacen sigue AUSENTE."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=False)
    antes = _arbol(tmp_path)
    rc, out = _paso2c(env, raiz, modo="upgrade", autorizar=1)
    assert rc == 0, out
    assert _arbol(tmp_path) == antes, "2c es SOLO LECTURA"


def test_RC104_U3_upgrade_con_almacen_valido_pasa(tmp_path):
    """Esperado: rc 0."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=True)
    rc, out = _paso2c(env, raiz, modo="upgrade")
    assert rc == 0, out


def test_RC104_U4_fresh_sin_almacen_pasa_sin_crearlo(tmp_path):
    """Esperado: rc 0 y arbol intacto (en fresh lo crea el paso 6)."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=False)
    antes = _arbol(tmp_path)
    rc, out = _paso2c(env, raiz, modo="fresh")
    assert rc == 0, out
    assert _arbol(tmp_path) == antes


def test_RC104_U5_candidata_legacy_con_decisiones_bloquea_aun_autorizado(tmp_path):
    """Esperado: rc != 0 (decisiones huerfanas) aunque se pase --autorizar-creacion-review-db;
    misma regla que el paso 6."""
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=False)
    legacy = tmp_path / "legacy-root" / "viewer" / "output" / "reviews-v3" / "review.sqlite3"
    legacy.parent.mkdir(parents=True)
    assert rs.preparar("fresh", str(legacy)).rc == 0
    import sqlite3  # noqa: PLC0415
    con = sqlite3.connect(legacy)
    con.execute("INSERT INTO human_decisions (decision_id, workspace, proposal_id, request_id, record_json, "
                "created_at) VALUES ('d','ws','p','r','{}','2026-01-01T00:00:00Z')")
    con.commit()
    con.close()
    rc, out = _paso2c(env, raiz, modo="upgrade", autorizar=1, legacy_root=tmp_path / "legacy-root")
    assert rc != 0 and "huerfanas" in out, out


@pytest.mark.parametrize("modo,autorizar,almacen", [("upgrade", 0, False), ("upgrade", 1, False),
                                                    ("upgrade", 0, True), ("fresh", 0, False)])
def test_RC104_E1_2c_y_paso_6_coinciden_en_el_veredicto_del_almacen(tmp_path, modo, autorizar, almacen):
    """Esperado: 2c rc==0 si y solo si el paso 6 REAL rc==0 (misma autoridad review_store.py)."""
    rcs = []
    for nombre, fn in (("a", _paso2c), ("b", _paso6)):
        sub = tmp_path / nombre
        sub.mkdir()
        env, raiz = plantilla_productiva_en(sub, URL, almacen=almacen)
        rcs.append(fn(env, raiz, modo=modo, autorizar=autorizar)[0] == 0)
    assert rcs[0] == rcs[1], rcs


# ===========================================================================
# Mutantes: cada uno tiene que poner ROJO su testigo
# ===========================================================================
def test_RC1_M2_2c_despues_de_3b_se_detecta_por_el_guardian_de_orden():
    """Esperado: mover el bloque 2c despues del paso 3b (el defecto RC1-03/04) pone rojo O1."""
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    bloque = _tramo(texto, MARCA_2C_INI, MARCA_2C_FIN)
    mut = texto.replace(bloque, "").replace("# --- fin del paso 3b ---", "# --- fin del paso 3b ---\n" + bloque)
    assert mut != texto and not _orden_global_ok(mut)


def test_RC1_M3_2c_sin_https_deja_pasar_la_url_ausente(tmp_path):
    """Esperado: el mutante que quita validate_https_contract de la funcion hace pasar 2c con la URL
    ausente (N1/url_ausente en rojo)."""
    val = VALIDATE_SH.read_text(encoding="utf-8")
    linea = '    validate_https_contract "${viewer_env}" "${ambiente}" || rc=1\n'
    assert val.count(linea) == 1
    mutado = tmp_path / "validate_mut.sh"
    mutado.write_text(val.replace(linea, ""), encoding="utf-8")
    sub = tmp_path / "t"
    sub.mkdir()
    env, raiz = plantilla_productiva_en(sub, URL, quitar=("S9K_PUBLIC_BASE_URL",))
    rc, out = _paso2c(env, raiz, validate=mutado)
    assert rc == 0, "el mutante deberia aceptar la URL ausente"


def test_RC1_M4_sin_la_excepcion_de_modo_2c_rechaza_un_secreto_0644(tmp_path):
    """Esperado: sin el aplazamiento del MODO del secreto, 2c bloquearia un 0644 que el paso 5b
    habria normalizado (regresion de falso STOP): P1 en rojo."""
    val = VALIDATE_SH.read_text(encoding="utf-8")
    linea = '    if [ "${S9K_VALIDACION_PREVIA:-0}" = "1" ]; then return 0; fi\n'
    assert val.count(linea) == 1
    mutado = tmp_path / "validate_mut.sh"
    mutado.write_text(val.replace(linea, ""), encoding="utf-8")
    sub = tmp_path / "t"
    sub.mkdir()
    env, raiz = plantilla_productiva_en(sub, URL)
    _secreto(sub).chmod(0o644)
    rc, out = _paso2c(env, raiz, validate=mutado)
    assert rc != 0 and "permisos inseguros" in out


def test_RC1_M5_sin_el_die_del_almacen_2c_deja_pasar_el_upgrade_sin_almacen(tmp_path):
    """Esperado: quitar la comprobacion del almacen de 2c (el defecto RC1-04) hace pasar U1 (rojo)."""
    texto = DEPLOY_SH.read_text(encoding="utf-8")
    bloque = _tramo(texto, MARCA_2C_INI, MARCA_2C_FIN)
    mut_bloque = bloque.replace('"${_rev2c_autorizar[@]}" \\\n    || die', '"${_rev2c_autorizar[@]}" \\\n    || true; : die')
    assert mut_bloque != bloque
    env, raiz = plantilla_productiva_en(tmp_path, URL, almacen=False)
    rc, out = _paso2c(env, raiz, modo="upgrade", deploy_texto=texto.replace(bloque, mut_bloque))
    assert rc == 0, "el mutante deberia dejar pasar el upgrade sin almacen"
