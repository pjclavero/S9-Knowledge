# -*- coding: utf-8 -*-
"""Sonda de GENERALIZACION de la politica de factualidad.

POR QUE EXISTE
--------------
El ciclo de correccion amplio el vocabulario de `cues.py` despues de que la
puerta 6 encontrase cuatro violaciones. Dos de las frases anadidas
—«cabe suponer que», «barajan la posibilidad de que»— son **literales del
corpus de factividad**. Volver a medir el mismo corpus contesta a la pregunta
equivocada: diria si el parche tapa los casos que lo motivaron, no si el sistema
entiende la no-factividad.

Es exactamente el error que este proyecto ya pago caro con el motor v2:
predicado 0,81 con dev==test, 0,24 en real.

Esta sonda es el conjunto de control. Cada frase usa un marcador no-factivo
**que no aparece en ninguna lista de `cues.py`** y **que no esta en
`cases.json`**. Si la politica solo acierta en el corpus y falla aqui, el
arreglo fue memorizacion; si acierta en ambos, generaliza.

Las frases se escribieron leyendo las listas de `cues.py` para EVITARLAS, no
para imitarlas. La comprobacion de que ninguna cue conocida aparece en el texto
esta automatizada mas abajo: si alguien anade despues una de estas frases al
vocabulario, la sonda lo denuncia y deja de ser control.

Uso:
    PYTHONPATH=data-engine/app python3 \
      artifacts/v3-final-validation/factivity_generalization_probe.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from knowledge_v3.extraction import cues as C
from knowledge_v3.extraction.cues import analyze_raw_text

OUT = Path("artifacts/v3-final-validation/factivity-generalization-probe.json")

#: Clases que significan "esto es un hecho del mundo y se escribiria".
FACT_CLASSES = {"ASSERTED_FACT", "NEGATED_FACT"}

#: (id, texto, familia, ¿debe leerse como hecho del mundo?)
#: `False` = el sistema NO debe materializar una relacion factual.
PROBE: tuple[tuple[str, str, str, bool], ...] = (
    # --- HIPOTESIS (marcadores nuevos, ninguno en EPISTEMIC_CUES) -----------
    ("gen:hip:01", "No es descartable que Yevin Aroca guarde todavía el cetro de sal.", "HIPOTESIS", False),
    ("gen:hip:02", "Nada garantiza que la Orden del Yunque siga fiel al puerto.", "HIPOTESIS", False),
    ("gen:hip:03", "Se barrunta entre los escribas que Delia Sarn encabeza la partida.", "HIPOTESIS", False),
    ("gen:hip:04", "En el supuesto de que Marto Quiles mande la flota, el bloqueo caería solo.", "HIPOTESIS", False),
    # --- RUMOR --------------------------------------------------------------
    ("gen:rum:01", "Según se murmura en los muelles, Delia Sarn pertenece a la Liga del Cardo.", "RUMOR", False),
    ("gen:rum:02", "Voces sin nombre aseguran que el cetro de sal descansa en la Cripta Baja.", "RUMOR", False),
    ("gen:rum:03", "De boca en boca se repite que Yevin Aroca traicionó a la Liga del Cardo.", "RUMOR", False),
    ("gen:rum:04", "Trascendió, sin que nadie lo confirmara, que Marto Quiles sirve a la Casa Ondel.", "RUMOR", False),
    # --- PREGUNTA (indirecta, sin signos) -----------------------------------
    ("gen:pre:01", "Quiso saber el veedor si Delia Sarn manda de verdad en la Liga del Cardo.", "PREGUNTA", False),
    ("gen:pre:02", "Planteó la duda de si el cetro de sal salió alguna vez de la Cripta Baja.", "PREGUNTA", False),
    ("gen:pre:03", "¿Custodia Yevin Aroca el cetro de sal desde la caída del puerto?", "PREGUNTA", False),
    # --- CONDICIONAL --------------------------------------------------------
    ("gen:con:01", "Con tal de que Marto Quiles dirija la flota, el Cardo aceptará el pacto.", "CONDICIONAL", False),
    ("gen:con:02", "A condición de que Delia Sarn abandone la Liga, se levantará el destierro.", "CONDICIONAL", False),
    ("gen:con:03", "Como no sea que Yevin Aroca entregue el cetro, no habrá tregua alguna.", "CONDICIONAL", False),
    # --- CONTRAFACTUAL ------------------------------------------------------
    ("gen:cfa:01", "De no haber muerto el viejo maestre, Delia Sarn jamás habría mandado en la Liga.", "CONTRAFACTUAL", False),
    ("gen:cfa:02", "Habría bastado con que Marto Quiles firmase para que la Casa Ondel cediera el puerto.", "CONTRAFACTUAL", False),
    ("gen:cfa:03", "Otro gallo cantaría si el cetro de sal siguiera en la Cripta Baja.", "CONTRAFACTUAL", False),
    # --- DESEO --------------------------------------------------------------
    ("gen:des:01", "Ansía el veedor que Delia Sarn renuncie al mando de la Liga del Cardo.", "DESEO", False),
    ("gen:des:02", "No le importaría a Marto Quiles que la Casa Ondel perdiese el puerto.", "DESEO", False),
    # --- ORDEN --------------------------------------------------------------
    ("gen:ord:01", "Abstente de entregar el cetro de sal a nadie de la Casa Ondel.", "ORDEN", False),
    ("gen:ord:02", "Guárdate muy bien de jurar lealtad a la Liga del Cardo.", "ORDEN", False),
    ("gen:ord:03", "Cúmplase la sentencia: que Yevin Aroca devuelva el cetro a la Cripta Baja.", "ORDEN", False),
    # --- FALSEDAD ATRIBUIDA -------------------------------------------------
    ("gen:fal:01", "Quedó desmentido en el consejo que Delia Sarn mandara en la Liga del Cardo.", "FALSEDAD_ATRIBUIDA", False),
    ("gen:fal:02", "El heraldo atribuyó sin fundamento a Marto Quiles el mando de la flota.", "FALSEDAD_ATRIBUIDA", False),
    # --- FICCION DENTRO DE FICCION ------------------------------------------
    ("gen:fic:01", "En el entremés que representaron los cómicos, Yevin Aroca robaba el cetro de sal.", "FICCION_EN_FICCION", False),
    ("gen:fic:02", "El romance de ciego hace a Delia Sarn señora de la Cripta Baja.", "FICCION_EN_FICCION", False),
    # --- CONTROLES POSITIVOS: SI son hechos y deben leerse como tales -------
    ("gen:pos:01", "Yevin Aroca custodia el cetro de sal en la Cripta Baja.", "HECHO_AFIRMADO", True),
    ("gen:pos:02", "Delia Sarn encabeza la Liga del Cardo desde la caída del puerto.", "HECHO_AFIRMADO", True),
    ("gen:pos:03", "Marto Quiles no pertenece a la Casa Ondel.", "NEGACION_FACTUAL", True),
    ("gen:pos:04", "El cetro de sal nunca salió de la Cripta Baja.", "NEGACION_FACTUAL", True),
)


def known_cue_phrases() -> list[str]:
    """Todo el vocabulario literal que `cues.py` conoce hoy."""
    out: list[str] = []
    for name in dir(C):
        value = getattr(C, name)
        if not isinstance(value, tuple) or not value:
            continue
        for item in value:
            if isinstance(item, tuple) and item and isinstance(item[0], str):
                out.append(item[0])
            elif isinstance(item, str):
                out.append(item)
    return [p for p in out if " " in p or len(p) > 4]


def main() -> None:
    vocab = known_cue_phrases()
    rows = []
    contaminated = []
    for case_id, text, family, is_fact in PROBE:
        low = text.lower()
        hits = sorted({p for p in vocab if p in low})
        if hits and not is_fact:
            # La frase usa una cue conocida: ha dejado de ser control ciego.
            contaminated.append({"case_id": case_id, "cues": hits})
        verdict = analyze_raw_text(text)
        fact = verdict.factivity
        read_as_fact = fact.factivity_class.value in FACT_CLASSES
        rows.append(
            {
                "case_id": case_id,
                "family": family,
                "text": text,
                "should_be_world_fact": is_fact,
                "factivity_class": fact.factivity_class.value,
                "policy_action": fact.action.value,
                "read_as_world_fact": read_as_fact,
                "correct": read_as_fact == is_fact,
                "known_cues_in_text": hits,
            }
        )

    non_factive = [r for r in rows if not r["should_be_world_fact"]]
    controls = [r for r in rows if r["should_be_world_fact"]]
    leaks = [r for r in non_factive if r["read_as_world_fact"]]
    missed = [r for r in controls if not r["read_as_world_fact"]]

    report = {
        "probe": "factivity-generalization",
        "purpose": (
            "conjunto de control con marcadores no-factivos AUSENTES de cues.py y "
            "de cases.json: distingue generalizacion de memorizacion del parche"
        ),
        "generated_by": "opus-fase3",
        "totals": {
            "cases": len(rows),
            "non_factive": len(non_factive),
            "controls": len(controls),
            "non_factive_read_as_fact": len(leaks),
            "controls_missed": len(missed),
            "non_factive_accuracy": round(
                1 - len(leaks) / len(non_factive), 4
            ) if non_factive else None,
            "control_accuracy": round(
                1 - len(missed) / len(controls), 4
            ) if controls else None,
        },
        "contaminated_cases": contaminated,
        "leaks": [
            {"case_id": r["case_id"], "family": r["family"],
             "class": r["factivity_class"], "text": r["text"]}
            for r in leaks
        ],
        "missed_controls": [
            {"case_id": r["case_id"], "class": r["factivity_class"], "text": r["text"]}
            for r in missed
        ],
        "by_family": {
            fam: dict(Counter(r["factivity_class"] for r in rows if r["family"] == fam))
            for fam in sorted({r["family"] for r in rows})
        },
        "rows": rows,
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )

    t = report["totals"]
    print(f"casos={t['cases']}  no-factivos={t['non_factive']}  controles={t['controls']}")
    print(f"FUGAS (no-factivo leido como hecho): {t['non_factive_read_as_fact']}/{t['non_factive']}"
          f"  -> acierto no-factivo {t['non_factive_accuracy']}")
    print(f"CONTROLES fallados: {t['controls_missed']}/{t['controls']}"
          f"  -> acierto control {t['control_accuracy']}")
    if contaminated:
        print(f"AVISO: {len(contaminated)} frases usan cues ya conocidas; dejan de ser control ciego")
        for c in contaminated:
            print("   ", c["case_id"], c["cues"])
    for leak in report["leaks"]:
        print(f"  FUGA {leak['case_id']:14} {leak['family']:20} {leak['class']:16} {leak['text'][:70]}")
    print(f"escrito {OUT}")


if __name__ == "__main__":
    main()
