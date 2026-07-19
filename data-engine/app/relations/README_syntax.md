# Adaptador sintáctico desacoplado (`relation-syntax/v1`)

`relations/syntax.py` aporta **señales estructurales** (frases, tokens con
offsets, sujeto/verbo/objeto aproximados, negación, voz pasiva, idioma) que un
futuro consenso podrá consumir. Es un **adaptador**: define una interfaz pública
estable y trae un **proveedor por defecto ligero y sin dependencias**. Si más
adelante se integra spaCy / Stanza / un servicio externo, se implementa otro
proveedor con la misma interfaz sin tocar el resto del pipeline.

Este módulo **no decide** relaciones ni consenso: solo describe estructura.

## Garantías de diseño

- **Import sin efectos secundarios.** Importar `relations.syntax` (o el paquete
  `relations`) **no carga modelos, no descarga nada y no abre red**.
- **Proveedor por defecto sin dependencias pesadas.** El heurístico usa solo
  `re` de la stdlib (no spaCy, no Stanza, no torch, no `requests`/`httpx`).
- **Sin red / sin descarga / sin Neo4j / sin escritura / sin LLM.**
- **Offsets Unicode-correctos.** Para todo token se cumple
  `text[token.start:token.end] == token.text`, incluidos acentos y emoji.
- **Salida serializable y determinista.** `to_dict` / `to_json` /
  `from_dict` / `from_json` con round-trip estable y orden fijo.
- **Fallo claro de proveedores externos.** Pedir un proveedor pesado no
  instalado lanza `SyntaxProviderUnavailable` (nunca instala ni descarga).

## Interfaz pública

Estructuras de datos (dataclasses inmutables, serializables):

| Tipo | Campos principales |
| --- | --- |
| `SyntaxToken` | `index`, `text`, `start`, `end`, `lemma?`, `pos?`, `head?`, `dep`, `is_negation` |
| `SyntaxDependency` | `head_index`, `dependent_index`, `relation` |
| `SyntaxSentence` | `index`, `text`, `start`, `end`, `tokens`, `dependencies`, `subject_index?`, `main_verb_index?`, `object_index?`, `negated`, `passive` |
| `SyntaxAnalysis` | `text`, `language`, `provider`, `version`, `sentences`, `degraded`, `quality`, `notes` |

Interfaz de proveedor:

```python
class SyntaxAnalyzer(ABC):
    name: str
    def available(self) -> bool: ...
    def analyze(self, text: str, *, language: str | None = None) -> SyntaxAnalysis: ...
```

Fábrica y ayudas:

```python
from relations.syntax import analyze, get_analyzer, safe_analyze

a = analyze("Aragorn ama a Arwen.")            # proveedor 'heuristic' por defecto
a = get_analyzer("heuristic").analyze(texto)   # equivalente
a = safe_analyze(algun_proveedor, texto)       # aísla fallos del proveedor
```

`get_analyzer` acepta `"heuristic"` (por defecto), `"null"`; `"spacy"`/`"stanza"`
lanzan `SyntaxProviderUnavailable`.

### Formato de salida (`to_dict`)

```json
{
  "text": "...",
  "language": "es",
  "provider": "heuristic",
  "version": "relation-syntax-1.0.0",
  "degraded": false,
  "quality": 0.65,
  "notes": [],
  "sentences": [
    {
      "index": 0, "text": "Aragorn ama a Arwen.", "start": 0, "end": 20,
      "subject_index": 0, "main_verb_index": 1, "object_index": 3,
      "negated": false, "passive": false,
      "tokens": [{"index": 0, "text": "Aragorn", "start": 0, "end": 7,
                  "lemma": null, "pos": null, "head": 1, "dep": "nsubj",
                  "is_negation": false}, "..."],
      "dependencies": [{"head_index": 1, "dependent_index": 0, "relation": "nsubj"}, "..."]
    }
  ]
}
```

`quality` es una confianza heurística ordinal en `[0,1]` (0.0 vacío, 0.2
degradado, `0.4 + 0.5 * cobertura_verbal` en idioma soportado); **no** es una
probabilidad calibrada.

## Proveedor por defecto: heurístico (sin dependencias)

Reglas deterministas, best-effort:

- **Segmentación de frases** por terminadores (`.`, `!`, `?`, `…`), colapsando
  corridas y preservando offsets.
- **Tokenización** Unicode-aware (`\w+` o un carácter no-espacio) con offsets
  sobre el texto original.
- **Idioma**: hint explícito o autodetección barata por solapamiento de
  palabras función / verbos frecuentes (empate a favor de `es`).
- **Negación** por marcadores (`no`, `nunca`, `sin`, ... / `not`, `never`, ...).
- **Voz pasiva** heurística: auxiliar (`ser`/`be`) + participio (sufijo regular
  o irregular frecuente) en ventana corta.
- **SVO aproximado**: verbo principal = primer verbo conocido; sujeto = última
  palabra de contenido antes del verbo (o `None` si se omite, pro-drop); objeto
  = primera palabra de contenido tras el verbo.

### Modo degradado (idioma no soportado)

Idiomas fuera de `SUPPORTED_LANGUAGES` (`es`, `en`) **no fallan**: se procesan en
modo degradado (`degraded=True`) con solo segmentación + tokenización + offsets,
sin negación / pasiva / SVO. Se anota el motivo en `notes` y `quality` baja.

### Limitaciones honestas

El heurístico reconoce un **conjunto curado** de verbos frecuentes y no calcula
lema ni POS abierto (`lemma`/`pos` suelen ser `null`; solo se marca `PUNCT`/`NUM`).
Es deliberado: sin modelo no se puede inferir morfología con fiabilidad. Para
análisis lingüístico completo se requiere un proveedor pesado (abajo).

## Proveedores pesados (spaCy / Stanza) — NOT_EXECUTED

Integrar spaCy o Stanza aportaría lema, POS y dependencias reales, pero:

- **Requiere añadir dependencias** (spaCy/Stanza + modelos descargables). Esta
  tarea tiene **prohibido** modificar `requirements`, por lo que **no se añaden**.
- `data-engine/requirements.lock` solo trae `nltk`, `numpy` y `regex` (ninguna
  librería de parsing sintáctico con modelos). No se asume su presencia.

Por eso se entrega la clase `ExternalModelSyntaxAnalyzer` como **placeholder**
con `available() == False` y `analyze()` que lanza `SyntaxProviderUnavailable`
(fallo claro, sin descargas). La ejecución real de un proveedor pesado queda
marcada **NOT_EXECUTED**.

**Alternativa recomendada** cuando se decida integrarlo (fuera de alcance aquí):

1. Añadir la dependencia y el modelo de forma explícita al lockfile.
2. Subclasar `SyntaxAnalyzer` (p. ej. `SpacySyntaxAnalyzer`) mapeando la salida
   del modelo a `SyntaxToken`/`SyntaxSentence`/`SyntaxAnalysis` (mismos offsets).
3. Registrarlo en la fábrica `get_analyzer`. El resto del pipeline no cambia.

## Ejecución

```bash
S9K_ALLOW_REAL_INGEST="" python3 -m pytest data-engine/app/tests/test_relation_syntax.py -q
```
