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

Salida: rc 0 si coherente; rc 1 si hay contradicciones (las lista).
"""
from __future__ import annotations

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
# Se pone a True si el punto 0 ha corrido sobre una historia TRUNCADA que no se
# ha podido completar. Lo lee `main()` para CALIFICAR EL TITULAR: un verde bajo
# «DOCUMENTACION COHERENTE» a secas es exactamente la fuga que este fichero
# existe para no tener (ver el titular de `S9_DOCS_SKIP_GIT`).
HISTORY_TRUNCATED = False
# Desfase OBSERVADO (no error) entre `main_commit`/`latest_merged_pr` y la punta
# de `main`. Lo lee `main()` para CALIFICAR EL TITULAR: el desfase deja de ser
# rojo, pero no puede volverse invisible. Un dato que solo aparece a media
# pagina no lo lee nadie; en la ultima linea, si.
MAIN_COMMIT_LAG = 0
PR_LAG = 0
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


def _deepen_if_shallow() -> bool:
    """Completa la historia si el clon es SUPERFICIAL. True si ya es completa.

    El rescate que vivia dentro de `_resolve_main` era CODIGO MUERTO en CI, y
    lo demostro el rojo de `main@0dfa788` el 2026-08-12: `actions/checkout` con
    `fetch-depth: 1` deja `main` Y `origin/main` creados, asi que
    `_try_local_main` acertaba a la primera y `_resolve_main` volvia ANTES de
    llegar al `--unshallow`. Resultado: el punto 0 se ejecutaba sobre una
    historia de UN commit y acusaba a `main_commit` de «NO EXISTE en el
    repositorio» siendo un ancestro perfectamente real.

    Resolver `main` NO basta: el punto 0 necesita HISTORIA para responder a la
    ancestria y al desfase. Por eso la profundidad se asegura aqui, en el unico
    sitio por el que pasan todas las comprobaciones, y no como efecto colateral
    de no encontrar una referencia.
    """
    if _git("rev-parse", "--is-shallow-repository") != "true":
        return True
    # `--unshallow` completa la historia; si el remoto no lo admite, se dira.
    _git("fetch", "--quiet", "--unshallow", "origin", "main")
    return _git("rev-parse", "--is-shallow-repository") != "true"


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

    # La historia tiene que ser COMPLETA antes de preguntar nada sobre ella.
    complete = _deepen_if_shallow()
    global HISTORY_TRUNCATED, MAIN_COMMIT_LAG, PR_LAG
    HISTORY_TRUNCATED = not complete
    MAIN_COMMIT_LAG = PR_LAG = 0  # se recalculan abajo; nunca se heredan

    findings: list[str] = []
    declared = str(development.get("main_commit", "")).strip().lower()

    # QUE ES ERROR Y QUE ES OBSERVACION (rediseñado el 2026-08-13)
    #
    # `main_commit` documenta EL COMMIT SOBRE EL QUE SE MIDIERON LAS CIFRAS.
    # Envejecer no lo vuelve falso: que se hayan fusionado commits detras no
    # demuestra ninguna contradiccion, solo demuestra que hubo merges.
    #
    # La version anterior trataba el desfase como ERROR, y eso hacia la puerta
    # INSOSTENIBLE POR CONSTRUCCION: cada merge invalidaba el refresco anterior,
    # con PRs de 10+ commits el refresco caducaba EN EL MOMENTO DE FUSIONARSE, y
    # `main` paso casi toda la sesion del 2026-08-13 en rojo bloqueando a la vez
    # TODAS las ramas abiertas. Medido: al fusionar el #168 quedo 9 commits
    # atras; el carril M lo refresco a `e752dbe` y su propio merge lo desfaso
    # otra vez. Mantenerlo verde exigia encadenar refrescos manuales a
    # perpetuidad. Eso no es un gate: es una tarea de mantenimiento que ademas
    # bloquea a terceros.
    #
    # Subir `max_lag_commits` NO es el arreglo —es el antipatron que este mismo
    # fichero deja escrito, y solo mueve el problema unos merges mas alla—.
    # El arreglo es distinguir HECHO de RELOJ:
    #
    #   ERROR (contradiccion demostrable, sigue ROJO):
    #     - el SHA no existe                          -> C6
    #     - el SHA no es ancestro de `main`            -> C10
    #     - el SHA no es de 40 hex                     -> C16
    #     - el PR declarado NO esta en la historia     -> C6
    #     - los contadores no cuadran con los workflows-> C13/C13b/C13c
    #     - los documentos y el YAML se contradicen    -> C1/C2
    #     - hay valores declarados que NO se han podido comprobar -> C19a
    #
    #   OBSERVACION (cierta pero no contradictoria, AVISO + titular calificado):
    #     - cuantos commits/PR han entrado desde entonces.
    #
    # Lo que queda en rojo sigue siendo lo que este gate existe para cazar: la
    # calibracion del 2026-08-11 (SHA `1111111…` + `#4242` propagados a los
    # cinco documentos) sigue enrojeciendo, y de hecho este gate ha cazado tres
    # veces el CHANGELOG de quien lo escribia.
    #
    # `max_lag_commits` deja de ser un umbral de error: es el umbral a partir
    # del cual el desfase se ANUNCIA. Subirlo ya no compra nada.
    max_lag = int(development.get("max_lag_commits", 3))
    if declared:
        exists = _git("rev-parse", "--verify", "--quiet", f"{declared}^{{commit}}")
        if not exists and not complete:
            # «No lo veo» NO es «no existe». Con la historia truncada, un
            # ancestro real es invisible, y acusar al documento de mentir seria
            # un diagnostico FALSO. Sigue siendo ROJO —fail-closed: no se ha
            # podido comprobar— pero dice la verdad sobre lo que ha pasado.
            findings.append(
                f"docs/project-status.yaml: development.main_commit "
                f"{declared[:12]} NO SE HA PODIDO COMPROBAR: el clon es "
                f"SUPERFICIAL y `--unshallow` no ha completado la historia, "
                f"asi que un ancestro real seria indistinguible de uno "
                f"inventado. Ejecuta el gate sobre un clon completo "
                f"(`fetch-depth: 0`)"
            )
        elif not exists:
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
                # OBSERVACION, no error: el commit es real y esta en `main`.
                MAIN_COMMIT_LAG = lag
                print(
                    f"AVISO: development.main_commit {declared[:12]} va {lag} "
                    f"commits por detras de {ref} ({real_sha[:12]}), por encima "
                    f"del umbral de aviso ({max_lag}). Las cifras se midieron "
                    f"sobre ese commit y siguen siendo coherentes; refrescarlo "
                    f"es mantenimiento, no una contradiccion."
                )

    declared_pr = development.get("latest_merged_pr")
    # Se lee del SHA ya resuelto, no del nombre simbolico: `_deepen_if_shallow`
    # acaba de hacer un `fetch`, que puede haber MOVIDO `origin/main` bajo
    # nuestros pies. Contra `real_sha` las tres preguntas (existencia,
    # ancestria, ventana de PR) hablan todas del mismo commit.
    prs = _merged_prs(real_sha) if complete else []
    if not complete:
        # Sobre un commit de historia, «no aparece entre los 1 ultimos PR
        # fusionados» no es un hallazgo: es ruido, y ese diagnostico falso fue
        # justo lo que puso rojo `main@0dfa788`.
        #
        # Pero SALTARSE la comprobacion en silencio abria una fuga peor, medida
        # el 2026-08-13: con la punta como `main_commit`, la existencia y la
        # ancestria son triviales, la ventana de PR no se miraba, y un
        # `latest_merged_pr: #4242` INVENTADO pasaba en VERDE bajo el titular
        # «DOCUMENTACION COHERENTE» a secas. Era el mismo defecto que este
        # script ya habia corregido para `S9_DOCS_SKIP_GIT` reapareciendo por
        # otra puerta. Si hay un valor DECLARADO que no se ha podido verificar,
        # se dice en ROJO; no se asume.
        print("AVISO: historia truncada; la ventana de PR no se ha podido comprobar.")
        if declared_pr is not None:
            findings.append(
                f"docs/project-status.yaml: development.latest_merged_pr "
                f"(#{declared_pr}) NO SE HA PODIDO COMPROBAR: la historia esta "
                f"truncada (clon superficial que `--unshallow` no ha "
                f"completado). Ejecuta el gate sobre un clon completo "
                f"(`fetch-depth: 0`)"
            )
    if declared_pr is not None and prs:
        declared_pr = int(declared_pr)
        if declared_pr not in prs:
            findings.append(
                f"docs/project-status.yaml: development.latest_merged_pr dice "
                f"#{declared_pr}, que no aparece entre los {len(prs)} ultimos "
                f"PR fusionados en {ref} (el ultimo es #{prs[0]})"
            )
        elif prs.index(declared_pr) > max_lag:
            # El MISMO reloj, y por tanto la misma observacion: que hayan
            # entrado PR despues no vuelve falso al que se declara. Que ESTE en
            # la historia (comprobado arriba) si es un hecho, y sigue en rojo.
            PR_LAG = prs.index(declared_pr)
            print(
                f"AVISO: development.latest_merged_pr #{declared_pr} esta en la "
                f"historia de {ref}, pero desde entonces se han fusionado "
                f"{prs.index(declared_pr)} PR mas (el ultimo es #{prs[0]}). "
                f"Ojo: el ultimo NO es el de numero mayor."
            )
    return findings


# --- CI: el validador lee los workflows, no solo los documentos ----------
#
# Limitacion declarada (RK-20, parte no cerrable aqui): que un job sea CHECK
# REQUERIDO vive en los ajustes de proteccion de rama de GitHub, no en el
# repositorio. Este script NO puede leerlo sin red ni credenciales, asi que
# `ci_checks_required` no se contrasta contra GitHub: se contrasta contra la
# ARITMETICA declarada en el propio YAML (jobs que corren menos los que el
# YAML declara no exigidos). Eso mata la cifra inventada, no la mentira
# deliberada y coherente sobre los ajustes de GitHub. Queda por escrito.
#
# Limitacion declarada (2): `development.latest_ci` NO LO VALIDA NADIE. Es el
# unico campo del bloque que solo vive en el YAML; declararlo "green" sobre un
# commit con la CI en rojo pasa en verde. El oraculo esta fuera —el estado de
# CI de un commit vive en GitHub, y este script corre sin red ni credenciales—
# y no se finge cobertura con una comprobacion de vocabulario que no podria
# fallar en el caso que importa. Declarado con `xfail(strict=True)` en la fila
# test_c20_latest_ci_mentiroso_no_lo_detecta_nadie, que gritara por XPASS el
# dia que alguien conecte ese oraculo.

WORKFLOWS = Path(".github") / "workflows"

# Afirmaciones que NIEGAN o RESTRINGEN el disparo de CI. La primera version de
# estos patrones solo cazaba la redaccion historica literal ("test/** no dispara
# CI"): en la revision de 2026-08-12 se comprobo que seis frases igual de falsas
# —«siguen sin disparar CI», «CI no se dispara en ramas ops/**», «no lanza CI»,
# «CI unicamente corre en main», «solo las ramas de la lista blanca disparan
# CI»— pasaban las seis en verde contra el repo real. Se cubren cuatro familias:
#   (a) negacion antes de CI:      "no (se) dispara/lanza/corre/ejecuta ... CI"
#   (b) negacion despues de CI:    "CI ... no se dispara/lanza/corre"
#   (c) negacion por "sin":        "sin disparar/lanzar/ejecutar ... CI"
#   (d) exclusividad:              "solo/unicamente ... dispara ... CI"
#   (e) exclusion de forma FIJA:   "CI (queda) excluido en ...", "CI se limita
#                                  a ...", "... fuera del alcance de CI"
# La familia (e) se anadio el 2026-08-12 tras la segunda revision: son tres
# idiomas CERRADOS, no parafrasis abiertas, y «se limita a» es la misma
# exclusividad de (d) escrita de otra manera.
#
# La familia (e) esta ANCLADA A UN TOKEN DE RAMA (`_BRANCH`) porque sin esa
# ancla producia falsos positivos sobre prosa legitima, medidos en la tercera
# revision: «CI se limita a informar: no bloquea el merge» —que es literalmente
# la tesis de RK-20b—, «el job de CI se limita a 20 minutos», «CI se limita a
# 14 jobs por PR» y «ese refactor queda fuera del alcance de este PR; CI no
# cambia», un descargo de alcance frecuentisimo en CHANGELOG y ROADMAP, que
# estan en DOCS. Estas frases NO hablan de que ramas disparan CI, que es lo
# unico que R5 puede juzgar leyendo `on.push.branches`. Un gate que muerde
# nuestro propio texto correcto se acaba desactivando.
# La estrechez que QUEDA esta DECLARADA, con sus CUATRO frases concretas, en
# test_c4e_estrechez_declarada_de_r5: «el workflow ignora …» (no contiene el
# token CI), «nunca en el push» (negacion desplazada al disparador),
# «invisible para CI» (metafora) y «hay una lista blanca de prefijos» (describe
# un mecanismo sin negar nada). Esas cuatro no son enumerables; las tres que si
# lo eran —«excluido», «se limita a», «fuera del alcance»— se cubren arriba.
_VERBS = r"(?:dispara|disparan|lanza|lanzan|corre|corren|ejecuta|ejecutan|activa|activan|tiene|tienen)"
_VERBS_INF = r"(?:disparar|lanzar|ejecutar|correr|activar)"
_ONLY = r"(?:solo|solamente|unicamente|exclusivamente)"
# Token de rama: sin el, la familia (e) juzga frases que no hablan de ramas.
_BRANCH = r"(?:\bramas?\b|\bbranch(?:es)?\b|\*\*)"
RX_NO_CI = re.compile(
    r"\bno\s+(?:se\s+)?" + _VERBS + r"\b[^.\n]{0,40}\bCI\b"
    r"|\bCI\b[^.\n]{0,40}\bno\s+(?:se\s+)?" + _VERBS + r"\b"
    r"|\bsin\s+" + _VERBS_INF + r"\b[^.\n]{0,30}\bCI\b"
    r"|\b" + _ONLY + r"\b[^.\n]{0,60}\b" + _VERBS + r"\b[^.\n]{0,20}\bCI\b"
    r"|\bCI\b[^.\n]{0,40}\b" + _ONLY + r"\b[^.\n]{0,30}(?:\bse\s+)?" + _VERBS + r"\b"
    r"|\bCI\b[^.\n]{0,25}\bexclui(?:d[oa]s?|r)\b[^.\n]{0,40}" + _BRANCH
    + r"|\bCI\b[^.\n]{0,25}\bse\s+limita\b[^.\n]{0,40}" + _BRANCH
    + r"|" + _BRANCH + r"[^.\n]{0,40}\bfuera\s+del\s+alcance\b[^.\n]{0,30}\bCI\b",
    re.IGNORECASE,
)
# "toda rama dispara CI", "cada rama dispara CI", "cualquier rama lanza CI",
# "CI en todas las ramas".
RX_ALL_CI = re.compile(
    r"\b(?:toda|todas|cada|cualquier)\s+(?:las?\s+)?ramas?\b[^.\n]{0,40}\b" + _VERBS + r"\b"
    r"|\bCI\b[^.\n]{0,30}\ben\s+(?:toda|todas|cada|cualquier)\s+(?:las?\s+)?ramas?\b",
    re.IGNORECASE,
)


def _load_workflows() -> dict[str, dict]:
    out: dict[str, dict] = {}
    wf_dir = REPO / WORKFLOWS
    if not wf_dir.is_dir():
        return out
    for path in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            out[path.name] = data
    return out


def _push_branches(wf: dict) -> list[str]:
    # PyYAML lee `on:` como el booleano True (YAML 1.1). Se aceptan ambos.
    trig = wf.get("on", wf.get(True)) or {}
    if not isinstance(trig, dict):
        return []
    push = trig.get("push") or {}
    if not isinstance(push, dict):
        return []
    branches = push.get("branches") or []
    return [str(b) for b in branches] if isinstance(branches, list) else [str(branches)]


def check_ci_claims(workflows: dict[str, dict]) -> list[str]:
    """Cierra R5: las afirmaciones sobre los DISPARADORES de CI se leen de `ci.yml`.

    Hasta aqui el validador no abria un solo workflow, asi que la frase
    «`test/**` no dispara CI» —falsa desde `e21f766`, y el defecto exacto que
    hizo NO CONFORME a `bf03ca7`— pasaba en verde.
    """
    findings: list[str] = []
    ci = workflows.get("ci.yml")
    if ci is None:
        return ["falta .github/workflows/ci.yml: no se pueden verificar los disparadores de CI"]
    branches = _push_branches(ci)
    universal = "**" in branches

    for rel in DOCS + ["docs/coordination/risk-register.md"]:
        path = REPO / rel
        if not path.exists():
            continue
        in_historic = False
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ANY_HEADING.match(raw):
                in_historic = bool(HISTORIC_HEADING.match(raw))
            if in_historic or IGNORE_MARK in raw:
                continue
            text = _strip_accents(raw)
            if universal and RX_NO_CI.search(text):
                findings.append(
                    f"{rel}:{n}: afirma que algo NO dispara CI, pero "
                    f".github/workflows/ci.yml tiene on.push.branches={branches} "
                    f"(toda rama dispara CI)"
                )
            if not universal and RX_ALL_CI.search(text):
                findings.append(
                    f"{rel}:{n}: afirma que toda rama dispara CI, pero "
                    f".github/workflows/ci.yml limita on.push.branches a {branches}"
                )
    return findings


def check_ci_job_counts(development: dict, workflows: dict[str, dict]) -> list[str]:
    """Cierra R7 (la parte verificable): 14/11 se contrastan, no se creen.

    Los numeros de RK-20 vivian en el mismo YAML que este gate exige verificar
    contra Git, y nada los miraba: ponerlos a 99/99 daba verde.
    """
    findings: list[str] = []
    declared_running = development.get("ci_jobs_running")
    declared_required = development.get("ci_checks_required")
    not_required = [str(x) for x in (development.get("ci_running_but_not_required") or [])]
    if declared_running is None and declared_required is None:
        return findings

    names: list[str] = []
    for wf in workflows.values():
        jobs = wf.get("jobs") or {}
        if isinstance(jobs, dict):
            for key, job in jobs.items():
                names.append(str((job or {}).get("name", key)))
    if not names:
        return ["no se ha podido contar ningun job en .github/workflows/"]

    if declared_running is not None and int(declared_running) != len(names):
        findings.append(
            f"docs/project-status.yaml: development.ci_jobs_running dice "
            f"{declared_running}, pero .github/workflows/ define {len(names)} jobs"
        )
    normalized = {_strip_accents(x) for x in names}
    for missing in [x for x in not_required if _strip_accents(x) not in normalized]:
        findings.append(
            f"docs/project-status.yaml: ci_running_but_not_required cita el job "
            f"«{missing}», que no existe en .github/workflows/"
        )
    if declared_required is not None and declared_running is not None:
        expected = int(declared_running) - len(not_required)
        if int(declared_required) != expected:
            findings.append(
                f"docs/project-status.yaml: ci_checks_required dice "
                f"{declared_required}, pero {declared_running} jobs menos "
                f"{len(not_required)} declarados no exigidos son {expected}"
            )
    return findings


def check_workflows_do_not_skip_git(workflows: dict[str, dict]) -> list[str]:
    """`S9_DOCS_SKIP_GIT` es una valvula MANUAL: en CI seria un verde ciego."""
    findings: list[str] = []
    wf_dir = REPO / WORKFLOWS
    if not wf_dir.is_dir():
        return findings
    for path in sorted(wf_dir.iterdir()):
        if not path.is_file():
            continue
        if SKIP_GIT_ENV in path.read_text(encoding="utf-8", errors="replace"):
            findings.append(
                f"{WORKFLOWS}/{path.name}: menciona {SKIP_GIT_ENV}. Esa variable "
                f"desactiva la verificacion contra Git: en un workflow convierte "
                f"el gate en un verde que no ha comprobado nada"
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

    workflows = _load_workflows()

    findings: list[str] = []
    for rel in DOCS:
        findings += scan_doc(REPO / rel)
    findings += check_canonical(production)
    findings += check_git_authority(development)
    findings += check_development(development)
    findings += check_ci_claims(workflows)
    findings += check_ci_job_counts(development, workflows)
    findings += check_workflows_do_not_skip_git(workflows)

    if findings:
        print("DOCUMENTACION NO COHERENTE — contradicciones detectadas:")
        for f in findings:
            print(f"  - {f}")
        print(f"\nTotal: {len(findings)} contradiccion(es).")
        return 1

    if os.environ.get(SKIP_GIT_ENV) == "1":
        # El titular tiene que decir lo que NO se ha comprobado. «COHERENTE» a
        # secas tras un aviso es justo el verde que este script existe para no
        # dar: quien lee la ultima linea de un log se lleva la mentira.
        print("DOCUMENTACION COHERENTE (SIN VERIFICAR CONTRA GIT): "
              f"{SKIP_GIT_ENV}=1 desactivo el punto 0.")
    elif MAIN_COMMIT_LAG or PR_LAG:
        # El desfase ya no es rojo, pero TIENE que verse en la ultima linea. Un
        # titular «COHERENTE» a secas sobre un bloque medido 13 commits atras es
        # la misma clase de fuga que ya se corrigio dos veces en este fichero.
        partes = []
        if MAIN_COMMIT_LAG:
            partes.append(f"main_commit {MAIN_COMMIT_LAG} commits por detras")
        if PR_LAG:
            partes.append(f"{PR_LAG} PR fusionados despues del declarado")
        print(f"DOCUMENTACION COHERENTE (DESFASADA: {'; '.join(partes)}): "
              "sin contradicciones; las cifras se midieron sobre "
              "`development.main_commit` y refrescarlo es mantenimiento.")
    elif HISTORY_TRUNCATED:
        # La misma regla, por la otra puerta: el punto 0 ha corrido sobre una
        # historia truncada, asi que parte de lo que dice el YAML NO se ha
        # podido contrastar. El titular tiene que llevarlo escrito.
        print("DOCUMENTACION COHERENTE (HISTORIA TRUNCADA): el clon es "
              "superficial y `--unshallow` no lo ha completado; el punto 0 "
              "solo ha comprobado lo que cabe en la historia disponible.")
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
