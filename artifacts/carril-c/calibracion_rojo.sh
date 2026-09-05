#!/usr/bin/env bash
# CARRIL C -- el rojo ocurre por la causa correcta, demostrado UNA vez.
#
# Reproduce literalmente el guard del paso "Writer y E2E V3 contra Neo4j REAL"
# de `.github/workflows/ci.yml` y le da un Neo4j que NO puede arrancar (imagen
# inexistente). La fixture responde con `skip`, pytest sale con rc=0 y "N
# skipped": sin el guard, ESO seria un job VERDE con el writer sin probar.
#
#   bash artifacts/carril-c/calibracion_rojo.sh
#
# Se espera: rc=1 y el mensaje "se OMITIERON; no hubo Neo4j efimero".
set -u
cd "$(dirname "$0")/../.."

export S9K_WRITER_NEO4J_REAL=1
export S9K_WRITER_NEO4J_IMAGE="s9k-imagen-que-no-existe:0"

set +e
out="$(python3 -m pytest \
         data-engine/app/tests/test_knowledge_v3_writer_neo4j_real.py \
         data-engine/app/tests/test_knowledge_v3_e2e_neo4j_real.py \
         -q --tb=short --no-header 2>&1)"
rc=$?
set -e
echo "$out" | tail -5
echo "--- pytest rc=$rc (un rc=0 aqui es exactamente el falso verde que se ataca)"

veredicto=0
if [ "$rc" -ne 0 ]; then
  echo "GUARD 'writer fallo' -> ROJO"
  veredicto=1
elif grep -qi "skipped" <<<"$out"; then
  echo "GUARD 'se OMITIERON; no hubo Neo4j efimero' -> ROJO"
  veredicto=1
elif ! grep -qE '[0-9]+ passed' <<<"$out"; then
  echo "GUARD 'no llegaron a ejecutarse' -> ROJO"
  veredicto=1
fi

if [ "$veredicto" -eq 1 ]; then
  echo "veredicto=CALIBRADO: sin Neo4j el paso se pone ROJO, no verde"
  exit 0
fi
echo "veredicto=NO_CALIBRADO: el paso habria salido VERDE sin Neo4j"
exit 1
