# -*- coding: utf-8 -*-
"""Microcarril de seguridad: ``next`` no puede convertirse en autoridad externa.

QUÉ SE COMPRUEBA Y POR QUÉ ASÍ
------------------------------
No basta con preguntarle a ``_safe_next()`` qué string devuelve. El defecto que
motiva este módulo existe **precisamente** porque una cadena que a nuestro código
le parece una ruta (``/\\evil.example/x``) **cambia de significado** cuando
Chrome o Firefox interpretan la cabecera ``Location``: normalizan ``\\`` a ``/``
y el destino se vuelve ``//evil.example/x``, protocolo-relativo, fuera del sitio.

Por eso aquí se mide **el efecto observable en HTTP**: la cabecera ``Location``
de la respuesta real y el valor que viaja en el formulario renderizado. La
comprobación de lo que un navegador REAL acaba haciendo con ese ``Location``
vive en ``tests/browser/test_browser_next_open_redirect.py``, que el job
«Login browser contract (Playwright)» ejecuta con chromium obligatorio.

TECHO DE ESTE MÓDULO (qué NO ve)
--------------------------------
- No ejecuta un navegador: mide la cabecera, no la navegación. La navegación es
  del módulo de browser; este archivo **no** cubre esa parte y no debe leerse
  como si la cubriera.
- No cubre otras redirecciones del producto que no pasen por ``_safe_next``. El
  test de alcance de abajo delimita exactamente cuáles son ésas.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re

import pytest

# Todos los dominios hostiles son de ejemplo (RFC 2606/6761). Ninguno existe.
HOSTIL = "evil.example"

PW = "contrasena-de-laboratorio-1234567890-ABCdef"

# ---------------------------------------------------------------------------
# La tabla. Cada entrada es (etiqueta, valor de `next`).
# ---------------------------------------------------------------------------

ACEPTAR = [
    ("raiz del producto", "/"),
    ("raiz de la consola", "/v3/review"),
    ("consola con barra final", "/v3/review/"),
    ("consola filtrada", "/v3/review?workspace=alpha&job_id=job-A"),
    ("un solo filtro", "/v3/review?workspace=alpha"),
    ("filtro con valor codificado", "/v3/review?workspace=alpha%20beta&job_id=job-A"),
    ("filtro con valor vacio", "/v3/review?workspace=alpha&job_id="),
    ("otra consola con filtros", "/panel/sources?workspace=alpha&estado=pendiente"),
    # D4: el fragmento se ACEPTA, y por eso esta aqui y no en RECHAZAR. Ver el
    # razonamiento en `app/auth/next_url.py`: rechazarlo hacia que un `next`
    # con ancla perdiese TAMBIEN los filtros, que es la regresion que el corte
    # anterior acababa de arreglar.
    ("ancla sola", "/v3/review#ficha-3"),
    ("ancla con filtros", "/v3/review?workspace=alpha&job_id=job-A#ficha-3"),
]

RECHAZAR = [
    ("absoluta https", f"https://{HOSTIL}/x"),
    ("absoluta https en mayusculas", f"HTTPS://{HOSTIL}/x"),
    ("absoluta http", f"http://{HOSTIL}/x"),
    ("protocolo-relativa", f"//{HOSTIL}/x"),
    ("tres barras", f"///{HOSTIL}/x"),
    ("cuatro barras", f"////{HOSTIL}/x"),
    ("backslash", f"/\\{HOSTIL}/x"),
    ("backslash doble", f"/\\\\{HOSTIL}/x"),
    ("backslash codificada mayus", f"/%5C{HOSTIL}/x"),
    ("backslash codificada minus", f"/%5c{HOSTIL}/x"),
    ("barras codificadas mayus", f"/%2F%2F{HOSTIL}/x"),
    ("barras codificadas minus", f"/%2f%2f{HOSTIL}/x"),
    ("espacio delante", f" //{HOSTIL}/x"),
    ("CRLF crudo", "/inicio\r\nLocation: https://" + HOSTIL),
    ("CRLF codificado", "/inicio%0d%0aLocation:%20https://" + HOSTIL),
    ("CR suelto", f"/\r//{HOSTIL}"),
    ("LF suelto", f"/\n//{HOSTIL}"),
    # Añadidas por el criterio por componentes, no por la tabla mínima:
    ("tabulador crudo", f"/\t//{HOSTIL}/x"),
    ("tabulador codificado", f"/%09//{HOSTIL}/x"),
    ("nulo codificado", f"/%00//{HOSTIL}/x"),
    ("backslash tras punto", f"/./\\{HOSTIL}/x"),
    ("doble codificacion de barra", f"/%252F%252F{HOSTIL}/x"),
    ("doble codificacion de backslash", f"/%255C{HOSTIL}/x"),
    ("scheme sin barras", f"javascript:alert(1)"),
    ("scheme de datos", "data:text/html,<script>1</script>"),
    ("relativa sin barra", f"{HOSTIL}/x"),
    ("cadena vacia", ""),
    ("solo espacios", "   "),
    ("porcentaje roto", "/v3/%zz"),
    ("subida de directorio", "/v3/../../etc/passwd"),
    # D1 y D2. MEDIDO: ninguno de estos sale del origen. Se rechazan igual
    # porque son cadenas que el navegador RESUELVE a otra cosa antes de pedir
    # nada, y aceptar lo ambiguo es justo lo que este validador dice no hacer.
    # Van en la tabla para que ese endurecimiento este probado y no solo
    # declarado.
    ("segmento punto", "/./x"),
    ("punto y barra doble", "/.//x"),
    ("punto y barra doble hostil", f"/.//{HOSTIL}/x"),
    ("barra doble interior", "/v3//review"),
    ("barra doble interior hostil", f"/v3//{HOSTIL}/x"),
    ("subida relativa", "/v3/../x"),
    # El fragmento se acepta, pero no con cualquier contenido:
    ("ancla con backslash", f"/v3/review#\\{HOSTIL}"),
    ("ancla con porcentaje roto", "/v3/review#%zz"),
]

# Un `Location` que empiece así ya no apunta a este producto: el navegador lo
# lee como autoridad. `//` y `///` porque un navegador salta TODAS las barras
# iniciales al entrar en la autoridad; `\` cruda porque ahí sí la normaliza.
_PREFIJOS_FUERA = ("//", "/\\", "\\", "http://", "https://", "HTTP", "HTTPS")


def _location_sale_del_sitio(location: str) -> bool:
    """¿Este `Location` CRUDO puede resolverse a otro origen en un navegador?

    Es la pregunta fuerte, y sólo la responde el PREFIJO. Que el dominio del
    atacante aparezca más adentro (`/v3//evil.example/x`) no saca a nadie del
    sitio: eso es otra cosa, y la mide `_location_lleva_el_valor_hostil`.
    Confundir las dos produciría un rojo que dice «redirección abierta» sobre
    un caso que no lo es, y un rojo que miente sobre su causa no vale más que
    uno sin causa.
    """
    if not location:
        return False
    return location.startswith(_PREFIJOS_FUERA)


def _location_lleva_el_valor_hostil(location: str) -> bool:
    """¿Llegó el valor del atacante hasta la cabecera, aunque no escape?

    Más débil que la anterior y aun así exigible: el destino hostil no tiene
    por qué aparecer en un `Location` bajo ninguna forma.
    """
    return bool(location) and HOSTIL in location


# ---------------------------------------------------------------------------
# Entorno
# ---------------------------------------------------------------------------

@pytest.fixture
def entorno(tmp_path):
    """Visor con auth real y base SQLite temporal. Nada persiste en el repo."""
    db = tmp_path / "auth.db"
    previo = {k: os.environ.get(k) for k in (
        "S9K_AUTH_ENABLED", "S9K_AUTH_DB_PATH", "S9K_CSRF_SECRET",
        "S9K_SESSION_SECURE", "S9K_GRAPH_PROVIDER",
    )}
    os.environ["S9K_AUTH_ENABLED"] = "true"
    os.environ["S9K_AUTH_DB_PATH"] = str(db)
    os.environ["S9K_CSRF_SECRET"] = "clave-csrf-de-laboratorio-larga-1234567890-xyz"
    os.environ["S9K_SESSION_SECURE"] = "false"
    os.environ.setdefault("S9K_GRAPH_PROVIDER", "mock")

    from app.auth.config import get_auth_settings
    from app.config import get_settings
    from app.deps import get_provider
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()

    from app.auth import db as auth_db
    from app.auth.passwords import hash_password
    auth_db.ensure_migrated(db)
    with auth_db.get_conn(db) as conn:
        auth_db.create_user(
            conn, username="lab", display_name="Lab",
            password_hash=hash_password(PW), role="viewer",
            must_change_password=False,
        )
    yield db
    for k, v in previo.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_auth_settings.cache_clear()
    get_settings.cache_clear()
    get_provider.cache_clear()


def _cliente():
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _csrf_de(texto: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]*)"', texto)
    assert m, "no se encontró csrf_token en la página de login"
    return m.group(1)


def _post_login(cliente, next_valor: str):
    """POST /login real, con su CSRF de doble envío. Devuelve la respuesta."""
    pagina = cliente.get("/login")
    return cliente.post("/login", data={
        "username": "lab", "password": PW,
        "csrf_token": _csrf_de(pagina.text), "next": next_valor,
    })


# ---------------------------------------------------------------------------
# SUPERFICIE 1 — POST /login: la cabecera Location
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,valor", RECHAZAR, ids=[e for e, _ in RECHAZAR])
def test_post_login_no_emite_location_externo(entorno, etiqueta, valor):
    c = _cliente()
    resp = _post_login(c, valor)
    location = resp.headers.get("location")
    assert resp.status_code in (302, 303), (
        f"[{etiqueta}] next={valor!r}: se esperaba una redirección y llegó "
        f"{resp.status_code}"
    )
    assert not _location_sale_del_sitio(location), (
        f"REDIRECCIÓN ABIERTA en POST /login: con next={valor!r} la cabecera "
        f"Location vale {location!r}. Ese prefijo hace que un navegador lo "
        f"resuelva contra OTRA autoridad y no contra la nuestra (salta todas "
        f"las barras iniciales al entrar en la autoridad; y una '\\\\' cruda la "
        f"normaliza a '/'). Causa: [{etiqueta}] no fue rechazada por el "
        f"validador por componentes."
    )
    assert not _location_lleva_el_valor_hostil(location), (
        f"VALOR HOSTIL EN LA CABECERA de POST /login: con next={valor!r} el "
        f"Location vale {location!r}. Esto NO es por sí solo una redirección "
        f"abierta —el prefijo sigue siendo interno—, pero el destino del "
        f"atacante no debe llegar a una cabecera de redirección bajo ninguna "
        f"forma. Causa: [{etiqueta}]."
    )
    assert location == "/", (
        f"[{etiqueta}] next={valor!r}: el destino hostil debía caer al destino "
        f"interno por defecto '/', pero el Location vale {location!r}. Una "
        f"entrada ambigua se RECHAZA, no se transforma y se acepta."
    )


@pytest.mark.parametrize("etiqueta,valor", ACEPTAR, ids=[e for e, _ in ACEPTAR])
def test_post_login_conserva_el_destino_interno(entorno, etiqueta, valor):
    c = _cliente()
    resp = _post_login(c, valor)
    location = resp.headers.get("location")
    assert location == valor, (
        f"REGRESIÓN DE ERGONOMÍA en POST /login: con next={valor!r} el Location "
        f"vale {location!r}. El destino interno legítimo —incluida su query de "
        f"filtros, que el corte anterior acaba de hacer persistente— debe "
        f"conservarse EXACTAMENTE. Causa: [{etiqueta}] endurecida de más."
    )


# ---------------------------------------------------------------------------
# SUPERFICIE 2 — GET /login: el valor que se renderiza en el formulario
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("etiqueta,valor", RECHAZAR, ids=[e for e, _ in RECHAZAR])
def test_get_login_no_reinyecta_el_destino_hostil(entorno, etiqueta, valor):
    """GET /login mete `next` en un campo oculto que vuelve al POST.

    Si el valor hostil sobrevive aquí, la defensa del POST es lo único que
    queda: el transporte no debe llevarlo siquiera.
    """
    c = _cliente()
    resp = c.get("/login", params={"next": valor})
    assert resp.status_code == 200, f"[{etiqueta}] GET /login devolvió {resp.status_code}"
    m = re.search(r'name="next" value="([^"]*)"', resp.text)
    assert m, f"[{etiqueta}] el formulario de login perdió su campo `next`"
    import html as _html
    renderizado = _html.unescape(m.group(1))
    # Comparación EXACTA contra el destino por defecto, no «ausencia del
    # dominio». Comprobar sólo la ausencia deja pasar cualquier otra cosa que
    # no sea `/`, y apoyarse en «Jinja ya escapa» es apoyarse en el escapado
    # para una propiedad que no es de escapado sino de validación. El positivo
    # de dos funciones más abajo ya comparaba exacto; esto lo iguala.
    assert renderizado == "/", (
        f"TRANSPORTE HOSTIL en GET /login: con next={valor!r} el formulario "
        f"renderiza value={renderizado!r} en vez del destino interno por "
        f"defecto '/', con lo que el valor del atacante vuelve a viajar en el "
        f"siguiente POST. Causa: [{etiqueta}]."
    )
    assert HOSTIL not in renderizado, (
        f"[{etiqueta}] el dominio externo sigue presente: {renderizado!r}"
    )


@pytest.mark.parametrize("etiqueta,valor", ACEPTAR, ids=[e for e, _ in ACEPTAR])
def test_get_login_conserva_el_destino_interno(entorno, etiqueta, valor):
    c = _cliente()
    resp = c.get("/login", params={"next": valor})
    m = re.search(r'name="next" value="([^"]*)"', resp.text)
    assert m, f"[{etiqueta}] el formulario de login perdió su campo `next`"
    import html as _html
    renderizado = _html.unescape(m.group(1))
    assert renderizado == valor, (
        f"REGRESIÓN DE ERGONOMÍA en GET /login: next={valor!r} se renderizó "
        f"como {renderizado!r}; el destino interno y sus filtros deben viajar "
        f"intactos hasta el POST. Causa: [{etiqueta}] endurecida de más."
    )


# ---------------------------------------------------------------------------
# SUPERFICIE 3 — POST /partida/select: el OTRO `_safe_next`, que también
# emite un `Location` con el valor del usuario.
# ---------------------------------------------------------------------------

def _cliente_logueado(db):
    from app.auth import db as auth_db
    from app.auth.config import get_auth_settings
    from app.auth.sessions import create_session
    with auth_db.get_conn(db) as conn:
        user = auth_db.get_user_by_username(conn, "lab")
        token, _ = create_session(conn, user)
    c = _cliente()
    c.cookies.set(get_auth_settings().S9K_SESSION_COOKIE_NAME, token)
    return c


@pytest.mark.parametrize("etiqueta,valor", RECHAZAR, ids=[e for e, _ in RECHAZAR])
def test_partida_select_no_emite_location_externo(entorno, etiqueta, valor):
    c = _cliente_logueado(entorno)
    pagina = c.get("/entities", headers={"accept": "text/html"})
    csrf = _csrf_de(pagina.text)
    # partida_id vacío = «volver a la capa juego»: no toca asignaciones ni
    # workspace, así que la prueba mide el redirect y nada más.
    resp = c.post("/partida/select", data={
        "partida_id": "", "next": valor, "csrf_token": csrf,
    })
    assert resp.status_code == 302, (
        f"[{etiqueta}] /partida/select devolvió {resp.status_code}: {resp.text[:200]}"
    )
    location = resp.headers.get("location")
    assert not _location_lleva_el_valor_hostil(location), (
        f"VALOR HOSTIL EN LA CABECERA de POST /partida/select: con "
        f"next={valor!r} el Location vale {location!r}. Causa: [{etiqueta}]."
    )
    assert not _location_sale_del_sitio(location), (
        f"REDIRECCIÓN ABIERTA en POST /partida/select: con next={valor!r} el "
        f"Location vale {location!r}, resoluble contra OTRA autoridad por un "
        f"navegador. Causa: [{etiqueta}]. Esta superficie tenía su PROPIA copia "
        f"de `_safe_next` —funcionalmente IDÉNTICA a la de auth.py, no "
        f"divergente: el riesgo era la duplicación, no una divergencia ya "
        f"consumada—. Si sólo se arregló una de las dos, la otra sigue abierta."
    )
    assert location == "/", (
        f"[{etiqueta}] next={valor!r}: se esperaba caída al destino interno "
        f"'/' y el Location vale {location!r}."
    )


@pytest.mark.parametrize("etiqueta,valor", ACEPTAR, ids=[e for e, _ in ACEPTAR])
def test_partida_select_conserva_el_destino_interno(entorno, etiqueta, valor):
    c = _cliente_logueado(entorno)
    csrf = _csrf_de(c.get("/entities", headers={"accept": "text/html"}).text)
    resp = c.post("/partida/select", data={
        "partida_id": "", "next": valor, "csrf_token": csrf,
    })
    assert resp.headers.get("location") == valor, (
        f"REGRESIÓN DE ERGONOMÍA en POST /partida/select: next={valor!r} produjo "
        f"Location {resp.headers.get('location')!r}. Causa: [{etiqueta}]."
    )


# ---------------------------------------------------------------------------
# ALCANCE — el inventario de llamantes se comprueba, no se recuerda
# ---------------------------------------------------------------------------

#: Inventario esperado, obtenido por AST (no por grep) sobre `viewer/app`.
#: (módulo, función que llama, ruta declarada por su decorador o None)
LLAMANTES_ESPERADOS = {
    ("app/routers/auth.py", "login_page"),
    ("app/routers/auth.py", "_login_error"),
    ("app/routers/auth.py", "login_submit"),
    ("app/routers/partida.py", "select_partida"),
}


def _inventario_por_ast():
    raiz = pathlib.Path(__file__).resolve().parent.parent / "app"
    definiciones = set()
    llamantes = set()
    for fichero in sorted(raiz.rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        padres = {}
        for nodo in ast.walk(arbol):
            for hijo in ast.iter_child_nodes(nodo):
                padres[hijo] = nodo
        rel = str(fichero.relative_to(raiz.parent))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == "_safe_next":
                definiciones.add(rel)
            if isinstance(nodo, ast.Call):
                f = nodo.func
                nombre = f.id if isinstance(f, ast.Name) else (
                    f.attr if isinstance(f, ast.Attribute) else None)
                if nombre != "_safe_next":
                    continue
                actual, envolvente = nodo, None
                while actual in padres:
                    actual = padres[actual]
                    if isinstance(actual, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        envolvente = actual
                        break
                llamantes.add((rel, envolvente.name if envolvente else "?"))
    return definiciones, llamantes


def test_alcance_todos_los_llamantes_estan_en_la_prueba():
    definiciones, llamantes = _inventario_por_ast()
    assert llamantes == LLAMANTES_ESPERADOS, (
        "EL ALCANCE CAMBIÓ: el inventario de llamantes de `_safe_next` obtenido "
        f"por AST es {sorted(llamantes)}, y la prueba cubre "
        f"{sorted(LLAMANTES_ESPERADOS)}. Toda superficie que decida un destino "
        "con `_safe_next` debe entrar en la tabla de aceptación/rechazo de este "
        "módulo antes de existir."
    )
    assert definiciones == {"app/routers/auth.py", "app/routers/partida.py"}, (
        f"Aparecieron definiciones de `_safe_next` no previstas: {sorted(definiciones)}"
    )


def test_todas_las_definiciones_delegan_en_la_autoridad_unica():
    """Cada `_safe_next` debe DELEGAR, no reimplementar el criterio.

    Se comprueba por AST —estructura, no texto—: el cuerpo de la función es un
    único `return ruta_interna_o_defecto(...)`. Dos copias del criterio fue
    exactamente la forma que tomó este defecto.
    """
    raiz = pathlib.Path(__file__).resolve().parent.parent / "app"
    vistas = 0
    for fichero in sorted(raiz.rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if nodo.name != "_safe_next":
                continue
            vistas += 1
            cuerpo = [s for s in nodo.body if not (
                isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str))]
            assert len(cuerpo) == 1 and isinstance(cuerpo[0], ast.Return), (
                f"{fichero.name}: `_safe_next` tiene lógica propia "
                f"({len(cuerpo)} sentencias tras el docstring). El criterio vive "
                "en app/auth/next_url.py y NO se reimplementa aquí."
            )
            llamada = cuerpo[0].value
            assert isinstance(llamada, ast.Call), f"{fichero.name}: `_safe_next` no delega"
            nombre = getattr(llamada.func, "id", getattr(llamada.func, "attr", None))
            assert nombre == "ruta_interna_o_defecto", (
                f"{fichero.name}: `_safe_next` delega en {nombre!r} en vez de en "
                "`ruta_interna_o_defecto`, la autoridad única del criterio."
            )
    assert vistas == 2, f"se esperaban 2 definiciones de `_safe_next`, vistas {vistas}"
