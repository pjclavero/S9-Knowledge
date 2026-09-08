# -*- coding: utf-8 -*-
"""INTEGRACION CARRIL 7 -- el escenario de la tanda 6 SIN EL RODEO.

Identico al de la tanda 6 salvo en la fuente de la partida A, que usa la frase
ORIGINAL ("lidera la Cofradia de Ambar") en vez del patron de rodeo. Se deja en
el repo porque el resultado MEDIDO importa: NO llega a `apply`, y la causa no es
el determinante. Ver `artifacts/carril7-integracion/`.

De la tanda 6:

No es una prueba mas: es el GUION que el integrador ejecuta para demostrar que
los tres carriles (6A ruta canonica, 6B clasificacion del rollback, 6C sesion
de partida) componen UN producto y no tres parches que solo funcionan por
separado.

    workspace W
      capa juego (lore)          -> entidades COMPARTIDAS
      partida A - sesion 3       -> conocimiento propio de A
      partida B - sesion 7       -> REUTILIZA la Entity compartida + lo suyo
      -> apply repetido -> NOOP
      -> rollback B -> A intacta, compartido intacto, RESIDUE vacio
      -> rollback A -> S0

Todo pasa por `python -m knowledge_v3.pipeline.ingest_cli` y por
`knowledge_v3.writer.cli_rollback`: NO se llama a la libreria por dentro y NO
se ejecuta un solo `CREATE` propio. El esquema lo instala el producto
(`bootstrap_writer_schema`, dentro de la fixture efimera).

DISCIPLINA DE MEDIDA
  * El grafo arranca VACIO y se COMPRUEBA.
  * UNA consulta por cosa contada; cada censo se afirma NO VACIO antes de
    compararlo. Dos `MATCH` sueltos dan producto cartesiano y, con un lado
    vacio, CERO filas: un verde que no mide nada.
  * Se SIGUEN LOS VALORES. Sesiones 3 y 7, operadores distintos: ningun valor
    por defecto puede coincidir con los dos.
  * `elementId` NUNCA es identidad durable.
  * Las propiedades no se ADIVINAN: se introspeccionan y se imprimen.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

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
AHORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PARTIDA_A, SESION_A, OP_A = "partida:A", 3, "operador-A-alicia"
PARTIDA_B, SESION_B, OP_B = "partida:B", 7, "operador-B-bruno"
OP_LORE = "operador-lore-lucia"

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
        self.pw = tmp / "neo4j.pw"
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
        r = subprocess.run(cmd, capture_output=True, text=True, env=self._env(apply_real))
        return r

    def rollback(self, argv):
        cmd = [sys.executable, "-m", "knowledge_v3.writer.cli_rollback"] + argv
        r = subprocess.run(cmd, capture_output=True, text=True, env=self._env(True))
        return r


def fuente(tmp, nombre, texto):
    r = tmp / nombre
    r.write_text(texto, encoding="utf-8")
    return r


def corrida(op, f, out, *, partida=None, sesion=None, operador, tipos_alta):
    """Las TRES fases del operador: seco -> aprobar altas -> apply real.

    Devuelve `(rc_apply, informe)`. `tipos_alta` es `{entity_id: TIPO}`: en un
    grafo nuevo el resolutor no puede inferir el tipo y el mando falla cerrado
    en vez de descartar el alta en silencio.
    """
    out.mkdir(parents=True, exist_ok=True)
    ambito = []
    if partida:
        ambito = ["--partida", partida, "--sesion", str(sesion)]

    # 1. SECO con grafo: produce decisiones.json
    # `--catalogo` NO es opcional aunque haya `--desde-grafo`, y el motivo esta
    # MEDIDO: el extractor determinista no tiene reconocedor de entidades
    # propio, su vocabulario sale del glosario (alias del perfil + nombres del
    # catalogo). Con el grafo VACIO, `--desde-grafo` no aporta vocabulario
    # ninguno, todas las menciones salen `entity:prov:*` y el apply muere con
    # rc=3 ("altas sin aprobacion humana"). Las dos fuentes responden a
    # preguntas distintas: el catalogo dice COMO SE LLAMAN las cosas, el grafo
    # dice CUALES YA ESTAN.
    base = [str(f), "--perfil", str(PERFIL), "--catalogo", str(CATALOGO),
            "--workspace", WS, "--ahora", AHORA,
            "--desde-grafo", "--out-dir", str(out), "--formato", "json"] + ambito
    r1 = op.ingest(base + op.conexion_args())
    dec = out / "decisiones.json"
    if not dec.exists():
        print(f"     (seco rc={r1.returncode}) sin decisiones.json")
        print("     stderr:", r1.stderr[-400:])
        return r1.returncode, None

    # 2. REVISION: aprobar las altas (firma humana), con su tipo declarado
    doc = json.loads(dec.read_text(encoding="utf-8"))
    # El documento trae `decisions`, y el alta es la que pide CREATE. NO se
    # filtran los `entity:prov:*`: son exactamente las altas que hay que
    # aprobar. El tipo se declara con `--tipo-alta` cuando el resolutor no
    # pudo inferirlo (el caso tipico en un grafo nuevo), porque sin tipo la
    # creacion no se puede construir y el mando falla cerrado.
    altas = [(d.get("entity_id"), d.get("entity_type"))
             for d in (doc.get("decisions") or [])
             if d.get("decision") == "CREATE_ENTITY_REQUIRED" and d.get("entity_id")]
    print(f"     altas a aprobar: {altas}")
    if altas:
        argv = [str(f), "--revisar", "--decisiones", str(dec), "--revisor", operador]
        for a, t in altas:
            argv += ["--aprobar-alta", a]
            tipo = tipos_alta.get(a) or t
            if tipo:
                argv += ["--tipo-alta", f"{a}={tipo}"]
        r2 = op.ingest(argv)
        if r2.returncode != 0:
            print(f"     (revision rc={r2.returncode}) {r2.stdout[-300:]} {r2.stderr[-300:]}")

    # 3. APPLY real
    r3 = op.ingest(base + op.conexion_args() + [
        "--apply", "--operador", operador, "--decisiones", str(dec),
        "--rollback-out", str(out / "rollback.json")], apply_real=True)
    inf = None
    if (out / "informe.json").exists():
        inf = json.loads((out / "informe.json").read_text(encoding="utf-8"))
    if r3.returncode != 0:
        print(f"     (apply rc={r3.returncode}) stderr: {r3.stderr[-300:]}")
    return r3.returncode, inf


def censo(driver):
    """El estado durable, por identidad logica. NUNCA por elementId."""
    ent = filas(driver, "MATCH (e:V3Entity {workspace:$ws}) "
                        "RETURN e.entity_id AS id, e.partida_id AS p ORDER BY id, p", ws=WS)
    ase = filas(driver, "MATCH (a:V3Assertion {workspace:$ws}) "
                        "RETURN a.assertion_id AS id, a.partida_id AS p ORDER BY id, p", ws=WS)
    nodos = filas(driver, "MATCH (n) RETURN count(n) AS c")[0]["c"]
    aristas = filas(driver, "MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    return {"entidades": ent, "aserciones": ase, "nodos": nodos, "aristas": aristas}


def main():
    tmp = pathlib.Path(os.environ.get("ESCENARIO_TMP", "/tmp/escenario-carril7"))
    tmp.mkdir(parents=True, exist_ok=True)

    with neo4j_efimero_conexion("s9k-carril7") as cx:
        driver = cx.driver
        op = Operador(cx, tmp)

        print("\n== S0: el grafo arranca VACIO (se comprueba, no se presume) ==")
        s0 = censo(driver)
        check("S0 sin nodos", s0["nodos"] == 0, f"nodos={s0['nodos']}")
        check("S0 sin aristas", s0["aristas"] == 0, f"aristas={s0['aristas']}")

        f_lore = fuente(tmp, "lore.md",
                        "# Lore de la cofradia\n\n"
                        "Sela Marrec es miembro de la Cofradia de Ambar.\n")
        # MEDIDO, y por eso las frases son estas: el extractor determinista no
        # tiene reconocedor de entidades propio. Con "Sela Marrec lidera la
        # Cofradia de Ambar" el SUJETO enlaza con la entidad compartida
        # (`LINK_EXISTING`) pero el OBJETO sale `CREATE_PROVISIONAL`, el claim
        # se va a `REVIEW` con `no_promovible_por: ["object_entity_id"]` y la
        # corrida no aplica nada. No es cosa de estos tres carriles --y NO se
        # arregla aqui--: se usa el patron que si resuelve, que es el mismo que
        # 6C dejo probado.
        f_a = fuente(tmp, "A-s3.md",
                     "# Partida A, sesion 3\n\n"
                     "Sela Marrec lidera la Cofradia de Ambar.\n")
        f_b = fuente(tmp, "B-s7.md",
                     "# Partida B, sesion 7\n\n"
                     "Sela Marrec es miembro del Consejo de Umbra.\n")

        TIPOS = {"entity:sela-marrec": "Character", "entity:cofradia-ambar": "Faction",
                 "entity:consejo-umbra": "Faction"}

        print("\n== CAPA JUEGO (lore): entidades COMPARTIDAS ==")
        rc_l, inf_l = corrida(op, f_lore, tmp / "lore", operador=OP_LORE, tipos_alta=TIPOS)
        check("lore aplica rc=0", rc_l == 0, f"rc={rc_l}")
        c_lore = censo(driver)
        check("lore creo entidades", len(c_lore["entidades"]) > 0,
              f"{[(e['id'], e['p']) for e in c_lore['entidades']]}")
        compartidas = {e["id"] for e in c_lore["entidades"] if e["p"] is None}
        check("las entidades del lore son de CAPA JUEGO (partida_id NULL)",
              bool(compartidas), f"compartidas={sorted(compartidas)}")

        print("\n== PARTIDA A - sesion 3 ==")
        rc_a, inf_a = corrida(op, f_a, tmp / "A", partida=PARTIDA_A, sesion=SESION_A,
                              operador=OP_A, tipos_alta=TIPOS)
        check("A aplica rc=0", rc_a == 0, f"rc={rc_a}")
        c_a = censo(driver)

        print("\n== PARTIDA B - sesion 7 (debe REUTILIZAR la Entity compartida) ==")
        rc_b, inf_b = corrida(op, f_b, tmp / "B", partida=PARTIDA_B, sesion=SESION_B,
                              operador=OP_B, tipos_alta=TIPOS)
        check("B aplica rc=0", rc_b == 0, f"rc={rc_b}")
        c_b = censo(driver)

        ids_ent = [e["id"] for e in c_b["entidades"]]
        check("(workspace, entity_id) sigue siendo UNICO tras las dos partidas",
              len(ids_ent) == len(set(ids_ent)), f"{sorted(set(ids_ent))}")
        # REUTILIZAR = la compartida sigue siendo UNA, no aparece un gemelo de
        # otro ambito. Que B traiga ademas entidad propia es lo esperado: lo
        # que se afirma es que no DUPLICO la compartida.
        check("B REUTILIZO la Entity compartida (no la duplico)",
              compartidas.issubset(set(ids_ent)),
              f"entidades={sorted(set(ids_ent))} compartidas={sorted(compartidas)}")
        dup = [e for e in c_b["entidades"] if e["id"] in compartidas and e["p"] is not None]
        check("la Entity compartida NO tiene copia con ambito de partida",
              not dup, f"copias={dup}")

        # ---- LA TABLA DE SEGUIMIENTO DE LOS SEIS VALORES -------------------
        print("\n== SEGUIMIENTO DE LOS SEIS VALORES: entrada -> Neo4j ==")

        print("  -- propiedades REALES (introspeccion, no adivinanza) --")
        for lbl in ("V3Assertion", "V3AppliedOperation", "V3Entity", "V3Evidence"):
            pr = filas(driver, f"MATCH (n:{lbl}) WITH keys(n) AS k LIMIT 1 RETURN k AS props")
            print(f"     {lbl}: {pr[0]['props'] if pr else '(sin nodos)'}")

        for et, partida, sesion, oper in (("A", PARTIDA_A, SESION_A, OP_A),
                                          ("B", PARTIDA_B, SESION_B, OP_B)):
            rows = filas(driver,
                         "MATCH (a:V3Assertion {workspace:$ws, partida_id:$p}) "
                         "RETURN a.known_from_session AS s, count(*) AS c", ws=WS, p=partida)
            if check(f"{et}: censo de aserciones de la partida NO VACIO", bool(rows),
                     f"filas={len(rows)}"):
                ses = sorted({r["s"] for r in rows})
                tot = sum(r["c"] for r in rows)
                check(f"{et}: partida_id={partida} llego a Neo4j", tot > 0, f"aserciones={tot}")
                check(f"{et}: known_from_session={sesion} llego (y SOLO ese)",
                      ses == [sesion], f"en Neo4j={ses}")
                # operator en la AUDITORIA de la propia asercion
                ops = filas(driver,
                            "MATCH (a:V3Assertion {workspace:$ws, partida_id:$p}) "
                            "RETURN DISTINCT a.written_by_operator AS op", ws=WS, p=partida)
                vistos = sorted({r["op"] for r in ops if r["op"]})
                check(f"{et}: operator={oper} en la AUDITORIA", vistos == [oper], f"{vistos}")

        tipos = filas(driver, "MATCH (e:V3Entity {workspace:$ws}) "
                              "RETURN e.entity_id AS id, e.entity_type AS t ORDER BY id", ws=WS)
        check("entity_type llego a Neo4j", bool(tipos) and all(r["t"] for r in tipos),
              f"{[(r['id'], r['t']) for r in tipos]}")

        sup = filas(driver, "MATCH (a:V3Assertion {workspace:$ws})-[:SUPPORTED_BY]->(f:V3Evidence) "
                            "RETURN count(DISTINCT f) AS frag, count(*) AS enlaces", ws=WS)
        check("evidence realmente ENLAZADA (SUPPORTED_BY)", bool(sup) and sup[0]["enlaces"] > 0,
              f"{sup[0] if sup else '?'}")

        for et, inf in (("lore", inf_l), ("A", inf_a), ("B", inf_b)):
            ident = (inf or {}).get("apply_identity") or {}
            print(f"     {et}: apply_id={ident.get('apply_id')} plan_id={ident.get('plan_id')} "
                  f"reloj_fijado={ident.get('reloj_fijado')} carencia={ident.get('carencia')}")

        aid = filas(driver, "MATCH (o:V3AppliedOperation {workspace:$ws}) "
                            "WHERE o.apply_id IS NOT NULL "
                            "RETURN DISTINCT o.apply_id AS k ORDER BY k", ws=WS)
        check("apply_id estampado en V3AppliedOperation", bool(aid), f"distintos={len(aid)}")

        # ---- APPLY REPETIDO -> NOOP ---------------------------------------
        print("\n== APPLY REPETIDO -> NOOP legitimo, rc=0 ==")
        antes = censo(driver)
        rc_r, inf_r = corrida(op, f_b, tmp / "B-repeat", partida=PARTIDA_B, sesion=SESION_B,
                              operador=OP_B, tipos_alta=TIPOS)
        despues = censo(driver)
        check("apply repetido rc=0", rc_r == 0, f"rc={rc_r}")
        check("apply repetido NO cambia el censo durable",
              antes["entidades"] == despues["entidades"] and antes["aserciones"] == despues["aserciones"],
              f"nodos {antes['nodos']}->{despues['nodos']}")
        wr = (inf_r or {}).get("write") or {}
        print(f"     outcome={wr.get('outcome')} aplicadas={wr.get('applied_operations')} "
              f"noop={wr.get('noop_operations')} codes={wr.get('codes')}")

        # ---- ROLLBACK DE B -------------------------------------------------
        print("\n== ROLLBACK DE B ==")
        docB = tmp / "B" / "rollback.json"
        estado_pre_rb = censo(driver)
        if not docB.exists():
            nota(f"no hay documento de rollback de B en {docB}: el ciclo no se puede medir")
        else:
            audit = tmp / "auditoria-rollback.jsonl"
            r = op.rollback([str(docB), "--workspace", WS, "--operator", OP_B,
                             "--audit-log", str(audit), "--execute",
                             "--doc-out", str(tmp / "B" / "rollback-ejecutado.json")]
                            + op.conexion_args())
            print(f"     rc={r.returncode}")
            acta = None
            for linea in (r.stdout or "").splitlines():
                linea = linea.strip()
                if linea.startswith("{"):
                    try:
                        acta = json.loads(linea)
                    except Exception:
                        pass
            if acta is None:
                print("     stdout:", (r.stdout or "")[-700:])
                print("     stderr:", (r.stderr or "")[-400:])
                nota("el acta del rollback de B no se pudo leer como JSON")
            else:
                # Los contadores viven en `hechos` (ver `cli_rollback`), no en
                # la raiz del acta. Se buscan en los dos sitios para no medir
                # un `None` y llamarlo verde.
                h = acta.get("hechos") if isinstance(acta.get("hechos"), dict) else acta
                print(f"     acta: outcome={acta.get('outcome')} code={acta.get('code')}")
                print(f"     hechos: " + ", ".join(
                    f"{k}={h.get(k)}" for k in
                    ("clean", "deleted_anything", "deleted_nodes", "deleted_relationships",
                     "deleted_marks", "residues", "retained", "observations",
                     "unrecoverable", "executed", "purges")))
                check("rollback B: limpio (clean=true)", h.get("clean") is True,
                      str(h.get("clean")))
                # RESIDUE == vacio es LA definicion de rollback limpio (6B).
                check("rollback B: RESIDUE vacio", h.get("residues") == 0,
                      f"residues={h.get('residues')}")
                check("rollback B: nada irrecuperable", h.get("unrecoverable") == 0,
                      f"unrecoverable={h.get('unrecoverable')}")
                acta_h = h

            post = censo(driver)
            # A INTACTA: por identidad durable, no por posicion ni por conteo
            a_pre = sorted([e for e in estado_pre_rb["aserciones"] if e["p"] == PARTIDA_A],
                           key=lambda d: (d["id"] or "", d["p"] or ""))
            a_post = sorted([e for e in post["aserciones"] if e["p"] == PARTIDA_A],
                            key=lambda d: (d["id"] or "", d["p"] or ""))
            check("rollback B: A INTACTA (identidad durable)", a_pre == a_post,
                  f"pre={len(a_pre)} post={len(a_post)}")
            comp_post = {e["id"] for e in post["entidades"] if e["p"] is None}
            check("rollback B: lo COMPARTIDO intacto", comp_post == compartidas,
                  f"{sorted(comp_post)} vs {sorted(compartidas)}")
            b_post = [e for e in post["aserciones"] if e["p"] == PARTIDA_B]
            check("rollback B: B desaparece", not b_post, f"quedan={len(b_post)}")

            # deleted_anything COINCIDE con los hechos
            borro_de_verdad = (estado_pre_rb["nodos"] != post["nodos"])
            if acta is not None:
                check("deleted_anything COINCIDE con los hechos",
                      bool(acta_h.get("deleted_anything")) == borro_de_verdad,
                      f"acta={acta_h.get('deleted_anything')} hechos={borro_de_verdad} "
                      f"(nodos {estado_pre_rb['nodos']}->{post['nodos']})")

        # ---- ROLLBACK DE A -> S0 ------------------------------------------
        print("\n== ROLLBACK DE A ==")
        docA = tmp / "A" / "rollback.json"
        if not docA.exists():
            nota(f"no hay documento de rollback de A en {docA}")
        else:
            r = op.rollback([str(docA), "--workspace", WS, "--operator", OP_A,
                             "--audit-log", str(tmp / "auditoria-rollback.jsonl"), "--execute"]
                            + op.conexion_args())
            print(f"     rc={r.returncode}")
            post_a = censo(driver)
            a_rest = [e for e in post_a["aserciones"] if e["p"] == PARTIDA_A]
            check("rollback A: A desaparece", not a_rest, f"quedan={len(a_rest)}")
            comp_fin = {e["id"] for e in post_a["entidades"] if e["p"] is None}
            check("rollback A: lo COMPARTIDO del lore sigue intacto",
                  comp_fin == compartidas, f"{sorted(comp_fin)}")
            print(f"     censo final: nodos={post_a['nodos']} aristas={post_a['aristas']}")

        print("\n== RESULTADO ==")
        print(f"  OK={len(OK)}  FALLA={len(KO)}  NOTAS={len(NOTAS)}")
        if KO:
            print("  FALLOS:")
            for k in KO:
                print(f"    - {k}")
    return 1 if KO else 0


if __name__ == "__main__":
    sys.exit(main())
