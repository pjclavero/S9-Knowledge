SHA=e54d7445f612ad52d9cc1ece46287a44d8e33b03
while true; do
  gh api "repos/pjclavero/S9-Knowledge/commits/$SHA/check-runs?per_page=100" \
     --jq '.check_runs[] | "\(.status)/\(.conclusion//"pendiente") \(.name)"' > /tmp/ci2.txt 2>/dev/null
  if [ -s /tmp/ci2.txt ] && ! grep -q pendiente /tmp/ci2.txt; then
    echo "CI TERMINADA"
    awk '{print $1}' /tmp/ci2.txt | sort | uniq -c
    grep -v "completed/success" /tmp/ci2.txt
    break
  fi
  sleep 120
done
