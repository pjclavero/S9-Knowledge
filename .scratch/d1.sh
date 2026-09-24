set -u
P=$1
B=http://127.0.0.1:$P
echo "  POST /login SIN cuerpo            -> $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' -X POST $B/login)"
echo "  POST /login sin csrf_token        -> $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' -d 'username=u&password=p' $B/login)"
echo "  GET  /login                       -> $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' $B/login)"
