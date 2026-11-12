#!/usr/bin/env bash
# Librería común para los scripts operativos de S9 Knowledge.
# Sin secretos. Solo funciones de apoyo.
# shellcheck shell=bash
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# H-06 + H-08 · UNA AUTORIDAD para usuario de servicio, state root, modo de
# fichero y modo de directorio: `service_state.py`. Aquí NO se escribe ninguna
# de esas cifras; se PIDEN (`servicio_cifra service_user`). Solo stdlib.
# ---------------------------------------------------------------------------
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S9K_SERVICE_STATE_PY="${S9K_SERVICE_STATE_PY:-${_LIB_DIR}/../../data-engine/app/knowledge_v3/service_state.py}"
VIEWER_UNIT_NAME="s9-knowledge-viewer.service"
WORKER_UNIT_NAME_LIB="s9-knowledge-worker.service"
HEALTH_UNIT_NAME="s9-knowledge-healthcheck.service"
HEALTH_TIMER_NAME="s9-knowledge-healthcheck.timer"

# ---------------------------------------------------------------------------
# Raíces configurables (sobreescribibles por variables de entorno)
# El state root por defecto sale de la AUTORIDAD (no es un literal de aquí).
# ---------------------------------------------------------------------------
S9K_ROOT="${S9K_ROOT:-/opt/s9-knowledge}"
S9K_STATE_ROOT="${S9K_STATE_ROOT:-$(python3 "${S9K_SERVICE_STATE_PY}" get state_root)}"
S9K_CONFIG_ROOT="${S9K_CONFIG_ROOT:-/etc/s9-knowledge}"
S9K_LOG_ROOT="${S9K_LOG_ROOT:-/var/log/s9-knowledge}"
S9K_VIEWER_URL="${S9K_VIEWER_URL:-http://127.0.0.1:8088}"
if [ -z "${S9K_STATE_ROOT}" ]; then
    echo "lib.sh: la autoridad de estado (${S9K_SERVICE_STATE_PY}) no respondió" >&2
    # shellcheck disable=SC2317
    return 1 2>/dev/null || exit 1
fi

# Número de releases a conservar (las más antiguas se eliminan automáticamente)
S9K_RELEASES_TO_KEEP="${S9K_RELEASES_TO_KEEP:-3}"

# ---------------------------------------------------------------------------
# Colores de terminal
# ---------------------------------------------------------------------------
_c_reset='\033[0m'
_c_red='\033[31m'
_c_grn='\033[32m'
_c_yel='\033[33m'
_c_blu='\033[34m'

# ---------------------------------------------------------------------------
# Funciones de log (siempre a stderr excepto log que va a stdout también)
# Las variables se pasan a printf de forma segura (sin eval, sin expansión no controlada)
# ---------------------------------------------------------------------------
log()  { printf '%b[s9k]%b %s\n'  "$_c_grn"  "$_c_reset" "$*"; }
warn() { printf '%b[s9k]%b %s\n'  "$_c_yel"  "$_c_reset" "$*" >&2; }
err()  { printf '%b[s9k]%b %s\n'  "$_c_red"  "$_c_reset" "$*" >&2; }
info() { printf '%b[s9k]%b %s\n'  "$_c_blu"  "$_c_reset" "$*"; }
die()  { err "$*"; exit 1; }
# ok: resultado satisfactorio de un check. Definida aquí para que todos los
# scripts que sourcean lib.sh puedan usarla sin que el texto del argumento
# se ejecute como comando (el bug histórico de verify-deployment.sh).
ok()   { log "PASS $*"; }

# ---------------------------------------------------------------------------
# Comprueba que existe un comando.
# ---------------------------------------------------------------------------
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "falta el comando requerido: $1"
}

# ---------------------------------------------------------------------------
# Comprueba un puerto TCP escuchando localmente (ss con fallback a netstat).
# ---------------------------------------------------------------------------
port_listening() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${1}$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${1}$"
    else
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Devuelve el commit corto del repo actual (o 'unknown').
# ---------------------------------------------------------------------------
repo_commit() {
    git -C "${S9K_ROOT}/current" rev-parse --short HEAD 2>/dev/null \
        || git rev-parse --short HEAD 2>/dev/null \
        || printf 'unknown'
}

# ---------------------------------------------------------------------------
# resolve_release_commit <ref> [--repo-url URL] [--work-dir DIR] [--allow-branch]
#
# Resuelve UNA referencia de release a un ÚNICO SHA de commit canónico.
# Es la función central de resolución de refs para todo el utillaje de deploy:
# ninguna otra ruta debe reimplementar "rev-parse || echo <ref>".
#
# CONTRATO (regresión "forward-ref" corregida):
#   entrada admitida  : tag deploy-*, SHA completo, SHA corto inequívoco;
#                       branch SOLO con --allow-branch (entorno de desarrollo).
#   stdout            : EXCLUSIVAMENTE el SHA del commit (40/64 hex) + \n.
#                       Nunca el ref original, ni mensajes, ni "ok", ni espacios.
#   stderr            : todos los diagnósticos.
#   código de salida  : 0 si resuelve a un commit; != 0 en cualquier otro caso.
#
# Procedimiento: 1) validar sintaxis; 2) resolver local en silencio;
#   3) si falta y hay --repo-url, fetch específico y seguro; 4) resolver a
#   <ref>^{commit}; 5) validar que el objeto es un commit; 6) emitir un único
#   SHA; 7) return 0. `git rev-parse --verify -q` es silencioso, falla sin
#   emitir nada, y rechaza refs ambiguas (múltiples objetos) por diseño.
# ---------------------------------------------------------------------------
resolve_release_commit() {
    local ref="" repo_url="" work_dir="${S9K_ROOT}/current" allow_branch=0
    local positional_set=0
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --repo-url)     repo_url="${2:-}"; shift 2 ;;
            --work-dir)     work_dir="${2:-}"; shift 2 ;;
            --allow-branch) allow_branch=1; shift ;;
            --)             shift; ref="${1:-}"; positional_set=1; shift || true ;;
            -*)             err "resolve_release_commit: opción desconocida: $1"; return 2 ;;
            *)              if [ "${positional_set}" -eq 0 ]; then ref="$1"; positional_set=1; shift
                            else err "resolve_release_commit: exceso de argumentos"; return 2; fi ;;
        esac
    done

    # (1) Validación sintáctica estricta -----------------------------------
    [ -n "${ref}" ] || { err "resolve_release_commit: ref vacía"; return 2; }
    # Rechazar inyección de opciones: una ref nunca empieza por '-'.
    case "${ref}" in -*) err "resolve_release_commit: ref no puede empezar por '-': ${ref}"; return 2 ;; esac
    # Charset seguro: hex, letras, dígitos, '.', '_', '/', '-'. Cualquier otra
    # cosa (espacios, saltos de línea, '^', '~', ':', '@{', control) se rechaza.
    case "${ref}" in *[!A-Za-z0-9._/-]*) err "resolve_release_commit: ref con caracteres no permitidos: ${ref}"; return 2 ;; esac
    # En modo release (sin --allow-branch) solo se admite tag deploy-* o SHA hex.
    if [ "${allow_branch}" -ne 1 ]; then
        case "${ref}" in
            deploy-*) : ;;
            *) case "${ref}" in
                   *[!0-9a-fA-F]*) err "resolve_release_commit: en modo release solo se admite tag deploy-* o SHA hex: ${ref}"; return 2 ;;
                   *) [ "${#ref}" -ge 7 ] || { err "resolve_release_commit: SHA demasiado corto (ambiguo): ${ref}"; return 2; } ;;
               esac ;;
        esac
    fi
    [ -d "${work_dir}/.git" ] || [ -d "${work_dir}" ] || { err "resolve_release_commit: work-dir inexistente: ${work_dir}"; return 2; }

    local sha=""
    # (2) Resolución local silenciosa. --verify -q emite el SHA solo si resuelve
    #     a un único objeto commit; nada (y rc!=0) en fallo o ambigüedad.
    if sha="$(git -C "${work_dir}" rev-parse --verify -q "${ref}^{commit}" 2>/dev/null)"; then
        printf '%s\n' "${sha}"; return 0
    fi

    # (3) No está localmente: hace falta fetch. Sin URL no se puede materializar.
    if [ -z "${repo_url}" ]; then
        err "resolve_release_commit: '${ref}' no está en ${work_dir} y no se dio --repo-url para traerlo"; return 1
    fi
    case "${repo_url}" in -*) err "resolve_release_commit: repo-url no puede empezar por '-'"; return 2 ;; esac

    # Fetch específico y seguro. '--' separa opciones de refs para que ni ref ni
    # url puedan interpretarse como opciones de git-fetch. FETCH_HEAD contiene
    # exactamente lo que se pidió.
    if git -C "${work_dir}" fetch --quiet --tags -- "${repo_url}" "${ref}" 2>/dev/null; then
        if sha="$(git -C "${work_dir}" rev-parse --verify -q "FETCH_HEAD^{commit}" 2>/dev/null)"; then
            printf '%s\n' "${sha}"; return 0
        fi
    fi
    # Fallback: muchos servidores no sirven SHA arbitrarios por 'want'. Traer
    # todas las tags (y, si se permite, las ramas a un namespace propio) y
    # re-resolver por nombre. Nunca se hace fetch en 'current' (rompería su
    # checksum): el work-dir es la copia nueva o un laboratorio.
    git -C "${work_dir}" fetch --quiet --tags -- "${repo_url}" 2>/dev/null || true
    if [ "${allow_branch}" -eq 1 ]; then
        git -C "${work_dir}" fetch --quiet -- "${repo_url}" '+refs/heads/*:refs/remotes/s9k-resolve/*' 2>/dev/null || true
    fi
    if sha="$(git -C "${work_dir}" rev-parse --verify -q "${ref}^{commit}" 2>/dev/null)"; then
        printf '%s\n' "${sha}"; return 0
    fi
    if [ "${allow_branch}" -eq 1 ] && sha="$(git -C "${work_dir}" rev-parse --verify -q "refs/remotes/s9k-resolve/${ref}^{commit}" 2>/dev/null)"; then
        printf '%s\n' "${sha}"; return 0
    fi
    err "resolve_release_commit: no se pudo resolver '${ref}' a un commit tras fetch desde el remoto"
    return 1
}

# ---------------------------------------------------------------------------
# Genera un ID único de release: <git-short-sha>-<timestamp>
# Requiere que el directorio de trabajo tenga un .git accesible.
# ---------------------------------------------------------------------------
create_release_id() {
    local repo_dir="${1:-.}"
    local short_sha
    short_sha="$(git -C "${repo_dir}" rev-parse --short HEAD 2>/dev/null || printf 'nogit')"
    local ts
    ts="$(date -u '+%Y%m%d-%H%M%S')"
    printf '%s-%s' "${short_sha}" "${ts}"
}

# ---------------------------------------------------------------------------
# Symlink atómico: reemplaza <link> apuntando a <target> sin ventana de rotura.
# Usa un nombre temporal + mv -T (Linux) o mv con overwrite.
# ---------------------------------------------------------------------------
atomic_symlink() {
    local target="${1}"
    local link="${2}"
    local tmp_link
    tmp_link="${link}.tmp.$$"
    ln -sfn "${target}" "${tmp_link}"
    # mv -T fuerza que el destino sea exactamente el nombre dado (no dentro de él)
    if mv -T "${tmp_link}" "${link}" 2>/dev/null; then
        return 0
    else
        # Fallback: mv sin -T (algunos sistemas no lo soportan)
        mv "${tmp_link}" "${link}"
    fi
}

# ---------------------------------------------------------------------------
# Adquiere un lock exclusivo en /var/lock/s9k-deploy.lock.
# El FD 200 se hereda por el proceso que llama; el lock se libera al salir.
# ---------------------------------------------------------------------------
lock_deploy() {
    local lockfile="/var/lock/s9k-deploy.lock"
    # Intentamos crear el lockfile; si no tenemos permisos en /var/lock usamos /tmp
    if ! touch "${lockfile}" 2>/dev/null; then
        lockfile="/tmp/s9k-deploy.lock"
    fi
    exec 200>"${lockfile}"
    if ! flock -n 200; then
        die "Otro proceso de deploy/rollback está en ejecución (${lockfile}). Espera o elimina el lock."
    fi
    log "Lock adquirido: ${lockfile}"
}

# ---------------------------------------------------------------------------
# Valida que un fichero JSON de manifiesto tiene los campos obligatorios.
# No imprime el contenido completo (puede tener rutas). Solo valida estructura.
# ---------------------------------------------------------------------------
validate_manifest() {
    local manifest_path="${1}"
    if [ ! -f "${manifest_path}" ]; then
        err "Manifiesto no encontrado: ${manifest_path}"
        return 1
    fi
    local required_fields="release_id git_commit created_at created_by python_version schema_versions compatible_rollback_to"
    for field in ${required_fields}; do
        if ! python3 -c "
import json, sys
try:
    d = json.load(open('${manifest_path}'))
    sys.exit(0 if '${field}' in d else 1)
except Exception:
    sys.exit(2)
" 2>/dev/null; then
            err "Manifiesto inválido: falta campo '${field}' en ${manifest_path}"
            return 1
        fi
    done
    return 0
}

# ---------------------------------------------------------------------------
# Checksum de contenido de una release.
#
# Lista de exclusión ÚNICA y COMPARTIDA entre generación (create_manifest) y
# verificación (verify_release_checksum). Si divergen, el checksum es inútil.
#
# Solo se excluye contenido DERIVADO o MUTABLE (bytecode, cachés de test,
# cobertura, logs, temporales). Nunca código, templates, static, units, scripts
# ni el resto del contenido versionado.
#
# manifest.json se excluye porque contiene el propio checksum (autorreferencia).
#
# `-type f` deja fuera por construcción sockets, FIFOs, dispositivos y symlinks.
# ---------------------------------------------------------------------------
S9K_CHECKSUM_EXCLUDE_DIRS="${S9K_CHECKSUM_EXCLUDE_DIRS:-.venv __pycache__ .pytest_cache .mypy_cache .ruff_cache .tox htmlcov node_modules}"
# OJO: no excluir *.bak — data-engine/backups/*.bak es contenido VERSIONADO real,
# no un artefacto derivado. Excluirlo dejaría código fuera del checksum.
S9K_CHECKSUM_EXCLUDE_GLOBS="${S9K_CHECKSUM_EXCLUDE_GLOBS:-manifest.json *.pyc *.pyo *.pyd *.log *.tmp *.temp *.swp *.swo .coverage .coverage.* coverage.xml}"

# Lista los ficheros que ENTRAN en el checksum (NUL-separados).
_checksum_file_list() {
    local dir="${1}"
    local -a args=( "${dir}" )
    local d g first=1

    args+=( '(' )
    for d in ${S9K_CHECKSUM_EXCLUDE_DIRS}; do
        [ "${first}" -eq 1 ] || args+=( -o )
        args+=( -name "${d}" )
        first=0
    done
    args+=( ')' -prune -o -type f )

    for g in ${S9K_CHECKSUM_EXCLUDE_GLOBS}; do
        args+=( ! -name "${g}" )
    done
    args+=( -print0 )

    find "${args[@]}"
}

# Algoritmo declarado en los manifiestos NUEVOS. Los emitidos antes del hotfix
# no llevan campo `checksum_algo` y se verifican con la fórmula v1.
S9K_CHECKSUM_ALGO="v2"

# release_files_checksum_v1 <release_dir> -> imprime "sha256:<hex>"
#
# Verificador de compatibilidad para manifiestos emitidos ANTES del hotfix.
#
# Conserva el flujo original (rutas absolutas, `sort` del locale, `xargs
# sha256sum`) para reproducir el valor declarado, pero PODA los artefactos
# derivados. Esa poda no altera el resultado: los artefactos no existían cuando
# se emitió el manifiesto. Sin ella, v1 es inverificable en produccion, porque el
# propio servicio en marcha regenera __pycache__ y se invalida solo.
#
# Comprobado contra la release real de RC2: con 172 cachés presentes reproduce
# exactamente el files_checksum del manifiesto.
#
# LIMITACIÓN CONOCIDA — v1 NO es un control antimanipulación:
#
#   `xargs` sin -0 parte los nombres por los espacios, así que sha256sum nunca
#   ve los ficheros cuyo nombre los contiene: quedan FUERA del hash. En la
#   release de RC2 eso afecta a un fichero real y versionado:
#       docs/project dossier and checklist.md
#   (la fórmula original hashea 431 ficheros; la correcta, 432).
#
#   Es decir: ese fichero puede alterarse sin que v1 lo detecte. El defecto es
#   del manifiesto emitido, no de este verificador; corregirlo aquí solo haría
#   que v1 dejara de reproducir lo declarado y abortara despliegues sanos.
#
#   v2 sí lo cubre (-print0/-0). Cada release nueva nace con manifiesto v2, con
#   lo que el punto ciego desaparece en cuanto RC2 deje de ser la release activa.
#
# NO usar para releases nuevas: además, el `sort` del locale no es reproducible
# entre entornos. Para eso está v2.
release_files_checksum_v1() {
    local dir="${1}"
    if [ ! -d "${dir}" ]; then
        err "release_files_checksum_v1: no es un directorio: ${dir}"
        return 1
    fi
    need_cmd find; need_cmd sha256sum
    local hash
    # `xargs` SIN -0 y `sort` SIN LC_ALL=C: ambos defectos se conservan a
    # propósito. v1 no es un algoritmo que se elija, es el que ya se usó: su
    # único trabajo es reproducir lo que declara un manifiesto ya emitido.
    # "Arreglarlo" haría que dejara de coincidir y la compuerta abortaría
    # despliegues de releases sanas.
    #
    # `set +o pipefail` en la subshell: ante un nombre con espacios, xargs parte
    # la ruta, sha256sum falla sobre los trozos y xargs sale 123. El hash que
    # imprime awk es correcto igualmente (es justo el que declara el manifiesto),
    # pero con pipefail la pipeline se da por fallida. Sin esto la función solo
    # "funcionaba" cuando se la llamaba dentro de un `||`, porque ahí bash
    # suprime errexit: dependía del contexto de llamada.
    # shellcheck disable=SC2038  # fidelidad deliberada con la fórmula original
    hash="$(set +o pipefail
        find "${dir}" \
            \( -name .venv -o -name __pycache__ -o -name .pytest_cache \
               -o -name .mypy_cache -o -name .ruff_cache \) -prune -o \
            -type f ! -name 'manifest.json' ! -name '*.pyc' ! -name '*.pyo' -print \
            | sort | xargs sha256sum 2>/dev/null | sha256sum | awk '{print $1}')"
    if [ -z "${hash}" ]; then
        err "release_files_checksum_v1: no se pudo calcular el hash en ${dir}"
        return 1
    fi
    printf 'sha256:%s' "${hash}"
}

# release_files_checksum <release_dir> -> imprime "sha256:<hex>"  (algoritmo v2)
#
# Se fija LC_ALL=C porque el `sort` de v1 dependía del locale y por tanto no era
# reproducible entre entornos. Eso, junto con las exclusiones ampliadas, hace que
# v2 NO reproduzca los checksums de v1: por eso el algoritmo va versionado en el
# manifiesto en vez de romper los ya emitidos.
release_files_checksum() {
    local dir="${1}"
    if [ ! -d "${dir}" ]; then
        err "release_files_checksum: no es un directorio: ${dir}"
        return 1
    fi
    need_cmd find; need_cmd sha256sum
    local hash
    hash="$(_checksum_file_list "${dir}" \
        | LC_ALL=C sort -z \
        | xargs -0 -r sha256sum 2>/dev/null \
        | sha256sum | awk '{print $1}')"
    printf 'sha256:%s' "${hash}"
}

# verify_release_checksum <release_dir> [manifest_path]
#   0 = coincide · 1 = NO coincide o no se puede comprobar.
#   Nunca reescribe el manifiesto: solo compara e informa.
verify_release_checksum() {
    local dir="${1}"
    local manifest="${2:-${dir}/manifest.json}"
    if [ ! -f "${manifest}" ]; then
        err "verify_release_checksum: manifiesto no encontrado: ${manifest}"
        return 1
    fi
    local expected actual algo
    expected="$(manifest_field "${manifest}" files_checksum)"
    if [ -z "${expected}" ] || [ "${expected}" = "unknown" ]; then
        err "verify_release_checksum: el manifiesto no declara files_checksum utilizable"
        return 1
    fi

    # Sin campo `checksum_algo` el manifiesto es anterior al hotfix: se verifica
    # con v1, que es la fórmula con la que se emitió. Verificarlo con v2 daría un
    # falso "release alterada" en releases perfectamente sanas (RC2 incluida).
    algo="$(manifest_field "${manifest}" checksum_algo)"
    [ -n "${algo}" ] || algo="v1"

    case "${algo}" in
        v1) actual="$(release_files_checksum_v1 "${dir}")" || return 1 ;;
        v2) actual="$(release_files_checksum "${dir}")" || return 1 ;;
        *)  err "verify_release_checksum: algoritmo desconocido '${algo}'"; return 1 ;;
    esac

    if [ "${expected}" = "${actual}" ]; then
        log "checksum de release OK (${dir}, algoritmo ${algo})"
        return 0
    fi
    err "checksum de release NO coincide en ${dir} (algoritmo ${algo})"
    err "  declarado:   ${expected}"
    err "  recalculado: ${actual}"
    if [ "${algo}" = "v1" ]; then
        err "  v1 es sensible a __pycache__ y al locale: si se ejecutaron tests"
        err "  dentro de la release, borrar los artefactos derivados y reintentar."
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Genera un manifiesto JSON en <release_dir>/manifest.json.
# NO incluye secretos, variables de entorno ni tokens.
# ---------------------------------------------------------------------------
create_manifest() {
    local release_dir="${1}"
    local release_id="${2}"
    local git_commit="${3}"
    local environment="${4}"

    local python_version
    python_version="$(python3 --version 2>&1 | awk '{print $2}' || printf 'unknown')"

    # D2 (carril I): esto era el sha256 de `viewer/requirements.txt`, que es el
    # fichero de RANGOS. Dos despliegues con el mismo fingerprint podian tener
    # arboles instalados distintos: el campo afirmaba identificar las
    # dependencias y no lo hacia. Mismo genero que `auth_db: 1`.
    #
    # Ahora se calcula sobre lo REALMENTE RESUELTO (`pip freeze` del venv de la
    # release, que deploy.sh acaba de crear). Y cuando el venv no existe, el
    # valor NO se disfraza de lo que no es: lleva prefijo `ranges-sha256:` y se
    # deja constancia del modo en `dependency_fingerprint_source`, para que
    # ningun consumidor lo confunda con una huella de versiones resueltas.
    local dep_hash="unknown"
    local dep_source="none"
    #
    # Y `pip freeze` tiene que producir ALGO: un pip que sale 0 sin salida daba
    # el sha256 de la cadena vacia (e3b0c442...) etiquetado como resuelto, que
    # es el mismo defecto que D2 venia a cerrar —un campo que afirma
    # identificar dependencias resueltas sin identificar ninguna— y ademas dos
    # despliegues rotos compartirian huella y se leerian como «mismas
    # dependencias». Se exige salida no vacia y que contenga los paquetes
    # declarados; si no, el modo es `unresolved` y NO se disfraza de resuelto.
    local venv_pip="${release_dir}/viewer/.venv/bin/pip"
    local freeze_out=""
    if [ -x "${venv_pip}" ]; then
        freeze_out="$("${venv_pip}" freeze --all 2>/dev/null | LC_ALL=C sort || true)"
    fi
    local freeze_ok=0
    local declarados=""
    if [ -n "${freeze_out}" ]; then
        freeze_ok=1
        if [ -f "${release_dir}/viewer/requirements.txt" ]; then
            declarados="$(sed -e 's/#.*//' -e 's/[][<>=!~,;].*//' \
                              -e 's/[[:space:]]//g' \
                              "${release_dir}/viewer/requirements.txt" \
                          | grep -v '^$' || true)"
            local paquete paquete_re
            for paquete in ${declarados}; do
                # OJO con la clase: incluir `-` hacia que `fastapi-extra==1.0`
                # satisficiera el requisito de `fastapi`, y un venv sin
                # `fastapi` se etiquetaba `resolved:pip-freeze`. El separador
                # valido tras el nombre es `=`, `<`, `>`, `!`, `~`, `@` o
                # espacio; `-` forma parte del NOMBRE del paquete siguiente.
                #
                # Y el NOMBRE se interpola como TEXTO, no como patron. Sin
                # escapar, el `.` de `zope.interface` era un comodin y
                # `zope-interface` satisfacia el requisito: la huella se
                # etiquetaba `resolved:pip-freeze` afirmando identificar unas
                # dependencias que no eran las declaradas. Es el mismo defecto
                # que la clase con `-`, por la otra punta.
                # Se escapa TODO lo que no sea alfanumerico, `_` o `-`: un
                # nombre PEP 508 solo puede llevar ademas `.`, asi que esto lo
                # cubre entero sin depender de acertar una lista de
                # metacaracteres (la primera version de esta linea se equivoco
                # justo ahi, con una clase mal cerrada que no escapaba nada).
                paquete_re="$(printf '%s' "${paquete}" \
                              | sed 's/[^A-Za-z0-9_-]/\\&/g')"
                if ! printf '%s\n' "${freeze_out}" \
                     | grep -qiE "^${paquete_re}([[:space:]=<>!~@]|$)"; then
                    freeze_ok=0
                    break
                fi
            done
        fi
    fi
    if [ "${freeze_ok}" -eq 1 ]; then
        dep_hash="sha256:$(printf '%s\n' "${freeze_out}" | sha256sum | awk '{print $1}')"
        dep_source="resolved:pip-freeze"
    elif [ -x "${venv_pip}" ]; then
        dep_hash="unknown"
        dep_source="unresolved"
        printf 'AVISO: pip freeze del venv no identifica las dependencias declaradas; dependency_fingerprint=unknown\n' >&2
    elif [ -f "${release_dir}/viewer/requirements.txt" ]; then
        dep_hash="ranges-sha256:$(sha256sum "${release_dir}/viewer/requirements.txt" | awk '{print $1}')"
        dep_source="declared-ranges"
    fi

    # Usa la MISMA lista de exclusión que verify_release_checksum.
    local files_hash="unknown"
    if command -v find >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
        files_hash="$(release_files_checksum "${release_dir}")"
    fi

    local created_at
    created_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    # Versiones de esquema: se EXTRAEN del código de la release. Antes eran un
    # literal `{"auth_db": 1, "job_store": 1}` aquí mismo, y llevaban años
    # mintiendo (el código iba por SCHEMA_VERSION = 3). Si no se pueden leer,
    # se aborta: un manifiesto que declara una versión inventada es peor que
    # un despliegue que no arranca.
    local schema_block
    if ! schema_block="$(python3 "$(dirname "${BASH_SOURCE[0]}")/schema_versions.py" "${release_dir}")"; then
        echo "ERROR: no se pudieron determinar las versiones de esquema de ${release_dir}" >&2
        return 1
    fi

    python3 - <<PYEOF
import json
schema_block = json.loads(r'''${schema_block}''')
manifest = {
    "release_id": "${release_id}",
    "git_commit": "${git_commit}",
    "environment": "${environment}",
    "created_at": "${created_at}",
    "created_by": "deploy.sh",
    "python_version": "${python_version}",
    "dependency_fingerprint": "${dep_hash}",
    "dependency_fingerprint_source": "${dep_source}",
    "schema_versions": schema_block["schema_versions"],
    "schema_supported_ranges": schema_block["schema_supported_ranges"],
    "compatible_rollback_to": [],
    "files_checksum": "${files_hash}",
    "checksum_algo": "${S9K_CHECKSUM_ALGO}"
}
with open("${release_dir}/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
print("Manifiesto creado: ${release_dir}/manifest.json")
PYEOF
}

# ---------------------------------------------------------------------------
# Lee un campo del manifiesto JSON de forma segura.
# ---------------------------------------------------------------------------
manifest_field() {
    local manifest_path="${1}"
    local field="${2}"
    python3 -c "
import json, sys
try:
    d = json.load(open('${manifest_path}'))
    print(d.get('${field}', ''))
except Exception as e:
    print('', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || printf ''
}

# ---------------------------------------------------------------------------
# Lista las releases disponibles ordenadas de más nueva a más antigua.
# ---------------------------------------------------------------------------
list_releases() {
    local releases_dir="${S9K_ROOT}/releases"
    if [ ! -d "${releases_dir}" ]; then
        warn "No existe directorio de releases: ${releases_dir}"
        return 0
    fi
    find "${releases_dir}" -maxdepth 1 -mindepth 1 -type d | sort -r
}

# ---------------------------------------------------------------------------
# Devuelve el ID de la release actualmente activa (symlink current).
# ---------------------------------------------------------------------------
current_release_id() {
    local current_link="${S9K_ROOT}/current"
    if [ -L "${current_link}" ]; then
        basename "$(readlink -f "${current_link}")"
    else
        printf ''
    fi
}

# ---------------------------------------------------------------------------
# Escribe /var/lib/s9-knowledge/deploy/deployment-state.json de forma atómica.
# Uso: write_deployment_state <active_release> <active_commit>
#                             <previous_release|-> <previous_commit|->
#                             <deployment_id>
# Los campos prev* aceptan '-' para indicar "no aplica".
# ---------------------------------------------------------------------------
write_deployment_state() {
    local active_release="${1}"
    local active_commit="${2}"
    local previous_release="${3:-}"
    local previous_commit="${4:-}"
    local deployment_id="${5:-}"
    local state_file="${S9K_DEPLOY_STATE_FILE:-${S9K_STATE_ROOT}/deploy/deployment-state.json}"
    local here_scripts
    here_scripts="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "${here_scripts}/retention.py" \
        --state-file "${state_file}" \
        --write-state \
        "${active_release}" \
        "${active_commit}" \
        "${previous_release:--}" \
        "${previous_commit:--}" \
        "${deployment_id}" \
    || warn "write_deployment_state: fallo al escribir ${state_file} (no bloquea el deploy)"
}

# ---------------------------------------------------------------------------
# Elimina releases antiguas de forma FAIL-CLOSED usando retention.py.
# POR DEFECTO: dry-run. Para borrar de verdad: S9K_RETENTION_APPLY=1.
# ---------------------------------------------------------------------------
cleanup_old_releases() {
    local here_scripts
    here_scripts="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local state_file="${S9K_DEPLOY_STATE_FILE:-${S9K_STATE_ROOT}/deploy/deployment-state.json}"
    local mode="--dry-run"
    [ "${S9K_RETENTION_APPLY:-0}" = "1" ] && mode="--apply"

    log "Retención de releases (${mode}): invocando retention.py"
    python3 "${here_scripts}/retention.py" \
        --releases-root "${S9K_ROOT}/releases" \
        --current-link  "${S9K_ROOT}/current" \
        --state-file    "${state_file}" \
        --keep          "${S9K_RELEASES_TO_KEEP}" \
        "${mode}" \
    || warn "retention.py salió con error — ninguna release borrada (fail-closed)"
}

# ---------------------------------------------------------------------------
# _campo_json <json> <clave> [<clave>...] -> imprime el valor anidado.
#   Una lista se imprime unida por "; ". Sin eval: solo indexación por clave.
# ---------------------------------------------------------------------------
_campo_json() {
    local json="${1}"; shift
    printf '%s' "${json}" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1:]:
    d = d[k]
if isinstance(d, list):
    print("; ".join(str(x) for x in d))
elif isinstance(d, bool):
    print("true" if d else "false")
else:
    print(d)
' "$@"
}

# ---------------------------------------------------------------------------
# paso4_migrar_o_validar_estado <json de detect_state.py>
#
#   B2 (USABLE-V1) · H-01/H-43. Paso 4 de deploy.sh. UNA SOLA AUTORIDAD para
#   «¿se puede seguir?»: el campo `decision` de detect_state.py, que ya aplica
#   las reglas POR TIPO de base y POR MODO (upgrade|fresh).
#
#   EL DEFECTO QUE CIERRA. Antes este paso decidía con `global_state` (lo peor
#   de auth y jobs) e ignoraba `decision` y el modo: una máquina limpia con
#   `--mode fresh` daba PROCEED en el paso 3 y moría aquí por EMPTY_STATE
#   (H-01), y un host sano con jobs.db ausente o vacía no podía actualizarse
#   (H-43), contradiciendo el propio comentario de detect_state.py.
#
#   Después de decidir, la MIGRACIÓN se hace POR TIPO (auth y jobs por
#   separado); nunca se crea una auth.db vacía y nunca se elige en silencio.
#   Usa las globales de deploy.sh: HERE, LEGACY_AUTH_DB, LEGACY_JOBS_DB,
#   NEW_AUTH_DB, NEW_JOBS_DB.
# ---------------------------------------------------------------------------
paso4_migrar_o_validar_estado() {
    local json="${1}" _decision _motivos _auth _jobs
    _decision="$(_campo_json "${json}" decision)"
    if [ "${_decision}" != "PROCEED" ]; then
        _motivos="$(_campo_json "${json}" reasons)"
        die "detect_state decide ${_decision}: ${_motivos:-sin motivo} (nunca crear auth.db vacía ni elegir DB en silencio)"
    fi
    _auth="$(_campo_json "${json}" per_kind auth state)"
    _jobs="$(_campo_json "${json}" per_kind jobs state)"

    case "${_auth}" in
        LEGACY_STATE)
            log "    auth: migrando legacy -> state root (controlado, atómico, .backup)"
            python3 "${HERE}/migrate_sqlite.py" --kind auth --src "${LEGACY_AUTH_DB}" --dst "${NEW_AUTH_DB}" --apply --confirm \
                || die "migración auth falló/bloqueó"
            ;;
        NEW_STATE|MIXED_EQUIVALENT_STATE)
            log "    auth: estado nuevo ya presente y equivalente; sin migración" ;;
        EMPTY_STATE)
            # Solo llega aquí con decision=PROCEED, es decir en --mode fresh.
            log "    auth: sin usuarios (primera release). FIRST_ADMIN_PENDING: el primer"
            log "    administrador se crea en /setup/admin; el instalador NO lo crea."
            ;;
        *) die "auth en ${_auth} con decision=PROCEED: salida de detect_state incoherente" ;;
    esac

    case "${_jobs}" in
        LEGACY_STATE)
            if [ -f "${LEGACY_JOBS_DB}" ]; then
                log "    jobs: migrando legacy -> state root"
                python3 "${HERE}/migrate_sqlite.py" --kind jobs --src "${LEGACY_JOBS_DB}" --dst "${NEW_JOBS_DB}" --apply --confirm \
                    || die "migración jobs falló/bloqueó"
            fi
            ;;
        NEW_STATE|MIXED_EQUIVALENT_STATE)
            log "    jobs: estado nuevo ya presente; sin migración" ;;
        EMPTY_STATE)
            log "    jobs: sin cola todavía (legítimo: el visor la crea al arrancar)" ;;
        *) die "jobs en ${_jobs} con decision=PROCEED: salida de detect_state incoherente" ;;
    esac
}

# ---------------------------------------------------------------------------
# preparar_estado_del_worker <user> <group> <jobs_db> <proposals_dir> <review_db>
#   B3 (USABLE-V1) · H-02. Deja a nombre del usuario del servicio del worker el
#   estado que COMPARTE con el visor: el directorio de la cola, `jobs.db` y sus
#   ficheros WAL si ya existen, y el almacén de propuestas. Idempotente.
#   C1 · H-04/H-18: tambien el almacen de DECISIONES humanas (`review.sqlite3`):
#   su directorio (SQLite crea ahi los -wal/-shm) y la base con sus WAL. Es
#   obligatorio: el worker lee las decisiones antes de proponer.
#
#   POR QUÉ: el visor que arranca `deploy.sh` corre como root (H-08, sin
#   resolver) y crea `jobs.db` 0644 root:root; el worker corre como el usuario
#   del servicio y, sin esto, abriría la cola en solo lectura y fallaría en el
#   primer `claim` ("attempt to write a readonly database"). Al revés no hay
#   problema: root lee y escribe ficheros ajenos (y SQLite, cuando corre como
#   root, crea sus -wal/-shm con el dueño de la base; no medido aquí: techo).
#   rc=0 ok; rc!=0 si falta un argumento o falla install/chown.
# ---------------------------------------------------------------------------
preparar_estado_del_worker() {
    local user="${1:?usuario}" group="${2:?grupo}" jobs_db="${3:?jobs.db}" props="${4:?propuestas}" review_db="${5:?review.sqlite3}" f
    local dir_mode file_mode
    # H-06: modos de la AUTORIDAD (0700/0600), no un 0750 propio de este guion.
    dir_mode="$(servicio_cifra dir_mode)" || return 1
    file_mode="$(servicio_cifra file_mode)" || return 1
    install -d -m "${dir_mode}" -o "${user}" -g "${group}" "$(dirname -- "${jobs_db}")" "${props}"
    install -d -m "${dir_mode}" -o "${user}" -g "${group}" "$(dirname -- "${review_db}")"
    for f in "${jobs_db}" "${jobs_db}-wal" "${jobs_db}-shm" "${review_db}" "${review_db}-wal" "${review_db}-shm"; do
        if [ -e "${f}" ]; then
            chown "${user}:${group}" -- "${f}"
            chmod "${file_mode}" -- "${f}"
        fi
    done
    return 0
}

# ---------------------------------------------------------------------------
# servicio_cifra <clave>  -> imprime una cifra de la autoridad
#   (service_user | service_group | state_root | file_mode | dir_mode | umask |
#    subdirs | runuser_prefix). rc!=0 si la autoridad no responde.
# ---------------------------------------------------------------------------
servicio_cifra() {
    python3 "${S9K_SERVICE_STATE_PY}" get "${1:?clave}"
}

# ---------------------------------------------------------------------------
# asegurar_identidad_de_servicio
#   H-06 §10. Crea, IDEMPOTENTE, el grupo y el usuario de SISTEMA del servicio
#   (sin login: shell nologin, sin home de login, sin sudo) y COMPRUEBA el
#   resultado (no que useradd "dijo que si"): existe, es de sistema (uid<1000),
#   su shell no es utilizable y no pertenece a grupos de privilegio.
#   rc!=0 con la causa si no se puede.
# ---------------------------------------------------------------------------
asegurar_identidad_de_servicio() {
    local user group shell uid grupos g nologin
    user="$(servicio_cifra service_user)" || { err "la autoridad de identidad no responde"; return 1; }
    group="$(servicio_cifra service_group)" || return 1
    nologin="$(command -v nologin 2>/dev/null || true)"; nologin="${nologin:-/usr/sbin/nologin}"
    if ! getent group "${group}" >/dev/null 2>&1; then
        groupadd --system "${group}" || { err "no se pudo crear el grupo ${group}"; return 1; }
        log "    grupo de sistema ${group} creado"
    fi
    if ! getent passwd "${user}" >/dev/null 2>&1; then
        useradd --system --gid "${group}" --no-create-home --home-dir /nonexistent \
            --shell "${nologin}" --comment "S9 Knowledge service" "${user}" \
            || { err "no se pudo crear el usuario ${user}"; return 1; }
        log "    usuario de sistema ${user} creado"
    fi
    uid="$(id -u "${user}")"; shell="$(getent passwd "${user}" | cut -d: -f7)"
    [ "${uid}" -lt 1000 ] || { err "el usuario ${user} existe pero NO es de sistema (uid ${uid})"; return 1; }
    [ "${uid}" -ne 0 ] || { err "el usuario ${user} es root"; return 1; }
    case "${shell}" in
        */nologin|*/false) ;;
        *) err "el usuario ${user} tiene un shell utilizable (${shell}): se espera nologin"; return 1 ;;
    esac
    grupos=" $(id -nG "${user}") "
    for g in sudo wheel adm root docker; do
        case "${grupos}" in *" ${g} "*) err "el usuario ${user} pertenece al grupo de privilegio ${g}"; return 1 ;; esac
    done
    return 0
}

# ---------------------------------------------------------------------------
# parar_y_verificar_servicios
#   H-06 §8 pasos 3-5. Para el timer de salud, el healthcheck, el worker y el
#   visor y COMPRUEBA que estan parados (estado + sin PID principal): ningun
#   fichero de estado se toca con un proceso vivo. Idempotente: unidades
#   ausentes o ya paradas no fallan. Un servicio que no para -> rc!=0 (el
#   llamador hace STOP). S9K_REANUDAR_TIMER=1 si el timer estaba activo.
# ---------------------------------------------------------------------------
S9K_REANUDAR_TIMER=0
parar_y_verificar_servicios() {
    local unit i main
    if systemctl is-active --quiet "${HEALTH_TIMER_NAME}" 2>/dev/null; then
        S9K_REANUDAR_TIMER=1
        systemctl stop "${HEALTH_TIMER_NAME}" || { err "no se pudo parar ${HEALTH_TIMER_NAME}"; return 1; }
    fi
    for unit in "${HEALTH_UNIT_NAME}" "${WORKER_UNIT_NAME_LIB}" "${VIEWER_UNIT_NAME}"; do
        if systemctl is-active --quiet "${unit}" 2>/dev/null; then
            log "    parando ${unit}"
            systemctl stop "${unit}" || { err "systemctl stop ${unit} falló"; return 1; }
        fi
    done
    for unit in "${HEALTH_UNIT_NAME}" "${WORKER_UNIT_NAME_LIB}" "${VIEWER_UNIT_NAME}"; do
        for i in 1 2 3 4 5; do
            main="$(systemctl show -p MainPID --value "${unit}" 2>/dev/null || echo 0)"
            if ! systemctl is-active --quiet "${unit}" 2>/dev/null && { [ -z "${main}" ] || [ "${main}" = "0" ]; }; then
                break
            fi
            if [ "${i}" -eq 5 ]; then
                err "${unit} sigue activo tras pararlo (PID ${main}): STOP, no se toca el estado"
                return 1
            fi
            sleep 1
        done
    done
    log "    visor, worker y healthcheck parados y verificados"
    return 0
}

# ---------------------------------------------------------------------------
# reanudar_timer_de_salud  -> reactiva el timer si estaba activo antes de parar.
# ---------------------------------------------------------------------------
reanudar_timer_de_salud() {
    if [ "${S9K_REANUDAR_TIMER}" = "1" ]; then
        systemctl start "${HEALTH_TIMER_NAME}" || warn "no se pudo reactivar ${HEALTH_TIMER_NAME}"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# verificar_estado_por_efecto <state_root> <viewer.env> [<role>]
#   H-06 §8 pasos 10-11. POR EFECTO, no por bits:
#     - como el usuario de servicio (`runuser -u`): lee y escribe de verdad lo
#       que necesita (service_state.py access);
#     - como OTRO usuario (`nobody`): no accede a las bases ni al state root
#       (service_state.py deny).
#   Exige root (runuser). rc!=0 con la causa.
# ---------------------------------------------------------------------------
verificar_estado_por_efecto() {
    local raiz="${1:?state_root}" env_file="${2:?viewer.env}" role="${3:-viewer}" user f
    if [ "$(id -u)" -ne 0 ]; then
        err "verificar_estado_por_efecto necesita root (runuser): el despliegue real corre como root"
        return 1
    fi
    command -v runuser >/dev/null 2>&1 || { err "falta runuser (util-linux)"; return 1; }
    user="$(servicio_cifra service_user)" || return 1
    # Las rutas las resuelve ROOT (viewer.env esta en /etc 0700, ilegible para
    # el usuario de servicio) y viajan por stdin: no son secretos.
    local rutas
    rutas="$(python3 "${S9K_SERVICE_STATE_PY}" paths --env-file "${env_file}" --role "${role}")" \
        || { err "no se pudieron resolver las rutas de estado de ${env_file}"; return 1; }
    printf '%s\n' "${rutas}" | runuser -u "${user}" -- python3 "${S9K_SERVICE_STATE_PY}" access \
        --state-root "${raiz}" --paths-stdin \
        || { err "${user} NO puede leer/escribir el estado que necesita (arriba, la ruta)"; return 1; }
    printf '%s\n' "${rutas}" | runuser -u nobody -- python3 "${S9K_SERVICE_STATE_PY}" deny \
        --state-root "${raiz}" --paths-stdin \
        || { err "otro usuario local ACCEDE al estado privado (arriba, la ruta)"; return 1; }
    # SECRET: el servicio LEE sus secretos y NO puede escribirlos (§9)
    local secretos=()
    while IFS= read -r -d '' f; do secretos+=("${f}"); done < <(find "${S9K_CONFIG_ROOT}/secrets" -type f -print0 2>/dev/null)
    if [ "${#secretos[@]}" -gt 0 ]; then
        runuser -u "${user}" -- python3 "${S9K_SERVICE_STATE_PY}" secret-probe "${secretos[@]}" \
            || { err "${user} no lee sus secretos o puede escribirlos (arriba, la ruta)"; return 1; }
    fi
    log "    por efecto: ${user} lee/escribe su estado, lee (sin escribir) sus secretos y 'nobody' no accede a nada"
    return 0
}

# ---------------------------------------------------------------------------
# preparar_secretos_del_servicio [<config_root>]
#   H-06 + H-08 (fase 2, §9) · politica SECRET. Los secretos provisionados NO se mueven
#   al state root: se quedan en <config_root>/secrets y se dejan root:<grupo de
#   servicio>: config 0710 (el grupo atraviesa, no lista), secrets 0750, ficheros
#   0640. El servicio LEE y NO escribe. Idempotente; los modos salen de la AUTORIDAD.
# ---------------------------------------------------------------------------
preparar_secretos_del_servicio() {
    local cfg="${1:-${S9K_CONFIG_ROOT}}" grupo f
    grupo="$(servicio_cifra service_group)" || return 1
    [ -d "${cfg}" ] || { err "no existe ${cfg}"; return 1; }
    chgrp "${grupo}" "${cfg}" && chmod "$(servicio_cifra config_dir_mode)" "${cfg}" || return 1
    [ -d "${cfg}/secrets" ] || return 0
    chgrp "${grupo}" "${cfg}/secrets" && chmod "$(servicio_cifra secret_dir_mode)" "${cfg}/secrets" || return 1
    while IFS= read -r -d '' f; do
        chown "root:${grupo}" "${f}" && chmod "$(servicio_cifra secret_file_mode)" "${f}" || return 1
        python3 "${S9K_SERVICE_STATE_PY}" secret-check "${f}" || return 1
    done < <(find "${cfg}/secrets" -type f -print0)
    return 0
}

# ---------------------------------------------------------------------------
# preparar_raiz_de_backups <ruta>
#   §10 · BACKUP separado del state vivo: root:<grupo> 0750 (el healthcheck lee, no escribe).
#   Rechaza una ruta dentro del state root. No toca el contenido.
# ---------------------------------------------------------------------------
preparar_raiz_de_backups() {
    local ruta="${1:?ruta}" grupo
    grupo="$(servicio_cifra service_group)" || return 1
    case "$(realpath -m -- "${ruta}")/" in
        "$(realpath -m -- "${S9K_STATE_ROOT}")"/*) err "la raíz de backups ${ruta} está DENTRO del state root"; return 1 ;;
    esac
    install -d -m 0750 -o root -g "${grupo}" "${ruta}"
}

# ---------------------------------------------------------------------------
# verificar_procesos_no_root <unit>...
#   H-06 §13 / N8. El proceso VIVO de cada unidad corre como el usuario de
#   servicio: ni root ni otro. Lee /proc/<MainPID>/status (no la unidad).
# ---------------------------------------------------------------------------
verificar_procesos_no_root() {
    local unit pid uid esperado
    esperado="$(id -u "$(servicio_cifra service_user)")" || return 1
    for unit in "$@"; do
        pid="$(systemctl show -p MainPID --value "${unit}" 2>/dev/null || echo 0)"
        if [ -z "${pid}" ] || [ "${pid}" = "0" ]; then
            err "${unit}: sin proceso principal (¿no arrancó?)"; return 1
        fi
        uid="$(awk '/^Uid:/ {print $3}' "/proc/${pid}/status" 2>/dev/null || true)"
        if [ "${uid}" != "${esperado}" ]; then
            err "${unit}: el proceso ${pid} corre como uid ${uid:-?}; esperado ${esperado} ($(servicio_cifra service_user))"
            return 1
        fi
        # C-7 (ronda 2): sin capabilities EFECTIVAS ni ambientales y con NoNewPrivs, medido en
        # el proceso vivo (un drop-in con AmbientCapabilities= no pasaria por aqui).
        local capeff capamb nnp
        capeff="$(awk '/^CapEff:/ {print $2}' "/proc/${pid}/status" 2>/dev/null || true)"
        capamb="$(awk '/^CapAmb:/ {print $2}' "/proc/${pid}/status" 2>/dev/null || true)"
        nnp="$(awk '/^NoNewPrivs:/ {print $2}' "/proc/${pid}/status" 2>/dev/null || true)"
        case "${capeff}" in ""|*[!0]*) err "${unit}: el proceso ${pid} tiene capabilities efectivas (CapEff=${capeff:-?})"; return 1 ;; esac
        case "${capamb}" in ""|*[!0]*) err "${unit}: el proceso ${pid} tiene capabilities ambientales (CapAmb=${capamb:-?})"; return 1 ;; esac
        [ "${nnp}" = "1" ] || { err "${unit}: el proceso ${pid} NO tiene NoNewPrivs (=${nnp:-?})"; return 1; }
    done
    return 0
}

# ---------------------------------------------------------------------------
# verificar_entorno_efectivo <unit>...
#   C-6 (ronda 2, §12 «sin fail-open silencioso»). La excepcion de tests
#   (S9K_STATE_VALIDATION) o el interruptor retirado (S9K_STATE_ENFORCE) no
#   pueden entrar por la puerta de atras: un drop-in con `Environment=`, un
#   `EnvironmentFile=` extra o el entorno heredado. Se mira el entorno EFECTIVO
#   de cada unidad (lo que systemd va a pasar: `systemctl show -p Environment,
#   EnvironmentFiles,DropInPaths`) y el del proceso VIVO (/proc/<pid>/environ,
#   como root). Cualquier aparicion -> rc!=0 con la fuente.
# ---------------------------------------------------------------------------
verificar_entorno_efectivo() {
    local unit pid valor f patron='(^|[[:space:]])S9K_STATE_(VALIDATION|ENFORCE)='
    local fallo=0
    for unit in "$@"; do
        valor="$(systemctl show -p Environment --value "${unit}" 2>/dev/null || true)"
        if printf '%s\n' "${valor}" | grep -qE "${patron}"; then
            err "${unit}: el entorno EFECTIVO (Environment=, incluidos drop-ins) declara S9K_STATE_VALIDATION/ENFORCE"
            fallo=1
        fi
        # EnvironmentFiles: "ruta (ignore_errors=no)" por fichero.
        while IFS= read -r f; do
            f="${f%% (*}"; f="${f#-}"
            [ -n "${f}" ] && [ -f "${f}" ] || continue
            if grep -vE '^[[:space:]]*#' "${f}" | grep -qE '^[[:space:]]*(export[[:space:]]+)?S9K_STATE_(VALIDATION|ENFORCE)='; then
                err "${unit}: el EnvironmentFile ${f} declara S9K_STATE_VALIDATION/ENFORCE"
                fallo=1
            fi
        done < <(systemctl show -p EnvironmentFiles --value "${unit}" 2>/dev/null | tr ' ' '\n' | grep -E '^-?/' || true)
        for f in $(systemctl show -p DropInPaths --value "${unit}" 2>/dev/null || true); do
            [ -f "${f}" ] || continue
            if grep -vE '^[[:space:]]*[#;]' "${f}" | grep -qE 'S9K_STATE_(VALIDATION|ENFORCE)'; then
                err "${unit}: el drop-in ${f} declara S9K_STATE_VALIDATION/ENFORCE"
                fallo=1
            fi
        done
        pid="$(systemctl show -p MainPID --value "${unit}" 2>/dev/null || echo 0)"
        if [ -n "${pid}" ] && [ "${pid}" != "0" ] && [ -r "/proc/${pid}/environ" ]; then
            if tr '\0' '\n' < "/proc/${pid}/environ" | grep -qE '^S9K_STATE_(VALIDATION|ENFORCE)='; then
                err "${unit}: el proceso VIVO ${pid} tiene S9K_STATE_VALIDATION/ENFORCE en su entorno"
                fallo=1
            fi
        fi
    done
    [ "${fallo}" -eq 0 ] || return 1
    return 0
}

# ---------------------------------------------------------------------------
# _exportar_env_s9k <env_file>
#   Lee un EnvironmentFile (lo lee ROOT: /etc/s9-knowledge es 0710 y el usuario de
#   servicio no lo lista) y EXPORTA sus S9K_* (nunca en argv: los secretos no viajan
#   por la linea de comandos).
# ---------------------------------------------------------------------------
_exportar_env_s9k() {
    local env_file="${1:?env}" line k v
    [ -f "${env_file}" ] || { err "no existe ${env_file}"; return 1; }
    while IFS= read -r line || [ -n "${line}" ]; do
        case "${line}" in ''|'#'*) continue ;; esac
        case "${line}" in *=*) ;; *) continue ;; esac
        k="${line%%=*}"; v="${line#*=}"
        k="${k//[[:space:]]/}"
        case "${k}" in S9K_*) ;; *) continue ;; esac
        v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
        v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
        export "${k}=${v}"
    done < "${env_file}"
    return 0
}

# ---------------------------------------------------------------------------
# s9k_cli_destino <herramienta>  -> "componente|directorio|modo|objetivo"
#   H-1 (ronda 2). UNA tabla: cada CLI que puede crear o escribir estado del
#   servicio (las que llaman a `reject_root_cli("<herramienta>")`; un test cruza
#   los dos lados) y como se ejecuta en la release activa. rc 1 = desconocida.
# ---------------------------------------------------------------------------
s9k_cli_destino() {
    case "${1:-}" in
        auth)                  echo "viewer|viewer|-m|app.cli.auth" ;;
        health)                echo "viewer|viewer|-m|app.cli.health" ;;
        jobs)                  echo "data-engine|data-engine|script|app/cli/jobs.py" ;;
        media-jobs)            echo "data-engine|data-engine|script|app/cli/media_jobs.py" ;;
        glossary)              echo "data-engine|data-engine|script|app/glossary/glossary_cli.py" ;;
        external-ai)           echo "data-engine|data-engine|script|app/cli/external_ai.py" ;;
        job-store)             echo "data-engine|data-engine|script|app/jobs/job_store.py" ;;
        ingest)                echo "data-engine|data-engine/app|-m|knowledge_v3.pipeline.ingest_cli" ;;
        pipeline-runner)       echo "data-engine|data-engine/app|-m|knowledge_v3.pipeline.runner" ;;
        semantic-bench)        echo "data-engine|data-engine/app|-m|knowledge_v3.extraction.semantic_bench" ;;
        writer)                echo "data-engine|data-engine/app|-m|knowledge_v3.writer.cli" ;;
        writer-rollback)       echo "data-engine|data-engine/app|-m|knowledge_v3.writer.cli_rollback" ;;
        writer-schema)         echo "data-engine|data-engine/app|-m|knowledge_v3.writer.schema_cli" ;;
        relations)             echo "data-engine|data-engine/app|-m|relations.cli" ;;
        relations-benchmark)   echo "data-engine|data-engine/app|-m|relations.benchmark.cli" ;;
        relations-calibration) echo "data-engine|data-engine/app|-m|relations.calibration.cli" ;;
        relations-nvidia)      echo "data-engine|data-engine/app|-m|relations.calibration.nvidia_cli" ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# s9k_cli <herramienta> [args]   (H-06 §12 + H-1: el comando CANONICO)
#   Ejecuta la CLI como el usuario de servicio con `runuser -u`, con umask 0077
#   (defensa: los modos ya los fija la autoridad), desde la release activa y con
#   el entorno de viewer.env (y, para el motor, worker.env encima). Root NO puede
#   escribir estado con ninguna de ellas (la propia CLI lo rechaza, rc 4).
# ---------------------------------------------------------------------------
s9k_cli() {
    local herramienta="${1:-}" destino comp dir modo objetivo user
    destino="$(s9k_cli_destino "${herramienta}")" \
        || { err "herramienta desconocida '${herramienta}'. Conocidas: auth health jobs media-jobs glossary external-ai job-store ingest pipeline-runner semantic-bench writer writer-rollback writer-schema relations relations-benchmark relations-calibration relations-nvidia"; return 2; }
    shift
    IFS='|' read -r comp dir modo objetivo <<< "${destino}"
    user="$(servicio_cifra service_user)" || return 1
    _exportar_env_s9k "${S9K_CONFIG_ROOT}/viewer.env" || return 1
    if [ "${comp}" = "data-engine" ] && [ -f "${S9K_WORKER_ENV:-${S9K_CONFIG_ROOT}/worker.env}" ]; then
        _exportar_env_s9k "${S9K_WORKER_ENV:-${S9K_CONFIG_ROOT}/worker.env}" || return 1
    fi
    cd "${S9K_ROOT}/current/${dir}" || return 1
    umask 0077
    if [ "${modo}" = "-m" ]; then
        exec runuser -u "${user}" -- "${S9K_ROOT}/current/${comp}/.venv/bin/python" -m "${objetivo}" "$@"
    fi
    exec runuser -u "${user}" -- "${S9K_ROOT}/current/${comp}/.venv/bin/python" "${S9K_ROOT}/current/${comp}/${objetivo}" "$@"
}

# ---------------------------------------------------------------------------
# auth_cli <comando> [args]   (H-06 §12: el comando CANONICO de la CLI de auth)
#   Alias historico de `s9k_cli auth` (lo usan deploy/scripts/auth-cli.sh y el README).
# ---------------------------------------------------------------------------
auth_cli() {
    s9k_cli auth "$@"
}

# ---------------------------------------------------------------------------
# worker_activo <unit> [<lecturas>] [<pausa>]
#   B3 · H-02. `active` en TODAS las lecturas (por defecto 3, cada 2 s). Una
#   unidad con `Restart=always` cuyo proceso muere al arrancar alterna entre
#   `activating` y `active`: una sola lectura afortunada la daría por buena.
# ---------------------------------------------------------------------------
worker_activo() {
    local unit="${1:?unidad}" lecturas="${2:-3}" pausa="${3:-2}" i
    for i in $(seq 1 "${lecturas}"); do
        systemctl is-active --quiet "${unit}" || return 1
        if [ "${i}" -lt "${lecturas}" ]; then sleep "${pausa}"; fi
    done
    return 0
}

# ---------------------------------------------------------------------------
# revertir_worker <prev_release_dir|""> <unit_name> <unit_dest> <release_id>
#   B3 · H-02 (revision independiente, F3). El rollback de los pasos 14/14b/16
#   volvia `current` a la release previa y se limitaba a REINICIAR el worker.
#   Si la release previa no trae el venv del motor (toda release anterior a
#   B3), la unidad nueva apunta a un interprete que no existe: el worker quedaba
#   HABILITADO y en bucle de reinicios. Ahora:
#     - la release previa TIENE `data-engine/.venv/bin/python` ejecutable:
#       se restaura la unidad respaldada en el paso 8 (`<dest>.bak-<id>`) si la
#       hay, `daemon-reload` y reinicio del worker;
#     - NO lo tiene (o no hay release previa): `systemctl disable --now`, se
#       restaura la unidad respaldada si la habia y, si no, se QUITA la nueva.
#   rc=0 siempre que systemctl responda; los errores se avisan.
# ---------------------------------------------------------------------------
_unidad_con_identidad_vigente() {
    local usuario
    usuario="$(servicio_cifra service_user)" || return 1
    grep -qE "^User=${usuario}$" "${1:?unidad}"
}

revertir_worker() {
    local prev="${1:-}" unit="${2:?unidad}" dest="${3:?destino}" release_id="${4:?release}"
    local respaldo="${dest}.bak-${release_id}"
    # H-06 (decision de rollback): la IDENTIDAD no se revierte jamas. Una unidad
    # respaldada de antes de H-06 (root o www-data) NO se restaura: el estado ya
    # es de s9knowledge 0700 y esa unidad no podria leerlo. Se restaura solo si
    # el respaldo declara la identidad vigente de la autoridad.
    if [ -f "${respaldo}" ] && ! _unidad_con_identidad_vigente "${respaldo}"; then
        warn "rollback: el respaldo ${respaldo} es de una identidad anterior a H-06; NO se restaura"
        respaldo="/nonexistent-respaldo-descartado"
    fi
    if [ -n "${prev}" ] && [ -x "${prev}/data-engine/.venv/bin/python" ]; then
        if [ -f "${respaldo}" ]; then cp -a "${respaldo}" "${dest}"; fi
        systemctl daemon-reload || warn "daemon-reload falló en el rollback del worker"
        systemctl restart "${unit}" || warn "no se pudo reiniciar el worker en el rollback"
        return 0
    fi
    warn "rollback: la release previa no puede ejecutar el worker; se deshabilita ${unit}"
    systemctl disable --now "${unit}" || warn "no se pudo deshabilitar ${unit}"
    if [ -f "${respaldo}" ]; then
        cp -a "${respaldo}" "${dest}"
    else
        rm -f -- "${dest}"
    fi
    systemctl daemon-reload || warn "daemon-reload falló en el rollback del worker"
    return 0
}

# ---------------------------------------------------------------------------
# rollback_permitido <release_previa>
#   C-4 (ronda 2, §15). Puerta del rollback AUTOMATICO de deploy.sh (pasos 14,
#   14a, 14b, 16). Reactivar la release previa solo es seguro si ELLA entiende
#   la identidad vigente: el estado ya es de s9knowledge 0700/0600 y una release
#   anterior a H-06 no lo leeria (o lo escribiria en su release). Misma funcion
#   que rollback-release.sh (`release_entiende_la_identidad`).
#     rc 0 -> se puede reactivar; S9K_ROLLBACK_RESULTADO dice que se reactiva.
#     rc 1 -> NO: se PARAN visor y worker (no se arranca a ciegas) y
#             S9K_ROLLBACK_RESULTADO lleva el diagnostico para el `die`.
#   Sin release previa no se llama (S9K_ROLLBACK_RESULTADO conserva su valor).
#   Necesita validate_deploy.sh cargado (deploy.sh lo carga).
# ---------------------------------------------------------------------------
S9K_ROLLBACK_RESULTADO="sin release previa: no hay rollback posible"
rollback_permitido() {
    local prev="${1:-}"
    if [ -z "${prev}" ] || [ ! -d "${prev}" ]; then
        S9K_ROLLBACK_RESULTADO="sin release previa: no hay rollback posible"
        return 1
    fi
    if release_entiende_la_identidad "${prev}"; then
        S9K_ROLLBACK_RESULTADO="rollback ejecutado (release previa $(basename -- "${prev}") reactivada)"
        return 0
    fi
    err "rollback: la release previa ${prev} NO declara la identidad vigente (anterior a H-06 o unidad inválida, arriba): NO se reactiva"
    systemctl stop "${VIEWER_UNIT_NAME}" || warn "no se pudo parar ${VIEWER_UNIT_NAME}"
    systemctl stop "${WORKER_UNIT_NAME_LIB}" || warn "no se pudo parar ${WORKER_UNIT_NAME_LIB}"
    S9K_ROLLBACK_RESULTADO="rollback NO ejecutado: la release previa $(basename -- "${prev}") no entiende la identidad vigente; visor y worker PARADOS (diagnóstico arriba; ver deploy/README.md, recuperación)"
    return 1
}
