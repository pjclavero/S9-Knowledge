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
DRY-RUN. No escribe en el grafo, no abre driver de Neo4j y no aplica nada:
`apply` y `rollback` son cortes posteriores del Slice 2 y este handler no los
toca. Lo que produce es el informe de la corrida, resumido.

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
}


#: Codigos cuyo fallo NO puede cambiar reintentando. Una fuente invalida lo
#: seguira siendo en el segundo intento, asi que reintentarla solo retrasa el
#: ERROR que el operador esta esperando ver.
PERMANENTES = frozenset({"SOURCE_PACKAGE_INVALID"})


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


def _resumen(report: dict) -> dict:
    """Lo que el operador puede ver del informe. Curado, no el informe entero.

    El informe trae `run.source_path` (ruta del servidor), `procedencia_paquete`
    y los documentos completos del plan. Nada de eso se copia: este resumen se
    construye por LISTA BLANCA, de modo que un campo nuevo del informe no se
    publica solo por aparecer.
    """
    totales = report.get("totals") or {}
    corrida = report.get("run") or {}
    return {
        "episodios": totales.get("episodes"),
        "menciones": totales.get("mentions"),
        "afirmaciones": totales.get("assertions"),
        "claims": totales.get("claims"),
        "enlaces_a_entidades_existentes": totales.get("link_existing"),
        "altas_de_entidad_pendientes": totales.get("create_entity"),
        "en_revision": totales.get("review_identity"),
        "por_veredicto": totales.get("decisions_by_outcome") or {},
        "operaciones_planificadas": totales.get("plan_operations"),
        # Senal, no ruta: si la cadena se paro antes de tiempo el operador tiene
        # que saberlo, pero el motivo interno se queda en el log.
        "cadena_detenida_en": corrida.get("stopped_at"),
        "formato_detectado": corrida.get("source_kind"),
        "escritura": "NO (simulacion)",
    }


def handle_ingest_v3(payload: dict) -> dict:
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

    try:
        report = run_ingest(
            fuente,
            profile_path=perfil,
            catalog_path=catalogo,
            workspace=workspace,
            # DRY-RUN EXPLICITO. `apply=False` es el defecto de `run_ingest`,
            # y aun asi se escribe: el corte que active la escritura tendra que
            # cambiar esta linea, que es donde se mira.
            apply=False,
            driver=None,
        )
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

    resumen = _resumen(report)
    log.info(
        "ingesta completada: %s claims=%s assertions=%s",
        fuente, resumen.get("claims"), resumen.get("afirmaciones"),
    )
    return {
        "ok": True,
        "handler": JOB_TYPE,
        "code": "INGEST_OK",
        "message": "La ingesta ha terminado correctamente.",
        "source_title": payload.get("source_title") or None,
        "resumen": resumen,
    }
