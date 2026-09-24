set -u
P=$1
B=http://127.0.0.1:$P
CJ=/tmp/bs/crear.cj; rm -f $CJ
TOK=$(curl -s -c $CJ $B/setup/admin | grep -o 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//;s/"//')
curl -s -b $CJ -o /dev/null -w '  POST /setup/admin -> %{http_code} -> %{redirect_url}\n' \
  -d "username=admin-ficticio&display_name=Admin+Ficticio&password=$PW&csrf_token=$TOK" $B/setup/admin
