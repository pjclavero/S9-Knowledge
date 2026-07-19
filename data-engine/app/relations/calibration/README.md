# Calibración de relaciones en modo sombra

Arneses de validación (*probes*) que ejercitan los evaluadores de relaciones en
**modo sombra** contra proveedores reales, de forma aislada y **sin escritura**.
No forman parte del pipeline productivo.

## `ollama_shadow_probe` — Bloque 1

Valida `relations.local_llm_shadow.evaluate_relation_local` contra un servidor
**Ollama real** (API OpenAI-compatible en `<base>/v1`) sobre un corpus
**sintético**, midiendo repetibilidad, latencia y coste.

### Garantías (heredadas del evaluador, no reimplementadas)

- **Modo sombra**: nunca decide, nunca aprueba, nunca escribe (Neo4j / ficheros / caché).
- **Sin default productivo**: el endpoint es **siempre explícito**. Si falta, falla
  cerrado (`ConfigError`) sin abrir un solo socket.
- **Sin corpus privado**: solo casos sintéticos (personajes/facciones inventados).
- **Secretos redactados**: el informe nunca contiene claves; el host del endpoint se
  ofusca por defecto (`http://<host>/v1`).

### Uso (CLI)

```bash
# El endpoint es SIEMPRE explícito; no hay valor por defecto.
export PYTHONPATH="$PWD/data-engine/app"
python -m relations.calibration.cli \
    --endpoint http://localhost:11434/v1 \
    --model qwen2.5:7b \
    --repetitions 3 \
    --out informe.json
```

El CLI solo escribe el fichero indicado por `--out` (artefacto de calibración).
Nunca escribe en Neo4j ni toca infraestructura productiva.

### Test live gateado

`tests/wave2b/test_local_llm_ollama_live.py` solo corre con `S9K_OLLAMA_LIVE=1` y
`S9K_OLLAMA_BASE_URL` alcanzable; **en CI se salta** (sin red a Ollama, sin flaky).
Los tests unitarios del probe (`data-engine/app/tests/test_ollama_shadow_probe.py`)
usan transportes inyectados y corren siempre.

### Informe de validación real

Ver [`docs/coordination/sequential-program/block-1-ollama-shadow-report.md`](../../../../docs/coordination/sequential-program/block-1-ollama-shadow-report.md).
