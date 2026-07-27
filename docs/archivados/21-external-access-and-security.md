# 21 · Acceso externo y seguridad

Actualizado 2026-07-15 (añadida autenticación propia del visor).

## Acceso al visor S9 Knowledge

| Vía | URL | Notas |
|-----|-----|-------|
| LAN | `http://192.168.1.205:8088` | Con auth propia si `S9K_AUTH_ENABLED=true` |
| Tailscale | `http://100.103.100.105:8088` | Con auth propia si activada |
| Externo | `https://knowledge.seccionnueve.duckdns.org` | nginx VM104 Basic Auth + login propio |

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

### Autenticación propia del visor (feat/viewer-auth-foundation — 2026-07-15)

El visor ahora incluye un sistema de autenticación propio. Ver [docs/44](44-viewer-authentication-and-users.md) para el diseño completo.

**Estado**: implementado en rama `feat/viewer-auth-foundation`, no activado en producción.
**Para activar**: `S9K_AUTH_ENABLED=true` en `.env` y reiniciar el servicio.

**Doble barrera durante la transición**:
1. Basic Auth de nginx (VM104) — barrera perimetral de red.
2. Login propio del visor — identificación de operador por rol.

**Plan de retirada del Basic Auth de nginx**: una vez verificado el login propio en producción
con múltiples usuarios durante al menos una semana, se puede eliminar `auth_basic` del vhost nginx.
Solo eliminar cuando `S9K_AUTH_ENABLED=true` esté confirmado y operativo.

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

- Activar `S9K_AUTH_ENABLED=true` en producción y verificar (ver docs/44).
- Retirar Basic Auth de nginx tras verificar login propio (ver plan arriba).
- Cloudflare Access u OIDC si se quiere control por usuario/email (fase futura).
