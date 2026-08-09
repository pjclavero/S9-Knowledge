# 60 — QA de producto y E2E de navegador del visor

Rama: `test/viewer-browser-e2e-v1` (desde `origin/main` @ `d169052`).
Carril D. **Solo pruebas**: no se ha modificado nada bajo `viewer/app/**`.

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
| Buscar entidad | `test_la_busqueda_del_grafo_filtra_de_verdad`, `test_buscar_seleccionar_y_abrir_el_detalle` | ✅ |
| Seleccionar | `test_seleccionar_un_nodo_abre_su_ficha_lateral` (click real sobre el canvas) | ✅ |
| Abrir detalle | `test_desde_la_ficha_lateral_se_llega_a_la_ficha_completa` | ✅ |
| Sources / Jobs / Reviews | `test_las_secciones_de_reviewer_cargan_para_un_admin`, `test_la_navegacion_lleva_a_todas_sus_secciones` | ✅ |
| Estado sin datos | `test_estado_sin_datos_en_el_listado_de_entidades`, `test_reviews_sin_fuentes_no_finge_datos` | ✅ |
| 403 | `test_el_403_de_reviewer_si_es_una_pagina_del_visor` + hallazgo A-02 | ✅ |
| 404 | `test_las_rutas_inexistentes_no_dan_500_ni_filtran_trazas`, `test_el_404_de_la_ficha_de_entidad_es_una_pagina_del_visor` | ✅ |
| Error de backend controlado | `test_jobs_sin_base_de_datos_avisa_en_vez_de_reventar` | ✅ |
| Neo4j no disponible | `test_browser_backend_down.py` (9 pruebas) | ✅ |
| Usuario desactivado | `test_usuario_desactivado_no_puede_iniciar_sesion`, `test_desactivar_por_el_panel_corta_la_sesion_viva` | ✅ |
| **Sesión revocada → siguiente navegación denegada** | `test_revocar_sesiones_deniega_la_siguiente_navegacion` (+ API + aislamiento) | ✅ **real** |
| Teclado | login solo con teclado, foco visible, nav alcanzable con Tab, sin `tabindex` positivo, `<select>` operable | ✅ |
| Responsive básico | sin desbordamiento horizontal a 393 px (8 rutas), login usable en móvil, nav visible | ✅ |
| Sin errores JS graves en consola | `test_ninguna_pagina_lanza_errores_js_graves` (8 rutas) + aserción en cada prueba de sección | ✅ |

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
| **A-01** | Los 404 de rutas HTML devuelven **JSON crudo** al navegador. `/entity/{id}`, `/reviews/{id}`, `/jobs/{id}` y las rutas inexistentes lanzan `HTTPException` sin manejador propio, así que el usuario ve `{"detail": "..."}` sin navegación ni forma de volver. `/entities/{id}` sí usa `error.html`: la incoherencia es interna del producto. | `test_404_en_html_no_deberia_devolver_json_crudo` |
| **A-02** | Mismo defecto en el **403 de admin**: `require_admin` lanza `HTTPException` y el usuario ve JSON, mientras que `_require_reviewer_or_redirect` sí pinta `auth/403.html`. | `test_403_en_html_no_deberia_devolver_json_crudo` |
| **T-01** | *(corregido, estaba en mi zona)* El teardown de `test_login_browser.py` **borraba** `S9K_CSRF_SECRET` en vez de restaurarlo. Latente: en CI ese módulo corre solo, y en la corrida combinada se saltaba por falta de Playwright. Al instalar el navegador, `tests/test_auth_core.py::test_login_unknown_user_generic_message` empezó a recibir 403 (CSRF firmado con un secreto y validado con otro). | corrida combinada `viewer/`, 1 failed → 0 |

Nada de esto afecta a la **seguridad**: las denegaciones son correctas en código
de estado; lo que falla es la presentación.

## 8. Backlog de accesibilidad

Todos requieren tocar plantillas o CSS bajo `viewer/app/**` → **fuera de mi
zona**, ninguno corregido. Los siete están en el arnés como `xfail(strict=True)`:
no ensucian la CI y avisan solos cuando se arreglen.

| ID | Problema | Impacto | Dónde |
|---|---|---|---|
| **ACC-01** | `/graph` no tiene `<main>` ni **ningún encabezado**. La página del grafo es un `<div>` suelto: sin landmark ni título, es un agujero negro para navegación por encabezados. | Alto | `app/templates/graph.html` |
| **ACC-02** | Controles etiquetados **solo con `placeholder`**: `#search-input`, `#type-filter`, `#limit-select` en `/graph`; `q` y `entity_type` en `/entities`. El placeholder desaparece al escribir y muchos lectores no lo anuncian como nombre. | Alto | `graph.html`, `entities.html` |
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
| `cd viewer && python3 -m pytest tests/browser -q` | 138 | **130** | 0 | 8 | 158,35 s | **0** |
| `cd viewer && python3 -m pytest -q` | 813 | **805** | 0 | 8 | 173,40 s | **0** |
| `python3 -m pytest -q tests/` | 198 | **196** | 2 | 0 | 3,82 s | **0** |

Los 2 saltados de `tests/` son preexistentes y ajenos a este carril
(`test_external_nvidia_live.py` y `test_local_llm_ollama_live.py`: requieren API
key y un Ollama alcanzable). **Cero pruebas de navegador saltadas**: con el
navegador presente, saltárselas sería un verde que no comprueba nada, y el job de
CI ya falla explícitamente si aparece cualquier `skipped`.

Desglose de la suite de navegador (138 recogidas):

- `test_login_browser.py` — 24 (preexistentes, siguen verdes)
- `test_browser_auth_flows.py` — 22
- `test_browser_navigation.py` — 31
- `test_browser_backend_down.py` — 10
- `test_browser_accessibility.py` — 51 (43 verdes + 8 `xfail` de defectos ACC)

## 10. Limitaciones y dependencias

- **Playwright no está en `viewer/requirements.txt`**. Se instala en el job de CI
  (`pip install playwright && playwright install --with-deps chromium`). En local,
  sin él, todo el paquete se **salta** por `importorskip` — nunca se da por
  pasado. No se ha añadido a `requirements.txt` para no imponer una descarga de
  ~120 MB a quien solo quiere correr las pruebas de servidor; si se prefiere lo
  contrario, es un cambio de una línea.
- En la máquina de desarrollo sin `sudo`, Chromium necesita `libnspr4`/`libnss3`;
  se resolvió extrayendo los `.deb` en un directorio y usando `LD_LIBRARY_PATH`.
  En CI no aplica: `--with-deps` lo instala.
- El job **Combined Test Suite** de CI no instala Playwright, así que allí las
  pruebas de navegador se saltan. Es el comportamiento previo y no lo he
  cambiado; la cobertura real la da el job dedicado, que sí falla ante cualquier
  `skipped`.
- El proveedor de grafo es `mock`. Las pruebas de recorrido dependen de
  `viewer/examples/sample_graph.json`: `test_seleccionar_un_nodo_abre_su_ficha_lateral`
  usa el término «Kimi» porque aísla un único nodo, y **falla con un mensaje
  explícito** —no se salta— si algún día deja de aislarlo.
- Las pruebas de canvas dependen del color de tipo definido en `graph.js`
  (`Character` = `#6ea8fe`). Si cambia la paleta, hay que actualizar la constante.
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
