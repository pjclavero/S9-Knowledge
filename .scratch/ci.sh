SHA=89628a54dd6a298d0371127053bfc6885343bd64
while true; do
  gh api "repos/pjclavero/S9-Knowledge/commits/$SHA/check-runs?per_page=100" \
     --jq '.check_runs[] | "\(.status)/\(.conclusion//"pendiente") \(.name)"' > /tmp/ci.txt 2>/dev/null
  if ! grep -q pendiente /tmp/ci.txt; then
    echo "CI TERMINADA"
    awk '{print $1}' /tmp/ci.txt | sort | uniq -c
    grep -v "completed/success" /tmp/ci.txt
    break
  fi
  sleep 120
done
