# 64 · El resultado de una ejecución y su procedencia, en la interfaz

**Carril C del Slice 2.** Superficie de **sólo lectura**. Cero escrituras.

## 1. El hueco que se cierra

El documento [54 · Procedencia navegable](54-procedencia-navegable.md) dejó la
cadena `V3Source → V3Episode → V3Evidence` **persistida** en Neo4j y declaró,
en su §6, lo que quedaba abierto:

> «exponer evidencia a un lector final exige una decisión de visibilidad […]
> Mientras no exista, la evidencia sólo es alcanzable por quien ya tiene acceso
> directo a la base.»

Medido en `main@6fb686a3` antes de este bloque:

| pregunta del operador | superficie que la contestaba |
|---|---|
| ¿qué cambió esta ejecución? | ninguna |
| ¿de qué fuente viene un hecho? | ninguna |
| ¿qué evidencia literal lo sostiene? | ninguna |

Y, para que no se confundan: la columna **«Procedencia»** de `/panel/sources`
es `source_kind` —vocabulario de **extracción**— y sale `no disponible` cuando
falta. No es la procedencia del *apply*. El único consumidor de `apply_id` en
todo `viewer/` era un fichero de pruebas.

## 2. La decisión de visibilidad, dicha en una línea

La política ya decidida para V3.2 es que **ver una assertion NO da acceso a
toda su fuente**. Aquí se hace ejecutable así:

> Un hecho —y por él su evidencia— se entrega **si y sólo si TODOS sus extremos
> de entidad son visibles para quien mira**, según `PolicyFilteredProvider`.

Consecuencias, todas comprobadas y no razonadas:

* **No hay ninguna ACL nueva.** Los nodos de procedencia siguen escribiéndose
  sin `visibility`, sin `known_by` y sin la etiqueta pública `:Entity`. No se
  alcanzan por política propia: se alcanzan por la de la entidad que el lector
  **ya podía ver**, o no se alcanzan. El invariante que afirman
  `test_contrato_writer_a_visor_neo4j` y `test_integracion_tanda11` sigue en
  pie, y se vuelve a afirmar en la suite nueva.
* **Sólo el fragmento soportante.** El recorrido es
  `(:V3Assertion)-[:SUPPORTED_BY]->(:V3Evidence)` y **para ahí**. No sube al
  episodio para bajar a sus hermanos. Medido: el apply de ejemplo deja 7
  fragmentos y la ficha de un hecho enseña 1.
* **El episodio es localizador, no contenido.** Su `text` no está en la lista
  blanca, así que no se pide en la consulta. Las dos cosas se comprueban por
  separado: una lista blanca correcta con una consulta que pidiera `ep.text`
  aparte daría verde en la constante y fuga en la pantalla.
* **Ámbito ausente = DENY.** El workspace se comprueba contra
  `provider.workspaces()` —el del proveedor **filtrado**— *antes* de consultar
  nada.

## 3. El recorrido, con identidades durables

```
apply_id ──► V3AppliedOperation ──► idempotency_key
                                      ├─► (:Entity)            entidades escritas
                                      ├─► [r]                  relaciones escritas
                                      └─► V3Assertion
                                            └─[:SUPPORTED_BY]─► V3Evidence  (literal)
                                                                  ├─► V3Episode (dónde)
                                                                  └─► V3Source  (de qué)
```

`apply_id` (`apply:<32hex>`) y `idempotency_key` son las dos llaves, y las dos
son durables y del contrato. **Ni un `elementId`**: no se selecciona, no se
devuelve y no se usa para emparejar. Las relaciones V3 no tienen identidad
durable propia, así que se atribuyen por la terna `(from, to, type)`.

**Carencia conocida:** `V3AppliedOperation` no tiene ninguna arista hacia lo
que escribió. El único vínculo es **por valor**, `idempotency_key`. No hay nodo
que represente la ejecución en sí. Funciona, pero es una unión por valor y
conviene saberlo.

## 4. Ausencia ≠ cero

Cada bloque lleva su estado: `DISPONIBLE` · `VACIO` · `NO_DISPONIBLE` · `ERROR`.
Una pantalla que no pudo leer **no publica un `0`** —`total` vale `None`—,
porque ese cero no lo ha medido nadie.

`NO_DISPONIBLE` (este despliegue no lee procedencia) y «ese apply no existe»
son cosas distintas: el primero es una página uniforme para cualquier
identificador, el segundo es un 404.

## 5. Montaje

`/panel/resultado/{apply_id}` y `/panel/resultado/{apply_id}/hecho/{assertion_id}`.
Sólo `GET`, comprobado por enumeración del espacio de URL.

**No es un hueco del chasis**: `app/chassis.py` declara cuatro (C/B/F/G) y ese
contrato es de otro carril. Se monta como `readonly` y `review-console`.

Interruptor `S9K_PANEL_RESULTADO_ENABLED`, misma semántica que la de los huecos
(`FLAG_ON_VALUES`, importada y no reescrita): **apagado por defecto**.

Rol `reviewer`, la misma guarda que `/sources` y `/panel/sources`. Un recurso
no autorizado es indistinguible de uno inexistente: el mismo 404 y el mismo
cuerpo.

## 6. Cómo reproducir la evidencia

```
docker run --rm -d --name <tuyo> -p 127.0.0.1:17687:7687 \
    -e NEO4J_AUTH=neo4j/<clave> neo4j:5.26-community
NEO4J_TEST_URI=bolt://127.0.0.1:17687 NEO4J_TEST_PASSWORD=<clave> \
    python -m pytest viewer/tests/test_resultado_procedencia_neo4j_real.py
```

Esa suite **no siembra una sola línea de Cypher de escritura**: el apply lo hace
`ingest_cli.run_ingest(..., apply=True)` por la ruta del operador.

**Trampa medida en este carril, y por la que la fixture exige que la escritura
no abortara:** sin `bootstrap_writer_schema` el writer aborta con
`EXEC_SCHEMA_CONSTRAINTS_MISSING`, el informe trae su `apply_identity` **igual**
y el grafo se queda a cero. Un `apply_id` perfectamente válido para un apply que
**no existe**. Un arnés que no lo exija mide el vacío.

## 7. Lo que sigue faltando

* **Carril B.** Hoy no hay apply lanzado desde la interfaz: en `main` no existe
  un plan aprobado durable. Esta superficie parte del `apply_id` que produce la
  ruta que sí existe (CLI/pipeline) y **no depende de cómo se lanzó el apply**:
  cuando B entre, sigue valiendo sin cambios.
* **Vocabulario de estados.** El Carril A introduce
  `AVAILABLE/EMPTY/UNAVAILABLE/ERROR` en la pantalla de revisión; en esta base
  todavía no existe. Cuando entre, unificar los dos vocabularios en un módulo.
* **Sin entrada de menú.** Se llega por el `apply_id`. Una lista de ejecuciones
  exigiría un nodo que represente la ejecución (§3), que no existe.
