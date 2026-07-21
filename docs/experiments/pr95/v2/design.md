# V2 · Diseño — Realineamiento determinista y acotado

**Base SHA:** `92583f4`

## 1. Principio rector

El realineamiento **nunca relaja** la validación. Sustituye `evidence_text`/offsets del
modelo por una **rodaja literal del documento real** (`doc[start:end]`), de modo que la
validación estricta base sigue siendo la **única fuente de verdad** del invariante. Si el
realineamiento no logra un alineamiento seguro, no toca nada y la evidencia se rechaza
igual que en la base.

## 2. Mapa reversible original ↔ normalizado

`normalize_with_map(text) -> (norm, starts, ends)`

Para cada carácter `norm[k]` de la forma normalizada, `starts[k]`/`ends[k]` son el rango
`[start, end)` del texto **original** que lo produjo. Una coincidencia normalizada `[i:j)`
se traduce a la rodaja real `text[starts[i] : ends[j-1]]`, que es **siempre** una subcadena
literal del original (por ser una rodaja del propio `text`).

Normalización aplicada **igual** a documento y a evidencia:

1. **NFC por grupos** (base + marcas combinantes) — casa NFC↔NFD (acentos).
2. **Eliminación** de controles Bidi / zero-width (`_REMOVABLE`) — impide spoofing visual.
3. **Plegado** de comillas/apóstrofes tipográficos a ASCII (`_QUOTE_FOLD`): `« » " " „ ‹ › ' ' ´ ` ′ ″`.
4. **Colapso** de cualquier whitespace (incluye NBSP, narrow NBSP, tab, CR, LF) a un único espacio.

El colapso de un *run* de espacios asocia el espacio normalizado al rango original completo
del run (reversibilidad preservada). Los caracteres eliminados que quedan **entre** dos
caracteres conservados caen dentro de `[start, end)` y por tanto dentro de la rodaja real
(que sigue siendo literal); en los bordes simplemente se excluyen.

## 3. Escalera (estricta, de arriba a abajo)

| Peldaño | Función | Criterio de aceptación | Fallo → |
|--------|---------|------------------------|---------|
| 0 · exacto | `realign_evidence` | `evidence in doc`; hint válido o única ocurrencia | ambigüedad si múltiples sin hint |
| 1 · normalizado-exacto | `_tier_normalized` | `norm_ev` aparece en `norm_doc`; única rodaja real, o desambiguada por proximidad al hint | ambigüedad si empate/sin hint |
| 2 · fuzzy en ventana | `_tier_fuzzy` | `score ≥ REALIGN_SCORE_THRESHOLD` en ventana acotada; sin segundo candidato equivalente | `below_threshold` / `ambiguous` |
| — | (fin) | — | `no_match` → el llamante conserva el rechazo base |

### Desambiguación por offsets

Cuando hay varias ocurrencias equivalentes, se usa el offset propuesto por el modelo como
*hint*: se elige la ocurrencia cuyo `start` real está más cerca del hint. **Empate exacto
de distancia ⇒ rechazo por ambigüedad** (fail-closed). Sin hint y con múltiples ocurrencias
⇒ rechazo.

### Fuzzy acotado (peldaño 2)

- Ventana derivada del hint: `[hint_start − SLACK, hint_start + span + SLACK]`, acotada por
  `REALIGN_MAX_WINDOW`. Sin hint usable: `[0, REALIGN_MAX_WINDOW]` (cota dura).
- Alineamiento con `difflib.SequenceMatcher` (bloques de coincidencia); `score` = ratio de
  la rodaja candidata frente a `norm_ev`.
- **Ambigüedad:** se enmascara el mejor tramo y se busca un segundo candidato. Si puntúa
  `≥ umbral` y dista `≤ REALIGN_AMBIGUITY_EPS` del mejor **y** mapea a otra rodaja real ⇒
  rechazo.

## 4. Umbrales y cotas PREDECLARADOS

Constantes nombradas en `evidence_realignment.py` (no números mágicos):

| Constante | Valor | Rol |
|-----------|-------|-----|
| `REALIGN_SCORE_THRESHOLD` | `0.82` | mínimo para aceptar fuzzy; admite paráfrasis leve, rechaza fuerte |
| `REALIGN_AMBIGUITY_EPS` | `0.05` | margen de equivalencia entre candidatos |
| `REALIGN_WINDOW_SLACK` | `48` | holgura de ventana alrededor del hint |
| `REALIGN_MAX_WINDOW` | `4000` | cota dura de trabajo fuzzy (anti-DoS) |
| `REALIGN_MAX_EVIDENCE` | `2000` | evidencia mayor ⇒ no se realinea (`too_long`) |

## 5. Integración en `_validate_verdict`

```
_validate_verdict(raw, cand, cid, document_text, realignment_enabled=False)
```

- Con `realignment_enabled=False` (default) el flujo es **idéntico** a la base.
- Con el flag ON, si la evidencia no es literal o los offsets no casan, se intenta
  `realign_evidence(seg, ev, hint_start, hint_end)`. Si `ok`, se **asegura por `assert`**
  que `seg[start:end] == evidence_text` y se sustituyen `ev/start/end`; la validación base
  posterior vuelve a comprobar el invariante. Si no `ok`, se conserva el rechazo.
- El verdicto saneado añade trazabilidad: `evidence_realigned` (bool), `realignment_tier`
  (str), `realignment_score` (float). Estas claves están **siempre** presentes con valores
  neutros cuando no hay realineamiento, para no cambiar la forma del contrato de forma
  condicional.

## 6. Determinismo

Sin red, sin estado global, sin aleatoriedad. `difflib` es determinista. Misma entrada ⇒
misma salida (verificado por el test de `request_hash` en la suite base, que sigue verde).
