set -u
P=$1; U=$2
B=http://127.0.0.1:$P
CJ=/tmp/bs/login.cj; rm -f $CJ
TOK=$(curl -s -c $CJ $B/login | grep -o 'name="csrf_token" value="[^"]*"' | sed 's/.*value="//;s/"//')
curl -s -b $CJ -c $CJ -o /dev/null -w '  POST /login -> %{http_code} -> %{redirect_url}\n' \
  -d "username=$U&password=$PW&csrf_token=$TOK&next=/" $B/login
echo "  GET /admin/users/new (con sesion) -> $(curl -s -b $CJ -o /dev/null -w '%{http_code}' $B/admin/users/new)"
echo "  GET /setup/admin     (con sesion) -> $(curl -s -b $CJ -o /dev/null -w '%{http_code}' $B/setup/admin)"
