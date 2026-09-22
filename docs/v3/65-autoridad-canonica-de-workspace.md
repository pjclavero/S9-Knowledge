# Autoridad canónica de workspace (corte F-2)

Estado: implementado. Base del corte: `934a45f`.

## El defecto

Había **cuatro declaraciones** de workspace y **dos autoridades efectivas
distintas**:

* el **entorno** (`S9K_DEFAULT_WORKSPACE`) gobernaba `/admin/partidas` y
  `allowed_workspaces`;
* el **perfil de la bóveda** (`perfil-operador.json`) gobernaba el ámbito de la
  fuente, el paquete de propuestas, `/v3/review`, el apply y el grafo.

Con los valores de fábrica divergían. Consecuencias medidas: conceder acceso de
partida al workspace donde está el conocimiento devolvía **400 sin aviso**, y un
revisor con `allowed_workspaces={leyenda}` leía y **mutaba** material de otro
workspace.

## La regla

> **El perfil de la bóveda es la autoridad canónica. El entorno es una
> declaración secundaria que no gobierna.**

`viewer/app/authz/autoridad_workspace.py` es el único punto que lo decide.

### Veredicto y diagnóstico son ortogonales

| estado | `resuelto` | `diverge` | significado |
|---|---|---|---|
| `WORKSPACE_AUTHORITY_PROFILE` | sí | no | manda el perfil; el entorno calla |
| `WORKSPACE_AUTHORITY_PROFILE_CONFIRMED` | sí | no | los dos dicen lo mismo |
| `WORKSPACE_AUTHORITY_DIVERGENT` | **sí** | **sí** | manda el perfil **y** se reporta que el entorno lo contradice |
| `WORKSPACE_AUTHORITY_ENV_FALLBACK` | sí | no | no hay perfil; se usa el entorno |
| `WORKSPACE_AUTHORITY_UNDETERMINED` | no | no | ausencia: no hay autoridad |
| `WORKSPACE_AUTHORITY_MULTIPLE_PROFILES` | no | no | varias bóvedas discordantes |
| `WORKSPACE_AUTHORITY_CATALOG_UNAVAILABLE` | no | no | no se pudo mirar |

Devolver «sin workspace» ante una discrepancia convertiría **un diagnóstico de
configuración en una denegación total del producto**, y no eliminaría la doble
autoridad: la disfrazaría.

**AUSENCIA NO ES DIVERGENCIA.** «No hay perfil» y «hay perfil y el entorno lo
contradice» son hechos distintos y se dicen distintos.

## La ubicación declarada

> **El material de ejemplo del repositorio no es una declaración del operador.**

`sources_catalog.ubicacion_declarada(env)` es cierto sólo si el operador declaró
`S9K_VAULT_ROOT` o `S9K_INGEST_SOURCES_DIR`. Sin eso,
`directorio_de_fuentes()` cae en `examples/ingesta-v3/`, que trae su propio
`perfil-operador.json`: sin esta regla, **el workspace de un fichero de ejemplo
gobernaría los permisos de un despliegue**.

La regla se aplica **en los dos lados del camino, con el mismo predicado**:

* **autorización** — el perfil del ejemplo no da autoridad; se cae al fallback
  del entorno, declarado como tal;
* **ingesta** — `listar_fuentes()` no deriva el ámbito de ese perfil. La fuente
  se **sigue listando** (hay material) pero **sin workspace**, de modo que el
  alta falla cerrada con `SOURCE_PACKAGE_INVALID`.

Aplicarla a un solo lado reintroducía la doble autoridad íntegra, y además
**muda**. Medido con la configuración de fábrica antes de corregirlo:

```
AUTHZ            -> 'leyenda'      (FALLBACK_ENTORNO)
listar_fuentes() -> 'ws-cofradia'  (del perfil de examples/)
```

Es coherente con el preflight, que ya trata `S9K_INGEST_SOURCES_DIR` sin
declarar como **ROJO** porque «el catálogo caería en los ejemplos del
repositorio».

## Qué NO cambia

* `allowed_workspaces` **sigue siendo un singleton** del despliegue. Lo único
  que cambia es de dónde sale su único valor. El modelo usuario → varios
  workspaces sigue diferido (`49-multipartida-diseno.md`).
* Los corpus de revisión se siguen filtrando **por partida, no por workspace**.
* Los valores por defecto **no se alinearon**: alinearlos escondería la
  divergencia en vez de eliminar la segunda autoridad.

## Coste por petición

El resolvedor corre en la dependencia de visibilidad, es decir en cada petición.
Hubo una caché por firma `stat()` y **se retiró**: se midió que ninguna firma
basada en `stat()` es fiable aquí — con `mtime`+`size` basta restaurar el mtime
(`rsync -a`, `cp -p`, `tar -x`) y con `ctime` añadido la granularidad de este
sistema de ficheros es de **un segundo**, así que dos escrituras en el mismo
segundo vuelven a dejarla rancia. Siendo la autoridad de autorización, se
prefiere la garantía. Coste medido:

| configuración | coste |
|---|---|
| sin bóveda declarada (fábrica) | **3,6 µs** — no toca el disco |
| bóveda plana declarada, un perfil | **50,9 µs** |
| árbol de bóvedas declarado, doce juegos | **584,8 µs** |

Si algún día molesta, el remedio correcto es una caché con **invalidación
explícita**, no adivinar por `stat()`.

## Inversión de capas, declarada

`authz` depende de `sources_catalog` a través de este resolvedor. Es
deliberado: es el precio de tener **una** autoridad, y la alternativa es que
authz conserve la suya, que es el defecto. La dependencia es de un solo sentido
y está acotada a un resolvedor.
