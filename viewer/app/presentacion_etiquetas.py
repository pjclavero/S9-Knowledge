# -*- coding: utf-8 -*-
"""RESOLVEDOR UNICO DE NOMBRES HUMANOS — CORTE 6B-1.

## LA PROPIEDAD

La identidad interna (`workspace = ws-cofradia`, `partida_id = mesa1`) sigue
siendo la que gobierna URL, API, campos ocultos y JSON: **esto no cambia, y no
es el objetivo de este corte**. Lo que cambia es que la SUPERFICIE DE OPERADOR
puede pintar, en su lugar, un nombre humano — sin derivarlo del identificador
y sin crear una segunda autoridad capaz de divergir de la primera.

## EL FALLBACK

    label explicito -> se muestra el label
    label ausente    -> se muestra el IDENTIFICADOR CANONICO
    nunca            -> se inventa un nombre a partir del identificador

Generar «Mesa1» a partir de `partida:mesa1` esta PROHIBIDO: seria la misma
falsa confirmacion que el programa lleva un mes eliminando, con otra cara.

## DONDE VIVE EL LABEL (diagnosticado antes de este corte, no rediseñado aqui)

  - **Workspace**: en `metadata.label`, dentro del `perfil-operador.json` de
    la carpeta de juego que declara ese workspace. `metadata` es el bloque que
    el propio contrato declara abierto (EXCEPCION DOCUMENTADA a
    `additionalProperties: false`), y un label ahi VALIDA: en el primer nivel
    del perfil, no.
  - **Partida**: en `metadata.label`, dentro de
    `<juego>/partidas/<p>/manifiesto-partida.json` — la MISMA exencion de
    lista blanca que ya tiene `perfil-operador.json`
    (`sources_catalog._NO_SON_FUENTES`). NO en `partida_access`: ahi el label
    seria una fila por usuario, y la deduplicacion de
    `existencia.partidas_seleccionables` se queda con la PRIMERA fila que
    llegue — una segunda autoridad que puede divergir de si misma por azar de
    ordenacion.

NO hay tabla `partidas(id, nombre)`. Seria la segunda autoridad que este corte
existe para evitar.

## LA ESCRITURA NO ENTRA AQUI (6B-2)

Nadie escribe estos ficheros desde el producto hoy: el operador los edita a
mano. Un escritor de boveda (atomicidad, concurrencia, permisos, auditoria) es
6B-2. Este modulo SOLO LEE.

## EL NEGATIVO QUE MAS IMPORTA — AMBITO, NO SOLO FORMATO

El corte #254 cerro la propiedad: todo camino que recibe una identidad del
cliente la resuelve de nuevo desde la autoridad del servidor, dentro del
AMBITO AUTORIZADO de quien pregunta. Un resolvedor de labels que conteste
"¿como se llama `ws-ajeno`?" a quien no tiene ese ambito es la MISMA fuga con
otra cara — y ademas confirma que `ws-ajeno` existe, aunque no diga su nombre.

    workspace fuera del ambito -> se devuelve el identificador, EXACTAMENTE
    la misma respuesta que "no hay label" dentro de ambito. No hay una tercera
    respuesta que distinga "no tiene label" de "no tienes acceso": esa
    distincion YA ES la fuga.

### DE DONDE SALE EL AMBITO (ronda 2 — la guarda era TAUTOLOGICA)

En la ronda 1 el ambito era un ARGUMENTO de plantilla, y casi todas las
llamadas escribian `etiqueta_workspace(workspace, [workspace])`: el ambito era
el propio workspace que se iba a pintar, asi que `workspace not in {workspace}`
NUNCA era cierto y la guarda no se ejecutaba jamas desde una pantalla. Solo
corria en tests unitarios que pasaban el ambito a mano. Una defensa que parece
proteccion y no esta en el camino es PEOR que no tenerla, porque se cuenta como
cerrada: la seguridad real descansaba en que el llamante ya hubiera filtrado,
que es exactamente el patron de autoautorizacion que #254 vino a cerrar.

Por eso, desde la ronda 2, **la plantilla no puede elegir el ambito**: el
argumento DESAPARECIO de la superficie de Jinja. Los globals son
`pass_context` y toman el ambito de la PETICION (`ambito_de_peticion`), que lo
deriva de dos autoridades de servidor que ya existian:

  * `request.state.user_partidas` — las partidas que `authz.existencia`
    declaro seleccionables para ESTE usuario (workspace incluido);
  * `authz.existencia.workspace_canonico()` — el unico workspace que este
    despliegue sabe resolver, y que cualquier usuario autenticado ya ve escrito
    en la barra de estado. Se añade solo si hay usuario (o si la autenticacion
    esta apagada, donde no hay ambitos que separar).

Sin peticion, sin usuario y sin autoridad resoluble el ambito es VACIO, y el
resolvedor devuelve identificadores: falla cerrado. Y un workspace que no es
el canonico ni el de ninguna partida del usuario —por ejemplo una fila vieja
de `partida_access` en un workspace inventado, que `/admin/partidas` sigue
pintando— NO recibe nombre: ahi la guarda si se ejecuta.

## COSTE EN DISCO — UNA LECTURA POR PETICION, NO POR CELDA

Resolver una etiqueta cuesta un `iterdir` de la raiz de bovedas mas un
`read_text` por carpeta hasta encontrar la que declara el workspace, mas el
perfil, mas el manifiesto. Sin memoria eso se paga POR CELDA: una tabla de 50
filas con 20 juegos son ~1000 lecturas por render, mas la cabecera, que sale en
todas las paginas. Por eso el resolvedor de peticion lleva un `_Lector` con
cache (`_ResolvedorDePeticion`): dentro de UNA peticion cada ruta se lee UNA
vez. La cache muere con la peticion — no hay cache de proceso — de modo que
editar un perfil a mano sigue viendose en el render siguiente, que es como el
operador usa esto hoy (6B-2 todavia no existe).

## TECHO DECLARADO — LO QUE ESTE CORTE NO CONVIERTE

  * `templates/status.html:19` (`status.workspaces | join(', ')`) — es el
    censo del PROVEEDOR de grafo, no del ambito del usuario: enumera los
    workspaces que Neo4j contiene. Convertirlo exigiria resolver etiqueta por
    workspace de una lista que el resolvedor no puede acotar al ambito (y
    varios de ellos pueden no tener bóveda). Se queda con el identificador A
    PROPOSITO: es una pantalla de diagnostico tecnico.
  * Campos `value=` de formularios, URLs, `data-*` y `tojson`: son PROTOCOLO.
    El identificador sigue intacto ahi, y el control simetrico de la suite lo
    exige.
  * Mensajes de `HTTPException.detail` distintos del de `/admin/partidas/grant`
    (cubierto en la ronda 2): no nombran workspaces ni partidas; se midio por
    AST, no "se reviso".

## UN UNICO RESOLVEDOR

Las superficies de presentacion NO implementan cada una su propia conversion
identificador -> nombre. Todas llaman a `etiqueta_workspace` /
`etiqueta_partida` (instaladas como globals de Jinja, ver
`install_label_globals`). Sesenta conversiones locales serian sesenta
autoridades; el parseo Jinja de la suite lo comprueba EN LOS DOS SENTIDOS:

  * ninguna plantilla implementa su propia conversion, y
  * ninguna plantilla SE SALTA el resolvedor pintando el identificador crudo
    en una superficie de operador (inventario de apariciones de protocolo en
    `test_corte6b1_etiquetas_presentacion`: una aparicion nueva que no este
    declarada como protocolo pone la suite roja).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, Optional, Tuple

import jinja2

from app import sources_catalog

#: Nombres de los globals de Jinja instalados por `install_label_globals`.
GLOBAL_ETIQUETA_WORKSPACE = "etiqueta_workspace"
GLOBAL_ETIQUETA_PARTIDA = "etiqueta_partida"


class _Lector:
    """Las DOS lecturas de disco del resolvedor, con cache opcional.

    Sin cache (`cachear=False`, el modo por defecto de las funciones puras)
    se comporta exactamente como antes. Con cache vive lo que vive UNA
    peticion: dentro de un render, cada ruta se lee una sola vez y la raiz de
    bovedas se recorre una sola vez por workspace preguntado. La cache NO es
    de proceso a proposito — ver «COSTE EN DISCO» arriba.

    `lecturas` y `recorridos` son contadores OBSERVABLES: la suite los usa
    para medir el coste en vez de afirmarlo.
    """

    def __init__(self, cachear: bool = False):
        self.cachear = cachear
        self.lecturas = 0
        self.recorridos = 0
        self._json: Dict[str, Optional[dict]] = {}
        self._carpetas: Dict[Tuple[str, int], Optional[Path]] = {}

    def json_objeto(self, ruta: Path) -> Optional[dict]:
        clave = str(ruta)
        if self.cachear and clave in self._json:
            return self._json[clave]
        self.lecturas += 1
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = None
        if not isinstance(datos, dict):
            datos = None
        if self.cachear:
            self._json[clave] = datos
        return datos

    def carpeta_de_juego(
        self, workspace: str, env: Optional[dict] = None
    ) -> Optional[Path]:
        clave = (workspace, id(env) if env is not None else 0)
        if self.cachear and clave in self._carpetas:
            return self._carpetas[clave]
        carpeta = self._buscar_carpeta(workspace, env)
        if self.cachear:
            self._carpetas[clave] = carpeta
        return carpeta

    def _buscar_carpeta(
        self, workspace: str, env: Optional[dict] = None
    ) -> Optional[Path]:
        raiz = sources_catalog.raiz_de_bovedas(env)
        if raiz is not None:
            self.recorridos += 1
            try:
                carpetas = sorted(p for p in raiz.iterdir() if p.is_dir())
            except OSError:
                return None
            for carpeta in carpetas:
                perfil = carpeta / sources_catalog.NOMBRE_PERFIL
                if self._workspace_de(perfil) == workspace:
                    return carpeta
            return None

        if not sources_catalog.ubicacion_declarada(env):
            # Sin boveda declarada, el perfil que hubiera bajo `examples/` es
            # material del repositorio: no declara nada, ni aqui ni en la
            # ingesta.
            return None

        plano = sources_catalog.directorio_de_fuentes(env)
        perfil = plano / sources_catalog.NOMBRE_PERFIL
        return plano if self._workspace_de(perfil) == workspace else None

    def _workspace_de(self, perfil: Path) -> str:
        """El workspace que declara `perfil`, o `""`. UNA sola autoridad.

        La regla no se reescribe aqui: es `sources_catalog.workspace_de_perfil`
        sobre el JSON que ya tenemos leido (posiblemente de cache).
        """
        try:
            return sources_catalog.workspace_de_perfil(self.json_objeto(perfil))
        except Exception:
            return ""


def _normaliza_ambito(ambito_permitido: Optional[Iterable[object]]) -> FrozenSet[str]:
    """El conjunto de workspaces que quien pregunta puede ver. Nunca None."""
    if not ambito_permitido:
        return frozenset()
    return frozenset(
        w.strip() for w in ambito_permitido if isinstance(w, str) and w.strip()
    )


def _leer_json_objeto(ruta: Path, lector: Optional[_Lector] = None) -> Optional[dict]:
    """El contenido de `ruta` como objeto JSON, o `None` si no se puede leer.

    Cualquier fallo (ausente, ilegible, JSON invalido, no es un objeto) cae en
    `None`: aqui no hay autoridad que perder por no encontrar un manifiesto,
    solo el fallback al identificador.
    """
    return (lector or _Lector()).json_objeto(ruta)


def _label_declarado(datos: dict) -> str:
    """`metadata.label` si es una cadena no vacia; si no, `""`.

    NUNCA se deriva de otro campo. Un `label` en el primer nivel del objeto
    (fuera de `metadata`) se ignora a proposito: no es donde el contrato
    declaro la excepcion de lista blanca.
    """
    metadata = datos.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    label = metadata.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else ""


def _carpeta_de_juego(
    workspace: str,
    env: Optional[dict] = None,
    lector: Optional[_Lector] = None,
) -> Optional[Path]:
    """La carpeta de boveda cuyo `perfil-operador.json` declara `workspace`.

    Reutiliza los resolvedores de rutas de `sources_catalog` (los mismos que
    alimentan el ambito real de una fuente): no re-deriva ninguna ruta, para
    no abrir una segunda lectura de "donde esta la boveda de este workspace".
    """
    return (lector or _Lector()).carpeta_de_juego(workspace, env)


def etiqueta_workspace(
    workspace: Optional[str],
    ambito_permitido: Optional[Iterable[object]],
    env: Optional[dict] = None,
    lector: Optional[_Lector] = None,
) -> str:
    """El nombre humano de `workspace`, o el propio `workspace` si no hay uno.

    Devuelve SIEMPRE el mismo identificador de entrada cuando:
      - `workspace` esta vacio o no es una cadena;
      - `workspace` NO esta en `ambito_permitido` (fuera de ambito: la misma
        respuesta que "no tiene label", nunca una tercera que confirme
        existencia);
      - no hay perfil de boveda legible para ese workspace;
      - el perfil no declara `metadata.label`.
    """
    if not isinstance(workspace, str) or not workspace.strip():
        return workspace or ""
    workspace = workspace.strip()

    if workspace not in _normaliza_ambito(ambito_permitido):
        return workspace

    carpeta = _carpeta_de_juego(workspace, env, lector)
    if carpeta is None:
        return workspace

    datos = _leer_json_objeto(carpeta / sources_catalog.NOMBRE_PERFIL, lector)
    if datos is None:
        return workspace

    return _label_declarado(datos) or workspace


def etiqueta_partida(
    workspace: Optional[str],
    partida_id: Optional[str],
    ambito_permitido: Optional[Iterable[object]],
    env: Optional[dict] = None,
    lector: Optional[_Lector] = None,
) -> str:
    """El nombre humano de `(workspace, partida_id)`, o `partida_id` si no hay.

    Mismo contrato de ambito que `etiqueta_workspace`: `workspace` fuera de
    `ambito_permitido` devuelve `partida_id` tal cual, sin distinguir "no
    tiene label" de "no tienes acceso a ese workspace".
    """
    if not isinstance(partida_id, str) or not partida_id.strip():
        return partida_id or ""
    partida_id = partida_id.strip()

    if not isinstance(workspace, str) or not workspace.strip():
        return partida_id
    workspace = workspace.strip()

    if workspace not in _normaliza_ambito(ambito_permitido):
        return partida_id

    carpeta = _carpeta_de_juego(workspace, env, lector)
    if carpeta is None:
        return partida_id

    manifiesto = (
        carpeta / "partidas" / partida_id / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA
    )
    datos = _leer_json_objeto(manifiesto, lector)
    if datos is None:
        return partida_id

    return _label_declarado(datos) or partida_id


#: Atributo de `request.state` donde vive el resolvedor de ESTA peticion.
ATRIBUTO_RESOLVEDOR = "resolvedor_etiquetas"


def ambito_de_peticion(request) -> FrozenSet[str]:
    """Los workspaces que QUIEN HACE ESTA PETICION puede ver nombrados.

    NO lo elige la plantilla (ronda 1: `[workspace]`, tautologico). Sale de
    dos autoridades de servidor que ya existian:

      1. `request.state.user_partidas` — lo que `authz.existencia` declaro
         seleccionable para este usuario. Su workspace esta ahi por
         construccion.
      2. el workspace CANONICO del despliegue, y solo si hay usuario
         autenticado (o si la autenticacion esta apagada, donde no hay ambitos
         que separar). Es el unico que este despliegue sabe resolver y el que
         cualquier usuario ya ve escrito en su barra de estado.

    Sin peticion, sin usuario y sin autoridad resoluble: conjunto VACIO, o sea
    identificadores en todas partes. Falla cerrado.
    """
    if request is None:
        return frozenset()

    permitidos = set()
    for p in getattr(getattr(request, "state", None), "user_partidas", None) or []:
        ws = getattr(p, "workspace", None)
        if not isinstance(ws, str):
            ws = p.get("workspace") if isinstance(p, dict) else None
        if isinstance(ws, str) and ws.strip():
            permitidos.add(ws.strip())

    autenticado = getattr(getattr(request, "state", None), "user", None) is not None
    if not autenticado:
        try:
            from app.auth.settings import get_auth_settings  # noqa: PLC0415

            autenticado = not get_auth_settings().S9K_AUTH_ENABLED
        except Exception:
            autenticado = False
    if autenticado:
        try:
            from app.authz import existencia  # noqa: PLC0415

            canonico = existencia.workspace_canonico()
        except Exception:
            canonico = ""
        if canonico:
            permitidos.add(canonico)

    return frozenset(permitidos)


class _ResolvedorDePeticion:
    """Las etiquetas de UNA peticion: un ambito, una cache, cero sorpresas.

    El ambito se calcula UNA vez (leerlo cuesta resolver la autoridad de
    workspace) y las lecturas de disco se memoizan en su `_Lector`. Vive y
    muere con la peticion.
    """

    def __init__(self, request):
        self.request = request
        self.lector = _Lector(cachear=True)
        self._ambito: Optional[FrozenSet[str]] = None

    @property
    def ambito(self) -> FrozenSet[str]:
        if self._ambito is None:
            self._ambito = ambito_de_peticion(self.request)
        return self._ambito

    def workspace(self, workspace: Optional[str]) -> str:
        return etiqueta_workspace(workspace, self.ambito, None, self.lector)

    def partida(self, workspace: Optional[str], partida_id: Optional[str]) -> str:
        return etiqueta_partida(workspace, partida_id, self.ambito, None, self.lector)


def resolvedor_de_peticion(request) -> _ResolvedorDePeticion:
    """El resolvedor de esta peticion, creado una sola vez y reutilizado."""
    estado = getattr(request, "state", None)
    existente = getattr(estado, ATRIBUTO_RESOLVEDOR, None)
    if isinstance(existente, _ResolvedorDePeticion):
        return existente
    resolvedor = _ResolvedorDePeticion(request)
    if estado is not None:
        try:
            setattr(estado, ATRIBUTO_RESOLVEDOR, resolvedor)
        except Exception:
            pass
    return resolvedor


@jinja2.pass_context
def _global_etiqueta_workspace(ctx, workspace: Optional[str]) -> str:
    """`{{ etiqueta_workspace(ws) }}` — SIN ambito: lo pone la peticion.

    Que la plantilla no pueda pasar el ambito es el arreglo de la ronda 2: no
    hay forma de volver a escribir la guarda tautologica desde aqui.
    """
    return resolvedor_de_peticion(ctx.get("request")).workspace(workspace)


@jinja2.pass_context
def _global_etiqueta_partida(
    ctx, workspace: Optional[str], partida_id: Optional[str]
) -> str:
    """`{{ etiqueta_partida(ws, pid) }}` — SIN ambito: lo pone la peticion."""
    return resolvedor_de_peticion(ctx.get("request")).partida(workspace, partida_id)


def install_label_globals(envs: Iterable) -> None:
    """Instala `etiqueta_workspace`/`etiqueta_partida` en cada entorno Jinja.

    Igual patron que `chassis.install_nav_globals`: cada router trae su propia
    `Jinja2Templates`, y un global puesto solo en el entorno de `main` dejaria
    a la mitad de las pantallas pintando el identificador crudo en vez de
    llamar al resolvedor unico.
    """
    for env in envs:
        env.globals[GLOBAL_ETIQUETA_WORKSPACE] = _global_etiqueta_workspace
        env.globals[GLOBAL_ETIQUETA_PARTIDA] = _global_etiqueta_partida
