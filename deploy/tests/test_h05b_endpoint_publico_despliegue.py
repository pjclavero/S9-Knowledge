# -*- coding: utf-8 -*-
"""H-05 corte B, lado DESPLIEGUE: la instalación valida la URL pública con la
MISMA interpretación que el visor (contrato §19 y §6).

`viewer/app/public_endpoint.py` es la única interpretación de
`S9K_PUBLIC_BASE_URL`. El visor la usa al arrancar (aborta); el despliegue la
carga por ruta (corre fuera del venv) antes de declarar la instalación completa:

  * `preflight_https.verificar` (paso 16b) y `preflight_setup_admin` (gate A)
    devuelven un hallazgo con el CÓDIGO ESTABLE del visor;
  * `validate_deploy.sh::validate_https_contract` (paso 6, antes de instalar)
    BLOQUEA en production con el placeholder / comodín / URL malformada.

TECHO: el esquema https, el certificado y el destino TLS siguen en
`preflight_https` (urlsplit propio, sólo para abrir el socket); lo que decide
si la URL es UTILIZABLE por el visor no se copia aquí.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = REPO / "deploy" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import preflight_https as ph  # noqa: E402
import preflight_setup_admin as ps  # noqa: E402

VALIDATE_SH = _SCRIPTS / "validate_deploy.sh"
PLANTILLA = REPO / "deploy" / "config" / "viewer.env.example"

CASOS = [
    ("https://cambiar.por.el.nombre.real", "PUBLIC_URL_PLACEHOLDER"),
    ("http://cambiar.por.el.nombre.real:8080", "PUBLIC_URL_PLACEHOLDER"),
    ("https://*.example.com", "PUBLIC_URL_WILDCARD"),
    ("https://", "PUBLIC_URL_NO_HOSTNAME"),
    ("https://public..example", "PUBLIC_URL_INVALID_HOSTNAME"),
    ("https://pub lic.example", "PUBLIC_URL_MALFORMED"),
    ("https://user:pw@public.example", "PUBLIC_URL_MALFORMED"),
]


def _viewer_pe():
    """La interpretacion del visor, cargada POR RUTA (en una corrida combinada
    `import app` puede resolver al paquete de data-engine)."""
    assert ph.RUTA_PUBLIC_ENDPOINT == REPO / "viewer" / "app" / "public_endpoint.py"
    assert ph.RUTA_PUBLIC_ENDPOINT.is_file()
    return ph._cargar_public_endpoint()


@pytest.mark.parametrize("url,codigo", CASOS)
def test_el_preflight_devuelve_el_codigo_del_visor(url, codigo):
    h = ph.comprobar_endpoint_publico(url)
    assert h is not None and h.causa == codigo, h
    # y es la MISMA causa que aborta el arranque del visor
    with pytest.raises(_viewer_pe().PublicEndpointError) as e:
        _viewer_pe().interpretar_url_publica(url)
    assert e.value.code == h.causa


def test_el_preflight_no_se_queja_de_una_url_valida():
    for url in ("https://knowledge.example.net", "https://public.example:8443/"):
        assert ph.comprobar_endpoint_publico(url) is None, url


def test_verificar_con_placeholder_es_instalacion_no_completa_y_no_sondea():
    h = ph.verificar(ph.Entrada(url="https://cambiar.por.el.nombre.real",
                                session_secure=True, timeout=0.2))
    assert [x.causa for x in h] == ["PUBLIC_URL_PLACEHOLDER"], h
    assert ph.codigo_de_salida(h) == 1


def test_gate_a_de_setup_admin_con_placeholder_no_sondea():
    hallazgos, rec = ps.verificar_gate_a(ps.Entrada(
        url="https://cambiar.por.el.nombre.real", session_secure=True,
        credenciales=ps.Credenciales("-", ""), modo="gate-a", timeout=0.2))
    assert "PUBLIC_URL_PLACEHOLDER" in [h.causa for h in hallazgos], hallazgos
    assert rec.get_formulario is None


def _validar(tmp_path, url, ambiente="production"):
    env = tmp_path / "viewer.env"
    env.write_text("S9K_PUBLIC_BASE_URL=%s\nS9K_SESSION_SECURE=true\n" % url, encoding="utf-8")
    r = subprocess.run(
        ["bash", "-c", 'source "$1"; validate_https_contract "$2" "$3"',
         "_", str(VALIDATE_SH), str(env), ambiente],
        capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("url,codigo", [c for c in CASOS if " " not in c[0] and "@" not in c[0]])
def test_validate_https_contract_bloquea_en_production(tmp_path, url, codigo):
    rc, salida = _validar(tmp_path, url)
    assert rc != 0, salida
    assert codigo in salida, salida
    assert "URL_PUBLICA_NO_UTILIZABLE" in salida, salida


def test_validate_https_contract_con_la_plantilla_literal_bloquea(tmp_path):
    """La plantilla de despliegue, tal cual, NO es una instalación completa."""
    linea = next(l for l in PLANTILLA.read_text(encoding="utf-8").splitlines()
                 if l.startswith("S9K_PUBLIC_BASE_URL="))
    rc, salida = _validar(tmp_path, linea.split("=", 1)[1])
    assert rc != 0 and "PUBLIC_URL_PLACEHOLDER" in salida, salida


def test_validate_https_contract_control_positivo_url_real_pasa(tmp_path):
    rc, salida = _validar(tmp_path, "https://knowledge.example.net")
    assert rc == 0, salida
    assert "NO_UTILIZABLE" not in salida


def test_validate_https_contract_en_lab_avisa_no_bloquea(tmp_path):
    rc, salida = _validar(tmp_path, "https://cambiar.por.el.nombre.real", ambiente="lab")
    assert rc == 0 and "AVISO(lab)" in salida, salida


def test_el_cli_solo_endpoint_publico_no_abre_sockets(tmp_path):
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "preflight_https.py"),
         "--solo-endpoint-publico", "--url", "https://knowledge.example.net"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "preflight_https.py"),
         "--solo-endpoint-publico", "--url", "https://cambiar.por.el.nombre.real"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "PUBLIC_URL_PLACEHOLDER" in r.stdout
