# Segundo dictamen NO CONFORME: G1, G2, G3

El primer revisor independiente emitió NO CONFORME sobre H1/H2/H3. Corregidos
esos tres, el trabajo volvió a un revisor independiente —no al implementador— y
el segundo dictamen fue **también NO CONFORME**, con tres vías nuevas de la
misma familia. Ese hecho es el resultado más útil de todo el ejercicio: dos
rondas de revisión adversarial encontraron defectos reales que 675 y luego 698
pruebas verdes no encontraron.

El patrón compartido por H1, H2, H3, G1 y G3 es siempre el mismo:

> una barrera deja de evaluarse **sin que nada se ponga rojo**.

## G1 — un campo consumido sin tipar reventaba en vez de denegar

`can_view` hacía `int(node.get("session_index"))` y `party not in
ctx.party_membership` a pelo. Verificado por el revisor: `"tres"` daba
`ValueError`, `[]` y `{}` daban `TypeError`, y `party=["p1"]` daba
`TypeError: unhashable type`. Ambos campos llegan del Neo4j real (viajan en la
proyección desde M5c) y `safe_props` del writer acepta cadenas y listas, así que
son escribibles desde un payload de plan.

Como `filter_nodes` recorre el conjunto **entero**, un único nodo envenenado
convertía en 500 el listado, el grafo, la búsqueda y los conteos de todo el
workspace. **Un 500 no es fail-closed**: es denegación de servicio a partir de
un dato escribible. El requisito era explícito —un dato malformado se comporta
como recurso no visible, nunca como error— y `known_by` ya lo cumplía; estos dos
campos se quedaron fuera de esa disciplina.

Corregido: tipado estricto, `session_index_invalid` y `party_invalid`. `bool` se
rechaza aunque sea subclase de `int`, porque no es un índice de sesión.

## G2 — `/reviews` no pasaba por el ámbito del servidor

`reviews_view` y `reviews_detail_view` tomaban `?workspace=` del cliente con el
rol como única defensa: ni `PolicyFilteredProvider`, ni `VisibilityScope`, ni
saneamiento de ruta. Verificado por el revisor contra una raíz de prueba:

- `?workspace=<otro>` listaba la cola de revisión ajena;
- `?workspace=../../secretos` **salía del árbol** y enumeraba directorios
  arbitrarios del servidor.

La fuga es de material **anterior** a la visibilidad y al ámbito: entidades y
descripciones en crudo, todavía sin etiquetar. Es preexistente, pero contradecía
de frente la afirmación de que todo el material de revisión comparte el
aislamiento: `/review-console` usaba `get_visibility_scope`; `/reviews` no. Esa
asimetría es la fuga.

Corregido: el workspace efectivo lo decide el servidor
(`_reviews_workspace`), y el identificador se valida por **lista blanca** de
forma —no por lista negra de `..`, que se esquiva con codificaciones— más
comprobación de confinamiento de la ruta ya resuelta. Responde **404 y no 403**:
un 403 confirmaría que el workspace ajeno existe.

## G3 — la red anti-reincidencia contenía viva una reincidencia

`known_by_of` leía `known_by_characters` como respaldo. Ese campo no estaba en
la proyección ni en la lista congelada, y el test inverso solo inspeccionaba
`inspect.getsource(VisibilityPolicy.can_view)`: la lectura ocurre en
`policies/models.py`, así que la expresión regular nunca podía verla. Y no es
hipotético: `ingest_rpg.py` escribe ese campo en nodos `:Entity` reales.

La dirección del fallo era restrictiva, no una fuga. Pero es exactamente el
defecto original —una barrera apagada en silencio— **dentro de la red puesta
para impedirlo**, y por segunda vez.

Corregido: el campo viaja en ambos serializadores y está en la lista congelada;
la red inversa barre ahora los dos módulos de política enteros en vez de una
sola función, porque una regla puede mudarse de sitio y la red no debe depender
de dónde viva.

## Deuda registrada, no corregida aquí

- **`elementId` no es identidad durable.** Al validar el migrador contra una
  restauración aislada se comprobó que el UUID de base se regenera al restaurar
  un dump, de modo que un plan firmado no es reproducible entre restauraciones.
  Un plan que deba sobrevivir a backup/restore debe apuntar a IDs de dominio
  estables (`entity_id`, `assertion_id`) junto con `workspace` y un
  `expected_state_hash`.
- **G4 — el writer que estampa ámbito escribe etiquetas que el visor no lee.**
  El writer V3 produce `:V3Entity`/`:V3Assertion`; el proveedor consulta siempre
  `:Entity`. Los dos escritores que sí producen `:Entity` (`ingest_rpg`,
  `review/ingest_approved`) no pasan por `stamp`. Hoy no hay fuga porque la
  ausencia de `scope` deniega, pero la frase «el writer rechaza antes de Neo4j»
  solo es cierta del writer V3. En cuanto alguien añada `scope` a esos dos para
  hacer visible lo nuevo, entrará `visibility` sin contrato por la puerta de al
  lado.
- **G5 — `VisibilityScope` conserva la inferencia permisiva** que el motor
  acaba de eliminar: `workspace is None` y `partida_id is None` devuelven
  `True`. Está razonado (una fila que nunca tuvo partida no es un nodo que
  perdió su ámbito) y el recorte de `redact_job` limita el daño, pero merece
  decisión explícita.

## Tercer dictamen: T1–T7

El trabajo volvió a un tercer revisor independiente, y también fue **NO
CONFORME**. Corregidos aquí: **T3** (`id` era el único campo que el motor
consumía sin tipar, y justo el que la red inversa descartaba a mano),
**T4** (`float(confidence)` y valores de nodo usados como claves en
`quality_metrics`: un solo nodo visible con confianza textual devolvía 500 en
`/quality` para todo el workspace) y **T5** (rutas absolutas del servidor
entregadas a cualquier reviewer).

### T1 y T2 — decisión pendiente del operador

Las reglas 4 y 5 del motor —*party* y *sesión futura*— **no se evalúan nunca
sobre datos reales**, por dos causas independientes que se tapan la una a la
otra:

- **T1**: el motor lee `party`, `is_public` y `session_index`. Ningún escritor
  del repositorio escribe esos nombres: `ingest_rpg` persiste `known_by_party`,
  `known_publicly`, `known_from_session`. Verificado ejecutando: el nodo tal
  como se escribe hoy sale `visible`; el mismo nodo con los nombres que el motor
  espera sale `party_scoped` / `future_session`.
- **T2**: `build_viewer_context` no puebla `max_visible_session`,
  `party_membership`, `active_character` ni `character_knowledge`. La regla 4 no
  entra jamás y `knows()` devuelve siempre `False`, de modo que **todo el
  mecanismo `known_by` de H3 y G3 es inerte en producción**.

G3 corrigió esta misma desalineación para **uno de los cuatro campos hermanos**
de la tupla de `ingest_rpg` y dejó los otros tres. La red anti-reincidencia no
puede verlo: congela que el campo **viaje** en la proyección, nunca que alguien
lo **escriba**. Sale verde con `party` en la lista y ningún `party` en el grafo.

Hoy no es fuga viva porque el legacy está mudo. Se convierte en fuga el día que
se ejecute el plan descrito en G4. Las opciones son cablear las reglas de
extremo a extremo (toca ingestión), retirarlas del motor y documentar que esas
dimensiones no existen todavía, o dejarlas como deuda explícita. **Una regla que
no se evalúa da una falsa sensación de barrera**, que es el patrón que estos
tres dictámenes llevan persiguiendo.

## Estado

- 726 pruebas del visor y 196 de raíz en verde.
- La suite de integración contra Neo4j efímero **no** cubre
  `relations_for_entity`, que es donde `_rel_to_dict` se usa con relaciones
  devueltas sin sus nodos. Es el mayor hueco que le queda.
- **Despliegue: sigue sin autorizar.** Requiere un tercer dictamen CONFORME de
  un revisor independiente. No vale que quien corrige declare CONFORME.
