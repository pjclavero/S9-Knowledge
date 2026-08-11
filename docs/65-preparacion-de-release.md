# 65 · Preparación de release: compatibilidad de esquema y rollback

Carril I (release readiness). Rama `ops/release-readiness-v1`, base `main` =
`e9c66dc`.

Este documento cubre tres cosas y sólo tres: **qué versión de esquema soporta
cada componente**, **qué pasa cuando la base está fuera de ese rango**, y **cómo
se vuelve de v3 a v2 sin perder controles**. Todo lo que se afirma aquí tiene
una prueba que se ha visto ROJA (tabla de calibración al final).

---

## 1. Decisión implementada

> «auth_db.v3: N-1 no puede arrancar sobre schema v3 si pierde controles.
> Rango de schema soportado + REFUSE TO START; rollback antes de abrir
> escrituras = código N-1 + restaurar v2.»

Traducida a código:

| Regla | Dónde vive |
|---|---|
| Cada componente declara su rango soportado | `viewer/app/auth/schema_compat.py` (`MIN_SUPPORTED_SCHEMA` / `MAX_SUPPORTED_SCHEMA`) |
| Fuera de rango → el proceso se niega a arrancar | `schema_compat.assert_compatible()`, llamada desde `auth_db.ensure_migrated()` |
| Versión desconocida → se rehúsa igual | `schema_compat.read_schema_version()` |
| Nunca hay modo degradado | no existe ninguna rama que continúe tras un rango incumplido |

### 1.0. Alcance exacto de la puerta (y hasta dónde NO llega)

**La garantía es: «ningún proceso ARRANCA fuera de rango».**
**No es: «ningún acceso ocurre fuera de rango».**

La puerta se aplica en `auth_db.ensure_migrated()`, por donde pasan el `startup`
del visor, el middleware, los routers y la CLI antes de servir nada. Pero
`auth_db.get_conn()` (`db.py:46`, ~20 llamadores directos) **no la llama**: sobre
una base v4, `ensure_migrated` rehúsa y `get_conn` entrega datos igualmente.

Hoy eso no es alcanzable en el servicio, porque el arranque aborta antes de que
se atienda ninguna petición. Pero un entrypoint nuevo escrito con el idioma
dominante del repositorio —`with auth_db.get_conn(p) as conn:`— y sin pasar por
`ensure_migrated` **rodearía la puerta**.

Se decidió no llevar la comprobación a `get_conn()` por **coste medido**:
`assert_compatible()` abre su propia conexión de sólo lectura y encarece cada
`get_conn` un **113 %** (390 µs → 832 µs por llamada, 2000 iteraciones).
Cachearlo devolvería el problema a su sitio peor: una caché obsoleta serviría
una base cambiada bajo los pies, justo en la comprobación que debe ser
fail-closed.

Como la garantía se estrecha, el límite **se fija por prueba de
comportamiento**: `test_la_puerta_cubre_el_arranque_no_cada_acceso` caracteriza
el hueco contra bases SQLite reales. Si alguien cierra el hueco, se pone roja y
le obliga a revisar lo que está escrito. Verificado como control positivo: al
añadir `assert_compatible()` a `get_conn()`, la prueba falla (§4.2). Queda como
superviviente **S8** (§8).

> **Aquí hubo también una prueba sobre la VERACIDAD de los docstrings. Se ha
> borrado.** Exigía que apareciesen tres cadenas verdaderas, y eso no comprueba
> veracidad: bastaba con **añadir** la promesa falsa dejando las tres cadenas en
> su sitio para que siguiera verde (16 passed con la mentira dentro), mientras
> que reformular la frase honesta con sinónimos la ponía roja. Tampoco sirve
> invertirla para prohibir las frases falsas: la frase honesta contiene
> literalmente «ningún acceso ocurre fuera de rango» —negada— y la mentira
> contiene esa misma cadena en afirmativo; separarlas exige entender la
> negación, y una lista de prohibidas falla **en abierto** ante el primer
> parafraseo. La veracidad de la prosa no es un invariante comprobable
> comparando cadenas: una prueba así da confianza sin cubrir nada y además se
> rompe sola con el tiempo. El razonamiento completo queda en el propio fichero
> de pruebas, para que nadie la reponga.

### 1.1. Rangos declarados

| Componente | Versión que escribe | Rango soportado | Fuente de verdad |
|---|---|---|---|
| `auth_db` (`viewer/state/auth.db`) | 3 | v1 … v3 | `viewer/app/auth/db.py::SCHEMA_VERSION` |
| `job_store` (`data-engine/state/jobs.db`) | 1 | v1 | `data-engine/app/jobs/job_store.py::SCHEMA_VERSION` |

`job_store` no tiene tabla de versión: su única migración es aditiva e
idempotente (`ALTER TABLE ADD COLUMN` guiado por `PRAGMA table_info`). La
constante existe para que el manifiesto pueda declararla leyéndola del código.
Si alguna vez necesita una migración no aditiva, subir ese número obliga además
a darle tabla de versión y su propio rango.

### 1.2. Por qué el límite superior es el que muerde

`auth.db` v3 añadió a `partida_access`:

- `max_visible_session`: el tope de progresión de campaña, decidido en el
  **servidor**;
- `character_id`: el personaje con el que ese usuario juega esa partida (de él
  depende que `known_by` no sea inerte).

El código v2 no conoce ninguna de las dos. Si arrancase sobre una base v3:

1. **Lee de más**: no aplica el tope de sesión, así que sirve material por
   encima del límite de la campaña.
2. **Escribe sin control**: al conceder un acceso deja `max_visible_session`
   NULL, y NULL significa «sin tope». Esas filas sobreviven a la vuelta a N.

Por eso no basta con avisar: se rehúsa el arranque.

### 1.3. Ausencia de dato ≠ permiso

`read_schema_version()` distingue cinco estados y sólo uno continúa:

| Estado de la base | Resultado |
|---|---|
| El fichero no existe, o existe vacío, o es una base sin tablas | **instalación nueva** → se permite (se creará en la versión actual) |
| Tiene tablas y `schema_version` con una versión dentro de rango | se permite |
| Tiene tablas y **no** tiene `schema_version` | **REHÚSA** |
| Tiene `schema_version` **vacía** (`MAX(version)` = NULL) | **REHÚSA** |
| No es SQLite legible, o la versión no es numérica | **REHÚSA** |

El defecto previo era `except Exception: return 0`: cualquiera de los tres
últimos casos se leía como «versión 0», es decir, como una base virgen a la que
se le podía aplicar la migración completa por encima de sus datos.

---

## 2. El manifiesto no puede mentir sobre su esquema

`deploy/scripts/lib.sh` escribía a mano:

```
"schema_versions": {"auth_db": 1, "job_store": 1}
```

con el código en `SCHEMA_VERSION = 3` desde hacía versiones. Y
`verify_release_identity.py` sólo comprobaba que la clave **existiera**
(`schema_versions_present`, **no crítica**), de modo que la mentira pasaba la
verificación.

Corregido en dos frentes:

1. `deploy/scripts/schema_versions.py` **extrae** las versiones del código de la
   propia release (lee el fuente, no lo importa: el script corre sobre el
   directorio de release, sin su venv). `create_manifest` lo invoca y **aborta**
   si no puede leerlas. Ya no hay dos sitios que mantener, así que no pueden
   divergir. El manifiesto lleva además `schema_supported_ranges`.
2. `verify_release_identity.py` gana el indicador **crítico**
   `schema_versions_match_code`, que compara manifiesto contra código.

Y un tercer hallazgo, del mismo género, encontrado por el camino:
`_verdict()` sólo contaba como fallo `ok is False`. Un indicador **crítico** que
no se podía evaluar (`ok is None`) se colaba como VALID: UNKNOWN colapsaba a OK.
Ahora produce UNKNOWN.

---

## 3. Procedimiento de rollback v3 → v2

**Orden obligatorio. La restauración va ANTES de abrir escrituras.**

| # | Paso | Por qué en este punto |
|---|---|---|
| 1 | Parar el servicio (`systemctl stop`) | Mientras haya proceso vivo hay escrituras posibles |
| 2 | Verificar que existe la copia v2 y es legible | Si no la hay, **no se sigue**: no se puede volver |
| 3 | Desplegar el código N-1 (mover `current` a la release anterior) | Todavía sin arrancar |
| 4 | **Restaurar la base v2 en el sitio de la v3** | Este es el paso que no se puede posponer |
| 5 | Arrancar | Ahora código y datos coinciden |
| 6 | Comprobar `schema_version` = 2 y que el servicio responde | Confirmación, no confianza |

La copia v2 la produce la propia migración: `auth_db.migrate()` copia
`auth.db` → `auth.db.bak.v{versión_actual}` antes de aplicar los saltos, es
decir, `auth.db.bak.v2` al subir de v2 a v3.

### 3.1. Qué se rompe si se hace al revés

Invertir 4 y 5 (arrancar N-1 con la base v3 todavía puesta) rompe este
invariante:

> **Toda fila de `partida_access` fue escrita por código que conocía todos sus
> controles.**

Con el orden invertido, el código v2 concede accesos sin `max_visible_session`
(NULL = sin tope). El daño no se limita a la ventana de rollback: esas filas
**siguen ahí cuando se vuelva a N**, y restaurar la copia v2 *después* ya no las
recupera, porque se escribieron después de la copia. Se elige entre perder las
escrituras del intervalo o conservar filas sin control.

Con el gate puesto, el orden invertido **ya no es posible**: el paso 5 falla con
`SchemaCompatibilityError` en vez de arrancar. La red de seguridad es que el
error ocurra, no que alguien recuerde el orden.

### 3.2. Ejecutado, no sólo escrito

`viewer/tests/test_rollback_v3_a_v2.py` corre los dos órdenes contra bases
SQLite reales: el correcto arranca, el incorrecto se rehúsa, y
`test_invariante_que_rompe_el_orden_incorrecto` deja escrita la fila sin tope
que justifica todo lo anterior.

---

## 4. Tabla de calibración

Cada fila: se introduce la violación, se comprueba que el sistema se pone
**ROJO**, se revierte, se comprueba que vuelve a **VERDE**. Salidas reales de
`pytest -q`.

| # | Violación introducida | Rojo | Verde tras revertir |
|---|---|---|---|
| M1 | `schema_compat`: se anula el límite superior (`if version > MAX:` → `if False:`) | `5 failed, 14 passed` | `19 passed` |
| M2 | `schema_compat`: base sin tabla `schema_version` devuelve `0` en vez de rehusar | `2 failed, 13 passed` | `15 passed` |
| M3 | `auth_db.ensure_migrated`: se quita `assert_compatible()` | `4 failed, 15 passed` | `19 passed` |
| M4 | `lib.sh`: vuelve el literal `{"auth_db": 1, "job_store": 1}` | `1 failed, 13 passed` | `14 passed` |
| M5 | `verify_release_identity`: deja de comparar declarado vs real | `1 failed, 13 passed` | `14 passed` |
| M6 | `_verdict`: un crítico indeterminado vuelve a dar VALID | `1 failed, 13 passed` | `14 passed` |
| M7 | `review_console`: vuelve el `":".join(parts)` | `5 failed, 8 passed` | `13 passed` |
| M8 | `review_console`: se quita el workspace del `decision_id`/`event_id` | `3 failed, 10 passed` | `13 passed` |

Los cuatro mínimos exigidos quedan cubiertos: esquema fuera de rango → arranque
rehusado (M1, M3); esquema ausente → rehusado, no permisivo (M2); versión
declarada ≠ real → rojo (M4, M5); rollback en orden incorrecto → detectado (M3,
más `test_orden_incorrecto_codigo_n_menos_1_sobre_base_v3_no_arranca`).

### 4.1. El CABLEADO del indicador crítico (observación O-2)

M5 mutaba el **interior** de `_schema_versions_match`, así que probaba la
función y no su conexión con `classify()`. La revisión independiente lo
demostró: borrar el indicador entero o degradarlo a `critical=False` dejaba la
batería en **`39 passed`, cero fallos**. Un gate que se puede desconectar con el
CI en verde no es un gate — precisamente el defecto que persigue este carril, y
en el indicador que sostiene §2.

Cerrado con cuatro pruebas que atacan el cableado, no la función
(`deploy/tests/test_release_identity.py`, última sección). Recalibrado contra
las **mismas tres formulaciones**:

| # | Violación introducida | Antes (revisión) | Ahora rojo | Verde tras revertir |
|---|---|---|---|---|
| O2-a | se borra el `add("schema_versions_match_code", …)` entero | `39 passed` ❌ no mordía | `4 failed, 39 passed` | `43 passed` |
| O2-b | se degrada el indicador a `critical=False` | `39 passed` ❌ no mordía | `4 failed, 39 passed` | `43 passed` |
| O2-c | el indicador siempre dice que sí (`ok, detail = True, "ok"`) | — | `3 failed, 40 passed` | `43 passed` |

Los mismos 39 que antes pasaban siguen pasando: lo que cambia es que ahora hay
4 pruebas más que se ponen rojas.

### 4.2. La prueba de prosa borrada, y lo que queda en su sitio

Tercera vuelta de revisión. La prueba que comprobaba los docstrings fallaba en
las dos direcciones a la vez; se borra y se calibra lo que queda.

| Caso | Qué se hace | Resultado | Lectura |
|---|---|---|---|
| **N-4** | se **añade** la promesa falsa («NINGÚN acceso ocurre nunca fuera de rango… no se puede rodear») conservando las cadenas exigidas | `16 passed` (verde) | Antes esto pasaba **mientras una prueba decía cubrirlo**. Ahora pasa y **nada afirma lo contrario**: se ha eliminado la falsa cobertura, que era el defecto. |
| **N-5** | se reformula la frase honesta con sinónimos, sin cambio semántico | `16 passed` (verde) | El falso positivo desaparece: el texto se puede reescribir sin romper la batería. |
| **N-6** | `python -OO` (docstrings a `None`) | `16 passed` / `43 passed` | Ya no rompe por un motivo ajeno a la seguridad. |
| **Control positivo** | se **cierra** el hueco: `get_conn()` pasa a aplicar `assert_compatible()` | `1 failed, 15 passed` | La prueba de comportamiento que queda **sí muerde**: se la puede ver roja, luego es un gate. |
| **N-2** | se cuela un homónimo benigno **delante** del indicador real | `2 failed, 41 passed` | El ensombrecimiento por *first-match* queda detectado (`_ind_unico` exige unicidad). |

La lección, que es la misma que persigue todo el carril: una prueba de **forma**
(¿aparece esta cadena?) da confianza sin cubrir nada; una prueba de
**comportamiento** (¿se hunde el veredicto? ¿entrega datos esa conexión?)
congela el resultado. Cuando una de forma no se puede convertir en una de
comportamiento, se borra — no se deja puesta «por si acaso».

---

## 5. `/reviews` y el workspace con `:`

Se revisó si un `:` dentro de un identificador de workspace rompe algo.

**No era un fallo** (comprobado, para que nadie lo re-audite):

- El confinamiento en disco: `_WORKSPACE_ID_RE` es lista blanca sin `:`, aplicada
  con `fullmatch`, más una comprobación de la ruta ya resuelta.
- La pertenencia al ámbito: comparación exacta de cadenas contra un conjunto.
- El aislamiento en SQLite y Neo4j: columnas y parámetros, nunca claves de texto
  concatenadas.
- `ledger:{workspace}:{seq:08d}`: el `seq` es de anchura fija, así que no hay
  reagrupación posible.

**Sí era un fallo**, en `viewer/app/services/review_console.py`:

1. `_stable_suffix` unía los campos con `":".join(...)`. El `:` es un carácter
   **idiomático dentro** de los identificadores de este repositorio
   (`partida:uno`, `pc:ana`, `human:<uuid>`), así que `("a:b","c")` y
   `("a","b:c")` daban el mismo hash.
2. Ningún llamador metía el `workspace` en el identificador, y el almacén de
   laboratorio es **uno solo y compartido** (`lab_store_dir()`, un JSONL
   append-only). Dos partidas con el mismo `candidate_id` producían
   `decision_id`, `event_id` y `document_id` **idénticos** en el mismo fichero.

Demostrado antes del arreglo:

```
ws1 decision_id: dec_53a7a4393ee4e384
ws2 decision_id: dec_53a7a4393ee4e384
COLISION decision: True     COLISION event: True     ambiguo: True
```

Después:

```
ws1 decision_id: dec_b7e8aea6b1f35620
ws2 decision_id: dec_e8435f2d016f3612
COLISION decision: False    COLISION event: False    ambiguo: False
```

Arreglo: los campos se serializan como **lista canónica** (el mismo patrón que
ya usaba `services/v3_glossary_candidates.py`) y el `workspace` entra como
primer campo. Los límites entre campos los pone JSON, no un carácter que los
campos pueden contener.

**Efecto secundario que hay que conocer**: los `decision_id` y `event_id`
cambian de valor. Son identificadores de un almacén de **laboratorio**
append-only, no de producción, y no se referencian desde Neo4j ni desde
`auth.db`; aun así, los documentos ya emitidos conservan sus ids antiguos y no
se recalculan.

---

## 6. Dependencias: divergencias detectadas (para el carril M)

No se ha tocado ningún `requirements*.txt`. Se documenta lo encontrado.

**No hay contradicción de versiones hoy**: los 6 paquetes que aparecen a la vez
en `viewer/requirements.txt` (rangos) y en `data-engine/requirements.lock`
(pines) son compatibles — `jinja2` 3.1.6, `pydantic` 2.13.4, `neo4j` 5.28.4,
`pytest` 9.1.1, `httpx` 0.28.1, `jsonschema` 4.26.0, todos dentro del rango.

Las divergencias son de **método**, y una de ellas toca directamente a este
carril:

| # | Divergencia | Por qué importa |
|---|---|---|
| D1 | `viewer/` **no tiene lock**: sólo rangos. `data-engine/` tiene `.in` + `.lock`. | Dos despliegues del mismo commit pueden instalar versiones distintas. |
| D2 | `dependency_fingerprint` del manifiesto = sha256 de `viewer/requirements.txt`, que es el fichero de **rangos**. | El manifiesto afirma identificar las dependencias y no lo hace: mismo fingerprint, distinto árbol instalado. Es el mismo género de defecto que `auth_db: 1`: un campo que declara más de lo que sabe. |
| D3 | CI instala `viewer/requirements.txt` sin pines (`ci.yml` y `test-graph-js.yml`). | El CI no es reproducible en el lado del visor: un verde de ayer no garantiza el de hoy. |
| D4 | `python-multipart>=0.0.9` sin cota superior (único caso del fichero). | Una major nueva entra sola. |
| D5 | `data-engine/requirements.in` no declara `pytest`/`pytest-asyncio`, pero el `.lock` los fija. | El `.lock` no es reconstruible desde el `.in`; nada lo comprueba en CI. |
| D6 | `preflight.sh` acepta **Python 3.11+**; todo el CI corre **sólo 3.13**. | Se despliega sobre un intérprete que nunca se ha probado. |
| D7 | `docs/v3/02-multimodal.md` afirma `pypdf==6.14.2`; el lock dice `pypdf==6.15.0`. | Deriva de documentación (fichero fuera de mi alcance: no se ha corregido). |

Sugerencia para el carril M, sin implementarla: D2 se cierra haciendo que el
fingerprint se calcule sobre lo **instalado** (`pip freeze` del venv de la
release) en vez de sobre el fichero de rangos.

---

## 7. Qué NO se ha probado

- **Nada contra producción**: ni VM105, ni Neo4j productivo, ni despliegue, ni
  backup real. Todo son bases SQLite sintéticas en `tmp_path`.
- **El arranque real del servicio**: se prueba `auth_db.ensure_migrated()`, que
  es el punto por el que pasan el `startup` del visor, el middleware, los
  routers y la CLI. No se ha levantado uvicorn contra una base v4 para ver la
  unidad systemd fallar.
- **El acceso a datos fuera del arranque**: no está cubierto por diseño y está
  medido y declarado (§1.0, S8), no probado como si lo estuviera.
- **`create_manifest` sobre una release de verdad**: se ejecuta contra releases
  sintéticas en `tmp_path`, vía bash, como en producción, pero no sobre un
  `/opt/s9-knowledge/releases/...` real.
- **El código N-1 de verdad**: el rollback se prueba parcheando el rango
  soportado a v2, no desplegando el commit anterior. Lo que se prueba es la
  puerta, que es lo que decide.
- **`job_store`**: declara versión pero no tiene tabla de versión ni gate de
  arranque. Su rango no se verifica en tiempo de ejecución (superviviente, §8).
- **Las divergencias de dependencias** de §6: detectadas por lectura, no
  reparadas ni probadas.

---

## 8. Supervivientes

Cosas que siguen abiertas tras este carril, clasificadas.

**Riesgo real, fuera del alcance de este carril:**

- **S1** — `job_store` no tiene tabla de versión ni comprobación de rango al
  arrancar. Hoy es inofensivo (v1 desde siempre, migración aditiva); dejará de
  serlo en cuanto haya una migración no aditiva.
- **S2** — `dependency_fingerprint` (D2): un campo del manifiesto que afirma más
  de lo que sabe. Mismo género que el defecto corregido aquí.
- **S3** — Ningún camino de **creación** de workspace valida la forma del
  nombre: `scripts/dev/create_workspace.py`, `routers/admin.py` (sólo
  `.strip()`), `S9K_DEFAULT_WORKSPACE`, y `review/segmenter.py`. La validación
  existe sólo en el consumidor (`_reviews_dir`): una defensa colocada al final
  del camino.
  La revisión independiente lo confirma **más grave** de lo que yo lo dejé
  escrito: `segmenter.py` toma el workspace de la cabecera `- Workspace:` del
  propio `.md` y lo estampa en `Segment.workspace`, mientras la ruta en disco
  usa el del llamador. El **contenido de un fichero puede etiquetar candidatos
  con un ámbito distinto del directorio del que salen**. La validación de forma
  tiene que estar en la CREACIÓN, no sólo en el consumidor. Va a ticket aparte.
- **S8** — La puerta cubre el **arranque**, no el acceso a datos: `get_conn()`
  no la aplica (§1.0). Declarado, medido y fijado por prueba; no cerrado.
- **S9** — `checks.py:212` (health) valida **presencia de tablas**, no versión:
  una base fuera de rango puede reportarse HEALTHY mientras el proceso se niega
  a arrancar. Señal contradictoria. Ticket aparte.
- **S10** — TOCTOU: `assert_compatible()` corre **fuera** del `flock` de
  `migrate()`. Entre la comprobación y la migración, otro proceso puede cambiar
  la base. Ticket aparte.

**Aceptado a propósito:**

- **S4** — Los `decision_id`/`event_id` ya emitidos conservan su valor antiguo:
  no se recalculan documentos pasados (§5).
- **S5** — El checksum v1 de release sigue teniendo su limitación conocida
  (`xargs` sin `-0`); no se toca, porque «arreglarlo» haría que dejara de
  reproducir manifiestos ya emitidos.

**Pendiente de otro carril:**

- **S6** — `requirements*` (carril M): D1–D6.
- **S7** — `docs/v3/02-multimodal.md` (D7): deriva de documentación.
