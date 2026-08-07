# M5c — cierre de ámbito, serializadores y `known_by`

Corrección de los tres hallazgos (H1, H2, H3) del dictamen **NO CONFORME** del
revisor independiente de M5b. Bloquean el despliegue del visor hasta que otro
revisor igualmente independiente los dé por cerrados.

## Qué encontró la revisión

El defecto no estaba en el motor de políticas, que era correcto y estaba muy
probado. Estaba en la **frontera por la que los datos entran al motor**:

```
675 pruebas verdes del motor
+ un serializador que descartaba `partida_id`
= el aislamiento entre partidas no se evaluaba nunca sobre datos reales
```

`_node_to_dict` proyectaba los nodos de Neo4j con una lista **cerrada** de
claves que no incluía `partida_id` ni `known_by`; `_rel_to_dict` no incluía
`visibility`. El writer sí escribía esos campos: el dato existía y estaba bien
etiquetado, y se perdía al proyectarlo. `grep` de los serializadores reales en
toda la carpeta de pruebas daba **cero**.

La lección no es «faltaban campos». Es que **una proyección parcial silencia una
barrera entera sin poner nada en rojo**.

| | Antes | Después |
|---|---|---|
| **H1** aislamiento entre partidas | `partida_id` se perdía → la regla nunca se evaluaba | el campo viaja; regla activa |
| **H1b** acceso por ID | `elementId` global, sin acotar por workspace | acotado en el propio Cypher |
| **H2** relaciones | sin `visibility` → *todas* inválidas, visor sin aristas | el campo viaja; herencia observable |
| **H3** `known_by` | sin tipar: cadena → subcadena, dict → claves, entero → 500 | tipado estricto; malformado deniega |

## El cambio de fondo: el ámbito se declara

Antes, «sin `partida_id`» significaba capa juego compartida. Esa inferencia hacía
indistinguibles dos cosas que no lo son: un dato **deliberadamente** compartido y
un dato al que se le **perdió** el ámbito — y el segundo se resolvía hacia lo más
abierto. Neo4j tampoco distingue de forma útil una propiedad nula de una ausente.

Ahora existe un marcador positivo, `scope`:

```
scope = "juego"    -> lore compartido; no puede llevar partida_id
scope = "partida"  -> exige un partida_id legible y autorizado
ausente / otro     -> DENY
```

### Regla completa (fail-closed en todas las dimensiones)

| Situación | Resultado |
|---|---|
| `workspace` ausente o ilegible | `workspace_invalid` |
| `scope` ausente o desconocido | `scope_invalid` |
| `scope=juego` con `partida_id` | `scope_contradictorio` |
| `scope=partida` sin partida legible | `partida_id_blank` |
| partida no autorizada | `partida_not_allowed` |
| `visibility` ausente/inválida | `visibility_invalid` |
| `known_by` no lista de cadenas | `known_by_invalid` |

Un `known_by` malformado **no se repara sola**: convertir `"PJ01"` en `["PJ01"]`
dentro de una decisión de autorización es adivinar, y adivinar puede ampliar
permisos. Y ya no provoca un 500: se comporta como recurso no visible.

### Y para los datos nuevos

El writer **rechaza antes de llegar a Neo4j** lo que no declare su ámbito. No
basta con que la lectura falle cerrada:

```
legacy desconocido        -> se conserva como legacy
dato V3 nuevo desconocido -> no se escribe
```

## Consecuencia aceptada: el grafo legacy queda mudo

Los 199 nodos / 140 relaciones actuales no declaran ámbito, así que el visor
M5c no los mostrará. **Es deliberado**, está decidido por el operador y fijado
como prueba (`test_el_material_legacy_queda_mudo_y_eso_es_la_decision`), no como
efecto colateral que alguien pueda «arreglar» más adelante.

No se añade ninguna excepción de compatibilidad del tipo `if legacy:
missing_workspace_is_ok`. Ese camino alternativo se convertiría en una fuga
permanente, y sería convertir un hallazgo crítico bien detectado en deuda de
seguridad deliberada. Si hay que inspeccionar el legacy: acceso operativo
directo, separado del visor de usuario, auditado.

El grafo se conserva intacto — ver `docs/54-migracion-visibilidad-m5b.md`.

## Lo que impide que vuelva a pasar

1. **`test_provider_authz_fields_contract.py`** — congela la forma de los
   serializadores reales. Si alguien quita un campo de autorización de la
   proyección, se pone rojo aunque el motor siga perfecto. Incluye la red
   inversa: lee el código del motor y exige que todo `node.get(...)` que consulte
   esté declarado en la proyección.
2. **`test_neo4j_integration_authz.py`** — el test que faltaba por encima de
   todos. Escribe en un Neo4j efímero, lee con el proveedor real y decide con la
   política real: cruce de partidas, cruce de workspace, acceso por ID, conteos,
   búsqueda, relaciones, `known_by`, y datos corruptos que deben denegar sin
   reventar. En CI lo levanta un contenedor de servicio, y **el job falla si la
   suite se omite**: un `skip` verde equivale a no tener la prueba.

## Estado

Despliegue de M5b/M5c: **no autorizado**. Requiere revisor independiente —el
mismo u otro— con dictamen CONFORME. No vale que quien corrige declare CONFORME.
