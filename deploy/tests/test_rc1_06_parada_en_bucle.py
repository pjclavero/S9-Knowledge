# -*- coding: utf-8 -*-
"""RC1-06 · `parar_y_verificar_servicios` no puede dar por parado un servicio en BUCLE DE REINICIOS.

Contrato (H-06 §8): ningun fichero de estado se toca con un proceso vivo. Una unidad en
`activating (auto-restart)` NO esta `is-active`, pero systemd la sigue relanzando.

QUE SE EJECUTA: `lib.sh` REAL en bash con un `systemctl` simulado CON ESTADO que reproduce la
secuencia del bucle (ActiveState/SubState/MainPID por lectura). No hay systemd ni root.
TECHO: el efecto real de `stop` sobre `auto-restart` (que lo cancela) es comportamiento de
systemd: el simulado lo MODELA (`stop_works`); la prueba real es el escenario de laboratorio
(`runner/r1_repro_parada_en_bucle.sh` de la RC), no este fichero.

Los mutantes se aplican AQUI sobre una copia temporal de `lib.sh` (no hay calibrador externo):
cada uno tiene que poner ROJO su testigo.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
LIB_SH = RAIZ / "deploy" / "scripts" / "lib.sh"
SERVICE_STATE_PY = RAIZ / "data-engine" / "app" / "knowledge_v3" / "service_state.py"

VISOR = "s9-knowledge-viewer.service"
WORKER = "s9-knowledge-worker.service"
HEALTH = "s9-knowledge-healthcheck.service"
TIMER = "s9-knowledge-healthcheck.timer"
TODAS = (TIMER, HEALTH, WORKER, VISOR)

# systemctl simulado. Estado en $D:
#   <u>.load        "loaded" (defecto) | "not-found"
#   <u>.seq         lineas "ActiveState SubState MainPID", leidas EN ORDEN (cicla) mientras no se ha parado
#   <u>.stop_works  si existe, `stop` deja la unidad quieta (modelo de «stop cancela el auto-restart»)
#   <u>.stoprc      si existe, `stop` devuelve ese rc
#   <u>.stopped     lo crea `stop`; despues la unidad es `inactive dead 0`
# Una lectura de ActiveState/MainPID AVANZA el contador; LoadState y is-active no.
STUB = r'''
sleep() { :; }
_leer() {   # _leer <unit> <avanzar 0|1>  -> A S M
    local u="$1" adv="$2" n len lineas
    if [ -e "$D/$u.stopped" ] || [ ! -e "$D/$u.seq" ]; then A=inactive; S=dead; M=0; return 0; fi
    mapfile -t lineas < "$D/$u.seq"; len=${#lineas[@]}
    n=0; [ -e "$D/$u.n" ] && n="$(cat "$D/$u.n")"
    read -r A S M <<< "${lineas[$((n % len))]}"
    if [ "$adv" = 1 ]; then echo $((n + 1)) > "$D/$u.n"; fi
    return 0
}
systemctl() {
    echo "$*" >> "$D/calls.log"
    local cmd="$1"; shift
    case "$cmd" in
        is-active)
            [ "$1" = "--quiet" ] && shift
            _leer "$1" 0; [ "$A" = active ] ;;
        stop)
            if [ -e "$D/$1.stoprc" ]; then return "$(cat "$D/$1.stoprc")"; fi
            if [ -e "$D/$1.load" ] && [ "$(cat "$D/$1.load")" = "not-found" ]; then return 5; fi
            if [ -e "$D/$1.stop_works" ]; then : > "$D/$1.stopped"; fi
            return 0 ;;
        show)
            local props=() val=0 u="" load=loaded adv=0 p v
            while [ $# -gt 0 ]; do
                case "$1" in -p) props+=("$2"); shift 2 ;; --value) val=1; shift ;; *) u="$1"; shift ;; esac
            done
            if [ -e "$D/$u.load" ]; then load="$(cat "$D/$u.load")"; fi
            for p in "${props[@]}"; do case "$p" in ActiveState|MainPID) adv=1 ;; esac; done
            _leer "$u" "$adv"
            for p in "${props[@]}"; do
                case "$p" in
                    LoadState) v="$load" ;; ActiveState) v="$A" ;; SubState) v="$S" ;; MainPID) v="$M" ;; *) v="" ;;
                esac
                if [ "$val" = 1 ]; then echo "$v"; else echo "$p=$v"; fi
            done ;;
        *) return 0 ;;
    esac
}
'''


def _montar(base, unidades):
    """unidades: {unit: dict(load=, seq=[...], stop_works=bool, stoprc=int)}."""
    d = base / "estado"
    d.mkdir()
    (d / "calls.log").write_text("")
    for u, c in unidades.items():
        if "load" in c:
            (d / f"{u}.load").write_text(c["load"])
        if "seq" in c:
            (d / f"{u}.seq").write_text("\n".join(c["seq"]) + "\n")
        if c.get("stop_works"):
            (d / f"{u}.stop_works").write_text("")
        if "stoprc" in c:
            (d / f"{u}.stoprc").write_text(str(c["stoprc"]))
    return d


def _ejecutar(base, unidades, lib=LIB_SH, env_extra=None, cola="", sin_rc=False):
    base.mkdir(exist_ok=True)
    d = _montar(base, unidades)
    llamada = "parar_y_verificar_servicios" if sin_rc else \
        "if parar_y_verificar_servicios; then echo RC=0; else echo RC=1; fi"
    script = 'set -Eeuo pipefail\nD="%s"\nsource "%s"\n%s\n%s\n%s\n' % (d, lib, STUB, llamada, cola)
    env = {k: v for k, v in os.environ.items() if not k.startswith("S9K_")}
    # Una COPIA mutada de lib.sh en tmp_path resuelve la autoridad relativa a si misma
    # (`_LIB_DIR/../../data-engine/...`), que ahi no existe: se apunta a la REAL del repo.
    env["S9K_SERVICE_STATE_PY"] = str(SERVICE_STATE_PY)
    env.update(env_extra or {})
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)
    llamadas = (d / "calls.log").read_text().splitlines()
    return r, llamadas


BUCLE = ["activating auto-restart 0", "activating start 4242", "activating auto-restart 0"]


# ---------------------------------------------------------------------------
# Controles: lo que NO debe romperse
# ---------------------------------------------------------------------------
def test_RC106_C1_unidad_activa_normal_se_para(tmp_path):
    """Esperado: RC=0 y `stop` sobre visor y worker (activos hasta que se les para)."""
    r, ll = _ejecutar(tmp_path, {
        VISOR: dict(seq=["active running 100"], stop_works=True),
        WORKER: dict(seq=["active running 200"], stop_works=True)})
    assert "RC=0" in r.stdout, r.stderr
    assert f"stop {VISOR}" in ll and f"stop {WORKER}" in ll, ll


def test_RC106_C2_unidades_ausentes_no_fallan_ni_se_paran(tmp_path):
    """Esperado: RC=0 y NINGUN `stop` (sobre una unidad inexistente `stop` da rc 5)."""
    r, ll = _ejecutar(tmp_path, {u: dict(load="not-found") for u in TODAS})
    assert "RC=0" in r.stdout, r.stderr
    assert not [x for x in ll if x.startswith("stop ")], ll


def test_RC106_C3_unidad_ya_parada_no_falla(tmp_path):
    """Esperado: RC=0 (inactive/dead/0 en todas)."""
    r, _ = _ejecutar(tmp_path, {u: dict(seq=["inactive dead 0"]) for u in TODAS})
    assert "RC=0" in r.stdout, r.stderr


def test_RC106_C4_failed_sin_pid_cuenta_como_quieta(tmp_path):
    """Esperado: RC=0. `failed` con MainPID 0 (sin reinicio programado) es un estado estable."""
    r, _ = _ejecutar(tmp_path, {VISOR: dict(seq=["failed failed 0"])})
    assert "RC=0" in r.stdout, r.stderr


@pytest.mark.parametrize("activo,esperado", [(True, "1"), (False, "0")])
def test_RC106_C5_el_timer_se_reanuda_solo_si_estaba_activo(tmp_path, activo, esperado):
    """Esperado: S9K_REANUDAR_TIMER=1 con el timer activo, 0 con el timer parado."""
    seq = ["active waiting 0"] if activo else ["inactive dead 0"]
    r, _ = _ejecutar(tmp_path, {TIMER: dict(seq=seq, stop_works=True)},
                     cola='echo REANUDAR=${S9K_REANUDAR_TIMER}')
    assert f"REANUDAR={esperado}" in r.stdout, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# RC1-06: el bucle de reinicios
# ---------------------------------------------------------------------------
def test_RC106_B1_unidad_en_bucle_se_para_aunque_no_este_is_active(tmp_path):
    """Esperado: `stop` SE EMITE sobre la unidad en `activating (auto-restart)` (antes no: solo si
    is-active) y, al cancelar el stop el reinicio, RC=0 tras 3 lecturas quietas."""
    r, ll = _ejecutar(tmp_path, {VISOR: dict(seq=BUCLE, stop_works=True)})
    assert f"stop {VISOR}" in ll, "RC1-06: NO SE EMITIO STOP sobre la unidad en bucle: %r" % (ll,)
    assert "RC=0" in r.stdout, "RC1-06: la unidad en bucle no se dio por parada: %s" % r.stderr


def test_RC106_B2_el_hueco_entre_reinicios_no_basta(tmp_path):
    """Esperado: RC=1 y causa nombrada. El stop NO surte efecto (unidad que se sigue relanzando)
    y entre reinicios hay huecos de 2 lecturas `inactive/0`: ninguna ventana de 3 seguidas."""
    r, _ = _ejecutar(tmp_path, {VISOR: dict(
        seq=["inactive dead 0", "inactive dead 0", "activating auto-restart 0"])})
    assert "RC=1" in r.stdout, r.stdout + r.stderr
    assert VISOR in r.stderr and "STOP" in r.stderr, r.stderr


@pytest.mark.parametrize("estado", ["activating auto-restart 0", "deactivating stop-sigterm 77",
                                    "active running 99", "inactive dead 55"])
def test_RC106_B3_estados_no_quietos_son_rc1(tmp_path, estado):
    """Esperado: RC=1 para auto-restart, deactivating, active y un MainPID != 0 aunque `inactive`."""
    r, _ = _ejecutar(tmp_path, {VISOR: dict(seq=[estado])})
    assert "RC=1" in r.stdout, r.stdout + r.stderr


def test_RC106_B4_si_stop_falla_rc1_sin_verificar(tmp_path):
    """Esperado: RC=1 («systemctl stop ... falló»)."""
    r, _ = _ejecutar(tmp_path, {WORKER: dict(seq=["active running 5"], stoprc=1)})
    assert "RC=1" in r.stdout and "falló" in r.stderr, r.stderr


def test_RC106_B5_la_ventana_exige_lecturas_seguidas(tmp_path):
    """Esperado: con S9K_PARADA_LECTURAS=5 y una unidad que da 4 quietas y una no, RC=1;
    con 3 lecturas, RC=0. La ventana es el parametro que decide."""
    seq = ["inactive dead 0"] * 4 + ["activating auto-restart 0"]
    r5, _ = _ejecutar(tmp_path / "a", {VISOR: dict(seq=seq)},
                      env_extra={"S9K_PARADA_LECTURAS": "5", "S9K_PARADA_INTENTOS": "5"})
    assert "RC=1" in r5.stdout, r5.stdout + r5.stderr
    r3, _ = _ejecutar(tmp_path / "b", {VISOR: dict(seq=seq)}, env_extra={"S9K_PARADA_LECTURAS": "3"})
    assert "RC=0" in r3.stdout, r3.stdout + r3.stderr


# ---------------------------------------------------------------------------
# Mutantes (sobre una copia de lib.sh): cada uno tiene que poner rojo su testigo
# ---------------------------------------------------------------------------
_ANTIGUA = r'''
parar_y_verificar_servicios() {
    local unit i main
    if systemctl is-active --quiet "${HEALTH_TIMER_NAME}" 2>/dev/null; then
        S9K_REANUDAR_TIMER=1
        systemctl stop "${HEALTH_TIMER_NAME}" || { err "no se pudo parar ${HEALTH_TIMER_NAME}"; return 1; }
    fi
    for unit in "${HEALTH_UNIT_NAME}" "${WORKER_UNIT_NAME_LIB}" "${VIEWER_UNIT_NAME}"; do
        if systemctl is-active --quiet "${unit}" 2>/dev/null; then
            systemctl stop "${unit}" || { err "systemctl stop ${unit} falló"; return 1; }
        fi
    done
    for unit in "${HEALTH_UNIT_NAME}" "${WORKER_UNIT_NAME_LIB}" "${VIEWER_UNIT_NAME}"; do
        for i in 1 2 3 4 5; do
            main="$(systemctl show -p MainPID --value "${unit}" 2>/dev/null || echo 0)"
            if ! systemctl is-active --quiet "${unit}" 2>/dev/null && { [ -z "${main}" ] || [ "${main}" = "0" ]; }; then
                break
            fi
            if [ "${i}" -eq 5 ]; then err "${unit} sigue activo"; return 1; fi
            sleep 1
        done
    done
    return 0
}
'''


def _copia_mutada(tmp_path, nombre, f):
    src = LIB_SH.read_text(encoding="utf-8")
    nuevo = f(src)
    assert nuevo != src, f"el mutante {nombre} no cambia nada: patron no encontrado"
    p = tmp_path / f"lib_{nombre}.sh"
    p.write_text(nuevo, encoding="utf-8")
    return p


def test_RC106_M0_control_positivo_la_funcion_antigua_da_por_parado_el_bucle(tmp_path):
    """Esperado: con la funcion ANTERIOR al arreglo, RC=0 SIN emitir `stop` sobre una unidad en bucle
    (el defecto RC1-06). Si esto pasa a verde, el arnes ya no reproduce el defecto y los
    tests B1/B2 no prueban nada."""
    p = _copia_mutada(tmp_path, "antigua", lambda s: s + "\n" + _ANTIGUA)
    r, ll = _ejecutar(tmp_path / "x", {VISOR: dict(seq=BUCLE, stop_works=True)}, lib=p)
    assert "RC=0" in r.stdout, r.stdout + r.stderr
    assert f"stop {VISOR}" not in ll, ll


def test_RC106_M1_mutante_is_active_antes_del_stop_se_detecta(tmp_path):
    """Esperado: el mutante «solo stop si is-active» (el defecto) deja de emitir stop (B1 en rojo)."""
    def f(s):
        return s.replace('        log "    parando ${unit}"\n        systemctl stop "${unit}"',
                         '        systemctl is-active --quiet "${unit}" 2>/dev/null || continue\n'
                         '        log "    parando ${unit}"\n        systemctl stop "${unit}"')
    p = _copia_mutada(tmp_path, "isactive", f)
    _r, ll = _ejecutar(tmp_path / "x", {VISOR: dict(seq=BUCLE, stop_works=True)}, lib=p)
    assert f"stop {VISOR}" not in ll


def test_RC106_M2_mutante_una_sola_lectura_se_detecta(tmp_path):
    """Esperado: el mutante «basta una lectura» da RC=0 donde B2 exige RC=1 (B2 en rojo)."""
    p = _copia_mutada(tmp_path, "unalectura", lambda s: s.replace(
        'lecturas="${S9K_PARADA_LECTURAS:-3}"', 'lecturas="${S9K_PARADA_LECTURAS:-1}"'))
    r, _ = _ejecutar(tmp_path / "x", {VISOR: dict(
        seq=["inactive dead 0", "inactive dead 0", "activating auto-restart 0"])}, lib=p)
    assert "RC=0" in r.stdout


def test_RC106_M3_mutante_ignora_activestate_se_detecta(tmp_path):
    """Esperado: el mutante que solo mira MainPID (sin ActiveState) da RC=0 para `auto-restart/0`
    (B3 en rojo)."""
    p = _copia_mutada(tmp_path, "soloPID", lambda s: s.replace(
        'case "${active}" in inactive|failed) ;; *) return 1 ;; esac', ': ignorado'))
    r, _ = _ejecutar(tmp_path / "x", {VISOR: dict(seq=["activating auto-restart 0"])}, lib=p)
    assert "RC=0" in r.stdout


def test_RC106_S1_la_funcion_real_no_condiciona_el_stop_a_is_active():
    """Esperado: en el cuerpo de la funcion real, `is-active` solo aparece para el TIMER
    (recordar si reanudarlo); nunca como condicion de `stop` ni de la verificacion."""
    s = LIB_SH.read_text(encoding="utf-8")
    cuerpo = s[s.index("\nparar_y_verificar_servicios() {"):]
    cuerpo = cuerpo[:cuerpo.index("\n}\n")]
    usos = [ln for ln in cuerpo.splitlines() if "is-active" in ln]
    assert len(usos) == 1 and "HEALTH_TIMER_NAME" in usos[0], usos
