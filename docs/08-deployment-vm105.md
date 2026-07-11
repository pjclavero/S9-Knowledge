# 08 · Despliegue en VM105

Referencia del entorno donde vive el proyecto en producción. **Este repo no
despliega nada por sí mismo**; documenta el estado.

## Entorno

- Host: VM105 `common`, LAN `192.168.1.205` (Proxmox VE 8.4).
- Proyecto: `/opt/knowledge-services/property-graph`.
- Python: venv en `.venv` (no versionado; recrear con `requirements.lock`).
- Neo4j: contenedor `neo4j-knowledge` (bolt `127.0.0.1:7687`, también
  `192.168.1.205:7687` en LAN). Credenciales fuera del repo.
- Ollama: `192.168.1.157:11434`, modelo `qwen2.5:7b`.
- SilverBullet: contenedores `silverbullet-*` (LAN 3100–3112; HTTPS local
  4100–4112 vía nginx del contenedor Vaultwarden).

## Recrear el entorno del data-engine (referencia)

```bash
cd /opt/knowledge-services/property-graph
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cp .env.example .env    # y rellenar valores reales
.venv/bin/python -m pytest app/tests/ -q
```

## Reglas de operación

- No exponer Neo4j ni Ollama a Internet.
- No versionar secretos ni datos de campaña (audios, PDFs, transcripciones
  privadas).
- Cambios en producción con backup previo y prueba mínima.
- El estado de runtime (`state/`, `output/`, `logs/`, `staging/`, `*.db`) no se
  versiona: es específico de cada instalación.

## Backups existentes

En `property-graph/backups/` (no se copian al repo si son pesados; los `.bak` de
código sí pueden incluirse selectivamente). Ver informe de auditoría.
