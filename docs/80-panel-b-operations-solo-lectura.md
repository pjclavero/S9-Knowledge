# 80 — Panel B: Operations Dashboard (SOLO LECTURA)

Carril **B** del chasis de montaje (docs/69). Panel de operaciones de **solo
lectura** sobre la autorización y el chasis que ya existen. No añade ninguna
capacidad al backend: todo lo que muestra ya se podía leer sin escribir.

## Contrato (publicado, no negociado aquí)

| campo | valor |
|---|---|
| prefijo | `/panel/operations` |
| ruta raíz | `chassis_operations` |
| rol mínimo | `admin` |
| plantilla | `chassis/operations.html` |
| interruptor | `S9K_PANEL_B_ENABLED` (apagado por defecto; **sólo** `true` o `1` encienden) |

Es la fila `B` de `CONTRATO_PUBLICADO` en
`viewer/tests/test_chassis_mount_contract.py`, escrita a mano contra
`FEATURE_SLOTS`. Este carril no la ha tocado.

## Qué muestra, y de dónde sale cada dato

Ninguna consulta nueva, ningún endpoint nuevo:

| bloque | origen | notas |
|---|---|---|
| Disponibilidad de la cola | `app.jobs_client.jobs_db_status()` | comprueba que el fichero exista y sea legible; no lo crea. `db_path` **nunca** se publica |
| Recuento por estado | `app.jobs_client.scoped_counts(scope, …)` | cuenta **sobre lo visible**: filtra por ámbito y sólo entonces cuenta |
| Filas de la cola | `app.jobs_client.scoped_jobs(scope, …)` | filtra por ámbito y recorta el detalle operativo de quien no es autoridad plena |
| Última salud registrada | `app.health.storage.load_last()` | el informe **ya guardado**; este panel no ejecuta comprobaciones |

Filtros (todos GET): `workspace`, `status`, `job_type`, `limit` (techo
`MAX_ROWS = 100`).

**Lo que se dejó FUERA a propósito**: cualquier cosa que exigiera un endpoint
nuevo o una lectura con efecto lateral. En concreto, el estado de salud *en
vivo*. `/admin/health` ejecuta los checks con `runner.run_report()` y acto
seguido, **dentro del mismo GET**, los guarda con `storage.save_report(report)`.
Precisión que la primera redacción de este documento se saltó: **`run_report`
no escribe**; el efecto lateral es del manejador de la ruta. La conclusión no
cambia —ese camino, tomado entero, es un GET que escribe—, así que este panel
enseña el último informe guardado y lo dice cuando no hay ninguno. Si se quiere
salud en vivo, hace falta una lectura sin persistencia, y eso es backend nuevo:
queda fuera de este carril.

## Frontera de solo lectura: cómo se garantiza

1. **Enumeración del ESPACIO DE URL**, no del módulo. El gate recorre las rutas
   de la *app real* bajo `/panel/operations` con `iter_mounted_routes` (el censo
   aplanado compartido) y exige que ninguna declare métodos de escritura. Un
   `@app.post("/panel/operations/…)` escrito desde otro fichero se caza igual
   (caso **B12**, inyectado desde `main.py`).
2. **Suelo de plausibilidad** que sólo cuenta rutas con `path` resoluble (para
   que el fallo cerrado de `route_in_prefix` no lo autocumpla) y que **nombra
   los paths concretos** de este carril: `/panel/operations` y
   `/panel/operations/`.
3. **Frontera de segmento**, con control de falso positivo y su contrapeso:
   `/panel/operationsXYZ/purgar` no es de este panel (**B19**), y el gate no
   puede apagarse sin que salte (**B20**).
4. **La plantilla no ofrece ninguna acción**: un solo formulario y es `GET`
   (**B16**). Un botón de "reintentar" sería una acción ofrecida al humano
   aunque el backend la rechazara, y la enumeración de rutas no lo vería.
5. **Sin efectos laterales medidos**: tras recorrer el panel no existe el
   informe de salud (**B13**) ni la base de datos de trabajos.

Lo que el CHASIS ya resuelve y este carril **no** rehace: composición del
prefijo de los `Mount`, `methods` y `path` tri-estado (ausencia ⇒ fallo
cerrado) y comparación por segmentos. Está calibrado en
`scripts/calibrar_panel_review.py` (R9–R20) sobre el mismo instrumento.

## Autorización

Ni una regla nueva: la puerta es `slot_guard(SLOT)` —que para un hueco `admin`
es `require_admin`, la misma de `/admin/users`— y el ámbito de datos es
`get_visibility_scope`, el mismo que usa `/jobs`. El interruptor se evalúa
**después** de la guarda, para que un anónimo no pueda enumerar qué paneles
están encendidos comparando 404 contra 302 (**B2**).

### Con la autenticación desactivada

**Medido**: con `S9K_AUTH_ENABLED` ausente, `require_admin` no encuentra
principal y responde `302 → /login` (o `401` si la petición no es de
navegador). El panel **no se sirve**: sin principal no hay autoridad (docs/75).
Y si se llegara a entrar, el contexto sería anónimo de mínimo privilegio, así
que la consola saldría **vacía**. Ninguna de las dos cosas es un defecto que
arreglar.

El test que lo fija es **bidireccional** a propósito
(`test_sin_auth_no_reaparece_el_comportamiento_permisivo`):

* **mitad A** — sin auth, ni un identificador de trabajo sale por la respuesta;
  si alguien devolviera este hueco a una guarda no-op, se pone roja (**B21**);
* **mitad B** — con auth y un admin de verdad, **el mismo material sí se
  entrega**. Sin esta mitad, "ocultarlo todo siempre" pasaría la mitad A en
  verde, y un panel que no enseña nada no es una defensa: es una avería que se
  lee como defensa.

### Simulación de ámbito, y por qué muerde

`get_visibility_context` se llama como función normal desde
`get_filtered_provider` y desde `get_visibility_scope`, así que sustituirlo con
`dependency_overrides` es **inerte**. Lo que entra por `Depends` en este router
es `get_visibility_scope`, y es lo que se sustituye, con un control de colapso
(`test_la_sustitucion_de_ambito_muerde`) que exige que sin la sustitución el
resultado **cambie**. El punto de inyección congelado no se ha tocado.

El material de prueba se inyecta en la capa **cruda** del puente
(`jobs_client.list_jobs` / `get_counts_by_status` / `jobs_db_status`), no en
`scoped_jobs`/`scoped_counts`: así el filtrado por ámbito de producción sigue
ejecutándose sobre el material del test. Sustituyendo las de arriba se mide el
código real; sustituyendo las de abajo, todas las pruebas de aislamiento serían
adorno.

## Ausencia ≠ cero, y ningún contador antes de la autorización

* Cola no disponible ⇒ se declara *no disponible* y **no se publica ningún
  recuento**. Un `0` inventado es una afirmación falsa sobre producción
  (**B5**).
* Los contadores se calculan **después** de la autorización: `scoped_counts`
  filtra por ámbito y sólo entonces cuenta. Un total tomado antes de filtrar
  revelaría por diferencia lo que la política acaba de ocultar — misma doctrina
  que `viewer/app/graph_view.py` y docs/73. Medido: con 6 trabajos en la base y
  2 visibles, el panel publica **2** (**B3**, **B4**).
* Salud: se distinguen *ausente*, *ilegible* y *disponible*. Ninguno de los dos
  primeros se pinta como "todo bien".
* Del informe de salud se publican componente y estado; **nunca** `message` ni
  `details`, que pueden traer rutas, hosts o comandos del servidor.
* De un trabajo se publica la **señal** de incidencia, nunca el texto del error.
* Y **campo a campo**, no sólo por sección: un `attempts` ausente se pinta *no
  disponible*, mientras que un `0` de verdad se pinta `0` (**B23**). Doctrina y
  contrapeso: mentir en la otra dirección —convertir todo cero en ausencia— es
  igual de mentira.

## Estados desconocidos: fallo cerrado

* Estado de trabajo contrastado contra `jobs.job_store.VALID_STATUSES`
  (importado, no copiado). Lo que no esté ahí se marca *estado no reconocido* y
  no se pinta como bueno (**B6**).
* El vocabulario es **tri-estado**: si no se puede leer (data-engine ausente),
  no se reconoce **ningún** estado — no saber no concede (**B7**).
* Un filtro `status` que no se puede contrastar se rechaza con **400** y el
  nombre del parámetro. No es cosmético: `job_store.list_jobs` levanta
  `ValueError` ante un estado inválido, así que pasarlo sin contrastar
  convertía una consulta en un 500 con traza (**B9**).
* Estado de salud contrastado contra `HealthStatus` (**B8**). `UNKNOWN` es un
  estado *reconocido* que significa "no se sabe", y se distingue de un valor que
  este visor no reconoce.
* Errores: la pantalla publica `type(exc).__name__` y nunca `str(exc)` (que
  puede traer la ruta de la base) ni la traza (**B10**).
* Y no sólo en el contrato de máquina: la **clase CSS** —"el aspecto"— también
  distingue conocido de desconocido, con las dos direcciones exigidas (**B22**).

## Calibración

`python3 scripts/calibrar_panel_operations.py` → **23/23**: verdes sin mutar,
rojas con el defecto inyectado, reversión byte a byte verificada por sha256, y
el rojo cae en la comprobación declarada (un rojo por el motivo equivocado se
reporta como fallo del caso).

## Limitaciones, dichas y no apuntadas como defensa

* `test_los_metodos_de_escritura_son_rechazados_por_http` sondea **sólo** el
  prefijo raíz: **medido**, no se pone rojo con un `POST` colgado de una
  subruta. Se conserva como redundancia y **no** figura entre los tests que
  cazan **B11**. La defensa real es la enumeración del espacio de URL.
* La mitad "la pantalla no contiene el texto del error" es cierta por partida
  doble (`redact_job` aguas arriba **y** la plantilla, que no lo pinta): no
  puede cobrarse como defensa de este carril. Lo que sí es de este carril, y lo
  que muerde, es que `_fila` no puede emitir ese texto ni recibiendo el trabajo
  sin redactar (**B14**).
* El panel **no tiene ficha de detalle**: para un trabajo concreto ya existe
  `/jobs/{job_id}`, con el mismo ámbito. Duplicarlo aquí habría sido superficie
  nueva sin valor nuevo.
* La sección de salud es **global** (infraestructura), no material de partida:
  no se acota por ámbito, se acota por la puerta `admin` del hueco. Hoy no
  concede nada nuevo, porque esa puerta es el mismo `require_admin` que ya abre
  `/admin/health`, que muestra lo mismo y además ejecuta.
  **Condición de futuro**: el día que existan *admins de partida* —un rol de
  administración acotado a un ámbito, que hoy **no** existe—, estos nombres de
  componente serían infraestructura global expuesta a un administrador acotado,
  y habría que acotar la sección o retirarla. Igual si el informe llegara a
  incluir datos de partida.
* La ausencia de escritura se demuestra por **enumeración de métodos HTTP**. Un
  GET que escribiera en disco no lo caza el censo: por eso se comprueba aparte,
  y por observación del sistema de ficheros, que este panel no escribe (**B13**).
* Los recuentos de un ámbito con autoridad plena (`admin_full`) los sirve
  `get_counts_by_status` desde dentro de `scoped_counts` — es el camino de
  producción, el mismo de `/jobs`. Que coincida con el total de la base es
  correcto ahí: la autorización concede todo. La medida de que el recuento es
  posterior a la autorización se hace con un ámbito que **no** es pleno.
* Aserciones NEGATIVAS: las de fuga (`"…" not in text`) las satisface cualquier
  cuerpo vacío. Donde se usan se exige además el **200** y un marcador positivo
  de que la pantalla se pintó, para que una regresión que devuelva 302 o 404 no
  las deje verdes por vacuidad.

## Deuda ajena, sólo anotada

`app/jobs_client.py` usa `_SCOPE_LIMIT = 100_000` como ventana para filtrar
antes de contar: por encima de esa cifra los listados y los recuentos **truncan
en silencio**. Es preexistente y compartida con `/jobs` y `/api/jobs`; este
carril no la toca ni la arregla, sólo la deja escrita.

## Método, y un aviso de herramienta

Las tres garantías añadidas tras la revisión independiente (**B22**, **B23**, y
el refuerzo de la aserción negativa) siguieron el ciclo completo: falso negativo
**medido en VERDE primero** (con las dos mutaciones puestas a la vez la suite
salía **48 passed**), arreglo, **ROJO** por la comprobación declarada, reversión
verificada por sha256 y **VERDE** de nuevo.

Aviso: en este entorno `python` **no existe**, y una invocación con ese nombre
puede devolver código de salida 0 sin haber ejecutado nada. Se usa `python3` y
se lee la **línea de resumen** de pytest, nunca el código de salida a secas.
