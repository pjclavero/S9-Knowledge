#!/usr/bin/env bash
# lib_lab.sh — utilidades comunes de los guiones de laboratorio de H-06 + H-08.
#
# LABORATORIO = VM112 (maquina de pruebas dedicada). NUNCA la maquina de
# orquestacion (ia-server) ni produccion. Estos guiones crean un usuario de
# sistema, instalan en /opt/s9-knowledge, /etc/s9-knowledge y /var/lib/s9-knowledge
# y arrancan servicios systemd REALES: por eso el primer paso de cada uno es la
# comprobacion previa `lab_guard`, que PARA si no hay sudo, no hay systemd o la
# maquina no esta confirmada como laboratorio. Sin secretos ni IPs en el repo.
#
# Variables (todas con defecto razonable, ninguna es un secreto):
#   S9K_LAB_CONFIRMADO   debe valer VM112 (confirmacion explicita del operador)
#   S9K_LAB_BASE         directorio de trabajo (defecto /srv/s9-test/h06h08)
#   S9K_LAB_SHA          commit a probar (defecto: HEAD del clon de S9K_LAB_BASE/repo)
#   S9K_LAB_HEAVY_LOCK   cerrojo de carga pesada (defecto /srv/s9-test/heavy.lock)
#   S9K_LAB_PROHIBIDOS   regex de hostnames en los que NO se ejecuta
# shellcheck shell=bash
set -Eeuo pipefail
# runuser/useradd/nologin viven en /usr/sbin, que un usuario normal no lleva en el PATH.
export PATH="${PATH}:/usr/sbin:/sbin"

LAB_BASE="${S9K_LAB_BASE:-/srv/s9-test/h06h08}"
LAB_HEAVY_LOCK="${S9K_LAB_HEAVY_LOCK:-/srv/s9-test/heavy.lock}"
LAB_PROHIBIDOS="${S9K_LAB_PROHIBIDOS:-^(ia-server|ia02)$|prod|vm105|vm108}"
LAB_REPO="${S9K_LAB_REPO:-${LAB_BASE}/repo}"
LAB_LOGS="${S9K_LAB_LOGS:-/srv/s9-test/h06h08-logs}"
LAB_CREADO="${LAB_LOGS}/CREADO.txt"

# Registro de TODO lo que estos guiones crean fuera de su directorio de trabajo
# (lo lee 99_limpiar.sh). Una linea por cosa: «<fecha> <tipo> <ruta-o-nombre>».
lab_registrar() {
    mkdir -p "${LAB_LOGS}"
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "${LAB_CREADO}"
}

# Si se ejecuta como root SIN sudo instalado, `sudo` es una funcion transparente
# (con `-u usuario` cambia de usuario con runuser). Con sudo real no cambia nada.
if [ "$(id -u)" -eq 0 ] && ! command -v sudo >/dev/null 2>&1; then
    sudo() {
        if [ "${1:-}" = "-u" ]; then local u="$2"; shift 2; runuser -u "${u}" -- "$@"; else "$@"; fi
    }
fi

lab_log()  { printf '[lab] %s\n' "$*"; }
lab_fail() { printf '[lab] FALLO: %s\n' "$*" >&2; exit 1; }
lab_stop() { printf '[lab] PARADA: %s\n' "$*" >&2; exit 2; }

# Guarda MINIMA para las tandas SIN root (preparacion, serie pesada): solo exige que
# no sea la maquina de orquestacion/produccion y la confirmacion explicita.
lab_guard_basico() {
    local host
    host="$(hostname)"
    if printf '%s' "${host}" | grep -Eq "${LAB_PROHIBIDOS}"; then
        lab_stop "hostname '${host}' prohibido para estos guiones (maquina de orquestacion o produccion)"
    fi
    [ "${S9K_LAB_CONFIRMADO:-}" = "VM112" ] \
        || lab_stop "falta S9K_LAB_CONFIRMADO=VM112: confirme que esta maquina es el laboratorio"
    command -v flock >/dev/null 2>&1 || lab_stop "falta flock"
    mkdir -p "${LAB_LOGS}"
}

# Guarda COMPLETA (escenarios A/B/C, que necesitan root): PARA si no hay sudo o systemd, o si no es el laboratorio.
lab_guard() {
    local host
    host="$(hostname)"
    if printf '%s' "${host}" | grep -Eq "${LAB_PROHIBIDOS}"; then
        lab_stop "hostname '${host}' prohibido para estos guiones (maquina de orquestacion o produccion)"
    fi
    [ "${S9K_LAB_CONFIRMADO:-}" = "VM112" ] \
        || lab_stop "falta S9K_LAB_CONFIRMADO=VM112: confirme que esta maquina es el laboratorio"
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || lab_stop "no eres root y no hay sudo"
        sudo -n true 2>/dev/null || lab_stop "sudo sin contrasena no disponible (los escenarios necesitan root: useradd, systemd, chown)"
    fi
    command -v systemctl >/dev/null 2>&1 || lab_stop "no hay systemctl"
    [ -d /run/systemd/system ] || lab_stop "systemd no es el init de esta maquina (/run/systemd/system ausente)"
    command -v runuser >/dev/null 2>&1 || lab_stop "falta runuser (util-linux)"
    command -v flock >/dev/null 2>&1 || lab_stop "falta flock"
    mkdir -p "${LAB_LOGS}"
}

# Toma el cerrojo de carga pesada del laboratorio (los demas carriles de VM112 lo
# respetan) y lo retiene hasta que el guion termina. Espera si otro lo tiene.
lab_tomar_cerrojo() {
    mkdir -p "$(dirname "${LAB_HEAVY_LOCK}")"
    exec {LAB_LOCK_FD}>"${LAB_HEAVY_LOCK}"
    flock "${LAB_LOCK_FD}"
    lab_log "cerrojo ${LAB_HEAVY_LOCK} tomado"
}

lab_sha() {
    if [ -n "${S9K_LAB_SHA:-}" ]; then printf '%s' "${S9K_LAB_SHA}"; return; fi
    git -C "${LAB_REPO}" rev-parse HEAD
}

# Escribe /etc/s9-knowledge de laboratorio a partir de las plantillas LITERALES del
# repo (solo cambia lo que cambiaria un operador: URL publica y, en lab, HTTP).
lab_configurar() {
    local sha="$1" cfg=/etc/s9-knowledge
    lab_registrar "dir /etc/s9-knowledge (config, secretos, deploy.env, viewer.env, worker.env)"
    sudo install -d -m 0700 "${cfg}" "${cfg}/secrets"
    sudo install -m 0600 "${LAB_REPO}/deploy/config/viewer.env.example" "${cfg}/viewer.env"
    sudo install -m 0600 "${LAB_REPO}/deploy/config/worker.env.example" "${cfg}/worker.env"
    # laboratorio: HTTP plano declarado (opt-out explicito de lab) y URL publica de prueba.
    sudo sed -i -e 's|^S9K_SESSION_SECURE=.*|S9K_SESSION_SECURE=false|' \
                -e 's|^S9K_PUBLIC_BASE_URL=.*|S9K_PUBLIC_BASE_URL=https://lab.s9k.invalid|' "${cfg}/viewer.env"
    # secretos de laboratorio: contenido aleatorio generado aqui, nunca en argv ni en el repo.
    local f
    for f in neo4j_password neo4j_worker_password; do
        if [ ! -s "${cfg}/secrets/${f}" ]; then
            head -c 24 /dev/urandom | base64 | sudo tee "${cfg}/secrets/${f}" >/dev/null
        fi
        sudo chmod 0600 "${cfg}/secrets/${f}"
    done
    # origen del repo para el clon de la release: el clon local del laboratorio.
    printf 'S9K_REPO_URL=%s\n' "${LAB_REPO}" | sudo tee "${cfg}/deploy.env" >/dev/null
    sudo chmod 0600 "${cfg}/deploy.env"
    lab_log "configuracion de laboratorio escrita en ${cfg} (sha ${sha})"
}

# Un unico fallo se registra con su contexto y se sale con error: nada de seguir.
lab_assert() {
    local descripcion="$1"; shift
    if "$@"; then lab_log "PASS  ${descripcion}"; else lab_fail "${descripcion}"; fi
}

lab_modo()  { sudo stat -c '%a' "$1"; }
lab_owner() { sudo stat -c '%U:%G' "$1"; }
lab_sha256() { sudo sha256sum "$1" | cut -d' ' -f1; }

# Si `python3 -m venv` no puede crear un venv con pip (Debian sin python3-venv/ensurepip), deploy.sh
# (que construye un venv por release) lo haria fallar. En el LABORATORIO se antepone al PATH un
# `python3` que atiende `-m venv X` con `--without-pip` + get-pip.py y delega todo lo demas en
# /usr/bin/python3. No instala paquetes del sistema ni toca nada de /usr.
lab_shim_python() {
    local shim="${LAB_BASE}/shim"
    mkdir -p "${shim}"
    [ -s "${LAB_BASE}/get-pip.py" ] || curl -fsS --max-time 60 -o "${LAB_BASE}/get-pip.py" https://bootstrap.pypa.io/get-pip.py
    cat > "${shim}/python3" <<SHIM
#!/usr/bin/env bash
if [ "\${1:-}" = "-m" ] && [ "\${2:-}" = "venv" ] && [ -n "\${3:-}" ] && ! /usr/bin/python3 -c 'import ensurepip' 2>/dev/null; then
    /usr/bin/python3 -m venv --without-pip "\$3" && "\$3/bin/python" "${LAB_BASE}/get-pip.py" -q
else
    exec /usr/bin/python3 "\$@"
fi
SHIM
    chmod 0755 "${shim}/python3"
}

# deploy.sh del laboratorio (siempre --environment lab, nunca production).
lab_deploy() {
    local modo="$1"; shift
    lab_shim_python
    sudo env "PATH=${LAB_BASE}/shim:${PATH}" S9K_ENVIRONMENT=lab "${LAB_REPO}/deploy/scripts/deploy.sh" \
        --environment lab --release-ref "$(lab_sha)" --mode "${modo}" --confirm "$@"
}

# Todo el estado cumple el contrato (la MISMA comprobacion del arranque).
lab_estado_conforme() {
    sudo python3 "${LAB_REPO}/data-engine/app/knowledge_v3/service_state.py" check \
        --state-root /var/lib/s9-knowledge --env-file /etc/s9-knowledge/viewer.env
}

# El proceso principal de cada unidad corre como el usuario de servicio.
lab_procesos_como_servicio() {
    local u pid
    for u in s9-knowledge-viewer.service s9-knowledge-worker.service; do
        pid="$(systemctl show -p MainPID --value "${u}")"
        [ -n "${pid}" ] && [ "${pid}" != "0" ] || { echo "sin proceso para ${u}" >&2; return 1; }
        [ "$(ps -o user= -p "${pid}")" = "s9knowledge" ] || { echo "${u}: pid ${pid} corre como $(ps -o user= -p "${pid}")" >&2; return 1; }
    done
}

# Convierte la instalacion actual (la del escenario A) en una instalacion LEGACY
# anterior a H-06/H-08: servicios parados, estado root:root con modos 0644/0660,
# decisions/audit/candidatos/propuestas DENTRO de la release (como el codigo antiguo)
# y las unidades REALES del commit base ($1 = SHA base). Deja el visor legacy en marcha.
# Variables que deja: RV3_REL (directorio de reviews-v3 de la release actual).
lab_convertir_en_legacy() {
    local base_sha="$1" state=/var/lib/s9-knowledge actual
    actual="$(readlink -f /opt/s9-knowledge/current)"
    RV3_REL="${actual}/viewer/output/reviews-v3"
    lab_registrar "unit /etc/systemd/system/s9-knowledge-{viewer,worker}.service (fixture legacy)"
    sudo systemctl stop s9-knowledge-healthcheck.timer s9-knowledge-viewer.service s9-knowledge-worker.service 2>/dev/null || true
    sudo install -d -m 0755 "${RV3_REL}/glossary-candidates/ws" "${RV3_REL}/proposals"
    printf '{"decision_id":"legacy:1","h":"APPROVE"}\n{"decision_id":"legacy:2","h":"REJECT"}\n' | sudo tee "${RV3_REL}/decisions.jsonl" >/dev/null
    printf '{"event":"STALE_REVIEW","n":1}\n' | sudo tee "${RV3_REL}/audit.jsonl" >/dev/null
    printf '{"candidate_id":"glossary:legacy"}\n' | sudo tee "${RV3_REL}/glossary-candidates/ws/candidates.jsonl" >/dev/null
    printf '{"proposal_id":"p-legacy"}' | sudo tee "${RV3_REL}/proposals/p-legacy.json" >/dev/null
    sudo chmod 0644 "${RV3_REL}/decisions.jsonl" "${RV3_REL}/audit.jsonl" \
        "${RV3_REL}/glossary-candidates/ws/candidates.jsonl" "${RV3_REL}/proposals/p-legacy.json"
    sudo chown -R root:root "${state}"
    sudo find "${state}" -path "${state}/deploy" -prune -o -type d -exec chmod 0755 {} +
    sudo find "${state}" -path "${state}/deploy" -prune -o -type f -exec chmod 0644 {} +
    sudo chmod 0660 "${state}/reviews-v3/review.sqlite3"
    [ "$(lab_owner "${state}/auth/auth.db")" = "root:root" ] || lab_fail "la fixture legacy no quedo root:root"
    [ "$(lab_modo "${state}/auth/auth.db")" = "644" ] || lab_fail "la fixture legacy no quedo 0644"
    sudo git -C "${LAB_REPO}" show "${base_sha}:viewer/systemd/s9-knowledge-viewer.service" \
        | sudo tee /etc/systemd/system/s9-knowledge-viewer.service >/dev/null
    sudo git -C "${LAB_REPO}" show "${base_sha}:data-engine/systemd/s9-knowledge-worker.service" \
        | sudo tee /etc/systemd/system/s9-knowledge-worker.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl start s9-knowledge-viewer.service || true
    sleep 3
}
