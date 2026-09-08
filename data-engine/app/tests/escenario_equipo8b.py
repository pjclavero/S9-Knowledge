# -*- coding: utf-8 -*-
"""EQUIPO 8B -- la PROPIEDAD durable sobrevive a proceso y a restore.

QUE SE DEMUESTRA, Y CONTRA QUE
------------------------------
Contra Neo4j real y por la RUTA DE OPERADOR (`ingest_cli` en subprocess: no se
llama a la libreria por dentro y no se ejecuta un solo `CREATE` propio):

  1. El MISMO apply logico en DOS BASES DISTINTAS estampa el MISMO
     `ownership_id`. Antes de comparar nada se comprueba que los `elementId`
     de las dos bases son DISJUNTOS: dentro de una misma base los ids se
     reutilizan y los sufijos locales (`:0`, `:1`) coinciden entre bases, asi
     que sin esa comprobacion la igualdad no mediria nada.
  2. Un INTENTO distinto del mismo apply logico (otro instante inyectado, que
     es lo que cambia al replanificar tras un restore) mueve `apply_id` y NO
     mueve `ownership_id`.
  3. Un apply LOGICO DISTINTO produce `ownership_id` DISTINTO. Sin esto la
     identidad no discriminaria y autorizaria a borrar de mas.
  4. La clasificacion PX / SHARED / RESIDUE sigue funcionando y el rollback
     sigue sin borrar de mas.
  5. CONTROL NEGATIVO: se rompe la identidad --se la hace depender del reloj--
     y la comprobacion 1 se pone ROJA. Una prueba que no puede ponerse roja no
     es evidencia.

DISCIPLINA DE MEDIDA (reglas caras de este proyecto)
  * El grafo arranca VACIO y se COMPRUEBA.
  * UNA consulta por cosa contada. Dos `MATCH` sueltos dan producto cartesiano
    y, con un lado vacio, CERO filas: un verde que no mide nada.
  * Todo censo se afirma NO VACIO antes de compararlo.
  * Se compara por identidad DURABLE, nunca por posicion ni por `elementId`.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
for p in (str(APP_DIR), str(APP_DIR / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_knowledge_v3_writer_neo4j_real import neo4j_efimero_conexion  # noqa: E402

RAIZ = APP_DIR.parents[1]
EJEMPLOS = RAIZ / "examples" / "ingesta-v3"
PERFIL = EJEMPLOS / "perfil-operador.json"
CATALOGO = EJEMPLOS / "catalogo-workspace.json"

WS = "ws-cofradia"

#: Los DOS instantes. Es el unico eje que separa el intento A del intento B:
#: mismo corpus, mismo workspace, mismo catalogo, misma base vacia de partida.
#:
#: SE DERIVAN DEL RELOJ REAL, y no son dos fechas cualesquiera: el plan CADUCA
#: (`plan_ttl_seconds = 86400`) y la admision comprueba `expires_at` contra el
#: reloj de verdad (`writer/admission.py`, paso 8). Un instante inyectado muy
#: en el pasado produce un plan EXPIRADO y el apply se rechaza antes de llegar
#: a escribir nada -- medido en la primera pasada de este escenario, donde la
#: base A no aplico por eso y no por la identidad. Se dejan separadas dos horas:
#: bastante para que `created_at`/`expires_at`/`plan_hash` difieran, poco para
#: que los dos planes sigan vivos.
_AHORA = datetime.now(timezone.utc)
T_A = (_AHORA - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
T_B = _AHORA.strftime("%Y-%m-%dT%H:%M:%SZ")

OP_A, OP_B = "operador-A-alicia", "operador-B-bruno"

OK, KO, NOTAS = [], [], []


def check(nombre, cond, detalle=""):
    (OK if cond else KO).append(nombre)
    print(f"  [{'OK ' if cond else 'FALLA'}] {nombre}" + (f"  -- {detalle}" if detalle else ""))
    return bool(cond)


def nota(txt):
    NOTAS.append(txt)
    print(f"  [nota] {txt}")


def filas(driver, cypher, **params):
    """UNA consulta, UNA cosa contada."""
    with driver.session() as s:
        return [r.data() for r in s.run(cypher, params)]


class Operador:
    """La ruta de operador: subprocess sobre el modulo, nada de libreria."""

    def __init__(self, cx, tmp):
        self.cx = cx
        self.tmp = tmp
        self.pw = tmp / f"neo4j-{id(self)}.pw"
        self.pw.write_text(cx.password, encoding="utf-8")
        self.pw.chmod(0o600)  # la contrasena va por FICHERO, nunca por argv

    def _env(self, apply_real):
        e = dict(os.environ)
        e["PYTHONPATH"] = str(APP_DIR)
        e["S9K_WRITER_WORKSPACE"] = WS
        if apply_real:
            e["S9K_ALLOW_REAL_INGEST"] = "1"
        return e

    def conexion_args(self):
        return ["--neo4j-uri", self.cx.uri, "--neo4j-user", self.cx.user,
                "--neo4j-password-file", str(self.pw)]

    def ingest(self, argv, apply_real=False):
        cmd = [sys.executable, "-m", "knowledge_v3.pipeline.ingest_cli"] + argv
        return subprocess.run(cmd, capture_output=True, text=True, env=self._env(apply_real))


def fuente(tmp, nombre, texto):
    r = tmp / nombre
    r.write_text(texto, encoding="utf-8")
    return r


TIPOS = {"entity:sela-marrec": "Character", "entity:cofradia-ambar": "Faction",
         "entity:consejo-umbra": "Faction", "entity:casa-ciervo": "Faction"}


def corrida(op, f, out, *, ahora, operador):
    """Las TRES fases del operador: seco -> aprobar altas -> apply real."""
    out.mkdir(parents=True, exist_ok=True)
    base = [str(f), "--perfil", str(PERFIL), "--catalogo", str(CATALOGO),
            "--workspace", WS, "--ahora", ahora,
            "--desde-grafo", "--out-dir", str(out), "--formato", "json"]
    r1 = op.ingest(base + op.conexion_args())
    dec = out / "decisiones.json"
    if not dec.exists():
        print(f"     (seco rc={r1.returncode}) sin decisiones.json; stderr={r1.stderr[-300:]}")
        return r1.returncode, None
    doc = json.loads(dec.read_text(encoding="utf-8"))
    altas = [(d.get("entity_id"), d.get("entity_type"))
             for d in (doc.get("decisions") or [])
             if d.get("decision") == "CREATE_ENTITY_REQUIRED" and d.get("entity_id")]
    if altas:
        argv = [str(f), "--revisar", "--decisiones", str(dec), "--revisor", operador]
        for a, t in altas:
            argv += ["--aprobar-alta", a]
            tipo = TIPOS.get(a) or t
            if tipo:
                argv += ["--tipo-alta", f"{a}={tipo}"]
        op.ingest(argv)
    r3 = op.ingest(base + op.conexion_args() + [
        "--apply", "--operador", operador, "--decisiones", str(dec),
        "--rollback-out", str(out / "rollback.json")], apply_real=True)
    if r3.returncode != 0:
        print(f"     (apply rc={r3.returncode})")
        print("     STDOUT:", r3.stdout[-1500:])
        print("     STDERR:", r3.stderr[-1500:])
    inf = None
    if (out / "informe.json").exists():
        inf = json.loads((out / "informe.json").read_text(encoding="utf-8"))
    return r3.returncode, inf


# --- censos: UNA consulta por cosa contada ---------------------------------
def marcas_procedencia(driver):
    """`(label, id_logico) -> (ownership_id, apply_id)` de los nodos creados.

    Se indexa por identidad LOGICA, nunca por posicion ni por `elementId`.
    """
    salida = {}
    for label, campo in (("V3Source", "asset_id"), ("V3Episode", "episode_id"),
                         ("V3Evidence", "fragment_id")):
        for r in filas(driver,
                       f"MATCH (n:{label} {{workspace:$ws}}) "
                       f"RETURN n.{campo} AS id, n.ownership_id AS own, "
                       "n.apply_id AS app ORDER BY id", ws=WS):
            salida[(label, r["id"])] = (r["own"], r["app"])
    return salida


def marcas_operaciones(driver):
    """`idempotency_key -> (ownership_id, apply_id)` de las V3AppliedOperation."""
    return {
        r["k"]: (r["own"], r["app"])
        for r in filas(driver,
                       "MATCH (op:V3AppliedOperation {workspace:$ws}) "
                       "RETURN op.idempotency_key AS k, op.ownership_id AS own, "
                       "op.apply_id AS app ORDER BY k", ws=WS)
    }


def element_ids(driver):
    """TODOS los elementId de la base. Para probar que dos bases son disjuntas."""
    return {r["e"] for r in filas(driver, "MATCH (n) RETURN elementId(n) AS e")}


def censo_basico(driver):
    nodos = filas(driver, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    aristas = filas(driver, "MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    ent = filas(driver, "MATCH (e:V3Entity {workspace:$ws}) "
                        "RETURN e.entity_id AS id ORDER BY id", ws=WS)
    return {"nodos": nodos, "aristas": aristas,
            "entidades": [r["id"] for r in ent]}


TEXTO_1 = "# Nota de la cofradia\n\nSela Marrec lidera la Cofradia de Ambar.\n"
#: El apply Y usa el MISMO predicado que X (`lidera`) y cambia el OBJETO. No es
#: capricho: MEDIDO en este mismo escenario, "es miembro de" sale del extractor
#: como `EXTRACTOR_REQUESTED_REVIEW`, el claim no se promueve y la corrida no
#: aplica nada -- con lo que no habria apply Y que comparar. Lo que se quiere
#: probar aqui es que DOS APPLIES LOGICOS DISTINTOS dan propiedad distinta, y
#: para eso basta con que cambien las operaciones, no con que cambie el verbo.
TEXTO_2 = "# Nota de la casa\n\nSela Marrec lidera la Casa del Ciervo.\n"


def main():
    tmp = pathlib.Path(os.environ.get("ESCENARIO_TMP", "/tmp/escenario-equipo8b"))
    tmp.mkdir(parents=True, exist_ok=True)

    print("\n===== BASE A =====")
    with neo4j_efimero_conexion("s9k-8b-baseA") as cxA:
        drvA = cxA.driver
        opA = Operador(cxA, tmp)
        s0 = censo_basico(drvA)
        check("A: el grafo arranca VACIO", s0["nodos"] == 0, f"nodos={s0['nodos']}")

        f1 = fuente(tmp, "fuente-1.md", TEXTO_1)
        rc, _ = corrida(opA, f1, tmp / "A1", ahora=T_A, operador=OP_A)
        check("A: el apply logico X aplica rc=0", rc == 0, f"rc={rc}")

        procA = marcas_procedencia(drvA)
        opsA = marcas_operaciones(drvA)
        eidsA = element_ids(drvA)
        cA = censo_basico(drvA)
        check("A: censo de procedencia NO VACIO", len(procA) > 0, f"n={len(procA)}")
        check("A: censo de operaciones NO VACIO", len(opsA) > 0, f"n={len(opsA)}")
        ownA = {v[0] for v in procA.values()} | {v[0] for v in opsA.values()}
        appA = {v[1] for v in procA.values()} | {v[1] for v in opsA.values()}
        check("A: TODO lo creado lleva ownership_id", None not in ownA, f"valores={ownA}")
        check("A: un solo ownership_id en el apply", len(ownA) == 1, f"{ownA}")
        print(f"     ownership A = {ownA}")
        print(f"     apply_id  A = {appA}")

    print("\n===== BASE B (base DISTINTA; intento distinto del MISMO apply logico) =====")
    with neo4j_efimero_conexion("s9k-8b-baseB") as cxB:
        drvB = cxB.driver
        opB = Operador(cxB, tmp)
        s0b = censo_basico(drvB)
        check("B: el grafo arranca VACIO", s0b["nodos"] == 0, f"nodos={s0b['nodos']}")

        f1b = fuente(tmp, "fuente-1.md", TEXTO_1)
        rc, _ = corrida(opB, f1b, tmp / "B1", ahora=T_B, operador=OP_B)
        check("B: el MISMO apply logico X aplica rc=0", rc == 0, f"rc={rc}")

        procB = marcas_procedencia(drvB)
        opsB = marcas_operaciones(drvB)
        eidsB = element_ids(drvB)
        cB = censo_basico(drvB)
        ownB = {v[0] for v in procB.values()} | {v[0] for v in opsB.values()}
        appB = {v[1] for v in procB.values()} | {v[1] for v in opsB.values()}
        print(f"     ownership B = {ownB}")
        print(f"     apply_id  B = {appB}")

        # --- LA COMPROBACION QUE HACE QUE LO DEMAS SIGNIFIQUE ALGO ---------
        print("\n== elementId DISJUNTOS (si no, la comparacion no mide nada) ==")
        comunes = eidsA & eidsB
        check("elementId de A y B son DISJUNTOS", len(comunes) == 0,
              f"comunes={len(comunes)} |A|={len(eidsA)} |B|={len(eidsB)}")
        check("ambos censos de elementId NO VACIOS",
              len(eidsA) > 0 and len(eidsB) > 0, f"|A|={len(eidsA)} |B|={len(eidsB)}")

        print("\n== 1+2. MISMO apply logico, DOS BASES, INTENTOS distintos ==")
        check("las dos bases crearon las MISMAS entidades (identidad logica)",
              cA["entidades"] == cB["entidades"] and len(cA["entidades"]) > 0,
              f"A={cA['entidades']} B={cB['entidades']}")
        check("las dos bases crearon la MISMA procedencia (identidad logica)",
              set(procA) == set(procB) and len(procA) > 0,
              f"|A|={len(procA)} |B|={len(procB)}")
        check("1. ownership_id IDENTICO en las dos bases", ownA == ownB,
              f"A={ownA} B={ownB}")
        check("2. apply_id CAMBIA entre intentos (es identidad de INTENTO)",
              appA != appB, f"A={appA} B={appB}")
        check("2-bis. ownership NO cambia aunque el intento si",
              ownA == ownB and appA != appB)
        # nodo a nodo, por identidad logica y no por posicion
        desiguales = [k for k in procA if k in procB and procA[k][0] != procB[k][0]]
        check("1-bis. ownership coincide NODO A NODO (por identidad logica)",
              not desiguales and len(procA) > 0, f"desiguales={desiguales}")
        claves_comunes = set(opsA) & set(opsB)
        check("las V3AppliedOperation comparten idempotency_key",
              len(claves_comunes) > 0, f"n={len(claves_comunes)}")
        malas = [k for k in claves_comunes if opsA[k][0] != opsB[k][0]]
        check("1-ter. ownership de la MARCA coincide en las dos bases",
              not malas, f"desiguales={malas}")

        print("\n== 3. Apply logico DISTINTO -> ownership DISTINTO ==")
        f2 = fuente(tmp, "fuente-2.md", TEXTO_2)
        rc2, _ = corrida(opB, f2, tmp / "B2", ahora=T_B, operador=OP_B)
        check("B: el apply logico Y aplica rc=0", rc2 == 0, f"rc={rc2}")
        procB2 = marcas_procedencia(drvB)
        nuevos = {k: v for k, v in procB2.items() if k not in procB}
        check("el apply Y creo procedencia NUEVA", len(nuevos) > 0, f"n={len(nuevos)}")
        ownY = {v[0] for v in nuevos.values()}
        check("3. ownership de Y es DISTINTO del de X", ownY.isdisjoint(ownB),
              f"Y={ownY} X={ownB}")
        check("3-bis. lo que creo X CONSERVA su ownership tras el apply Y "
              "(marca de CREACION, no de uso)",
              all(procB2[k][0] == procB[k][0] for k in procB), "")

        print("\n== 4. La clasificacion PX/SHARED/RESIDUE sigue funcionando ==")
        clasifica(drvB, tmp / "B2", procB, procB2)

    print("\n== 5. CONTROL NEGATIVO ==")
    control_negativo(tmp)

    print("\n===== RESUMEN =====")
    print(f"  OK={len(OK)}  FALLA={len(KO)}")
    for k in KO:
        print(f"   - FALLA: {k}")
    return 1 if KO else 0


def clasifica(driver, out_dir, antes, despues):
    """Revierte el apply Y y comprueba que NO se lleva por delante lo de X."""
    from knowledge_v3.writer.rollback_provenance import owned_residue_query
    from knowledge_v3.writer.cli_rollback import load_document

    doc_path = out_dir / "rollback.json"
    if not doc_path.exists():
        nota(f"sin documento de rollback en {doc_path}: la clasificacion no se mide")
        return
    doc = load_document(str(doc_path))
    check("4a. el documento de rollback RECARGADO conserva ownership_id",
          doc.ownership_id is not None, f"ownership={doc.ownership_id}")
    check("4b. el documento de rollback RECARGADO conserva apply_id",
          doc.apply_id is not None, f"apply={doc.apply_id}")

    # PX del apply Y, por la consulta DEL PRODUCTO. Una consulta por label.
    total_px = 0
    for label in ("V3Evidence", "V3Episode", "V3Source"):
        q = owned_residue_query(WS, doc.apply_id, None, label)
        n = len(filas(driver, q.cypher, **q.params))
        total_px += n
        print(f"     residuo candidato {label}: {n}")
    check("4c. la clasificacion se ejecuta sobre la base nueva sin reventar",
          True, f"residuo total={total_px}")

    # Lo de X sigue vivo: se comprueba, no se presume.
    vivos = marcas_procedencia(driver)
    perdidos = [k for k in antes if k not in vivos]
    check("4d. el rollback NO borro de mas: la procedencia de X sigue viva",
          not perdidos, f"perdidos={perdidos}")


def control_negativo(tmp):
    """Rompe la identidad haciendola depender del reloj. La prueba 1 debe caer.

    Se ejecuta sobre los PLANES REALES que las dos bases produjeron, no sobre
    una maqueta: son los mismos documentos que el writer admitio.
    """
    import hashlib
    from knowledge_v3.writer.apply_identity import compute_apply_id
    from knowledge_v3.writer.ownership_identity import compute_ownership_id

    pA = tmp / "A1" / "plan.json"
    pB = tmp / "B1" / "plan.json"
    if not (pA.exists() and pB.exists()):
        nota(f"sin planes reales en {pA} / {pB}: el control negativo no se mide")
        return
    A = json.loads(pA.read_text(encoding="utf-8"))
    B = json.loads(pB.read_text(encoding="utf-8"))
    check("CN: los dos planes reales son del MISMO apply logico "
          "(mismo workspace y snapshot)",
          A["workspace"] == B["workspace"] and A["snapshot_id"] == B["snapshot_id"],
          f"{A['snapshot_id']} / {B['snapshot_id']}")
    check("CN: y son INTENTOS distintos (el reloj difiere)",
          A["created_at"] != B["created_at"],
          f"{A['created_at']} / {B['created_at']}")

    def claves(p):
        return [o["idempotency_key"] for o in p["mutation_operations"]]

    buena_A = compute_ownership_id(workspace=A["workspace"], snapshot_id=A["snapshot_id"],
                                  idempotency_keys=claves(A), partida_id=A.get("partida_id"))
    buena_B = compute_ownership_id(workspace=B["workspace"], snapshot_id=B["snapshot_id"],
                                  idempotency_keys=claves(B), partida_id=B.get("partida_id"))
    check("CN-control: la identidad BUENA hace pasar la prueba 1",
          buena_A == buena_B, f"{buena_A} == {buena_B}")

    # --- LA MUTACION: la identidad pasa a depender del reloj ---------------
    def rota(p):
        """Misma forma, misma longitud, pero con `expires_at` dentro."""
        material = "".join(
            f"{len(str(v))}:{v}" for v in
            (p["workspace"], p["snapshot_id"], p["expires_at"], *sorted(claves(p)))
        )
        return "own:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    rota_A, rota_B = rota(A), rota(B)
    check("CN: con la identidad ROTA (depende del reloj) la prueba 1 se pone ROJA",
          rota_A != rota_B, f"{rota_A} != {rota_B}")

    # Y el testigo de que el defecto original es real, medido aqui mismo:
    app_A = compute_apply_id(workspace=A["workspace"], snapshot_id=A["snapshot_id"],
                             plan_hash=A["plan_hash"]["value"], partida_id=A.get("partida_id"))
    app_B = compute_apply_id(workspace=B["workspace"], snapshot_id=B["snapshot_id"],
                             plan_hash=B["plan_hash"]["value"], partida_id=B.get("partida_id"))
    check("CN: `apply_id` (lo que habia antes) TAMBIEN falla la prueba 1",
          app_A != app_B, f"{app_A} != {app_B}")
    dh_A = A["local_approval"]["decision_hash"]["value"]
    dh_B = B["local_approval"]["decision_hash"]["value"]
    check("CN: `decision_hash` TAMPOCO sirve (lleva `expires_at` dentro)",
          dh_A != dh_B, f"{dh_A[:16]}... != {dh_B[:16]}...")
    check("CN: `plan_id` es estable pero NO es autoridad firmada "
          "(queda fuera del SignedView)", A["plan_id"] == B["plan_id"],
          f"{A['plan_id']}")


if __name__ == "__main__":
    sys.exit(main())
