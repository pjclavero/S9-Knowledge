#!/usr/bin/env python3
"""
check_docs_consistency.py — valida que la documentación no contradiga el estado
real del proyecto.

Direccion de autoridad: GIT + CODIGO + CI + EVIDENCIA OPERATIVA -> YAML -> DOCS.
Nunca al reves. `docs/project-status.yaml` es la fuente de verdad PARA LOS
DOCUMENTOS, pero el propio YAML se comprueba contra Git (punto 0): si el YAML y
los documentos mienten de forma COHERENTE ENTRE SI, el gate se pone rojo igual.

Este script comprueba:

  0. Que `development.main_commit` y `development.latest_merged_pr` coincidan
     con el repositorio REAL (`origin/main`, o `main` si no hay remoto).

     Por que existe el punto 0: el punto 3 (abajo) solo mide coherencia
     INTERNA. En la calibracion del 2026-08-11 se sustituyo `main_commit` por
     `1111111…` y `latest_merged_pr` por `#4242`, se propago la mentira a los
     cinco documentos, y el gate contesto "DOCUMENTACION COHERENTE": describia
     con total consistencia un repositorio que no existe. Mientras tanto el
     YAML entregado declaraba `28320bd`/#157 con `origin/main` en `e9c66dc`/#158
     y el gate estaba en verde.

  1. Que la documentación clave no contenga afirmaciones OBSOLETAS conocidas
     (Basic Auth como acceso vigente, login pendiente, visor no desplegado,
     numero de tests fijo, RC1/RC5 desplegadas, timer de 5 minutos activo,
     auth DB dentro de la release, v0.2.6-B1 como estado vigente, etc.).
  2. Que el documento canónico (docs/archivados/02-current-state.md) mencione el tag y el
     commit de produccion declarados en project-status.yaml.
  3. Que el bloque `development` no se contradiga con la documentacion:
     - el SHA que los documentos atribuyan a `main` debe ser el de
       `development.main_commit`;
     - el numero de PR que se cite como el ultimo mergeado debe ser
       `development.latest_merged_pr`;
     - ningun documento puede describir como pendiente un programa que
       `development` declara cerrado (lista `doc_forbids` de cada programa).

  Por que existe el punto 3: hasta el 2026-08-09 este script daba "COHERENTE"
  mientras el README anunciaba un `main` de tres dias atras, el ROADMAP decia
  que M5b no se habia empezado —estaba cerrado— y `main_commit` seguia
  apuntando a un commit viejo. Solo se validaba `production`, asi que el
  bloque que mas se mueve era justo el que nadie comprobaba: un verde que no
  comprobaba lo que fallaba.

Los bloques históricos marcados explícitamente se ignoran: una sección cuyo
encabezado contiene "HISTORICO"/"HISTÓRICO"/"DEPRECADO" (o una línea con el
marcador `<!-- consistency:ignore -->`) no se analiza. Esto evita falsos
positivos porque una frase obsoleta aparezca dentro de una nota histórica.

LIMITES CONOCIDOS. Se escriben para que nadie los descubra creyendo que
estaban cubiertos — un gate del que se supone de mas es peor que uno modesto:

  - NO detecta contradicciones DOCUMENTO contra DOCUMENTO. Si dos ficheros se
    contradicen entre si y ninguno choca con el YAML, con Git ni con la lista
    de frases obsoletas, esto no lo ve.
  - NO verifica que las CIFRAS de tests sean ciertas: haria falta ejecutar la
    suite, y este script no la ejecuta. Solo exige que una medicion que ya no
    corresponde a `main` este marcada `stale` y que caduque.
  - La deteccion del SHA de `main` EN PROSA depende de una redaccion concreta
    ("`main`, commit `abc1234`"). "La punta de `main` apunta hoy a `abc1234`"
    no se detecta. Es deliberado: un patron amplio enrojeceria sobre frases
    correctas como "el commit 47bc314 ya NO es main". La via dura —el punto 0,
    que compara el YAML con Git— cubre el caso igualmente.
  - Solo mira los ficheros de DOCS. Un documento nuevo no se vigila hasta que
    se anade a esa lista.

Salida: rc 0 si coherente; rc 1 si hay contradicciones (las lista).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
STATUS_YAML = REPO / "docs" / "project-status.yaml"

# Documentos que deben mantenerse coherentes con el estado real.
DOCS = [
    "README.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "viewer/README.md",
    "docs/archivados/02-current-state.md",
]

HISTORIC_HEADING = re.compile(r"^#{1,6}\s.*(HIST[OÓ]RICO|DEPRECAD|DEPRECATED)", re.IGNORECASE)
ANY_HEADING = re.compile(r"^#{1,6}\s")
IGNORE_MARK = "<!-- consistency:ignore -->"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# Patrones obsoletos: (id, regex_positiva, regex_de_excepcion_o_None).
# Se marca la línea si la positiva coincide y la de excepción NO (las negaciones
# como "sin basic auth", "basic auth retirada", "RC5 no desplegada" evitan el
# falso positivo). Todo sobre texto SIN acentos.
# Stems de negación (sin límites de palabra: "retirad" debe casar "retirada").
NEG_AUTH = re.compile(r"(\bsin\b|retirad|elimin|ya no|historic|deprecad|\bpropia\b|propio del)", re.IGNORECASE)
OBSOLETE = [
    ("basic-auth-vigente",
     re.compile(r"basic auth", re.IGNORECASE),
     NEG_AUTH),
    ("login-pendiente",
     re.compile(r"login (propio )?(pendiente|no implementado|sin implementar)", re.IGNORECASE),
     None),
    ("sin-login",
     re.compile(r"\b(solo basic auth|visor sin login|sin login propio)\b", re.IGNORECASE),
     re.compile(r"\bretirad|ya no\b", re.IGNORECASE)),
    ("visor-no-desplegado",
     re.compile(r"visor (web )?no desplegado|visor prototipo|solo mock", re.IGNORECASE),
     None),
    ("tests-fijos",
     re.compile(r"\b(220|249)\s*/?\s*(220|249)?\s*tests\b|\b(220|249) (tests|recopilad)", re.IGNORECASE),
     None),
    ("estado-v026b1",
     re.compile(r"v0\.2\.6-b1\b.*(actual|vigente|estado)", re.IGNORECASE),
     None),
    ("rc1-desplegada",
     re.compile(r"\brc1\b.*(desplegad|activa en produccion)", re.IGNORECASE),
     re.compile(r"no desplegad|nunca|candidata|abort", re.IGNORECASE)),
    ("rc5-desplegada",
     re.compile(r"\brc5\b(?!\.1).*(desplegad|activa en produccion)", re.IGNORECASE),
     re.compile(r"no desplegad|nunca|candidata|abort", re.IGNORECASE)),
    ("timer-5min-activo",
     re.compile(r"timer de 5\s*min(utos)?\s*activ|onunitactivesec=5min.*activ", re.IGNORECASE),
     None),
    ("authdb-en-release",
     re.compile(r"auth\.?db (dentro|en el interior) de (la )?release", re.IGNORECASE),
     None),
    ("rc4-activa",
     re.compile(r"\brc4\b.*(activa en produccion|es la release activa|current\s*->\s*91bdc51)", re.IGNORECASE),
     re.compile(r"previous|rollback|anterior", re.IGNORECASE)),
]


def scan_doc(path: Path) -> list[str]:
    findings: list[str] = []
    if not path.exists():
        return findings
    in_historic = False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ANY_HEADING.match(raw):
            in_historic = bool(HISTORIC_HEADING.match(raw))
        if in_historic or IGNORE_MARK in raw:
            continue
        text = _strip_accents(raw)
        for oid, rx, unless in OBSOLETE:
            if rx.search(text) and not (unless and unless.search(text)):
                try:
                    label = path.relative_to(REPO)
                except ValueError:
                    label = path
                findings.append(f"{label}:{n}: [{oid}] {raw.strip()[:100]}")
    return findings


# --- Bloque `development` -------------------------------------------------
#
# Los tres patrones de abajo son deliberadamente ESTRECHOS. Un patron amplio
# ("cualquier hex de 7 caracteres cerca de la palabra main") enrojeceria en
# cuanto un documento historico dijera "el commit 47bc314 ya NO es main", que
# es exactamente la frase correcta. Se prefiere no detectar algun caso a
# gritar sobre frases bien escritas: un gate ruidoso se acaba ignorando.

# "`main`, commit `28320bd`" / "main commit 28320bd"
RX_MAIN_SHA = re.compile(
    r"`?main`?\s*[,:]?\s*(?:commit|sha)\s*`?([0-9a-f]{7,40})`?", re.IGNORECASE
)
# "ultimo PR mergeado #157" / "CI verde en el ultimo merge (PR #157)"
RX_LAST_PR = re.compile(
    r"(?:ultimo (?:pr )?(?:merge(?:ado)?|fusionado)|ultimo pr)\b[^.\n]{0,40}?#(\d+)",
    re.IGNORECASE,
)


def check_development(development: dict) -> list[str]:
    """Valida el bloque `development` contra la documentacion."""
    findings: list[str] = []
    if not development:
        return ["project-status.yaml no tiene bloque `development`"]

    main_commit = str(development.get("main_commit", "")).strip()
    last_pr = development.get("latest_merged_pr")

    if not re.fullmatch(r"[0-9a-f]{40}", main_commit):
        findings.append(
            f"development.main_commit no es un SHA completo de 40 hex: {main_commit!r}"
        )

    for rel in DOCS:
        path = REPO / rel
        if not path.exists():
            continue
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if IGNORE_MARK in raw:
                continue
            text = _strip_accents(raw)

            for m in RX_MAIN_SHA.finditer(text):
                sha = m.group(1).lower()
                if main_commit and not main_commit.startswith(sha):
                    findings.append(
                        f"{rel}:{n}: atribuye a `main` el commit {sha}, pero "
                        f"development.main_commit es {main_commit[:12]}"
                    )

            if last_pr is not None:
                for m in RX_LAST_PR.finditer(text):
                    if int(m.group(1)) != int(last_pr):
                        findings.append(
                            f"{rel}:{n}: cita el PR #{m.group(1)} como el ultimo "
                            f"mergeado, pero development.latest_merged_pr es #{last_pr}"
                        )

    findings += _check_closed_programs(development)
    return findings


def _check_closed_programs(development: dict) -> list[str]:
    """Un programa declarado CERRADO no puede describirse como pendiente.

    Cada programa puede declarar `doc_forbids`: frases que, si aparecen en la
    documentacion, contradicen su estado. Es data-driven a proposito — cerrar
    un programa nuevo se documenta anadiendo datos, no tocando este script.
    """
    findings: list[str] = []
    for prog in development.get("completed_programs", []) or []:
        state = _strip_accents(str(prog.get("state", ""))).upper()
        forbids = prog.get("doc_forbids") or []
        if not forbids or "CERRADO" not in state:
            continue
        name = prog.get("name", "?")
        for rel in DOCS:
            path = REPO / rel
            if not path.exists():
                continue
            in_historic = False
            for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ANY_HEADING.match(raw):
                    in_historic = bool(HISTORIC_HEADING.match(raw))
                if in_historic or IGNORE_MARK in raw:
                    continue
                text = _strip_accents(raw).lower()
                for phrase in forbids:
                    if _strip_accents(str(phrase)).lower() in text:
                        findings.append(
                            f"{rel}:{n}: dice «{phrase}», pero «{name}» esta "
                            f"declarado {state} en development"
                        )
    return findings


# --- Punto 0: la autoridad es GIT, no el YAML ----------------------------

SKIP_GIT_ENV = "S9_DOCS_SKIP_GIT"
# "Carril A: Graph UX V2 (#158)" (squash) o "Merge pull request #157 from …"
RX_PR_SQUASH = re.compile(r"\(#(\d+)\)\s*$")
RX_PR_MERGE = re.compile(r"^Merge pull request #(\d+)\b")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _git_rc(*args: str) -> int | None:
    """Codigo de salida, para distinguir «respondio que NO» de «fallo».

    `merge-base --is-ancestor` devuelve 1 cuando la respuesta es «no es
    ancestro», que es informacion legitima, y tambien falla con otros codigos
    cuando no puede responder (historia incompleta). Confundirlos daria un rojo
    falso justo en un clon superficial.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode


def _try_local_main() -> tuple[str | None, str | None]:
    for ref in ("origin/main", "main"):
        sha = _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if sha and re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha, ref
    return None, None


def _resolve_main() -> tuple[str | None, str | None]:
    """SHA de la rama principal REAL.

    Prefiere `origin/main` sobre el `main` local, que en un worktree puede
    llevar dias sin actualizarse: precisamente el fallo que este gate debe
    detectar, no heredar.

    En CI el checkout es SUPERFICIAL (`fetch-depth: 1`), asi que `main` no
    existe en el clon y sin esto el gate se ponia rojo en cada PR. La salida
    NO es rendirse y pasar a verde —eso reabriria justo el agujero que este
    punto 0 cierra— sino traer `main` explicitamente. Si aun asi no aparece,
    rojo.
    """
    sha, ref = _try_local_main()
    if sha:
        return sha, ref

    if _git("rev-parse", "--is-shallow-repository") == "true":
        # `--unshallow` completa la historia y permite calcular ancestria y
        # desfase; si el remoto no lo admite, se cae al fetch normal.
        _git("fetch", "--quiet", "--unshallow", "origin", "main")
    _git("fetch", "--quiet", "--no-tags", "origin", "main")

    sha, ref = _try_local_main()
    if sha:
        return sha, ref
    sha = _git("rev-parse", "--verify", "--quiet", "FETCH_HEAD^{commit}")
    if sha and re.fullmatch(r"[0-9a-f]{40}", sha):
        return sha, "FETCH_HEAD (origin/main)"
    return None, None


def _merged_prs(ref: str, limit: int = 60) -> list[int]:
    """PRs fusionados en `main`, del mas reciente al mas antiguo.

    El orden es CRONOLOGICO, no numerico: en `main` real el #160 se fusiono
    ANTES que el #158, asi que "el ultimo" NO es "el mayor".
    """
    log = _git("log", f"-{limit}", "--format=%s", ref)
    if log is None:
        return []
    prs: list[int] = []
    for subject in log.splitlines():
        m = RX_PR_SQUASH.search(subject) or RX_PR_MERGE.match(subject)
        if m:
            prs.append(int(m.group(1)))
    return prs


def check_git_authority(development: dict) -> list[str]:
    if os.environ.get(SKIP_GIT_ENV) == "1":
        print(f"AVISO: verificacion contra Git DESACTIVADA por {SKIP_GIT_ENV}=1.")
        return []

    real_sha, ref = _resolve_main()
    if real_sha is None:
        # No se degrada a verde en silencio: si no se puede comprobar contra
        # Git, el gate lo dice en rojo. Saltarselo exige decirlo por variable.
        return [
            "no se ha podido resolver `main` en Git (¿clon superficial, sin "
            "remoto?): el YAML NO se ha verificado contra el repositorio real; "
            f"exporta {SKIP_GIT_ENV}=1 si aceptas asumirlo a mano"
        ]

    findings: list[str] = []
    declared = str(development.get("main_commit", "")).strip().lower()

    # No se exige IGUALDAD con la punta de `main`. Un gate que se pone rojo en
    # cuanto alguien fusiona algo estaria rojo en `main` de forma permanente, y
    # un rojo permanente no se lee: se ignora. Lo que se exige es que el commit
    # documentado sea REAL y este en la historia de `main` (eso ya mata al SHA
    # inventado), y que el desfase quepa en la ventana declarada abajo.
    max_lag = int(development.get("max_lag_commits", 3))
    if declared:
        exists = _git("rev-parse", "--verify", "--quiet", f"{declared}^{{commit}}")
        if not exists:
            findings.append(
                f"docs/project-status.yaml: development.main_commit "
                f"{declared[:12]} NO EXISTE en el repositorio"
            )
        elif (rc := _git_rc("merge-base", "--is-ancestor", declared, real_sha)) == 1:
            findings.append(
                f"docs/project-status.yaml: development.main_commit "
                f"{declared[:12]} no esta en la historia de {ref} "
                f"({real_sha[:12]}): describe una rama que no es `main`"
            )
        elif rc != 0:
            # Git no ha podido responder (historia incompleta). No se inventa
            # ni un verde ni un rojo: se dice que no se sabe, y se sigue con
            # las comprobaciones que si son fiables.
            print(
                f"AVISO: no se ha podido calcular la ancestria de "
                f"{declared[:12]} respecto a {ref} (historia incompleta); "
                f"no se comprueba el desfase."
            )
        else:
            lag_raw = _git("rev-list", "--count", f"{declared}..{real_sha}")
            lag = int(lag_raw) if lag_raw and lag_raw.isdigit() else 0
            if lag > max_lag:
                findings.append(
                    f"docs/project-status.yaml: development.main_commit "
                    f"{declared[:12]} va {lag} commits por detras de {ref} "
                    f"({real_sha[:12]}), y el maximo declarado es {max_lag}: "
                    f"la documentacion describe otro repositorio"
                )

    declared_pr = development.get("latest_merged_pr")
    prs = _merged_prs(ref)
    if declared_pr is not None and prs:
        declared_pr = int(declared_pr)
        if declared_pr not in prs:
            findings.append(
                f"docs/project-status.yaml: development.latest_merged_pr dice "
                f"#{declared_pr}, que no aparece entre los {len(prs)} ultimos "
                f"PR fusionados en {ref} (el ultimo es #{prs[0]})"
            )
        elif prs.index(declared_pr) > max_lag:
            findings.append(
                f"docs/project-status.yaml: development.latest_merged_pr dice "
                f"#{declared_pr}, pero desde entonces se han fusionado "
                f"{prs.index(declared_pr)} PR mas en {ref} (el ultimo es "
                f"#{prs[0]}), por encima del maximo declarado {max_lag}"
            )
    return findings


# --- La configuracion de CI tambien es codigo, y tambien manda -----------
#
# Sin esto, una frase como "`test/**` no dispara CI en push" pasaba en verde
# aunque `ci.yml` diga `branches: ['**']`. Era el defecto EXACTO que dejo
# NO CONFORME a `bf03ca7`, y el gate no podia verlo porque nunca leia `ci.yml`.

WORKFLOWS = [
    Path(".github") / "workflows" / "ci.yml",
    Path(".github") / "workflows" / "supply-chain.yml",
]

# "test/** no dispara CI", "los prefijos ops/** no disparan CI en push", …
RX_NO_CI = re.compile(
    r"`?([A-Za-z0-9_\-]+/\*\*)`?[^.\n]{0,80}?\bno\s+dispara\w*\s+ci\b",
    re.IGNORECASE,
)


def _load_workflow(rel: Path) -> dict | None:
    path = REPO / rel
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None


def _push_branches() -> list[str] | None:
    wf = _load_workflow(WORKFLOWS[0])
    if not wf:
        return None
    # `on` es la clave YAML 1.1 que se interpreta como booleano True.
    on = wf.get("on", wf.get(True, {})) or {}
    push = on.get("push") or {}
    branches = push.get("branches")
    return list(branches) if isinstance(branches, list) else None


def check_ci_claims() -> list[str]:
    """Ninguna documentacion puede negar un disparo de CI que `ci.yml` concede."""
    branches = _push_branches()
    if branches is None or "**" not in branches:
        # Si vuelve una lista blanca, la frase podria ser cierta: no se opina.
        return []

    findings: list[str] = []
    for rel in DOCS:
        path = REPO / rel
        if not path.exists():
            continue
        in_historic = False
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ANY_HEADING.match(raw):
                in_historic = bool(HISTORIC_HEADING.match(raw))
            if in_historic or IGNORE_MARK in raw:
                continue
            m = RX_NO_CI.search(_strip_accents(raw))
            if m:
                findings.append(
                    f"{rel}:{n}: dice que `{m.group(1)}` no dispara CI, pero "
                    f".github/workflows/ci.yml tiene on.push.branches: ['**'], "
                    f"que cubre CUALQUIER rama"
                )
    return findings


def _workflow_job_names() -> list[str]:
    names: list[str] = []
    for rel in WORKFLOWS:
        wf = _load_workflow(rel)
        for key, job in ((wf or {}).get("jobs") or {}).items():
            names.append(str((job or {}).get("name") or key))
    return names


def check_ci_inventory(development: dict) -> list[str]:
    """Los numeros de CI se derivan de los workflows, no se escriben a mano.

    Antes `ci_jobs_running: 14` y `ci_checks_required: 11` eran prosa numerica
    dentro del propio YAML que este gate obliga a verificar: se podian cambiar
    a 99/99 y pasaba en verde. Ahora el recuento de jobs sale de los ficheros
    de workflow y la aritmetica tiene que cuadrar.
    """
    findings: list[str] = []
    running = development.get("ci_jobs_running")
    required = development.get("ci_checks_required")
    required_names = development.get("ci_required_checks") or []
    not_required = development.get("ci_running_but_not_required") or []

    real = _workflow_job_names()
    if not real:
        return ["no se ha podido leer ningun job de .github/workflows/"]

    if running is not None and int(running) != len(real):
        findings.append(
            f"docs/project-status.yaml: ci_jobs_running dice {running}, pero "
            f"los workflows definen {len(real)} jobs"
        )

    for name in list(required_names) + list(not_required):
        if str(name) not in real:
            findings.append(
                f"docs/project-status.yaml: «{name}» no es el nombre de ningun "
                f"job definido en .github/workflows/"
            )

    if required is not None and required_names and int(required) != len(required_names):
        findings.append(
            f"docs/project-status.yaml: ci_checks_required dice {required}, "
            f"pero ci_required_checks enumera {len(required_names)} nombres"
        )

    if required_names and not_required:
        esperado = sorted(set(real) - set(map(str, required_names)))
        if esperado != sorted(map(str, not_required)):
            findings.append(
                "docs/project-status.yaml: ci_running_but_not_required no es "
                "exactamente «jobs de los workflows menos ci_required_checks»; "
                f"deberia ser {esperado}"
            )
    return findings


def check_tests_freshness(development: dict) -> list[str]:
    """Una marca `stale` sin caducidad es honesta pero inerte.

    NO se puede verificar que `collected: 7284` sea cierto sin ejecutar la
    suite, y este gate no la ejecuta (limite declarado). Lo que si se puede
    exigir es que una medicion vieja no se quede indefinidamente: si el commit
    medido ya no es `main`, hay que marcarla, y caduca.
    """
    tests = development.get("tests") or {}
    if not tests:
        return []
    findings: list[str] = []
    measured_commit = str(tests.get("commit", "")).strip()
    main_commit = str(development.get("main_commit", "")).strip()

    if measured_commit and main_commit and measured_commit != main_commit:
        if not tests.get("stale"):
            findings.append(
                f"docs/project-status.yaml: development.tests se midio en "
                f"{measured_commit[:12]}, que ya no es main_commit "
                f"({main_commit[:12]}), y no esta marcado `stale: true`"
            )
        max_age = int(development.get("max_test_age_days", 30))
        measured_at = str(tests.get("measured_at", "")).strip()
        try:
            age = (dt.date.today() - dt.date.fromisoformat(measured_at)).days
        except ValueError:
            return findings + [
                f"docs/project-status.yaml: development.tests.measured_at "
                f"({measured_at!r}) no es una fecha ISO-8601"
            ]
        if age > max_age:
            findings.append(
                f"docs/project-status.yaml: development.tests caduco — medido "
                f"hace {age} dias en un commit que ya no es `main`, y el maximo "
                f"declarado es {max_age}. Vuelve a medir o retira el bloque"
            )
    return findings


def check_canonical(production: dict) -> list[str]:
    findings: list[str] = []
    canonical = REPO / "docs" / "archivados" / "02-current-state.md"
    if not canonical.exists():
        return [f"falta el documento canónico {canonical.relative_to(REPO)}"]
    body = canonical.read_text(encoding="utf-8")
    for key in ("production_tag", "commit"):
        val = str(production.get(key, "")).strip()
        if val and val not in body:
            findings.append(
                f"docs/archivados/02-current-state.md no menciona {key}={val} (project-status.yaml, bloque production)"
            )
    return findings


def main() -> int:
    if not STATUS_YAML.exists():
        print(f"ERROR: falta {STATUS_YAML.relative_to(REPO)}", file=sys.stderr)
        return 1
    status = yaml.safe_load(STATUS_YAML.read_text(encoding="utf-8"))
    # project-status.yaml separa development/production/next_release desde
    # 2026-08-06; este script solo valida contra el estado de produccion.
    production = status.get("production", status)
    development = status.get("development", {})

    findings: list[str] = []
    for rel in DOCS:
        findings += scan_doc(REPO / rel)
    findings += check_canonical(production)
    findings += check_git_authority(development)
    findings += check_development(development)
    findings += check_ci_claims()
    findings += check_ci_inventory(development)
    findings += check_tests_freshness(development)

    if findings:
        print("DOCUMENTACION NO COHERENTE — contradicciones detectadas:")
        for f in findings:
            print(f"  - {f}")
        print(f"\nTotal: {len(findings)} contradiccion(es).")
        return 1

    # El titular tiene que decir la verdad sobre SU PROPIO alcance: si la
    # verificacion contra Git se ha desactivado, "COHERENTE" a secas seria
    # justo el tipo de verde comodo que este gate existe para impedir.
    if os.environ.get(SKIP_GIT_ENV) == "1":
        print("DOCUMENTACION COHERENTE (SIN VERIFICAR CONTRA GIT): "
              f"{SKIP_GIT_ENV}=1 desactivo el punto 0, asi que el estado "
              "declarado NO se ha contrastado con el repositorio real.")
    else:
        print("DOCUMENTACION COHERENTE: sin contradicciones conocidas.")
    print(f"  produccion:  {production.get('production_tag')} "
          f"({str(production.get('commit'))[:12]}) "
          f"release_id={production.get('production_release_id')}")
    print(f"  desarrollo:  main={str(development.get('main_commit'))[:12]} "
          f"ultimo PR mergeado=#{development.get('latest_merged_pr')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
