# Entrega — carril de transcripción manuscrita

Fecha: 2026-07-29
Rama: `feat/v3-handwritten-transcription`
Encargo normativo: `docs/v3/29-encargo-externo-transcripcion-manuscrita.md`

## Qué se construyó

- Cascada `VLM 1 -> revisión de coherencia solo-texto -> VLM 2 si procede ->
  diff literal local`.
- Disparadores deterministas por incoherencia, nombre propio, número/fecha y
  término ausente del glosario.
- Dos modelos visuales distintos y familia declarada
  `visual-transcription`.
- Prompt literal: prohíbe interpretar, resumir, normalizar, completar y pedir
  coordenadas; exige `[ilegible]`.
- Proyección al contrato congelado como `HTR_TEXT`, con offsets sobre la
  transcripción, `bbox=None` y hash de contenido propio del episodio.
- Marcado de revisión por tramo, sin bloquear el resto de la página.
- Etiquetas de origen en `metadata`: `source_file`, `ingested_by` y los cuatro
  campos opcionales, conservando autor y perspectiva por separado.
- Métricas obligatorias y adaptadores reales para los modelos NVIDIA
  verificados en `docs/v3/28-requisitos-de-instalacion.md`.
- Guarda de privacidad adelantada: una política privada incoherente se rechaza
  antes de enviar la imagen al proveedor.

No se añadió ninguna dependencia.

## Ficheros tocados

- `data-engine/app/knowledge_v3/multimodal/transcription.py`
- `data-engine/app/knowledge_v3/multimodal/adapters/visual.py`
- `data-engine/app/knowledge_v3/multimodal/__init__.py`
- `data-engine/app/tests/test_knowledge_v3_handwritten_transcription.py`
- `docs/v3/30-transcripcion-manuscrita.md`

No se tocaron contratos, extracción, resolución, motor, reconciliación, writer,
CI, `pytest.ini`, corpus gold, `heldout` ni `negation`.

## Medición

Material controlado:

```text
lectura 1: el grupo ve a Narek
lectura 2: el grupo ve a Narok
```

Resultado real:

```text
tokens transcritos: 5
tokens a revisión: 1 (Narek)
s9_transcription_review_fraction: 0.20
```

Los otros cuatro tokens quedan en fragmentos sin revisión. No se fija ni se
declara cumplido ningún umbral.

La batería de 40 líneas cambia solo las líneas 10 y 30 en la segunda lectura:
38 líneas quedan limpias y dos palabras se marcan para revisión.

## Tests ejecutados

Entorno:

```text
Python 3.13.10
pytest 9.1.1
Windows
```

Batería nueva:

```text
...........................                                              [100%]
27 passed in 0.69s
```

Toda la familia multimodal, incluida la batería nueva:

```text
........................................................................ [ 33%]
........................................................................ [ 67%]
................................sss....sss...........................    [100%]
207 passed, 6 skipped, 1 warning in 10.71s
```

Visuales positivos, negativos y transcripción:

```text
156 passed in 8.83s
```

Suite completa solicitada:

```text
python -m pytest data-engine/app/tests
collected 4482 items / 3 errors
3 errores de colección: ModuleNotFoundError: No module named 'resource'
```

Ejecución degradada excluyendo únicamente esos tres colectores E2E:

```text
43 failed, 4342 passed, 26 skipped, 496 warnings, 71 errors in 141.53s
```

Los fallos/errores restantes son ajenos a este cambio: hashes de corpus que no
coinciden por finales de línea en Windows, pruebas POSIX, permisos/symlinks y
migraciones. La familia multimodal completa pasa.

Viewer:

```text
python -m pytest viewer/tests/ -q
1 skipped, 1 warning, 2 errors in 1.69s
```

Bloqueos de colección: `fcntl` no existe en Windows y `os.geteuid` no está
disponible.

Suite raíz:

```text
python -m pytest -q
ImportError while loading conftest 'deploy/tests/conftest.py'
ModuleNotFoundError: No module named 'fcntl'
```

## Defectos ajenos encontrados

- `data-engine/app/knowledge_v3/pipeline/bundle.py:16` importa `resource` sin
  alternativa para Windows y bloquea tres módulos E2E durante colección.
- `viewer/app/auth/db.py:4` y `deploy/scripts/retention.py:18` importan `fcntl`
  sin alternativa para Windows.
- `viewer/tests/test_health_backups.py:321` llama `os.geteuid()` durante
  colección, API inexistente en Windows.
- El corpus de relaciones presente en este checkout no coincide con los hashes
  de su manifest al leerse con finales de línea Windows; no se modificó porque
  el encargo prohíbe tocar corpus gold.
- La guarda de privacidad del adaptador visual se aplicaba demasiado tarde:
  `IngestOptions.processing_policy()` se ejecutaba en el ensamblado, después de
  invocar el proveedor. Se corrigió dentro del subsistema autorizado y quedó
  cubierta por regresión.

## Limitaciones

- No se ejecutó una llamada NVIDIA de pago desde esta estación: la credencial
  solo debe cargarse desde `/etc/s9-knowledge/providers.env`, ubicación no
  disponible en Windows. El transporte real queda implementado reutilizando el
  cliente seguro existente; las pruebas inyectan respuestas controladas y no
  usan red ni secretos.
- La cifra `0.20` caracteriza el material controlado indicado arriba, no la
  letra real del usuario. La métrica queda instrumentada para medir el corpus
  real cuando se ejecute en el entorno autorizado.
- No se implementó vista por personaje, tal como ordena el encargo.
