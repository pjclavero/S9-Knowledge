set -u
P=$1; DB=$2
B=http://127.0.0.1:$P
echo "  GET /setup/admin (base v4 vacia)      -> $(curl -s -o /dev/null -w '%{http_code}' $B/setup/admin)   sello: $(python3 -c "
import sqlite3;print(list(sqlite3.connect('$DB').execute('SELECT key FROM install_state')))")"
python3 -c "
import sys,sqlite3
sys.path.insert(0,'/home/ia02/S9-Knowledge/.claude/worktrees/agent-a099e22c532796ef0/viewer')
from pathlib import Path
from app.auth import db as auth_db
from app.auth.passwords import hash_password
with auth_db.get_conn(Path('$DB')) as c:
    auth_db.create_user(c, username='admin-por-cli-ficticio', display_name='X',
                        password_hash=hash_password('clave-ficticia-de-pruebas-9'), role='admin')
print('  [alta por un camino que NO sella: create_user]')"
echo "  GET /setup/admin (con usuario)         -> $(curl -s -o /dev/null -w '%{http_code}' $B/setup/admin)   sello: $(python3 -c "
import sqlite3;print(list(sqlite3.connect('$DB').execute('SELECT key FROM install_state')))")"
python3 -c "
import sqlite3;c=sqlite3.connect('$DB');c.execute('DELETE FROM users');c.commit();print('  [DELETE FROM users]')"
echo "  GET /setup/admin (sin usuarios)        -> $(curl -s -o /dev/null -w '%{http_code}' $B/setup/admin)   sello: $(python3 -c "
import sqlite3;print(list(sqlite3.connect('$DB').execute('SELECT key FROM install_state')))")"
echo "  POST /setup/admin                      -> $(curl -s -o /dev/null -w '%{http_code}' -d 'username=intruso&password=x' $B/setup/admin)"
