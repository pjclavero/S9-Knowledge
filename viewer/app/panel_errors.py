"""Errores del camino de operador: CODIGO ESTABLE + FRASE ACCIONABLE.

POR QUE EXISTE ESTE MODULO
--------------------------
El reconocimiento del Slice 2 encontro dos fugas reales en el repo, que es
PUBLICO y que ya tuvo un incidente por topologia interna:

  * `ReviewError(f"paquete corrupto: {path}")` propagado tal cual como
    `detail=str(exc)` -> la ruta del servidor acaba en el navegador;
  * `f"{type(exc).__name__}: {exc}"` en el CLI -> lo mismo por otra puerta.

Y la correccion que ya aplicaban los paneles —emitir solo
`type(exc).__name__`— no filtra nada pero tampoco DICE nada: `KeyError` no le
sirve a un operador para decidir que hacer.

LA FORMA EXIGIDA, y la unica que este modulo sabe producir:

    SOURCE_PACKAGE_INVALID
    "El paquete de la fuente no es valido."

Dos mitades con dos destinatarios distintos:

  * el CODIGO es estable y es API: no cambia al reescribir el mensaje, se puede
    buscar en la documentacion y se puede correlacionar con el log del
    servidor;
  * la FRASE es para una persona, esta en castellano y dice que hacer.

LO QUE NUNCA SALE DE AQUI HACIA EL CLIENTE
------------------------------------------
Rutas, nombres de maquina, trazas, `str(exc)` y el nombre de la clase de la
excepcion. Todo eso va al LOG DEL SERVIDOR mediante `registrar`, que es la
unica funcion que toca el detalle tecnico. La separacion no es una convencion
que haya que recordar: `OperatorError` **no tiene** ningun campo que pueda
transportar el detalle tecnico hasta la plantilla.

ALCANCE, dicho explicitamente
-----------------------------
Esto se aplica al CAMINO NUEVO del Corte 1 (alta de fuente y su ejecucion). No
es un bloque de seguridad general ni reescribe los errores del resto del visor:
es la higiene de una superficie nueva que va a ensenar errores a usuarios.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("panel.operator")

__all__ = [
    "OperatorError",
    "CATALOGO",
    "de_codigo",
    "registrar",
    "codigos_conocidos",
    "CARENCIAS",
    "carencia",
]


@dataclass(frozen=True)
class OperatorError(Exception):
    """Lo que el operador puede ver, y NADA MAS.

    No hay campo `detail`, `path`, `exception` ni `traceback`, a proposito: si
    no existe el sitio donde meter la ruta del servidor, nadie la mete "solo
    esta vez". El detalle tecnico viaja por `registrar`, hacia el log.
    """

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - representacion trivial
        return f"{self.code}: {self.message}"


#: Catalogo cerrado. Un codigo que no este aqui no se puede emitir.
#:
#: Las frases estan escritas para alguien que NO conoce las tripas: no nombran
#: `plan_id`, ni `workspace`, ni rutas, ni mandos de backend. Esa es la
#: definicion de USABLE que rige el Slice 2.
CATALOGO: dict[str, str] = {
    # --- eleccion de fuente ---
    "SOURCE_NOT_SELECTED":
        "No has elegido ninguna fuente. Selecciona una de la lista y vuelve a "
        "solicitar la ingesta.",
    "SOURCE_UNKNOWN":
        "La fuente elegida ya no esta disponible. Vuelve a cargar la pantalla "
        "y eligela de la lista actualizada.",
    "SOURCE_PACKAGE_INVALID":
        "El paquete de la fuente no es valido.",
    "SOURCE_CATALOG_UNAVAILABLE":
        "No se puede consultar el catalogo de fuentes en este despliegue. "
        "Avisa a quien administra el servicio.",
    "PARTIDA_SIN_SESION_DECLARADA":
        "Esta fuente pertenece a una partida, y para ingerir material de una "
        "partida hay que declarar en que sesion se revelo. La carpeta no puede "
        "decirlo por ti: dar por supuesta una revelacion seria conceder a los "
        "personajes un conocimiento que nadie declaro.",
    # --- cola de trabajos ---
    "QUEUE_UNAVAILABLE":
        "La cola de trabajos no esta disponible en este despliegue, asi que la "
        "ingesta no se ha solicitado. Avisa a quien administra el servicio.",
    "INGEST_REQUEST_FAILED":
        "No se ha podido registrar la solicitud de ingesta. No se ha empezado "
        "nada; puedes volver a intentarlo.",
    # --- sellado y aplicacion del plan revisado (Slice 2 - Apply) ---
    "REVIEW_STORE_UNAVAILABLE":
        "No se puede consultar la cola de revision en este despliegue, asi que "
        "no se sabe que hay aprobado. No se ha aplicado nada. Avisa a quien "
        "administra el servicio.",
    "NO_APPROVED_PROPOSALS":
        "No hay ninguna propuesta aprobada en esta ingesta, asi que no hay nada "
        "que preparar. Aprueba primero en la pantalla de revision.",
    "NO_APPLICABLE_PROPOSALS":
        "Ninguna de las propuestas aprobadas se puede llevar al conocimiento tal "
        "como esta. No se ha preparado nada; el detalle de cada una aparece en "
        "esta misma pantalla.",
    "SEAL_CONFLICT":
        "Las decisiones han cambiado mientras se preparaba lo aprobado, asi que "
        "no se ha preparado nada. Vuelve a cargar la pantalla e intentalo otra vez.",
    "PLAN_NOT_SEALED":
        "No hay nada preparado para esta ingesta. Prepara primero lo aprobado.",
    "PLAN_ALREADY_APPLIED":
        "Lo aprobado de esta ingesta ya se anadio al conocimiento. No se ha "
        "vuelto a anadir: no se duplica nada.",
    "PLAN_APPLY_IN_FLIGHT":
        "Se empezo a anadir lo aprobado y no consta como termino, asi que no se "
        "reintenta solo: hacerlo podria duplicar conocimiento. Avisa a quien "
        "administra el servicio para que compruebe que quedo escrito.",
    "AUDIT_CHAIN_BROKEN":
        "El registro de auditoria de esta revision no verifica, asi que no se "
        "ha preparado nada. Avisa a quien administra el servicio.",
    # NO SE FABRICA LA CAUSA. Al estado `superseded` se llega por TRES caminos
    # (`_supersede_sealed` desde una decision de OTRA corrida del workspace,
    # un resellado de la misma corrida, y un APPLY FALLIDO) y la frase anterior
    # --«Una decision cambio despues de preparar lo aprobado»-- solo describia
    # el primero. En el tercero ocultaba que lo que fallo fue la ESCRITURA.
    #
    # Cuando el almacen SI distingue el camino (el plan lleva notas de apply),
    # se publica `PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO`, que es el codigo de
    # abajo. Cuando no, la UI se limita a lo que el dato contiene.
    "PLAN_SUPERSEDED":
        "El plan ya no es aplicable, asi que no se ha aplicado nada. Es "
        "necesario volver a preparar lo aprobado de esta ingesta.",
    # SI SE CONOCE LA CAUSA CONCRETA, SE PUBLICA. Esta fila quedo `superseded`
    # porque un intento de aplicar FALLO --lo dicen sus notas de apply, que
    # solo escribe `finish_apply`--, no porque nadie cambiara de opinion.
    "PLAN_SUPERSEDED_TRAS_APPLY_FALLIDO":
        "El intento anterior de anadir lo aprobado al conocimiento no salio "
        "bien y no se escribio nada, asi que lo preparado dejo de valer. No es "
        "que haya cambiado ninguna decision. Vuelve a preparar lo aprobado; si "
        "vuelve a fallar, avisa a quien administra el servicio.",
    "APPLY_NOT_ENABLED":
        "Este despliegue no tiene habilitada la escritura en el conocimiento, "
        "asi que no se ha aplicado nada. No es cosa tuya: avisa a quien "
        "administra el servicio.",
    "GRAPH_UNAVAILABLE":
        "No se puede alcanzar el conocimiento en este despliegue, asi que no se "
        "ha aplicado nada. Avisa a quien administra el servicio.",
    # EL MOTIVO, CUANDO EL MOTOR LO DA. El rechazo del writer trae codigos
    # (`EXEC_*`) que dicen exactamente que falta; hasta ahora se quedaban en
    # `log.error` y el operador solo podia reintentar en bucle hasta que
    # alguien mirase el log por SSH. Los que cambian LA DECISION de quien lee
    # --si reintentar sirve o no-- tienen frase propia.
    "APPLY_REJECTED":
        "Lo preparado no se ha podido anadir al conocimiento y no se ha escrito "
        "nada. El motivo queda registrado en el servidor para quien lo administra.",
    # MEDIDO, Y POR ESO NO PROMETE: `EXEC_SCHEMA_CONSTRAINTS_MISSING` lo emite
    # `writer._schema_incompleto` TANTO cuando faltan restricciones COMO cuando
    # `SHOW CONSTRAINTS` no se pudo ejecutar (grafo inalcanzable). El codigo no
    # distingue los dos casos, asi que la frase tampoco los distingue: decir
    # "reintentar no sirve" seria fabricar una certeza que el dato no contiene,
    # que es justo el defecto que este corte cierra en `PLAN_SUPERSEDED`.
    "APPLY_REJECTED_ESQUEMA":
        "No se ha podido dar por buena la preparacion del grafo del "
        "conocimiento --o le faltan las restricciones que esta escritura "
        "exige, o no se han podido comprobar--, asi que no se ha escrito nada. "
        "Esto no se arregla reintentando sin mas: avisa a quien administra el "
        "servicio.",
    "APPLY_REJECTED_SESION":
        "Esta corrida es de una partida y no consta declarada la sesion en la "
        "que se revela, asi que no se ha escrito nada. REINTENTAR NO VA A "
        "CAMBIARLO mientras falte esa declaracion: avisa a quien administra el "
        "servicio.",
    "APPLY_REJECTED_GRAFO":
        "No se ha podido hablar con el conocimiento mientras se anadia lo "
        "preparado, asi que no se ha escrito nada. Puedes volver a intentarlo "
        "mas tarde; si sigue fallando, avisa a quien administra el servicio.",
    "APPLY_FAILED":
        "La operacion no ha terminado correctamente. El detalle queda registrado "
        "en el servidor para quien lo administra.",
    # PARCIAL, y se dice. Lo aprobado SI se escribio, asi que decir "no se ha
    # anadido nada" seria falso; y algo de lo que se declaro NO llego a
    # materializarse, asi que decir "ya forma parte del conocimiento" tambien.
    # Se cuenta lo uno y lo otro, y se ofrece terminarlo.
    "APPLY_INCOMPLETE":
        "Lo aprobado se ha escrito, pero algo de lo que iba con ello no ha "
        "llegado a quedar registrado, asi que todavia no esta completo. No "
        "hace falta volver a prepararlo: vuelve a anadirlo y se terminara lo "
        "que falta. El detalle queda registrado en el servidor para quien lo "
        "administra.",
    # --- ejecucion (las produce el worker, las pinta el panel) ---
    "INGEST_FAILED":
        "La ingesta no ha terminado correctamente. El detalle queda registrado "
        "en el servidor para quien lo administra.",
    # --- observacion del grafo (Slice 2 - Corte 5) ---
    #
    # Las dos dicen lo MISMO que se ha perdido --la ingesta no ha podido
    # comprobar contra el grafo lo que iba a proponer-- y se diferencian en lo
    # unico que le sirve a quien las lee: si tiene sentido reintentar.
    "GRAPH_OBSERVATION_UNCONFIGURED":
        "Este despliegue no tiene declarada la conexion al grafo, asi que la "
        "ingesta no puede comprobar contra el que existe lo que va a proponer. "
        "No se ha ingerido nada. Avisa a quien administra el servicio.",
    "GRAPH_OBSERVATION_UNAVAILABLE":
        "No se ha podido consultar el grafo, asi que la ingesta no puede "
        "comprobar contra el que existe lo que va a proponer. No se ha "
        "ingerido nada; puedes volver a intentarlo cuando el grafo responda.",
}


#: LO QUE LA CORRIDA NO PUDO HACER, DICHO PARA UNA PERSONA.
#:
#: El motor ya declaraba estas carencias (`ingest_report._carencias`) y su
#: propio CLI las imprime bajo «## CARENCIAS declaradas · No se rellena con
#: ceros que parezcan datos». El producto no las consumia: la pantalla ensenaba
#: `menciones: 0` y `cadena detenida en: engine` sin decir por que.
#:
#: Aqui NO se traduce el `detail` del motor --lleva `run.stop_reason` e
#: identificadores del grafo dentro--, se traduce el CODIGO. Un codigo que no
#: este aqui NO se descarta: la pantalla lo nombra tal cual, porque tirar una
#: carencia a la basura es exactamente el silencio que este apartado cierra.
CARENCIAS = {
    "SIN_GLOSARIO":
        "No habia ni una entrada de glosario para esta fuente, y sin glosario "
        "el extractor no puede reconocer ningun nombre.",
    "SIN_MENCIONES":
        "La fuente se leyo entera, pero ningun nombre del texto figura en el "
        "glosario: no se reconocio ni una sola mencion.",
    "SIN_CLAIMS":
        "Se reconocieron menciones, pero no se pudo emitir ninguna relacion "
        "entre ellas.",
    "CADENA_DETENIDA":
        "El proceso se paro antes de llegar al final, asi que lo que ves esta "
        "incompleto. El punto exacto y su motivo quedan registrados en el "
        "servidor para quien lo administra.",
    "SIN_PLAN":
        "No se llego a preparar ningun cambio sobre el conocimiento.",
    "PLAN_NO_APROBADO":
        "Se preparo un conjunto de cambios, pero el propio motor no lo aprobo: "
        "no hay nada de esta corrida que se pueda anadir.",
    "PLAN_REVISION_SIN_OPERACIONES":
        "Hay decisiones pendientes de revisar, pero el plan de revision no "
        "lleva ninguna operacion asociada.",
}


def carencia(code: str) -> str:
    """La frase de una carencia. Un codigo desconocido SE NOMBRA, no se calla.

    Devolver "" o saltarse la fila convertiria una carencia declarada por el
    motor en una ausencia invisible, que es el defecto que este apartado cierra.
    """
    conocida = CARENCIAS.get(code)
    if conocida:
        return conocida
    return (
        "El motor declaro una carencia que esta pantalla todavia no sabe "
        f"explicar ({code}). Avisa a quien administra el servicio."
    )


def codigos_conocidos() -> frozenset:
    """Los codigos que se pueden emitir. Util para probar por enumeracion."""
    return frozenset(CATALOGO)


def de_codigo(code: str) -> OperatorError:
    """Construye el error a partir del codigo. FALLA RUIDOSAMENTE si no existe.

    Un codigo inventado no se degrada a "mensaje generico": eso convertiria una
    errata en un mensaje mudo en produccion. Se levanta `KeyError` y lo ve la
    suite.
    """
    return OperatorError(code=code, message=CATALOGO[code])


def registrar(code: str, exc: Optional[BaseException] = None, **contexto) -> None:
    """Deja el DETALLE TECNICO en el log del servidor, nunca en la respuesta.

    Aqui si van la ruta concreta, la traza y el mensaje de la excepcion: este
    es el lado del servidor. `exc_info=True` hace que el logging emita la traza
    completa, que es justo lo que el cliente no puede ver.
    """
    log.error(
        "operador: %s | contexto=%s",
        code,
        {k: str(v) for k, v in contexto.items()},
        exc_info=exc if exc is not None else False,
    )
