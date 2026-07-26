# Registro de mutación — Bloque 1 (cierre de defectos)

**Método.** Cada mutante se aplica sobre el fichero de **producción** indicado (nunca sobre un
alias, una constante muerta ni el propio test), se purga `__pycache__` **antes y después**, se
ejecuta la batería indicada y se restaura el fichero original. Un mutante está *muerto* si la
batería falla.

**NO se usa `PYTHONDONTWRITEBYTECODE=1`** (rompe
`deploy/tests/test_release_checksum.py::test_import_real_de_python_no_altera_checksum`). La
disciplina es purgar bytecode, no prohibir su escritura.

Comando por mutante:

```
find . -name __pycache__ -type d -prune -exec rm -rf {} +
cd data-engine/app && /usr/bin/python3 -m pytest <baterias> -q --no-header --tb=no -p no:cacheprovider
find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

`B1` = `tests/test_relation_v2e_block1_defects.py`.
`B7` = `tests/test_relation_v2_b7_external.py`.

---

## Ronda 1 — 16 mutantes

| # | Mutante | Fichero de producción | Batería | Resultado |
|:-:|---|---|---|---|
| M1 | La clave de la caché vuelve a ser el texto crudo (`_digest(text)` → `text`) | `relations/syntax.py` | B1 | MUERTO (1 failed) |
| M2 | `set_scope` cambia el ámbito pero **no purga** | `relations/syntax.py` | B1 | MUERTO (1 failed) |
| M3 | `DEFAULT_CACHE_TTL_SECONDS = None` (sin caducidad por defecto) | `relations/syntax.py` | B1 | **SUPERVIVIENTE** |
| M4 | Se elimina la llamada a `_purge_expired` en `analyze` | `relations/syntax.py` | B1 | MUERTO (2 failed) |
| M5 | Se elimina el desalojo LRU (`popitem(last=False)`) | `relations/syntax.py` | B1 | MUERTO (2 failed) |
| M6 | B5-D7: el acierto devuelve el objeto cacheado (`return entry[1]`) | `relations/syntax.py` | B1 | MUERTO (1 failed) |
| M7 | B5-D7: se guarda el objeto entregado al llamador (sin copia) | `relations/syntax.py` | B1 | MUERTO (3 failed) |
| M8 | B5-D7: copia **superficial** (`dataclasses.replace`) en el acierto | `relations/syntax.py` | B1 | **SUPERVIVIENTE** |
| M9 | `reset_default_analyzer` limpia la caché pero **no suelta** el singleton | `relations/syntax.py` | B1 | MUERTO (1 failed) |
| M10 | El pipeline vuelve a `safe_analyze(get_default_analyzer(), text)` | `relations/pipeline.py` | B1 | MUERTO (2 failed) |
| M11 | `REALIGN_OK_TIERS` vuelve a `{exact, normalized}` | `relations/evidence_realignment.py` | B1+B7 | MUERTO (2 failed) |
| M12 | Además, `normalized` vuelve a devolver `ok=True` con offsets | `relations/evidence_realignment.py` | B1 | MUERTO (3 failed) |
| M13 | Se desconecta `validate_external_verdict` del camino real (vuelve a resolver por su cuenta) | `relations/external_ai_shadow.py` | B1 | MUERTO (2 failed) |
| M14 | La "precisión" de negación se calcula sobre `gt.negated` (es decir, vuelve a ser recall) | `relations/benchmark/metrics.py` | B1 | MUERTO (3 failed) |
| M15 | El gate `negation_precision` devuelve siempre `PASS` | `relations/benchmark/report.py` | B1 | MUERTO (3 failed) |
| M16 | `uncertain` vuelve a cortocircuitar sin validar la evidencia | `relations/external_consult.py` | B1+B7 | MUERTO (1 failed) |

**14 muertos, 2 supervivientes.**

## Supervivientes: análisis y corrección

### M3 — `DEFAULT_CACHE_TTL_SECONDS = None`

**Por qué sobrevivió.** Los tres tests de TTL inyectaban `ttl_seconds` y un reloj falso a mano
para poder probar la caducidad sin dormir. Ninguno comprobaba que el analizador que **usa el
pipeline** (`new_scoped_analyzer`) ni el singleton de proceso nacieran con caducidad. El
invariante estaba enunciado; la ruta real no estaba cubierta.

**Corrección.** Test nuevo `test_el_analizador_de_PRODUCCION_nace_con_TTL_y_con_tope`: exige
que `DEFAULT_CACHE_TTL_SECONDS` sea un número positivo, que `new_scoped_analyzer` lo propague
(`stats()["ttl_seconds"]`), que el tope sea 512, y que el singleton tampoco nazca sin TTL.

### M8 — copia superficial en el acierto

**Por qué sobrevivió.** El test de anidamiento envenenaba el objeto devuelto en el **fallo** de
caché. Ese objeto es el del llamador: la caché guarda una copia aparte, así que la
contaminación nunca llegaba al almacén. Con copia superficial el vector real es distinto — el
objeto servido en un **acierto** comparte la tupla `sentences` con lo guardado — y ese caso no
se estaba ejerciendo.

**Corrección.** `test_la_contaminacion_alcanza_tambien_a_las_estructuras_anidadas` se reescribió
para: (1) provocar un acierto, (2) envenenar la frase y el token del objeto **servido en el
acierto**, (3) comprobar que un tercer llamador recibe estructuras limpias y objetos anidados
distintos.

---

## Ronda 2 — reejecución de los supervivientes

| # | Mutante | Batería | Resultado |
|:-:|---|---|---|
| M3 | `DEFAULT_CACHE_TTL_SECONDS = None` | B1 | **MUERTO** (1 failed, 29 passed) |
| M8 | Copia superficial `dataclasses.replace(entry[1])` | B1 | **MUERTO** (1 failed, 29 passed) |
| M8b | Copia superficial `copy.copy(entry[1])` (variante) | B1 | **MUERTO** (1 failed, 29 passed) |

---

## Resultado

**18 mutantes aplicados, 18 muertos.** Ningún superviviente queda sin reportar ni sin cerrar.
Ninguna corrección consistió en relajar el mutante o el test: en los dos casos se añadió
cobertura de la ruta real que faltaba.
