#!/usr/bin/env bash
# PROPUESTA — NO INSTALADA. Ver README.md de este directorio.
#
# Copia local consistente de S9 Knowledge:
#   - auth.db y jobs.db con `sqlite3 .backup` (nunca `cp` de un fichero abierto)
#   - Neo4j por exportacion logica (la edicion community no admite backup en
#     caliente y APOC no esta instalado; el dump fisico exige detener la base)
#   - manifiesto con hash, tamano y fecha de cada fichero
#   - publicacion ATOMICA: se construye en .tmp-<id> y se renombra al final
#   - retencion aplicada SOLO despues de publicar y verificar la copia nueva
#
# No para servicios, no migra, no compacta, no cambia flags, no rota secretos y
# no escribe en Neo4j. Escribe unicamente dentro de $DEST.
set -Eeuo pipefail

DEST="${S9K_BACKUP_DIR:-/var/lib/s9-knowledge/backups}"
AUTH_DB="${S9K_AUTH_DB_PATH:-/var/lib/s9-knowledge/auth/auth.db}"
JOBS_DB="${S9K_JOBS_DB:-/var/lib/s9-knowledge/jobs/jobs.db}"
NEO4J_CONTAINER="${S9K_NEO4J_CONTAINER:-neo4j-knowledge}"
MIN_FREE_MB="${S9K_BACKUP_MIN_FREE_MB:-500}"

RETENCION_DIARIAS="${S9K_RETENTION_DAILY:-7}"
RETENCION_SEMANALES="${S9K_RETENTION_WEEKLY:-4}"
RETENCION_MENSUALES="${S9K_RETENTION_MONTHLY:-3}"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_ID="auto-${STAMP}"
TMP="${DEST}/.tmp-${BACKUP_ID}"
FINAL="${DEST}/${BACKUP_ID}"
LOCK="${DEST}/.backup.lock"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Un fallo a mitad NO debe dejar un directorio que parezca un backup valido:
# se borra el temporal, jamas una copia ya publicada.
limpiar_si_falla() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log "FALLO (rc=$rc): se descarta el temporal, no se publica nada"
        rm -rf "${TMP}"
    fi
    exit $rc
}
trap limpiar_si_falla EXIT

# ---------------------------------------------------------------- preflight
preflight() {
    log "preflight"
    [[ -d "${DEST}" ]] || { log "destino inexistente: ${DEST}"; return 1; }
    [[ -r "${AUTH_DB}" ]] || { log "auth.db ilegible"; return 1; }
    [[ -r "${JOBS_DB}" ]] || { log "jobs.db ilegible"; return 1; }

    local libre_mb
    libre_mb="$(df -Pm "${DEST}" | awk 'NR==2 {print $4}')"
    if [[ "${libre_mb}" -lt "${MIN_FREE_MB}" ]]; then
        log "espacio insuficiente: ${libre_mb} MB libres, minimo ${MIN_FREE_MB} MB"
        return 1
    fi
    log "espacio libre: ${libre_mb} MB"

    if ! docker inspect "${NEO4J_CONTAINER}" >/dev/null 2>&1; then
        log "contenedor de Neo4j no disponible: ${NEO4J_CONTAINER}"
        return 1
    fi
}

cypher() {
    docker exec "${NEO4J_CONTAINER}" bash -lc \
        "/var/lib/neo4j/bin/cypher-shell -u neo4j -p \"\${NEO4J_AUTH#neo4j/}\" --format plain \"$1\""
}

# ------------------------------------------------------------------- copia
copiar() {
    mkdir -p "${TMP}/sqlite" "${TMP}/neo4j" "${TMP}/meta"

    log "sqlite: copia consistente"
    sqlite3 "${AUTH_DB}" ".backup '${TMP}/sqlite/auth.db'"
    sqlite3 "${JOBS_DB}" ".backup '${TMP}/sqlite/jobs.db'"

    log "sqlite: integridad de las COPIAS"
    for db in auth jobs; do
        local res
        res="$(sqlite3 "${TMP}/sqlite/${db}.db" 'PRAGMA integrity_check;')"
        [[ "${res}" == "ok" ]] || { log "integridad ${db}: ${res}"; return 1; }
    done

    log "neo4j: exportacion logica"
    cypher "MATCH (n) RETURN id(n) AS id, labels(n) AS etiquetas, properties(n) AS props ORDER BY id(n);" \
        > "${TMP}/neo4j/nodos.txt"
    cypher "MATCH (a)-[r]->(b) RETURN id(r) AS id, id(a) AS origen, id(b) AS destino, type(r) AS tipo, properties(r) AS props ORDER BY id(r);" \
        > "${TMP}/neo4j/relaciones.txt"
    cypher "SHOW INDEXES;" > "${TMP}/neo4j/indexes.txt"
    cypher "SHOW CONSTRAINTS;" > "${TMP}/neo4j/constraints.txt"

    log "metadatos"
    {
        echo "backup_id=${BACKUP_ID}"
        echo "release=$(readlink -f /opt/s9-knowledge/current)"
        echo "commit=$(cat /opt/s9-knowledge/current/COMMIT 2>/dev/null || echo desconocido)"
        echo "neo4j=$(docker exec "${NEO4J_CONTAINER}" /var/lib/neo4j/bin/neo4j --version)"
        echo "sqlite=$(sqlite3 --version | cut -d' ' -f1)"
        echo "host=$(hostname)"
    } > "${TMP}/meta/despliegue.txt"

    sqlite3 "${TMP}/sqlite/auth.db" '.schema' > "${TMP}/meta/auth-schema.sql"
    sqlite3 "${TMP}/sqlite/jobs.db" '.schema' > "${TMP}/meta/jobs-schema.sql"

    # Configuracion: nombres de clave, valores REDACTADOS. Nunca secretos.
    if [[ -r /etc/s9-knowledge/viewer.env ]]; then
        sed -E 's/^([A-Z0-9_]+)=.*/\1=<REDACTADO>/' /etc/s9-knowledge/viewer.env \
            > "${TMP}/meta/viewer.env.claves"
    fi
    for u in s9-knowledge-viewer.service s9-knowledge-healthcheck.service s9-knowledge-healthcheck.timer; do
        systemctl cat "${u}" > "${TMP}/meta/${u}" 2>/dev/null || true
    done
}

manifiesto() {
    log "manifiesto"
    ( cd "${TMP}" && find . -type f ! -name 'MANIFEST*' | sort | while read -r f; do
        printf '%s  %s  %s  %s\n' \
            "$(sha256sum "$f" | cut -d' ' -f1)" \
            "$(stat -c '%s' "$f")" \
            "$(stat -c '%y' "$f" | cut -d'.' -f1)" \
            "$f"
      done > MANIFEST.sha256 )

    # Un fichero vacio inesperado invalida la copia: mejor no publicar que
    # publicar algo que el chequeo de antiguedad dara por bueno.
    local vacios
    vacios="$(find "${TMP}" -type f -empty ! -name 'constraints.txt' | wc -l)"
    [[ "${vacios}" -eq 0 ]] || { log "hay ${vacios} ficheros vacios inesperados"; return 1; }
}

verificar_publicado() {
    log "verificacion del manifiesto publicado"
    ( cd "${FINAL}" && awk '{print $1"  "$NF}' MANIFEST.sha256 > .chk \
        && sha256sum -c .chk >/dev/null && rm -f .chk )
}

retencion() {
    # Se ejecuta SOLO tras publicar y verificar: nunca se borra lo viejo antes
    # de tener lo nuevo validado.
    log "retencion (${RETENCION_DIARIAS}d/${RETENCION_SEMANALES}s/${RETENCION_MENSUALES}m)"
    python3 "$(dirname "$0")/retencion.py" \
        --dest "${DEST}" \
        --diarias "${RETENCION_DIARIAS}" \
        --semanales "${RETENCION_SEMANALES}" \
        --mensuales "${RETENCION_MENSUALES}"
}

main() {
    exec 9>"${LOCK}"
    if ! flock -n 9; then
        log "otra copia en curso: se aborta sin hacer nada"
        exit 0
    fi

    preflight
    copiar
    manifiesto
    mv "${TMP}" "${FINAL}"
    chmod -R go-rwx "${FINAL}"
    verificar_publicado
    retencion
    log "OK ${BACKUP_ID} -> ${FINAL}"
}

main "$@"
