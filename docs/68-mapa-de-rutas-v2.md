# Mapa de rutas v2 — contrato mecánico de las rutas del visor

Repo: `S9-Knowledge` · rama `audit/route-contract-map-v2` · base auditada `cb874fe`
(carril L ya dentro de main), rama rebasada después sobre `8c70226`. Reconstruido
entero, no parcheado. Los artefactos de `artifacts/route-map/` llevan el HEAD con
el que se generaron; el árbol de la app no ha cambiado entre `cb874fe` y ese HEAD
en lo que este mapa mide (mismas 59 rutas, mismos recuentos).

> **Estado**: tras un dictamen *conforme con observaciones*, están corregidos y
> calibrados los tres defectos que encontró la revisión —Q1 (barrido ciego en los
> `POST` por el muro del CSRF), Q2 (404 de recurso inexistente contado como
> denegación) y Q3 (falsas rutas capturadas al compartirse el objeto `Route`)—.
> Ver §3.0, §4.1, §4.2 y §6.1. La calibración pasa de 12 a **15 casos**.

## 1. Qué arregla respecto al mapa anterior

El instrumento anterior **contaba menciones como cobertura**: que el nombre de una
ruta apareciera en un fichero se tomaba por prueba de que estaba montada, enlazada,
probada o autorizada. Ninguna de esas cuatro cosas se deduce de un `grep`.

Aquí cada propiedad tiene su propio mecanismo y su propia evidencia:

| propiedad | de dónde sale la evidencia | qué NO es |
|---|---|---|
| `defined` | AST de los decoradores `@router.<método>("...")` bajo `viewer/app/` | mención en un comentario |
| `mounted` | censo de rutas efectivas de la app **REAL** `app.main.app` | aparecer en `app.routes` |
| `linked` | BFS: navegación → ruta → plantilla que renderiza → sus enlaces y el JS que carga | que la cadena aparezca en algún HTML |
| `tested` | una petición atravesó el objeto `Route` de la app real durante `pytest` | que el nombre salga en un test |
| `authorized` | barrido HTTP real con auth activada: anónimo + un usuario por rol | que exista un `Depends` con nombre convincente |
| `consumed` | enlaces de plantillas/JS resueltos contra el enrutador + peticiones de tests | aparición del literal en cualquier fichero |

### El censo de rutas es el punto crítico

Con FastAPI 0.139 las rutas incluidas con `include_router` **no cuelgan de
`app.routes`**: quedan envueltas en objetos `_IncludedRouter` que resuelven sus
rutas efectivas en tiempo de petición. Medido en esta base:

- `app.routes` (enumeración ingenua): **11** rutas.
- censo efectivo (`iter_effective_routes`): **59** rutas.

Es decir, un auditor que use la API de Starlette declararía **48 rutas vivas como
muertas**. Es el mismo género de error que se venía a corregir, con el signo
cambiado. El censo efectivo recorre `effective_route_contexts()` y
`effective_low_priority_routes()`, y de cada contexto toma el path final, el
`dependant` ya combinado con las dependencias del `include_router`, y el objeto
`Route` ORIGINAL, que es el que FastAPI invoca realmente.

**Un único censo alimenta las tres medidas dinámicas** (montaje, sonda de
autorización y sonda de tests), de modo que no puede haber dos censos que
discrepen.

Nota medida, no supuesta: en esta base `app.url_path_for("entities_page")` **sí**
funciona (queda registrado en la calibración, caso M7). El problema real es la
enumeración, no `url_path_for`.

## 2. Cómo se ejecuta (reejecutable contra cualquier rama)

Todo se deriva de `--repo`, así que el mapa se puede recalcular contra otro árbol
—otra rama, otro worktree, un árbol mutado— sin tocar el repo:

```bash
# 1) evidencia de "probada": sonda sobre la app real durante la corrida
PYTHONPATH=scripts S9K_ROUTE_PROBE_OUT=/tmp/tested_routes.json \
  python3 -m pytest viewer/tests tests/integration tests/e2e \
  -p route_map.pytest_route_probe -q

# 2) mapa (incluye el barrido de autorización en un subproceso con auth ON)
python3 scripts/route_map/route_map.py --repo . \
  --tested /tmp/tested_routes.json \
  --out artifacts/route-map/route_map.json \
  --md  artifacts/route-map/route_map.md

# 3) calibración: inyecta defectos y exige que el mapa los vea
python3 scripts/route_map/calibrate.py --base . \
  --tested /tmp/tested_routes.json --out artifacts/route-map/calibracion.json
```

La sonda de autorización arranca la app en un **subproceso** con
`S9K_AUTH_ENABLED=true`, provider `mock` y una auth DB **efímera** en un
temporal; crea un usuario por rol y emite una sesión nueva por petición (el
barrido incluye rutas que revocan sesiones: una sesión reutilizada produciría
denegaciones falsas). No toca producción, ni Neo4j, ni la auth DB del repo.

## 3. Resultado sobre `cb874fe`

| medida | valor |
|---|---|
| rutas definidas (AST) | 59 |
| rutas montadas en la app real | 59 |
| alcanzables desde la navegación | 31 |
| ejercitadas de verdad por los tests | 47 |
| deniegan a un anónimo con auth ON | 57 (+2 públicas por diseño: `GET/POST /login`) |
| consumidas por alguien | 56 |

**Hallazgos duros: 0 rutas MUERTAS, 0 enlaces ROTOS, 0 rutas SIN AUTH.**
Ninguna ruta sirve 2xx a un anónimo salvo el formulario de login.

### 3.0 El titular «57 deniegan», recortado

El número suelto invita a leerlo como «57 rutas autorizan bien», y no es eso lo
que se ha medido. Desglose real (`desglose_denegaciones` en el JSON, y en la
primera línea del `.md`):

| tramo | valor |
|---|---|
| denegaciones **atribuibles** al control de acceso | **57** |
| de ellas, con guardián estático declarado | 56 (la excepción es `POST /logout`) |
| de ellas, de métodos con cuerpo (`POST`) | 12 + `POST /login`, pública por diseño |
| …sondeadas con un **token CSRF válido**, para que hable el guardián y no el CSRF | 12 de 12 |
| denegaciones **no atribuibles** dejadas FUERA del recuento | 0 |
| 404 ambiguos (ruta con `{param}` y sin guardián) dejados FUERA | 0 |

Las dos últimas filas son cero **en esta base**, y ése es el punto: son cubos que
existen y se llenan cuando hay motivo. Una revisión independiente demostró que
antes no existían y que su ausencia falseaba el titular en dos géneros distintos:

- **Q2 — el 404 gratis.** Una ruta `GET /fuga/{item_id}` **sin guardián alguno**,
  que devuelve el secreto con un id válido, respondía 404 al id fabricado por la
  sonda (`probe`) y se contaba como DENEGACIÓN. Medido sobre el árbol mutado con
  el instrumento anterior: `montadas` 59→60 y **`autorizadas` 57→58**, con
  `rutas_sin_auth = []`. Una ruta abierta de par en par **subía** el contador de
  rutas que deniegan. Afecta a toda ruta con `{param}`, o sea a la mayoría de la
  API. Además la misma fila decía a la vez `authz_probe: denegada` y
  `rol_minimo_observado: viewer`, y nada levantaba hallazgo.
- **Q1 — el muro del CSRF.** El barrido anónimo era **ciego** en los 13 `POST`:
  la comprobación CSRF respondía 403 antes que el guardián, así que un 403 de
  CSRF era indistinguible de un 401 de autorización. Medido: retirando
  `Depends(require_authenticated_user)` de `POST /partida/select`, el instrumento
  anterior seguía diciendo `autorizadas = 57` y `rutas_sin_auth = []`. La única
  señal era una lista **estática** y no calibrada.

Ahora: (a) el barrido **emite un token CSRF válido** —derivado con la misma
fórmula que el propio visor, sin tocar la app— para que quien decida sea el
control de acceso; (b) un 404 sin guardián estático se marca
`denegada-404-ambigua` y un 403 sin guardián estático `denegacion-no-atribuible`,
y **ninguno de los dos cuenta como denegación**; (c) el cruce de las dos señales
(«deniega al anónimo» + «servida a un rol» + sin guardián) es un hallazgo propio,
`contradiccion_deniega_y_sirve`. Los tres defectos están calibrados: casos
**M12, M13 y M14** de §4.

El detalle ruta por ruta —incluido el **rol mínimo medido** de cada una— está en
`artifacts/route-map/route_map.md` y `route_map.json`.

### 3.1 Rol por ruta (medido, no declarado)

El barrido repite cada ruta como `viewer`, `reviewer` y `admin`, y toma el rol
mínimo que obtiene respuesta servida. Resumen:

- **admin**: todo `/admin/**` y `/api/admin/health` (`viewer` y `reviewer` → 403).
- **reviewer**: `/sources*`, `/quality`, `/api/sources*`, `/api/quality`,
  `/reviews*`, `/review-console*`, `/v3/review*` (`viewer` → 403).
- **viewer**: `/`, `/graph`, `/status`, `/entities*`, `/entity/{id}`, `/jobs*`,
  `/account*` y las APIs de lectura general (`/api/status`, `/api/graph`,
  `/api/entities*`, `/api/search`, `/api/jobs*`, `/api/workspaces`,
  `/api/entity-types`) — 21 rutas.
- **nadie**: `/docs`, `/redoc`, `/openapi.json` (404 para todos mientras
  `S9K_AUTH_EXPOSE_DOCS=false`).

En los `POST` el veredicto de rol **ya no se declara no concluyente**. Antes sí,
y con razón: la comprobación CSRF respondía antes que el control de rol, así que
un 403 no distinguía «rol insuficiente» de «falta el token CSRF». La solución no
fue relajar la app —el instrumento se adapta a la app, nunca al revés— sino
**calcular el token que la propia app aceptaría** (`_csrf_para`, misma derivación
HMAC que `app.auth.middleware` y `app.auth.csrf`) y enviarlo. Con el CSRF
satisfecho, quien responde es el guardián, y los 13 `POST` pasan de
`no-concluyente-csrf` a un rol medido:

- **admin**: `/admin/users/**`, `/admin/partidas/**`, `/partida/select`.
- **reviewer**: `/review-console/source/{source_id}/decide`, `/v3/review/decide`,
  `/v3/review/undo`.
- **viewer**: `/account/change-password`.
- **ninguno sirve**: `POST /logout` (302 a `/login` para todos), `POST /login`.

El veredicto sólo se concluye si la sonda emitió un token válido en **las tres**
peticiones por rol; si no, vuelve a `no-concluyente-csrf`. Sigue midiéndose,
además, que ningún rol —ni el anónimo— obtiene 2xx.

### 3.2 Deudas señaladas (no son agujeros, pero conviene verlas)

- **12 rutas montadas y nunca ejercitadas** contra la app real: `GET /account`,
  `GET /admin/health`, `GET|POST /admin/users/new`, `GET|POST /admin/users/{user_id}`,
  `POST /admin/users/{user_id}/unlock`, `POST /admin/users/{user_id}/revoke-sessions`,
  `GET /review-console/`, `GET /v3/review/`, `GET /v3/review/glossary-candidates`,
  `POST /v3/review/undo`. La gestión de usuarios del panel admin es el hueco más
  visible: se prueba por otras vías, pero no atravesando sus rutas.
- **28 rutas no alcanzables desde la navegación**: casi todas son APIs JSON
  consumidas por fetch (legítimo). Al filtrar sólo las **pantallas HTML** quedan
  seis: `GET /admin/health`, `GET /quality`, `GET /review-console`,
  `GET /review-console/` , `GET /review-console/source/{source_id}`,
  `GET /v3/review/` y `GET /v3/review/glossary-candidates`. Cuando hablo de
  «cinco pantallas» me refiero a **pantallas distintas**: `/review-console/` y
  `/v3/review/` son la variante con barra de una pantalla cuya forma canónica sí
  está enlazada, así que no añaden una pantalla inalcanzable, sino una entrada
  más al censo. La lista cruda de 28, sin curar, está en el artefacto JSON.
  Existen, están protegidas y funcionan: simplemente no hay forma de llegar
  navegando. Material directo para el carril chasis.
- **`POST /logout` es la única ruta sin guardián estático detectable**; el
  barrido confirma que deniega igualmente (302 a `/login`), pero su protección no
  es declarativa.
- **Pares con y sin barra final** (`/review-console` y `/review-console/`,
  `/v3/review` y `/v3/review/`) son rutas distintas del censo con cobertura
  distinta: una está probada y la otra no.

### 3.3 Fragilidad estructural del patrón `Depends(html_guard)`

`html_guard` y `html_role_guard` **no deniegan por sí solos**: devuelven un
`RedirectResponse` que el handler tiene que devolver (`if isinstance(user,
RedirectResponse): return user`). Una ruta que declare la dependencia y olvide la
comprobación **sirve 200 a un anónimo aunque parezca protegida**. En `cb874fe`
todas las rutas que lo usan sí lo comprueban.

**Quién caza esto de verdad es el barrido anónimo.** La comprobación estática
(`guardian_declarado_pero_no_aplicado`) es una **ayuda heurística subordinada**,
no la garantía. Su primera versión era literalmente una búsqueda de subcadenas
(`"RedirectResponse" in src or "isinstance(" in src`): el mismo pecado que
denuncia §1 —contar menciones— sobreviviendo dentro de mi propio detector. Un
revisor metió un `isinstance(datos, list)` ajeno como señuelo y **la estática no
se disparó**; la ruta la cazó la dinámica. Ahora la comprobación es sintáctica
sobre el **parámetro concreto** al que está atado el guardián (exige un
`if isinstance(<ese parámetro>, ...)` que retorne, o un `return <ese parámetro>`)
y está calibrada con ese señuelo — caso **M11**. Aun así el orden de confianza es:
**primero la medida dinámica, después la estática**; si divergen, manda la que
hace la petición.

## 4. Calibración: el instrumento se ha visto rojo

«Una afirmación no constituye evidencia porque exista un test verde». Cada
defecto se inyecta en una **copia desechable** del árbol (nunca en el repo), se
recalcula el mapa, se comprueba que el hallazgo aparece, y se borra la copia; el
caso 0 sin mutar y la reejecución final sobre el árbol limpio deben dar
exactamente lo mismo.

| caso | defecto inyectado | salida real del mapa | ¿lo ve? |
|---|---|---|---|
| M0 | ninguno (control) | 0 hallazgos nuevos, `montadas` +0 | sí |
| M1 | `app.include_router(readonly_router.router)` comentado | `montadas` **−10** y 10 rutas MUERTAS nuevas (`GET /entities`, `/sources`, `/quality`, `/api/entities*`, `/api/sources*`…) + 11 enlaces ROTOS derivados | sí |
| M2 | `<a href="/ruta-que-no-existe">` en `base.html` | enlace ROTO nuevo: `/ruta-que-no-existe @ base.html` | sí |
| M3 | se quita `Depends(html_guard)` de `GET /entities` | SIN-AUTH nueva: `GET /entities` (200 anónimo) | sí |
| M4 | ruta nueva sin ningún test, con guardián declarado y no aplicado | NO PROBADA + SIN-AUTH + `guardian_declarado_pero_no_aplicado`: `GET /ruta-nueva-sin-test` | sí |
| M5 | `/ruta-solo-mencionada` citada en un comentario | **0 rutas nuevas**: la mención no crea ni cubre nada | sí |
| M6 | un test ejercita el router en una app `FastAPI()` **privada** | la sonda no registra `GET /entities`: no cuenta como cobertura | sí |
| M7 | censo: `app.routes` frente al censo efectivo | 0 rutas servidas fuera del censo efectivo, y **36 rutas que sirvieron respuesta se le pierden al censo ingenuo** | sí |
| M8 | `GET /admin/audit` degradada de `require_admin` a autenticado | rol mínimo medido cambia **admin → viewer** | sí |
| M9 | `NavItem` a una ruta no montada (navegación por datos) | ROTO con el `ChassisContractError` textual | sí |
| M10 | `/sources/panel` declarada **tras** `/sources/{source_id}` y **sin guardián** | `CAPTURADA` por `/sources/{source_id}` + rol `no-evaluable-capturada` | sí |
| M11 | guardián pasivo no devuelto, con `isinstance(datos, list)` **señuelo** | `guardian_declarado_pero_no_aplicado` + SIN-AUTH: `GET /ruta-con-senuelo` | sí |
| M12 | `GET /fuga/{item_id}` **sin guardián**, 404 con el id de la sonda (Q2) | `denegada-404-ambigua` + `contradiccion_deniega_y_sirve`, y **`autorizadas` +0** pese a `montadas` +1 | sí |
| M13 | se quita `Depends(require_authenticated_user)` de `POST /partida/select` (Q1) | el veredicto deja de ser `denegada` y **`autorizadas` −1** | sí |
| M14 | el mismo router incluido dos veces (`prefix="/dup"`) (Q3) | **0 capturadas nuevas** y las 10 rutas del segundo prefijo **medidas de verdad** | sí |

`reversion_identica: true` — tras las quince mutaciones, el árbol limpio devuelve
el mismo mapa. Salida completa en `artifacts/route-map/calibracion.json`.

### 4.1 M12, M13 y M14: rojo demostrado, no prometido

Los tres son defectos que encontró una revisión independiente, cada uno con su
mutación y sus cifras. Se reprodujeron **primero** contra el instrumento anterior
(`0b287f9`) para enseñar el falso negativo, y sólo después se arregló:

| caso | instrumento `0b287f9` | instrumento actual |
|---|---|---|
| M12 (404 sin guardián) | `detectado: false` · `autorizadas` **+1** · `denegacion_404_ambigua: []` · `contradicciones: []` | `detectado: true` · `autorizadas` **+0** · la ruta en los dos hallazgos |
| M13 (POST sin guardián) | `detectado: false` · `autorizadas` **±0** · veredicto sigue `denegada` (403 del CSRF) | `detectado: true` · `autorizadas` **−1** · veredicto `inconcluyente`, con el `AttributeError` real del handler sin usuario |
| M14 (router dos veces) | `detectado: false` · **10 capturadas falsas**, 10 rutas con rol `no-evaluable-capturada` | `detectado: true` · 0 capturadas · las 10 medidas (401 / 302 a `/login`, roles `viewer`/`reviewer`) |

Los dos ficheros están en `artifacts/route-map/diferencial-q1q2q3-instrumento-{viejo,nuevo}.json`.

Que las 10 rutas de M14 respondían **de verdad** (y no estaban capturadas) se
comprobó aparte con `TestClient` y auth desactivada: `GET /dup/entities` → **200**,
`GET /dup/api/entities` → **200**, igual que sus originales.

### 4.2 Ablación: ¿carga cada control su resultado?

Un control que nunca cambia ningún resultado no es defensa. Se quitó cada control
por separado, uno a uno, y se reejecutó su caso:

| control retirado | caso | resultado |
|---|---|---|
| cubo `denegada-404-ambigua` | M12 | **rojo** (`detectado: false`) |
| hallazgo `contradiccion_deniega_y_sirve` | M12 | **rojo** (`detectado: false`) |
| resolvedor indexado por `(id(route), path)` | M14 | **rojo** (`detectado: false`) |
| emisión del token CSRF válido | M13 | sigue verde |
| cubo `denegacion-no-atribuible` | M13 | sigue verde |
| **ambos a la vez** | M13 | **rojo** (`detectado: false`) |

Dicho sin adornos: para M12 y M14 cada control es **individualmente necesario**.
Para M13 los dos controles son **redundantes entre sí y necesarios en conjunto**:
sin el CSRF válido, el 403 del CSRF cae en el cubo «no atribuible» y la mutación
se ve igual; sin el cubo, el CSRF válido deja pasar la petición hasta el fallo
real del handler. Cada uno tapa el hueco del otro. No se anuncia como si fueran
dos defensas independientes.

La emisión del CSRF tiene además un efecto propio medible que ninguna ablación
disimula: los **13** veredictos de rol en `POST` pasan de `no-concluyente-csrf` a
un rol medido (§3.1). Sin ella, 13 de 59 rutas quedan sin medida de rol.

Sobre la **aserción de M7**: `len(censo_efectivo) > len(app.routes)` se cumple
sola y no prueba nada. La que carga el peso es doble y es la que se evalúa: el
censo **no pierde ninguna ruta que sirviera respuesta**, y el censo ingenuo **sí
pierde varias de ésas**.

**M10 y M11 nacieron rojos, y no por accidente**: son dos supervivientes que
encontró una revisión externa de este mismo mapa. Antes de arreglarlos, sobre el
árbol mutado idéntico, el instrumento `9afd737` daba `denegada`/`ninguno-sirve`
para la ruta capturada y **no marcaba nada** para el señuelo. La tabla comparativa
está en §6.

M1 y M3 son además la calibración pedida del enumerador: una ruta desmontada
desaparece del censo (y sale como muerta), y una ruta que sirve 200 aparece
montada. M6 cierra el error concreto que ya se cometió aquí: medir cobertura
contra una app privada de test.

## 5. Qué NO se cubrió (declarado, no disimulado)

- **`consumed` es el eslabón más débil.** Se resuelve por enlaces de plantillas y
  literales de URL en JS, con comentarios eliminados antes de mirar. No sigue
  URLs construidas dinámicamente más allá del caso `"/prefijo/" + variable`, ni
  consumidores externos al repo (nginx, otro servicio, un cliente humano). Una
  ruta marcada `consumed: false` puede tener consumidores reales fuera de vista.
- **Rol en `POST`: ya medido**, pero con una condición que conviene enunciar. La
  sonda calcula el token CSRF **reproduciendo la derivación del visor**. Si esa
  derivación cambia y el cálculo deja de coincidir, el barrido volvería a
  estrellarse contra el CSRF; lo que evita que eso pase en silencio es que
  `csrf_enviado` se registra por petición y el veredicto vuelve a
  `no-concluyente-csrf` si falta en alguna. Es una copia de una fórmula ajena, y
  como tal se puede desincronizar: M13 es lo que la mantiene honesta.
- **El barrido de `POST` ahora EJECUTA los handlers** (antes morían en el CSRF).
  Se ejecutan contra la auth DB **efímera** del subproceso y con provider `mock`,
  nunca contra nada persistente, y con una sesión nueva por petición. Aun así es
  un cambio de naturaleza del instrumento: pasa de mirar a tocar. Verificado que
  el resultado es **estable**: tres corridas seguidas dan un JSON idéntico.
- **Un 404 sin guardián estático no se cuenta como denegación, pero tampoco se
  declara agujero.** Queda en `denegada-404-ambigua`: es una ruta cuya
  autorización el instrumento **no sabe** medir con un id inventado. Para
  resolverlo haría falta un recurso existente por ruta, que el mapa no fabrica.
  El cruce con el rol observado (`contradiccion_deniega_y_sirve`) es lo que
  impide que ese «no sé» pase por un «sí».
- **El cubo ambiguo se decide con una señal ESTÁTICA** (¿declara guardián?), que
  es justo el tipo de señal que §1 desconfía. Se usa sólo para *no* dar por buena
  una denegación, nunca para darla por buena: el error posible es marcar como
  ambigua una ruta que sí denegaba, no al revés.
- **Nada de esto se probó contra producción ni contra Neo4j**: provider `mock`,
  auth DB efímera, sin red. El mapa describe el código, no el despliegue: no
  cubre reglas de nginx, redirecciones del proxy ni rutas servidas fuera de la
  app.
- **No se auditó la autorización de DATOS** (filtrado por visibilidad/partida:
  `get_filtered_provider`, `VisibilityScope`). El mapa distingue esas
  dependencias de las de control de acceso y las registra aparte, pero no evalúa
  si filtran bien: eso es de los carriles de authz/policies, que además están
  fuera de mi frontera.
- **Los `{param}` se sondean con un identificador inexistente**, así que en esas
  rutas se mide el control de acceso, no el comportamiento con datos reales.
- **La ejecución de tests no fija la lista de tests**: `tested` refleja la
  corrida concreta que se le pasa (`viewer/tests`, `tests/integration`,
  `tests/e2e`: 1054 pasados, 190 saltados). Con otro subconjunto, otra cobertura.
  190 tests saltados pueden ocultar cobertura real.
- **Sobre el chasis (PR #166) ya está ejecutado**: ver §5.bis. Lo que ahí NO se
  cubre: los huecos están vacíos (una pantalla sin funcionalidad), así que se
  verifica el montaje, no lo que cada carril meta dentro después; y el veredicto
  vale para `4b2ae5a`, no para lo que se le añada luego sin volver a medir.
- **Routers incluidos condicionalmente** (p. ej. `if os.environ.get(...):
  app.include_router(...)`) **no generan aviso**: el mapa describe el montaje del
  proceso que arranca con las variables de entorno de la sonda, así que una ruta
  que sólo existe con cierta configuración aparecerá montada o ausente según cómo
  se ejecute, sin señalar que su montaje es condicional. Es coherente con «el mapa
  describe el código, no el despliegue», pero conviene tenerlo presente: para una
  ruta así, hay que ejecutar el mapa una vez por configuración.
- **Este mapa no se revisa a sí mismo**: la calibración demuestra que el
  instrumento se pone rojo ante quince defectos concretos; no demuestra que no
  existan géneros de defecto que ninguno de los quince representa. La prueba está
  a la vista: **cinco de esos quince (M10, M11, M12, M13, M14) existen porque una
  revisión externa encontró lo que yo no había pensado en inyectar**, y las tres
  últimas atacaban directamente la afirmación central del carril («0 rutas sin
  auth», «57 deniegan»). El ritmo al que las revisiones siguen encontrando
  géneros nuevos es el dato honesto sobre la madurez de este instrumento.

## 5.bis Verificación del chasis (PR #166, `feat/chasis-montaje-v1` @ `4b2ae5a`)

> **Alcance: esto es un ENTREGABLE APARTE.** Las secciones 1–5 son el mapa y su
> calibración, que es lo que se revisó y avaló para este PR. Esta sección 5.bis es
> un **dictamen sobre un tercero** (PR #166), emitido con el mismo instrumento
> pero **no cubierto por el aval de la revisión de este PR**. Sus artefactos viven
> aparte, en `artifacts/route-map/chasis-4b2ae5a/`. Quien fusione el chasis debe
> tratarla como lo que es: una medición de K sobre otra rama, no una revisión
> independiente del chasis.

Es el paso para el que existe este mapa: **C/B/F/G no se montan hasta que se
verifique que el chasis no deja routers muertos, enlaces rotos ni rutas sin
auth**. Veredicto: **APTO**.

### Ajuste necesario del instrumento: la navegación pasó a ser DATOS

Con el chasis, `base.html` ya no lleva enlaces escritos a mano: recorre
`chassis_nav`, que resuelve **nombres** de ruta contra lo montado. Un mapa que
sólo leyera `href="..."` literales habría visto una navegación vacía y declarado
huérfano el visor entero — un falso positivo masivo. El mapa resuelve ahora
también el contrato (`app.chassis.nav_for` con un usuario de permisos máximos), y
un `ChassisContractError` **no se traga**: se reporta como enlace ROTO. Añadido
el caso de calibración **M9** para ese camino.

### Resultado sobre `4b2ae5a`

| medida | `cb874fe` | `4b2ae5a` |
|---|---|---|
| definidas / montadas | 59 / 59 | 61 / 67 |
| enlazadas | 31 | 35 |
| probadas | 47 | **67 (todas)** |
| deniegan al anónimo | 57 | 65 (+2 públicas) |

**0 rutas muertas · 0 enlaces rotos · 0 rutas sin auth · 0 rutas no probadas.**
Ninguna ruta preexistente perdió cobertura, enlace, rol ni denegación.

Los cuatro huecos, medidos uno a uno:

| hueco | montada | enlazada | probada | anónimo | rol contrato | **rol medido** |
|---|:-:|:-:|:-:|---|---|---|
| `GET /panel/review` | sí | sí | sí (7) | 302 → `/login` | reviewer | **reviewer** |
| `GET /panel/operations` | sí | sí | sí (7) | 302 → `/login` | admin | **admin** |
| `GET /panel/sources` | sí | sí | sí (7) | 302 → `/login` | reviewer | **reviewer** |
| `GET /panel/entities` | sí | sí | sí (6) | 302 → `/login` | viewer | **viewer** |

Contrato y medida **coinciden en los cuatro**; `viewer` recibe 403 en review,
sources y operations, y `reviewer` recibe 403 en operations. Ninguno cae en la
trampa del `RedirectResponse`: los cuatro devuelven la salida de
`html_role_guard` (`guardian_declarado_pero_no_aplicado: 0`), y el barrido
anónimo lo confirma en vez de fiarse del código.

### Censo cruzado: dos enumeradores independientes

`iter_effective_routes` (K) y `iter_mounted_routes` (chasis) se contrastaron
contra la verdad de campo (rutas que sirvieron respuesta en la corrida):

- 67 rutas en el censo de K, 68 en el del chasis. **Ninguna ruta sólo en K.**
- Única diferencia: el chasis cuenta el `Mount /static` como una ruta más; K lo
  clasifica aparte como montaje. No es una mentira de nadie: es una diferencia de
  clasificación. Consecuencia práctica nula, con un matiz: `route_index` del
  chasis indexa el nombre `static`, así que un `NavItem` que apuntara a `"static"`
  resolvería a `/static` en vez de reventar. Hoy ninguno lo hace.
- **0 rutas que sirvieron y falten en cualquiera de los dos censos.**

### Deuda menor, no bloqueante

Cada hueco monta dos rutas (`/panel/review` y `/panel/review/`). La variante con
barra está montada, probada y autorizada, pero **no enlazada** (`route_index`
prefiere el path corto). Duplica el censo (8 rutas por 4 pantallas) sin aportar
nada. Es cosmético; conviene decidirlo antes de que cuatro carriles lo copien.

### Las 5 pantallas huérfanas: el chasis las IGNORA

`NAV` no incluye ninguna de las cinco que señalé en 3.2. Tras el chasis siguen sin
un solo enlace que lleve a ellas: `GET /admin/health`, `GET /quality`,
`GET /review-console`, `GET /review-console/source/{source_id}` y
`GET /v3/review/glossary-candidates`. No las duplica ni las rompe: simplemente no
las adopta. Como `NAV` es ahora la fuente única de navegación, incorporarlas es
añadir una línea por pantalla — y mientras no se haga, existen y están protegidas,
pero son inalcanzables navegando.

### Calibración sobre la propia rama del chasis

Los quince casos se reejecutaron **contra `4b2ae5a`**, no sólo contra la base:
**15/15 detectados, `reversion_identica: true`**. Incluye M9 (menú de datos que
apunta a una ruta no montada → ROTO, con el `ChassisContractError` textual), M7
(censo: 11 vs 67, sin rutas servidas fuera del censo) y los tres casos nuevos
M12/M13/M14. Un instrumento que juzga una rama debe haberse visto rojo **en esa
rama**.

### Remedición tras el arreglo de Q1/Q2/Q3

El dictamen **APTO** del chasis se emitió con el instrumento anterior, que
arrastraba los tres defectos. Se ha vuelto a medir `4b2ae5a` entero con el
instrumento corregido para comprobar que el dictamen no dependía de ellos:

- Mismas 67 claves de ruta, mismos recuentos: 61 definidas / 67 montadas / 35
  enlazadas / 67 probadas / **65 deniegan** / 67 consumidas.
- **0 muertas · 0 enlaces rotos · 0 sin auth · 0 capturadas · 0 no probadas**, y
  además **0 en `denegada-404-ambigua`, 0 en `denegacion-no-atribuible` y 0
  contradicciones**.
- Los **cuatro huecos `/panel/**` no están afectados** por Q1 ni por Q2: son
  `GET`, sin `{param}`, con guardián declarado, y deniegan con 302 a `/login`.
  Su rol medido sigue siendo el mismo (reviewer / admin / reviewer / viewer).
- Única diferencia en las 67 filas: los **13 `POST`** pasan de
  `rol_minimo_observado: no-concluyente-csrf` a un rol medido. Es información
  añadida, no un cambio de veredicto.

**El dictamen APTO se mantiene sin cambios.** Los artefactos de
`artifacts/route-map/chasis-4b2ae5a/` están regenerados con el instrumento
corregido.

## 6. Rutas CAPTURADAS: detector, no aviso en prosa

Una ruta puede quedar **capturada** por otra declarada antes sin que nada falle:
`/sources/panel` la absorbe `/sources/{source_id}`, que responde «fuente no
encontrada» en vez de avisar de la colisión. Es la razón por la que el chasis
eligió el prefijo `/panel/…`.

**Esta sección afirmaba antes que una ruta capturada «se manifiesta como ruta
cuyo handler nunca es el que uno cree». Era falso, y una revisión lo demostró**:
una ruta capturada **y sin ningún guardián** no producía señal alguna. El mapa la
marcaba `rol_minimo_observado: "ninguno-sirve"` —el mismo valor que `/docs`,
`/redoc` y `/openapi.json`— y no entraba en `rutas_sin_auth`. Es decir: el mapa le
atribuía a la ruta capturada **el resultado de autorización del handler que la
ensombrece**, dando falsa tranquilidad justo en el «0 rutas sin auth», que es la
afirmación que sostiene este carril.

Ahora hay detector. Cada petición del barrido registra **qué handler la atendió
de verdad** (se instrumenta `handle` de cada ruta del censo). Si la URL
representativa de una ruta la atiende otro path, esa ruta es **CAPTURADA** y:

- entra en el hallazgo `rutas_capturadas` con el path del captor;
- su veredicto anónimo pasa a `CAPTURADA` (no «denegada»);
- su rol pasa a `no-evaluable-capturada` (no «ninguno-sirve»).

Una ruta capturada **nunca hereda el veredicto de autorización de su captor**,
porque su guardián no se ejecuta jamás. Diferencial real sobre el mismo árbol
mutado (`/sources/panel` declarada después de `/sources/{source_id}`, sin
guardián):

| | instrumento `9afd737` | instrumento actual |
|---|---|---|
| `GET /sources/panel` anónimo | `denegada` | **`CAPTURADA`** |
| rol mínimo | `ninguno-sirve` (igual que `/docs`) | **`no-evaluable-capturada`** |
| `rutas_capturadas` | detector inexistente | **`['GET /sources/panel']`** |

Calibrado en el caso **M10**, que no se conforma con «lo ve»: exige que lo
**distinga** de una ruta que legítimamente deniega a todos.

### 6.1 El detector se equivocaba al revés: falsas capturadas (Q3)

El mismo detector tenía su propio fallo, y del género *fail-quiet*: etiquetaba el
objeto `Route` **compartido** con el primer path efectivo que veía
(`route._s9k_resolver` cortaba el segundo envoltorio). Si un router se incluye dos
veces —`include_router(r)` y `include_router(r, prefix="/dup")`—, ambos montajes
comparten los mismos objetos `Route`, así que **10 rutas vivas se declaraban
CAPTURADAS** y `no-evaluable-capturada` mientras respondían 200 de verdad
(comprobado con `TestClient`). Su autorización dejaba de medirse **en silencio**,
que es exactamente el fallo que §6 venía a cerrar, con el signo cambiado.

El resolvedor se indexa ahora por **`(id(route), path)`**: se instala un único
envoltorio por objeto `Route`, que guarda todos los paths registrados para él y
en cada petición elige el que casa con la URL entrante. Calibrado en **M14**, que
exige la ausencia del falso positivo Y que las 10 rutas queden medidas de verdad.

Este repo no incluye hoy ningún router dos veces, así que el defecto no falseaba
la medición de `cb874fe`. Lo que falseaba era la **garantía**: cualquier rama que
introdujera un doble montaje habría perdido la medida de autorización de esas
rutas sin un solo aviso.

## 7. Ficheros

- `scripts/route_map/route_map.py` — censo, mapa, sondas e informe.
- `scripts/route_map/pytest_route_probe.py` — plugin de pytest: registra las
  peticiones que atraviesan la app real.
- `scripts/route_map/calibrate.py` — inyección de defectos y tabla de calibración.
- `artifacts/route-map/route_map.{json,md}` — mapa de `cb874fe`.
- `artifacts/route-map/calibracion.json` — salidas reales de la calibración.
- `artifacts/route-map/chasis-4b2ae5a/route_map.{json,md}` — mapa del chasis.
- `artifacts/route-map/chasis-4b2ae5a/calibracion.json` — calibración sobre la
  rama del chasis (15/15).
- `artifacts/route-map/diferencial-n3-n1-instrumento-{viejo,nuevo}.json` — el
  mismo árbol mutado (ruta capturada sin guardián + guardián con señuelo) visto
  por el instrumento `9afd737` y por el actual: el rojo previo de M10 y M11.
- `artifacts/route-map/diferencial-q1q2q3-instrumento-{viejo,nuevo}.json` — las
  mutaciones M12/M13/M14 vistas por el instrumento `0b287f9` (los tres falsos
  negativos, con sus deltas) y por el actual: el rojo previo de Q1, Q2 y Q3.
