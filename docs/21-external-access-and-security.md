# 21 · Acceso externo y seguridad

Actualizado 2026-07-12.

## Acceso al visor S9 Knowledge

| Vía | URL | Notas |
|-----|-----|-------|
| LAN | `http://192.168.1.205:8088` | directo, sin auth |
| Tailscale | `http://100.103.100.105:8088` | directo, sin auth |
| Externo | `https://knowledge.seccionnueve.duckdns.org` | nginx VM104 + Basic Auth |

### Acceso externo por dominio
- Reverse proxy: **nginx en VM104** (192.168.1.204), vhost
  `/etc/nginx/sites-available/knowledge.seccionnueve.duckdns.org.conf`.
- Flujo: Internet → 80/443 (router → VM104) → nginx → `http://192.168.1.205:8088`.
- Certificado: wildcard Let's Encrypt `*.seccionnueve.duckdns.org` (DuckDNS resuelve el subdominio).
- **Basic Auth**: `auth_basic` con `/etc/nginx/.htpasswd_s9knowledge`, usuario `s9admin`
  (contraseña en el gestor de contraseñas; no se guarda en claro en el repo).
- Cabeceras de seguridad: X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS.
- Nota histórica: este subdominio apuntaba antes a `silverbullet-index` (:3100); se repuntó a :8088.
  Backup del vhost previo en VM104: `/root/backups-s9-knowledge-domain/`.

> El visor no tiene login propio todavía: la única barrera externa es el Basic Auth del proxy.

## Seguridad de Neo4j

- El contenedor `neo4j-knowledge` (VM105) exponía 7474/7687 en `0.0.0.0` (accesible desde
  LAN/Tailscale). El 2026-07-12 se cerró a **solo 127.0.0.1**.
- Compose: `/opt/knowledge-services/neo4j/compose.yaml` (fuera de este repo).
  Cambio: `"7474:7474"` → `"127.0.0.1:7474:7474"` (idem 7687). Backup `compose.yaml.bak.2026-07-12-1102`.
- El visor sigue conectando por `bolt://127.0.0.1:7687`. `192.168.1.205:7474` ya rechaza conexión.

## Qué NO está expuesto

- Neo4j (7474/7687), Ollama (11434) y Nextcloud interno **no** se exponen a Internet.
- No se abrieron puertos nuevos en el router (se reutiliza 80/443 → VM104).

## Pendiente de seguridad

- Login propio del visor (más allá del Basic Auth del proxy).
- Cloudflare Access u OIDC si se quiere control por usuario/email.
