# 60 — QA de producto y E2E de navegador del visor

Rama: `test/viewer-browser-e2e-v1` (desde `origin/main` @ `d169052`).
Carril D. **Solo pruebas**: no se ha modificado nada bajo `viewer/app/**`.

> **Integrado en `main`** vía PR #154 (`d496c08`, 2026-08-09). Las 148 pruebas
> las ejecuta el check **requerido** *Login browser contract (Playwright)*,
> que corre el directorio `viewer/tests/browser` completo.
>
> **Aviso sobre CI y el prefijo `test/**` (histórico — YA RESUELTO).** Las
> cifras y el razonamiento de abajo se tomaron trabajando en una rama `test/**`
> cuando ese prefijo **no disparaba** CI en `push`: el carril solo tuvo señal de
> CI al abrir el PR. Por eso conviene leerlas como medidas en local, no en CI.
>
> Eso **ya no describe el repositorio**: desde el PR #160 (`e21f766`, en `main`)
> `on.push.branches` es `['**']` y toda rama dispara CI el día que nace. `RK-16`
> está **CERRADO**; ver [risk-register](coordination/risk-register.md).

---

## 1. Problema

El visor tenía pruebas de navegador reales, pero de un solo contrato: el envío
explícito del formulario de login (`viewer/tests/browser/test_login_browser.py`,
24 pruebas, check de CI *Login browser contract (Playwright)*). Todo lo demás
—sesión, roles, revocación, recorrido de producto, estados de error,
accesibilidad, responsive— se comprobaba únicamente con `TestClient` de FastAPI,
que no ejecuta JavaScript, no tiene cookies de navegador ni foco de teclado, y no
puede distinguir «el servidor deniega» de «el navegador se lo cree».

En concreto, no había ninguna prueba que demostrase que **revocar una sesión
deniega la siguiente navegación**, que es el invariante que el modelo de
autorización M5b necesita poder dar por cierto.

## 2. Solución

Se **extiende la infraestructura existente**, no se introduce una segunda
plataforma: mismo Playwright síncrono, mismo patrón de servidor `uvicorn` real
en un puerto libre, mismo alcance de módulo. Lo que se añade:

- `viewer/tests/browser/e2e_support.py`: arranque parametrizable del visor real
  (`start_viewer`), siembra de usuarios de laboratorio de los cuatro perfiles
  (admin, reviewer, viewer, cuenta desactivada), captura de errores de consola y
  de excepciones JS, y utilidades de sesión (`do_login`, `is_denied`,
  `is_allowed`).
- `viewer/tests/browser/conftest.py`: fixtures `viewer`, `browser`, `new_page`
  y `page`. `new_page` es una **fábrica** de contextos aislados: permite tener
  admin y víctima conectados a la vez, con cookies separadas, dentro de la misma
  prueba.
- Cuatro módulos de prueba nuevos (ver §5).

### 2.1 Dos reglas que se han respetado al pie de la letra

**No se simula la frontera que se quiere probar.** El servidor es
`app.main:app` con `S9K_AUTH_ENABLED=true`, base de auth SQLite real, sesiones
server-side reales y los mismos guardas de rol que producción. No hay ni un
doble de autorización. Lo único sustituido es el *origen de datos* del grafo
(`S9K_GRAPH_PROVIDER=mock`), que es un proveedor del propio producto y no
participa en la decisión de permitir o denegar.

**La revocación se prueba sin barrer nada debajo de la alfombra.** La secuencia
de `test_revocar_sesiones_deniega_la_siguiente_navegacion` es exactamente:

1. La víctima inicia sesión por el formulario y navega con éxito a `/entities`
   (200, contenido servido).
2. En **otra pestaña**, un admin abre `/admin/users/{id}` y pulsa el botón real
   «Revocar sesiones activas» del panel.
3. La víctima navega de nuevo. Sin tocarle la cookie, sin limpiar caché, sin
   reiniciar el servidor.

La prueba además **verifica que no ha alterado las cookies de la víctima**
(`assert victima.context.cookies() == cookies_antes`) antes de comprobar la
denegación: si alguien «arreglase» la prueba limpiando estado, esa aserción la
delataría.

**Resultado: la revocación real funciona.** La siguiente navegación se deniega y
redirige a `/login`; la misma revocación corta también la API JSON (401); y
revocar a un usuario **no** expulsa a los demás. No existe caché que prolongue el
permiso: `AuthMiddleware` consulta la base de auth en cada petición.

## 3. Decisiones

| Decisión | Motivo |
|---|---|
| Extender Playwright, no añadir framework | Ya existe y ya está en CI; una segunda plataforma sería deuda sin contrapartida. |
| Fixtures de alcance **módulo**, no sesión | `test_login_browser.py` limpia variables de entorno y cachés de configuración en su teardown; un servidor compartido de sesión quedaría hablando con una configuración que ya no existe. |
| Contextos de navegador separados por rol | Es la única forma honesta de probar revocación y aislamiento entre usuarios: dos sesiones vivas simultáneas. |
| Usuarios propios para las pruebas destructivas | Desactivar o revocar a `s9viewer` envenenaría el resto del módulo. `create_lab_user` crea uno por prueba. Es preparación de datos, no sustitución de la frontera. |
| Defectos conocidos como `xfail(strict=True)` | La prueba escrita es la **correcta**; hoy no enrojece la CI, y el día que alguien corrija el defecto el XPASS falla y obliga a retirar la marca. Un defecto así no se pudre en un backlog: vive en el arnés. |
| Localizar el nodo del grafo por **píxeles** del `<canvas>` | vis-network no expone `network` en `window` ni genera DOM por nodo. Se leen los píxeles realmente dibujados, se calcula el centroide del color del tipo y se hace un **click de ratón de verdad**. Nada de invocar la API interna del grafo. |

## 4. Ficheros

Nuevos (todos bajo `viewer/tests/browser/`):

- `e2e_support.py` — infraestructura reutilizable.
- `conftest.py` — fixtures.
- `test_browser_auth_flows.py` — sesión, roles, revocación, cuenta desactivada.
- `test_browser_navigation.py` — recorrido de producto, estados vacíos, 403/404.
- `test_browser_backend_down.py` — Neo4j inalcanzable.
- `test_browser_accessibility.py` — accesibilidad, teclado, responsive.

Modificado:

- `test_login_browser.py` — **una** corrección, dentro de mi zona: el teardown
  borraba `S9K_CSRF_SECRET` en vez de restaurarlo (ver §7, hallazgo T-01).

No se ha tocado `viewer/app/**` ni la configuración de CI.

## 5. Escenarios cubiertos

| Escenario del encargo | Dónde | Estado |
|---|---|---|
| Login correcto | `test_login_correcto_entra_y_muestra_identidad` | ✅ |
| Login incorrecto | `test_login_incorrecto_*` (mensaje genérico, sin cookie emitida) | ✅ |
| Logout | `test_logout_cierra_la_sesion_y_la_vuelta_atras_no_la_resucita` | ✅ |
| Admin abre el panel admin | `test_admin_abre_el_panel_de_admin` | ✅ |
| Un viewer normal NO puede | `test_viewer_no_puede_abrir_el_panel_de_admin` (×3 rutas) + nav sin enlaces + API 403 | ✅ |
| Abrir grafo | `test_el_grafo_se_dibuja` | ✅ |
| Buscar entidad | `test_la_busqueda_encuentra_centra_y_resalta_un_nodo_visible`, `test_buscar_seleccionar_y_abrir_el_detalle` | ✅ |
| Buscar algo inexistente | `test_la_busqueda_de_algo_inexistente_no_encuentra_nada` (×2: nombre e id) | ✅ |
| Buscar un nodo **no autorizado** | `test_un_nodo_no_autorizado_es_indistinguible_de_uno_inexistente` | ✅ |
| Seleccionar | la búsqueda centra el nodo y abre su ficha (medido por píxeles del canvas) | ✅ |
| Abrir detalle | `test_desde_la_ficha_lateral_se_llega_a_la_ficha_completa` | ✅ |
| Sources / Jobs / Reviews | `test_las_secciones_de_reviewer_cargan_para_un_admin`, `test_la_navegacion_lleva_a_todas_sus_secciones` | ✅ |
| Estado sin datos | `test_estado_sin_datos_en_el_listado_de_entidades`, `test_reviews_sin_fuentes_no_finge_datos` | ✅ |
| 403 | `test_el_403_de_reviewer_si_es_una_pagina_del_visor` + hallazgo A-02 | ✅ |
| 404 | `test_las_rutas_inexistentes_no_dan_500_ni_filtran_trazas`, `test_el_404_de_la_ficha_de_entidad_es_una_pagina_del_visor` | ✅ |
| Error de backend controlado | `test_jobs_carga_haya_o_no_base_de_datos` | ✅ |
| Neo4j no disponible | `test_browser_backend_down.py` (9 pruebas) | ✅ |
| Usuario desactivado | `test_usuario_desactivado_no_puede_iniciar_sesion`, `test_desactivar_por_el_panel_corta_la_sesion_viva` | ✅ |
| **Sesión revocada → siguiente navegación denegada** | `test_revocar_sesiones_deniega_la_siguiente_navegacion` (+ API + aislamiento) | ✅ **real** |
| Teclado | login solo con teclado, foco visible, nav alcanzable con Tab, sin `tabindex` positivo, `<select>` operable | ✅ |
| Responsive básico | sin desbordamiento horizontal a 393 px (8 rutas), login usable en móvil, nav visible | ✅ |
| Sin errores JS graves en consola | `test_ninguna_pagina_lanza_errores_js_graves` (8 rutas) + aserción en cada prueba de sección | ✅ |

El filtro de ruido de consola tolera **solo el favicon**, que el visor no sirve y
que todo navegador pide por su cuenta. La primera versión descartaba *todo* 404 y
*todo* `net::ERR_`, de modo que si un `.js` o un `.css` del producto
desapareciera, la página se rompería y esta prueba seguiría en verde. Se
comprobó que los seis estáticos que referencian las plantillas existen, así que
no hay 404 legítimos que tolerar. Como Chromium no pone la URL en el texto del
mensaje, el filtro mira también `msg.location['url']`.

### 5.1 Lo que NO se ha podido cubrir, y por qué

- **Expiración de sesión por TTL / inactividad**: exigiría esperar el tiempo real
  o manipular relojes; falsearlo tocando la base sería exactamente el tipo de
  atajo que este encargo prohíbe. Queda en el backlog como prueba con reloj
  inyectado (cambio de aplicación, fuera de mi zona).
- **Selección de una relación (arista) en el grafo**: mismo obstáculo que los
  nodos, pero sin punto de anclaje fiable — una arista es una línea de 1 px cuyo
  color se comparte con el resto. Cubierto el panel de nodo, no el de arista.
- **Reviews con fuentes reales**: `/reviews` lee de `output/reviews/<workspace>`,
  que en laboratorio está vacío. Se comprueba el estado vacío, no el recorrido de
  decisión sobre una fuente. Poblarlo exigiría material de ingesta, prohibido.
- **Neo4j «a medias»** (responde pero lento o con errores parciales): sólo se ha
  probado «no hay nadie escuchando». Un proxy que corte a mitad de respuesta
  daría más señal; queda en el backlog.
- **Contraste en foco/hover y en estados de error del formulario de admin**: se
  ha medido el estado en reposo. Los estados transitorios necesitan una pasada
  aparte.
- **Lector de pantalla real**: se auditan roles, nombres accesibles, encabezados
  y landmarks por DOM, que es lo que un test puede afirmar honestamente. Que
  NVDA/VoiceOver lo lean *bien* no se puede concluir de esto.

## 6. Control positivo (mutación)

Obligatorio: si al quitar una protección todo sigue verde, las pruebas no prueban
nada. Se hicieron **dos** mutaciones, ambas revertidas (`git status` limpio, sin
cambios en `viewer/app/**` en el commit final).

**Mutación 1 — se ignora la revocación.** En
`viewer/app/auth/sessions.py::get_valid_session` se comentó:

```python
    # if session.revoked_at is not None:
    #     return None
```

Simula justamente lo que el encargo advertía: una caché que prolonga el permiso.
Resultado: **3 pruebas en rojo**.

```
FAILED test_revocar_sesiones_deniega_la_siguiente_navegacion
       - la sesion revocada siguio sirviendo contenido protegido: status=200
FAILED test_revocar_sesiones_tambien_corta_la_api_json
       - la API acepto una sesion revocada (status=200)
FAILED test_la_revocacion_no_afecta_a_las_sesiones_de_otros_usuarios
3 failed, 19 passed
```

**Mutación 2 — se retira el guarda de admin.** En
`viewer/app/auth/dependencies.py::require_admin` se comentó la comprobación
`if not user.is_admin(): raise HTTPException(403, ...)`.
Resultado: **5 pruebas en rojo**, incluida una del módulo de backend caído:

```
FAILED test_viewer_no_puede_abrir_el_panel_de_admin[/admin/users]   - devolvio 200 a un viewer
FAILED test_viewer_no_puede_abrir_el_panel_de_admin[/admin/audit]   - devolvio 200 a un viewer
FAILED test_viewer_no_puede_abrir_el_panel_de_admin[/admin/partidas]- devolvio 200 a un viewer
FAILED test_reviewer_entra_en_reviews_pero_no_en_admin              - assert 200 == 403
FAILED test_los_roles_siguen_separados_con_el_backend_caido
5 failed, 27 passed
```

Ambas revertidas con `git checkout --` y verificado que el árbol sólo contiene
ficheros de prueba.

## 7. Hallazgos (defectos de aplicación — NO corregidos aquí)

Todos viven en `viewer/app/**`, zona de las PR #152/#153. Se documentan; no se
tocan.

| ID | Hallazgo | Evidencia |
|---|---|---|
| **A-01** | Los 404 de rutas HTML devuelven **JSON crudo** al navegador. `/entity/{id}`, `/reviews/{id}`, `/jobs/{id}` y las rutas inexistentes lanzan `HTTPException` sin manejador propio, así que el usuario ve `{"detail": "..."}` sin navegación ni forma de volver. `/entities/{id}` sí usa `error.html`: la incoherencia es interna del producto. | `test_el_404_de_entity_es_una_pagina_html_del_visor` (`xfail(strict=True)`) |
| **A-02** | Mismo defecto en el **403 de admin**: `require_admin` lanza `HTTPException` y el usuario ve JSON, mientras que `_require_reviewer_or_redirect` sí pinta `auth/403.html`. | `test_el_403_de_admin_es_una_pagina_html_del_visor` (`xfail(strict=True)`) |
| **T-01** | *(corregido, estaba en mi zona)* El teardown de `test_login_browser.py` **borraba** `S9K_CSRF_SECRET` en vez de restaurarlo. Latente: en CI ese módulo corre solo, y en la corrida combinada se saltaba por falta de Playwright. Al instalar el navegador, `tests/test_auth_core.py::test_login_unknown_user_generic_message` empezó a recibir 403 (CSRF firmado con un secreto y validado con otro). | corrida combinada `viewer/`, 1 failed → 0 |

**Verificación posterior de T-01** (con Chromium presente, así que el teardown se
ejecuta de verdad; con el navegador ausente todo el paquete se salta y el camino
del defecto ni se recorre). `test_login_unknown_user_generic_message` pasa en los
tres modos, y no se observó ningún fallo:

| Modo | Comando | Resultado |
|---|---|---|
| Módulo aislado | `pytest -q tests/test_auth_core.py` | 18 passed |
| Suite completa | `pytest -q` (en `viewer/`) | 810 passed, 13 xfailed |
| Orden invertido | `pytest -q tests/browser <resto en orden inverso>` | 810 passed, 13 xfailed |
| Navegador justo antes | `pytest -q tests/browser tests/test_auth_core.py` | 153 passed, 13 xfailed |

No hay `pytest-randomly` ni `pytest-random-order` instalados, así que el tercer
modo se construyó **invirtiendo la lista de ficheros a mano** y poniendo
`tests/browser` en primer lugar, que es el orden que más favorece la fuga: el
módulo que toca `S9K_CSRF_SECRET` corre antes que quien lo consume.

Además se comprobó el teardown **directamente**, sin depender del orden: con un
centinela en `S9K_CSRF_SECRET`, `start_viewer` lo restaura al valor previo al
terminar, y lo elimina si no existía. Las dos ramas de `finally` quedan cubiertas.

Nada de esto afecta a la **seguridad**: las denegaciones son correctas en código
de estado; lo que falla es la presentación.

A-01 y A-02 se escriben como la prueba **correcta** (esperan HTML) marcada
`xfail(strict=True)`. En la primera versión de este carril afirmaban lo contrario
—`assert es_json_crudo`— y se contaban entre las pruebas en verde: arreglar el
defecto habría puesto la suite roja, es decir, se castigaba el arreglo. Ahora el
arreglo produce un XPASS que obliga a retirar la marca, que es el aviso correcto.

## 8. Backlog de accesibilidad

Todos requieren tocar plantillas o CSS bajo `viewer/app/**` → **fuera de mi
zona**, ninguno corregido. Los siete primeros están en el arnés como
`xfail(strict=True)`: no ensucian la CI y avisan solos cuando se arreglen.

**Las marcas son lo más estrechas posible.** Un `xfail` ancho es una regresión
esperando ocurrir: absorbe en silencio cualquier defecto NUEVO que caiga bajo su
aserción. Por eso:

- **ACC-04** está parametrizado **por página**, con la marca solo sobre las cuatro
  defectuosas (`/entities`, `/graph`, `/sources`, `/admin/users`). Las cuatro que
  sí tienen `<h1>` (`/`, `/jobs`, `/status`, `/reviews`) se exigen **en verde**: si
  alguna lo perdiera, su parámetro se pone rojo en el acto. Antes era **un solo
  test** que recorría las ocho acumulando fallos, así que perder un `<h1>` no se
  habría notado.
- **ACC-02** ya solo conserva su `xfail` en `/entities` (ahora **ACC-02b**): la
  UX V2 del grafo etiquetó los controles de `/graph`, el `xfail(strict=True)`
  pasó a XPASS y —según la doctrina del propio fichero— se ha **quitado la
  marca**, de modo que `test_los_controles_del_grafo_estan_etiquetados` protege
  el arreglo en verde. Lo acompaña `test_no_aparecen_controles_sin_etiqueta_nuevos`,
  también en verde, que falla si aparece **uno nuevo**.
- **ACC-03** ya no barre la página entera: el `xfail` mira solo la columna
  «Fuente» (`[style*="color:#555"]`), y
  `test_no_aparecen_textos_con_mal_contraste_nuevos`, en verde, barre **todo lo
  demás** de `/entities`.
- **ACC-06** y **ACC-07** ya nacieron acotados con `pytest.param(..., marks=...)`.

| ID | Problema | Impacto | Dónde |
|---|---|---|---|
| **ACC-01** | `/graph` no tiene `<main>` ni **ningún encabezado**. La página del grafo es un `<div>` suelto: sin landmark ni título, es un agujero negro para navegación por encabezados. | Alto | `app/templates/graph.html` |
| **ACC-02** | ~~Controles de `/graph` etiquetados solo con `placeholder`~~. **CORREGIDO** por la UX V2 del grafo: `graph.html` declara `<label class="sr-only">` para sus controles. La prueba ya no lleva `xfail`. | — | `graph.html` |
| **ACC-02b** | Controles etiquetados **solo con `placeholder`** en `/entities` (`q`, `entity_type`). El placeholder desaparece al escribir y muchos lectores no lo anuncian como nombre. | Alto | `entities.html` |
| **ACC-03** | Contraste por debajo de AA: `#555` sobre `#14161c` = **2.43:1** (columna «Fuente» de `/entities`, 11 nodos de texto); `#666` = **3.15:1** (metadatos del detalle de usuario); rojo de error `#e5534b` = **4.45:1** (justo por debajo de 4.5). | Alto | `app/static/css/app.css` y estilos en línea |
| **ACC-04** | Jerarquía de encabezados incoherente: `/`, `/jobs`, `/status`, `/reviews` tienen `<h1>`; `/entities`, `/sources`, `/admin/*` y `/login` empiezan directamente en `<h2>`. | Medio | plantillas |
| **ACC-05** | No hay enlace «saltar al contenido». Quien navega con teclado atraviesa 8–10 enlaces de la barra en **cada** página. | Medio | `base.html` |
| **ACC-06** | La tabla de `/status` no tiene `<th>`: se lee como cuadrícula sin significado. | Medio | `status.html` |
| **ACC-07** | `/admin/users` **se desborda a lo ancho en móvil**: 613 px de contenido en un viewport de 393 px. Scroll horizontal = columnas «Acciones» inalcanzables con el pulgar. | Medio | `admin/users.html`, CSS |
| **ACC-08** | Ninguna tabla de datos tiene `<caption>` (`/entities`, `/sources`, `/admin/users`). Menor que ACC-06, pero mismo origen. | Bajo | plantillas |
| **ACC-09** | No hay estilos de foco propios: el visor depende del anillo por defecto de Chromium. Funciona hoy, pero es frágil sobre fondo oscuro y no está bajo control del producto. | Bajo | `app.css` (no hay ninguna regla `:focus`) |

Lo que **sí** está bien y ha quedado blindado con pruebas que fallarán si se
rompe: `lang="es"` en todas las páginas; formulario de login íntegramente
etiquetado, con `autocomplete` correcto y `required`; errores de login con
`role="alert"`; formulario de alta de usuario con todos sus campos etiquetados;
botón de cerrar el panel del grafo con `aria-label`; ningún control sin nombre
accesible; ningún `tabindex` positivo; login completo solo con teclado; y siete
de ocho rutas sin desbordamiento horizontal en móvil.

## 9. Cifras reales de las pruebas

Entorno: Debian trixie, Python 3.13, Playwright 1.62.0, Chromium 151 (headless).

| Comando | Recogidos | Pasados | Saltados | xfail | Duración | Salida |
|---|---|---|---|---|---|---|
| `cd viewer && python3 -m pytest -q tests/browser` | 148 | **135** | 0 | 13 | 172,04 s | **0** |
| `cd viewer && python3 -m pytest -q` | 823 | **810** | 0 | 13 | 182,40 s | **0** |
| `python3 -m pytest -q tests/` | 198 | **196** | 2 | 0 | 3,16 s | **0** |

Los `xfail` pasan de 8 a **13** sin que se haya descubierto ningún defecto nuevo:
ACC-04 se ha troceado en cuatro parámetros (uno por página defectuosa) en vez de
un único test acumulado, y A-01/A-02 pasan a estar marcados en vez de contarse
—incorrectamente— entre los verdes.

Los 2 saltados de `tests/` son preexistentes y ajenos a este carril
(`test_external_nvidia_live.py` y `test_local_llm_ollama_live.py`: requieren API
key y un Ollama alcanzable). **Cero pruebas de navegador saltadas**: con el
navegador presente, saltárselas sería un verde que no comprueba nada, y el job de
CI ya falla explícitamente si aparece cualquier `skipped`.

Desglose de la suite de navegador (148 recogidas):

- `test_login_browser.py` — 24 (preexistentes, siguen verdes)
- `test_browser_auth_flows.py` — 22
- `test_browser_navigation.py` — 31 (29 verdes + 2 `xfail`: A-01 y A-02)
- `test_browser_backend_down.py` — 10
- `test_browser_accessibility.py` — 61 (50 verdes + 11 `xfail` de defectos ACC)

**Cero `skipped` en la suite de navegador**, que es lo que exige el job
`test-login-browser` de CI. Por eso `test_jobs_carga_haya_o_no_base_de_datos` ya
no usa `pytest.skip` cuando el entorno sí tiene `jobs.db`: comprueba una cosa u
otra según el escenario, pero comprueba algo en ambos. Un `skip` condicional bajo
una guardia antisalto pone el job rojo por una circunstancia del entorno, no por
un defecto.

## 10. Limitaciones y dependencias

- **Playwright no está en `viewer/requirements.txt`**. Se instala en el job de CI
  (`pip install playwright && playwright install --with-deps chromium`). En local,
  sin él, todo el paquete se **salta** por `importorskip` — nunca se da por
  pasado. No se ha añadido a `requirements.txt` para no imponer una descarga de
  ~120 MB a quien solo quiere correr las pruebas de servidor; si se prefiere lo
  contrario, es un cambio de una línea.
- En la máquina de desarrollo sin `sudo`, Chromium necesita `libnspr4`, `libnss3`
  y una veintena más (`libatk`, `libcups`, `libgbm`, `libpango`…); se resuelve
  con `apt-get download` de esos paquetes, `dpkg-deb -x` en un directorio y
  `LD_LIBRARY_PATH` apuntando ahí. En CI no aplica: `--with-deps` lo instala.
- Si Chromium **no** puede arrancar, la fixture `browser` se salta el módulo, pero
  solo tras comprobar que el mensaje de error corresponde a «no está instalado» o
  «faltan librerías del sistema»; cualquier otro fallo de `launch()` se propaga en
  rojo. Antes se capturaba `except Exception` y un crash real se presentaba como
  «no disponible», es decir, como un verde. El texto que hay que mirar es
  `str(exc)`, donde Playwright adjunta el *call log* con el stderr del proceso:
  **no** sirve sondear `browser_type.executable_path`, que apunta al Chromium
  completo mientras que `launch()` arranca `chrome-headless-shell`, un binario
  distinto con dependencias distintas.
- El job **Combined Test Suite** de CI no instala Playwright, así que allí las
  pruebas de navegador se saltan. Es el comportamiento previo y no lo he
  cambiado; la cobertura real la da el job dedicado, que sí falla ante cualquier
  `skipped`.
- El proveedor de grafo es `mock`. Las pruebas de recorrido dependen de
  `viewer/examples/sample_graph.json`: usan «Oni de la Montaña Negra» porque es
  el único nodo de tipo `Creature` (color propio, localizable en el canvas) y
  «Culto del Pozo Viejo» / `n_culto_pozo_viejo` porque es el único nodo
  `visibility: secret`. Las tres pruebas **fallan con un mensaje explícito**
  —no se saltan— si esos supuestos dejan de cumplirse.
- Las pruebas de canvas dependen del color de tipo definido en `graph-core.js`
  (`Creature` = `#e5534b`). Si cambia la paleta, hay que actualizar la constante.
- Cada módulo levanta su propio `uvicorn` (≈1 s). La suite completa tarda
  ~2 min 40 s; asumible, y evita el acoplamiento entre módulos.

## 11. Pendientes

1. **Decidir quién arregla A-01/A-02** (manejador global de `HTTPException` que
   devuelva `error.html`/`auth/403.html` cuando el cliente acepta HTML). Es un
   cambio pequeño y de una sola pieza, pero está en zona de las PR #152/#153.
   Cuando se haga, las dos pruebas de documentación deben borrarse.
2. **Backlog ACC-01…ACC-09** (§8). Los tres primeros son los que de verdad
   dificultan el uso; los demás son higiene.
3. **Prueba de expiración de sesión con reloj inyectable** — requiere que la
   aplicación permita sustituir `_utcnow` en `app/auth/sessions.py`.
4. Considerar exponer el objeto `network` de vis-network en `window` bajo un flag
   de prueba: haría comprobables la selección de aristas y el zoom sin depender
   de leer píxeles.
5. Si se quiere cobertura de navegador también en el job combinado, añadir
   Playwright a sus dependencias — hoy es la única vía por la que estas pruebas
   pueden pasar inadvertidas.

---

**Este carril no ha desplegado nada, no ha tocado producción, no ha usado
credenciales reales, no ha escrito en Neo4j y no ha ejecutado ingestas ni
backups.** Todas las contraseñas de las pruebas son literales de laboratorio que
solo existen en bases SQLite temporales creadas y destruidas por la propia suite.
