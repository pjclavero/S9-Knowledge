"""Handler `ingest_v3`: la ingesta V3 de verdad, dentro de la cola que YA existe.

UNA SOLA INGESTA, Y SE DEMUESTRA
--------------------------------
Este handler llama a `knowledge_v3.pipeline.ingest_cli.run_ingest`, que es
EXACTAMENTE la misma funcion que invoca `main()` del CLI. No lanza `ingest_cli`
por shell, no construye un `argparse.Namespace` y no reimplementa ni un paso de
la cadena.

El reparto queda asi, y es el que pedia el encargo:

    run_ingest()                 <- EL NUCLEO. Unico.
      ^                 ^
      |                 |
    ingest_cli.main()   este handler
    (adaptador CLI)     (adaptador cola)

`run_ingest` ya era invocable sin argparse —recibe argumentos por palabra clave
y devuelve el informe— asi que no ha hecho falta extraer nada: la convergencia
se comprueba por AST en `viewer/tests/test_panel_operations_alta_fuente.py`
(`test_no_hay_dos_ingestas`), que exige que el unico llamante del nucleo aqui
sea `run_ingest` y que en este modulo no haya `subprocess`, `os.system` ni
`ingest_cli.main`.

QUE HACE Y QUE NO
-----------------
DRY-RUN DE ESCRITURA, OBSERVACION REAL DE LECTURA (Slice 2 · Corte 5).

No escribe en el grafo y no aplica nada: `apply=False` va literal mas abajo y
es lo UNICO que gobierna la escritura (`run_ingest` pasa
`writer_driver=driver if apply else None`, de modo que con `apply=False` el
writer no recibe driver ni aunque exista la conexion). `rollback` sigue siendo
de otro corte.

SI abre driver de Neo4j, y eso es nuevo. Hasta este corte pasaba `driver=None`
LITERAL, y esa linea era el final del camino del producto: sin driver, el
snapshot del motor sale de `bridge.entities_from_catalog` --entidades
DECLARADAS en un fichero-- y ninguna de sus anclas lleva `observed=True`. El
unico productor de `observed=True` en todo el motor es
`pipeline/graph_catalog.snapshot_entities`, alcanzable SOLO con driver. La
consecuencia, medida de punta a punta: el sobre de la corrida salia con las
anclas en `observed: false` y el sellado omitia toda proyeccion con
`PROJECTION_ANCHOR_NOT_OBSERVED`. La capacidad de proyectar existia, era
correcta, y el producto no la alcanzaba.

Y la negativa a proyectar era CORRECTA, no un atajo que se pueda saltar:
`SnapshotEntity.of` DERIVA `state_hash` de `{entity_id, entity_type, version}`,
asi que el hash de un catalogo en fichero es reconstruible sin haber mirado el
grafo --un valor plausible y falso--. Copiarlo a `expected_hash` seria presumir
el estado en vez de observarlo. Por eso lo que este corte cambia NO es el
sellado: es que la corrida MIRE el grafo de verdad.

LEER NO ES ESCRIBIR, Y AQUI SE DICE POR SEPARADO
------------------------------------------------
El driver que se construye aqui se usa para UNA cosa: la consulta de solo
lectura del catalogo del workspace (`graph_catalog.catalog_rows`). La escritura
la gobierna `apply`, que sigue en `False`. Son dos decisiones distintas y se
declaran en dos sitios distintos a proposito.

FALLO CERRADO, SIN RUTA DE REPUESTO
-----------------------------------
Si la conexion no esta declarada, o el grafo no responde, el job NO se completa
en silencio con una corrida sin observar. Se emite `GRAPH_OBSERVATION_*` y el
job queda en ERROR. Degradar a `driver=None` seria exactamente la ruta de
repuesto silenciosa que este corte viene a cerrar: produciria una corrida que
parece exitosa y cuyo plan no puede proyectar nada, sin decirselo a nadie.

ERRORES: CODIGO ESTABLE, NUNCA UNA RUTA
---------------------------------------
`worker.process_one` guarda `str(exc)` como `error_message` del job. Por eso
todo lo que sale de aqui hacia arriba es un `IngestV3Error`, cuyo `str()` es
`CODIGO: frase accionable` y NADA MAS. La ruta concreta, el mensaje original y
la traza van al log del servidor (`log.exception`), que es donde tienen que
estar. Un `PipelineError` con la ruta dentro —el caso medido, `f"{path}:
fichero vacio"`— se captura y se traduce; no se deja propagar.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

# EL NUCLEO. Es el mismo simbolo que usa `ingest_cli.main()`; importarlo es lo
# que impide que existan dos ingestas.
from knowledge_v3.pipeline.ingest_cli import run_ingest

# LA FABRICA DE CONEXION DEL PRODUCTO, NO UNA SEGUNDA. `knowledge_v3.
# driver_neo4j` es el unico modulo del motor que conoce el controlador de
# Neo4j, y ya impone las reglas que este handler necesita y no va a reescribir:
# la contrasena se lee de un fichero privado (nunca de `argv`, nunca de una
# variable con el secreto dentro), no hay URI por defecto, y la fabrica no
# conecta al construirse.
from knowledge_v3.driver_neo4j import (
    DriverConfigError,
    build_driver_factory,
    resolve_config,
)

log = logging.getLogger("jobs.handlers.ingest_v3")

__all__ = ["IngestV3Error", "handle_ingest_v3", "JOB_TYPE", "CODIGOS"]

#: Tipo de job de la cola generica que atiende este handler.
JOB_TYPE = "ingest_v3"

#: Codigos que este handler puede emitir. Mismo vocabulario que el catalogo del
#: visor (`app.panel_errors.CATALOGO`): un codigo que el panel no sepa pintar
#: seria un mensaje mudo para el operador, y la suite lo comprueba cruzando las
#: dos tablas.
CODIGOS = {
    "SOURCE_PACKAGE_INVALID": "El paquete de la fuente no es valido.",
    "INGEST_FAILED": (
        "La ingesta no ha terminado correctamente. El detalle queda registrado "
        "en el servidor para quien lo administra."
    ),
    # --- observacion del grafo (Slice 2 - Corte 5) ---
    "GRAPH_OBSERVATION_UNCONFIGURED": (
        "Este despliegue no tiene declarada la conexion al grafo, asi que la "
        "ingesta no puede comprobar contra el que existe lo que va a "
        "proponer. No se ha ingerido nada. Avisa a quien administra el "
        "servicio."
    ),
    "GRAPH_OBSERVATION_UNAVAILABLE": (
        "No se ha podido consultar el grafo, asi que la ingesta no puede "
        "comprobar contra el que existe lo que va a proponer. No se ha "
        "ingerido nada; puedes volver a intentarlo cuando el grafo responda."
    ),
}


#: Codigos cuyo fallo NO puede cambiar reintentando. Una fuente invalida lo
#: seguira siendo en el segundo intento, asi que reintentarla solo retrasa el
#: ERROR que el operador esta esperando ver.
#:
#: `GRAPH_OBSERVATION_UNCONFIGURED` entra aqui por la misma razon: una conexion
#: que NADIE HA DECLARADO no aparece sola entre dos intentos. Su hermana
#: `GRAPH_OBSERVATION_UNAVAILABLE` se queda fuera a proposito --un grafo que no
#: responde ahora puede responder en el reintento--, y esa es exactamente la
#: distincion que el worker no puede hacer por su cuenta.
PERMANENTES = frozenset({
    "SOURCE_PACKAGE_INVALID",
    "GRAPH_OBSERVATION_UNCONFIGURED",
})


class IngestV3Error(RuntimeError):
    """Fallo de ingesta EXPRESADO PARA UN OPERADOR.

    `str(self)` es lo que `worker.process_one` guarda en el job y lo que el
    panel acaba ensenando. Por eso no admite detalle tecnico: no hay campo
    donde meterlo.

    `retryable` es la declaracion que `worker.process_one` consulta para decidir
    si devuelve el job a la cola. No es una politica nueva del worker: es el
    handler diciendo lo unico que el worker no puede saber.
    """

    def __init__(self, code: str):
        self.code = code
        self.message = CODIGOS[code]
        self.retryable = code not in PERMANENTES
        super().__init__(f"{code}: {self.message}")


def _ruta(valor: Any, *, campo: str) -> Path:
    if not valor:
        raise IngestV3Error("SOURCE_PACKAGE_INVALID")
    try:
        return Path(str(valor))
    except (TypeError, ValueError) as exc:
        log.error("payload invalido en %s", campo, exc_info=exc)
        raise IngestV3Error("SOURCE_PACKAGE_INVALID") from exc


def _clasificar(exc: BaseException) -> str:
    """DECLARACION o INDISPONIBILIDAD. La diferencia es el consejo que se da.

    `GRAPH_OBSERVATION_UNAVAILABLE` es REINTENTABLE y su frase dice "puedes
    volver a intentarlo cuando el grafo responda". Darsela a un defecto que no
    puede cambiar es un consejo FALSO, y ademas gasta los tres intentos del
    worker mientras la pantalla dice que el trabajo sigue en la cola.

    Dos defectos que salian mal clasificados y son PERMANENTES:

    * `ConfigurationError` -- una URI con un esquema que el controlador no
      soporta (`http://`, medido). Nadie la va a corregir entre dos intentos.
    * `AuthError` -- usuario o contrasena que el servidor rechaza. El grafo
      responde perfectamente; lo que esta mal es lo declarado.

    Todo lo demas --`ServiceUnavailable`, tiempos de espera, DNS, el
    controlador ausente-- se queda reintentable, que es lo correcto cuando no
    se puede afirmar que el defecto sea permanente.

    Se compara por CLASE, no por el texto del mensaje: un mensaje cambia entre
    versiones del controlador y un `in` sobre el texto daria falsos negativos
    silenciosos. Si `neo4j` no esta instalado no hay nada que clasificar y la
    respuesta honesta es la reintentable.
    """
    try:
        from neo4j.exceptions import AuthError, ConfigurationError
    except Exception:  # noqa: BLE001 - sin controlador no hay clases que mirar
        return "GRAPH_OBSERVATION_UNAVAILABLE"
    if isinstance(exc, (AuthError, ConfigurationError)):
        return "GRAPH_OBSERVATION_UNCONFIGURED"
    return "GRAPH_OBSERVATION_UNAVAILABLE"


def _driver_de_observacion() -> Any:
    """Abre la conexion de SOLO LECTURA con la que la corrida observa el grafo.

    FALLO CERRADO EN DOS TRAMOS, y son dos cosas distintas:

    * la conexion NO ESTA DECLARADA -> `GRAPH_OBSERVATION_UNCONFIGURED`, y es
      permanente: nadie la va a declarar entre el primer intento y el tercero.
    * la conexion esta declarada y el grafo NO RESPONDE ->
      `GRAPH_OBSERVATION_UNAVAILABLE`, y es reintentable.

    Lo que NO hay es un tercer tramo que devuelva `None` y siga adelante. Esa
    era la ruta de repuesto silenciosa: una corrida sin observar que termina
    `complete` y cuyo plan no puede proyectar ni una arista, sin que el
    operador vea nada raro.

    La credencial la resuelve `driver_neo4j`, que exige fichero privado; si el
    fichero es legible por el grupo o por otros, la excepcion que sale de ahi
    es tambien `DriverConfigError` y cae en el tramo permanente, que es lo
    correcto: unos permisos flojos no se arreglan reintentando.
    """
    try:
        config = resolve_config()
    except DriverConfigError as exc:
        log.error("conexion al grafo no declarada para la observacion: %s", exc)
        raise IngestV3Error("GRAPH_OBSERVATION_UNCONFIGURED") from exc
    try:
        driver = build_driver_factory(config)()
    except DriverConfigError as exc:
        # El secreto se resuelve al invocar la fabrica, no al construirla: un
        # fichero ausente o con permisos flojos aparece AQUI y sigue siendo un
        # defecto de declaracion, no una indisponibilidad.
        log.error("credencial del grafo inutilizable: %s", exc)
        raise IngestV3Error("GRAPH_OBSERVATION_UNCONFIGURED") from exc
    except Exception as exc:  # noqa: BLE001 - controlador ausente o caido
        log.exception("no se pudo abrir la conexion de observacion al grafo")
        raise IngestV3Error(_clasificar(exc)) from exc
    try:
        # SE COMPRUEBA ANTES DE EXTRAER. Sin esto, un grafo inalcanzable no se
        # notaria hasta la consulta del catalogo, ya gastada la extraccion
        # entera; y el fallo de ahi sale del `except` de abajo como
        # `INGEST_FAILED` (MEDIDO: `ServiceUnavailable` no esta en la lista de
        # traduccion, asi que cae en el generico). Es decir, el operador leeria
        # "la ingesta no ha terminado correctamente" cuando lo que pasa es que
        # el grafo no responde, y no sabria que reintentar sirve. Un rojo por
        # la causa equivocada.
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        log.exception("el grafo no respondio a la comprobacion de conectividad")
        try:
            driver.close()
        except Exception:  # noqa: BLE001 - cerrar no puede tapar el motivo real
            log.warning("no se pudo cerrar el driver tras el fallo", exc_info=True)
        raise IngestV3Error(_clasificar(exc)) from exc
    return driver


def _resumen(report: dict) -> dict:
    """Lo que el operador puede ver del informe. Curado, no el informe entero.

    El informe trae `run.source_path` (ruta del servidor), `procedencia_paquete`
    y los documentos completos del plan. Nada de eso se copia: este resumen se
    construye por LISTA BLANCA, de modo que un campo nuevo del informe no se
    publica solo por aparecer.
    """
    totales = report.get("totals") or {}
    corrida = report.get("run") or {}
    por_veredicto = totales.get("decisions_by_outcome") or {}
    cola = report.get("cola_de_revision")
    return {
        "episodios": totales.get("episodes"),
        "menciones": totales.get("mentions"),
        "afirmaciones": totales.get("assertions"),
        "claims": totales.get("claims"),
        "enlaces_a_entidades_existentes": totales.get("link_existing"),
        "altas_de_entidad_pendientes": totales.get("create_entity"),
        # EL VEREDICTO `REVIEW` REAL, no otra cosa que se le parece.
        #
        # Hasta el Corte 4 `en_revision` mapeaba `review_identity`, que es la
        # revision DE IDENTIDAD de una mencion: otro hecho, otro numero. El
        # operador leia «terminado correctamente · en revision: 0» con
        # `REVIEW=2` y cuatro propuestas escritas, y no abria la consola de
        # revision. El dato de identidad no se pierde: se nombra por lo que es.
        "en_revision": int(por_veredicto.get("REVIEW") or 0),
        "revision_de_identidad": totales.get("review_identity"),
        # CUANTAS PROPUESTAS REVISABLES DEJO ESTA CORRIDA. `None` es "no se
        # exporto cola", que no es lo mismo que cero.
        "propuestas_de_revision": None if cola is None else cola.get("propuestas"),
        "por_veredicto": por_veredicto,
        "operaciones_planificadas": totales.get("plan_operations"),
        # Senal, no ruta: si la cadena se paro antes de tiempo el operador tiene
        # que saberlo, pero el motivo interno se queda en el log.
        "cadena_detenida_en": corrida.get("stopped_at"),
        "formato_detectado": corrida.get("source_kind"),
        "escritura": "NO (simulacion)",
        # LAS DOS MITADES, DICHAS POR SEPARADO. Antes solo se publicaba
        # `escritura`, y el operador no tenia forma de distinguir una corrida
        # que miro el grafo de una que se lo imagino a partir de un fichero.
        # Son la diferencia entre un plan que puede proyectar y uno que no.
        "observacion": "SI (grafo, solo lectura)",
    }


def handle_ingest_v3(payload: dict, *, job_id: Optional[str] = None) -> dict:
    """Ejecuta una ingesta V3 en dry-run y devuelve el resultado, ya resumido.

    `payload` lo construye el panel al encolar, no el operador:

        source_path   ruta de la fuente resuelta por el catalogo del servidor
        profile_path  perfil del workspace
        catalog_path  catalogo de entidades (opcional)
        workspace     ambito, derivado del perfil
        source_title  nombre humano de la fuente, para el acuse del panel
    """
    payload = payload or {}
    fuente = _ruta(payload.get("source_path"), campo="source_path")
    perfil = _ruta(payload.get("profile_path"), campo="profile_path")
    catalogo_crudo = payload.get("catalog_path")
    catalogo = Path(str(catalogo_crudo)) if catalogo_crudo else None
    workspace: Optional[str] = payload.get("workspace") or None

    # FALLO CERRADO ANTES DE EMPEZAR: una fuente que no esta, o que no es un
    # fichero, es un paquete invalido. Se dice con el codigo estable; la ruta
    # que no existe se queda en el log.
    if not fuente.is_file():
        log.error("fuente ausente o no es un fichero: %s", fuente)
        raise IngestV3Error("SOURCE_PACKAGE_INVALID")
    if not perfil.is_file():
        log.error("perfil ausente o no es un fichero: %s", perfil)
        raise IngestV3Error("SOURCE_PACKAGE_INVALID")

    # LA OBSERVACION SE ABRE ANTES DE EXTRAER, Y FALLA CERRADO.
    #
    # Va aqui, despues de validar el paquete de la fuente y antes de gastar una
    # corrida: si el grafo no se puede mirar, esta ingesta no puede producir un
    # plan proyectable y no tiene sentido empezarla.
    driver_lectura = _driver_de_observacion()
    try:
        report = run_ingest(
            fuente,
            profile_path=perfil,
            catalog_path=catalogo,
            workspace=workspace,
            # DRY-RUN EXPLICITO. `apply=False` es el defecto de `run_ingest`,
            # y aun asi se escribe: el corte que active la escritura tendra que
            # cambiar esta linea, que es donde se mira.
            #
            # Y es la UNICA linea que gobierna la escritura. `run_ingest` hace
            # `writer_driver=driver if apply else None`: con `apply=False` el
            # writer no ve el driver de abajo, por mucho que la conexion exista.
            apply=False,
            # SOLO LECTURA. Este driver entra para UNA cosa --la consulta del
            # catalogo del workspace-- y es lo que pone `observed=True` en las
            # anclas del sobre. No es una autorizacion de escritura y no la
            # concede: la escritura la decide `apply`, en la linea de arriba.
            driver=driver_lectura,
            # La identidad de la corrida, tal y como la puso la cola (NO el
            # payload). Es lo que ata las propuestas exportadas a ESTE job.
            job_id=job_id or None,
        )
    except IngestV3Error:
        # YA TRADUCIDA. Si `run_ingest` deja salir un codigo de este handler
        # --hoy no lo hace, pero la rama de abajo lo convertiria en
        # `INGEST_FAILED`-- se respeta tal cual: volver a traducirlo cambiaria
        # un motivo exacto por uno generico, que es el rojo por la causa
        # equivocada del que este corte va.
        raise
    except Exception as exc:
        # TODA excepcion del nucleo se traduce. `PipelineError` en particular
        # trae la ruta del fichero dentro del mensaje (medido:
        # `f"{path}: fichero vacio; no hay fuente que ingerir"`), asi que
        # dejarla propagar la escribiria en `error_message` del job, de donde
        # el panel podria acabar sacandola.
        log.exception("ingesta fallida para %s", fuente)
        nombre = type(exc).__name__
        if nombre in {"PipelineError", "FileNotFoundError", "ValueError",
                      "UnicodeDecodeError", "JSONDecodeError"}:
            raise IngestV3Error("SOURCE_PACKAGE_INVALID") from exc
        raise IngestV3Error("INGEST_FAILED") from exc
    finally:
        # LA CONEXION SE CIERRA PASE LO QUE PASE. Un job que falla no puede
        # dejar una sesion abierta contra el grafo: el worker es un proceso
        # largo y las iria acumulando corrida a corrida.
        try:
            driver_lectura.close()
        except Exception:  # noqa: BLE001 - cerrar no puede tapar el desenlace
            log.warning("no se pudo cerrar el driver de observacion",
                        exc_info=True)

    resumen = _resumen(report)
    log.info(
        "ingesta completada: %s claims=%s assertions=%s",
        fuente, resumen.get("claims"), resumen.get("afirmaciones"),
    )
    # EL DESENLACE SE DICE ENTERO, Y CONDUCE.
    #
    # «La ingesta ha terminado correctamente» con `REVIEW=2` es cierto y
    # ENGANOSO: el operador cierra la pantalla. Cuando hay revision real, el
    # acuse lo dice en la misma frase y ofrece el enlace a SU revision — no a
    # la cola entera, sino a las propuestas de ESTA corrida.
    pendientes = resumen["en_revision"]
    propuestas = resumen["propuestas_de_revision"]
    if pendientes:
        mensaje = (
            f"La ingesta ha terminado correctamente y ha dejado {pendientes} "
            f"{'decision' if pendientes == 1 else 'decisiones'} en REVIEW. "
            "No esta todo resuelto: hay que revisarlas."
        )
    else:
        mensaje = "La ingesta ha terminado correctamente y no ha dejado nada en revision."
    cola = report.get("cola_de_revision")
    return {
        "ok": True,
        "handler": JOB_TYPE,
        "code": "INGEST_OK",
        "message": mensaje,
        "source_title": payload.get("source_title") or None,
        "resumen": resumen,
        # El enlace se construye con la identidad de ESTA corrida. Sin
        # `job_id` no se ofrece enlace filtrado: mandar al operador a la cola
        # entera diciendole que son "sus" propuestas seria otra vez lo mismo.
        "revision": None if not cola else {
            "job_id": cola.get("job_id"),
            "workspace": cola.get("workspace"),
            "propuestas": cola.get("propuestas"),
            "proposal_ids": cola.get("proposal_ids") or [],
        },
    }
