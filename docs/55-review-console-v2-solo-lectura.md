# 55 — Review Console V2 (solo lectura)

Carril C. Rama `feat/review-console-v2-readonly`. Sin PR, sin despliegue.

## Problema

La cola de revisión V3 (`/v3/review`) presenta las propuestas de una en una y con
los campos justos para decidir. Para *entender* por qué algo está en revisión —y
para trabajar sobre cientos de elementos— faltaba una herramienta de inspección:
sin filtros por motivo, confianza, proveedor o extractor, sin búsqueda, sin
paginación, sin una ficha que enseñe evidencia, candidato, decisión y procedencia
juntos, y sin una explicación en palabras de por qué el motor no lo aplicó solo.

## Solución

Una consola **de solo lectura** en `/v3/review/console`, montada sobre los mismos
datos que ya existen. No aprueba, no rechaza, no corrige, no aplica lotes, no
escribe en Neo4j ni en el ledger de decisiones: no expone ni un solo método POST.
Las decisiones siguen viviendo, sin cambios, en `/v3/review`.

- **Lista**: filas con sujeto–predicado–objeto, decisión, acuerdo/desacuerdo,
  confianza, motivos, fragmento resaltado y enlaces a fuente y ficha.
- **Ficha** (`/v3/review/console/item/{proposal_id}`): Fuente, Evidencia,
  Candidato, Decisión y Procedencia en secciones separadas, con anterior/siguiente
  dentro del orden filtrado.
- **Por qué está en revisión**: frases construidas a partir de la decisión, los
  códigos de motivo con su etiqueta (reutilizando `reason_label`, sin diccionario
  paralelo), la confianza y el contraste con la decisión en sombra.

### Decisiones

1. **No se inventan campos.** La proyección (`row_view`) solo lee claves que
   escribe de verdad `data-engine/app/knowledge_v3/review_export.py`. El marcador
   literal `not_available`/`UNKNOWN` del exportador se traduce a ausencia y la
   interfaz dice "no disponible". No se ha añadido ninguna segunda API para
   rellenar huecos.
2. **Filtrar, ordenar y solo entonces paginar.** `build_view` filtra todo el
   conjunto visible, lo ordena y pagina el resultado. Los contadores de cabecera
   (`filtered_total`, desacuerdos, baja confianza, sin confianza, ya decididas)
   son del conjunto filtrado, nunca del recorte de la página. Hay un test que
   recorre las tres páginas y comprueba que no se pierde ni se repite nada.
3. **Autorización: cero código nuevo.** El ámbito llega por
   `get_visibility_scope` y se pasa tal cual a `ReviewService.queue(scope=...)`,
   que ya aplica la barrera de partida antes de contar. La consola no evalúa
   visibilidad, no lee `known_by`, `visibility`, `scope` ni `deny`, y no define
   vocabulario propio de permisos. El control de rol reutiliza literalmente
   `app.routers.v3_review._guard`.
4. **Sin tocar `main.py`.** El router se monta desde `app/routers/v3_review.py`
   con `router.include_router(...)`, porque `main.py` y `routers/admin.py` tienen
   otros propietarios. No cambia ninguna ruta existente.
5. **Sin endpoints nuevos de datos.** Todo es HTML servido por las rutas GET
   descritas; no se ha añadido ninguna API JSON.

### Ficheros

| Fichero | Qué es |
| --- | --- |
| `viewer/app/services/review_console_v2.py` | Proyección, filtros, orden, paginación, facetas y explicación. Nuevo. |
| `viewer/app/routers/review_console_v2.py` | Dos rutas GET (lista y ficha). Nuevo. |
| `viewer/app/templates/review_console_v2.html` | Lista, filtros, contadores, estados vacíos, atajos. Nuevo. |
| `viewer/app/templates/review_console_v2_item.html` | Ficha completa con navegación. Nuevo. |
| `viewer/app/routers/v3_review.py` | +2 líneas: importa y monta el router de la consola. Modificado. |
| `viewer/tests/test_review_console_v2.py` | 33 pruebas. Nuevo. |

## UX

- Filtros: estado (decisión del motor), motivo, proveedor, extractor, búsqueda
  libre, confianza mínima/máxima, "solo desacuerdos", "solo baja confianza"
  (umbral ajustable, 0.6 por defecto) e "incluir ya decididas".
- Orden: prioridad (REVIEW antes que ABSTAIN antes que REJECT_INVALID; dentro de
  cada grupo primero los desacuerdos, luego la menor confianza), confianza o
  fuente. El desempate es siempre `source_id, episode_id, proposal_id`: el orden
  es estable entre recargas.
- Los desplegables se calculan sobre todo el conjunto visible, no sobre la página,
  para que elegir un filtro no vacíe las opciones.
- Teclado: `j`/`k` mover, `Enter` abrir la ficha, `n`/`p` cambiar de página, `/`
  ir a la búsqueda; en la ficha, `j`/`k` siguiente/anterior y `Esc` volver.
- Navegación: fila → `/sources/{source_id}`, entidades resueltas →
  `/entities/{entity_id}`, y fuente → candidato → ficha.
- Estados vacíos distinguidos: sin workspace, sin propuestas en el workspace y
  "ningún elemento coincide con los filtros" (con el total visible a la vista).
- Errores explícitos: paquete de propuestas ilegible → 503 con mensaje en
  castellano; filtro fuera de rango → 400/422; orden desconocido → 400; workspace
  o propuesta inexistente (o fuera de ámbito) → 404 indistinguible.

## Seguridad

- Ningún secreto por `argv` ni por entorno; no se leen credenciales.
- Los mensajes de error no incluyen rutas del servidor, trazas ni excepciones
  originales: el 503 del paquete corrupto lleva solo el nombre de la clase de
  error. Hay pruebas que verifican que ni `Traceback` ni la ruta temporal
  aparecen en la respuesta.
- Todo lo que se muestra ya pasó por la barrera de ámbito de `ReviewService`.

## Tests

Comando: `python3 -m pytest -q tests/test_review_console_v2.py` (desde `viewer/`)
→ 33 recogidos, 33 pasados, 0 saltados, 2,19 s, salida 0.

Suite del visor: `cd viewer && python3 -m pytest -q` → 732 recogidos,
707 pasados, 24 saltados, **1 fallo**, 40,79 s, salida 1. El fallo es
`tests/test_auth_core.py::test_login_unknown_user_generic_message` (403 en vez de
401) y **es previo a este trabajo**: se reproduce igual sobre el árbol limpio
(674 pasados, 1 fallo) y depende del orden de ejecución (aislado, ese fichero pasa
18/18).

Suite de contratos: `python3 -m pytest -q tests/` (raíz) → 198 recogidos,
196 pasados, 2 saltados, 4,21 s, salida 0.

Cobertura: sin reviews, volumen (60 propuestas), cada filtro, búsqueda sin
acentos, paginación y coherencia de contadores, errores (paquete corrupto, filtro
inválido, orden inválido, 404), documentos parciales, procedencia ausente,
evidencia ausente, ausencia de decisión en sombra, ausencia de métodos de
escritura, y permisos (anónimo → 302 a `/login`, rol `viewer` → 403, partida ajena
invisible en lista, contadores y ficha).

### Control positivo (mutación y test rojo)

1. **Paginación antes de filtrar**: en `build_view`, sustituir
   `apply_filters` + `paginate` por `apply_filters(paginate(...).rows, spec)`.
   Resultado: 2 fallos, incluido
   `test_pagination_runs_after_filtering_and_counts_match` con
   `AssertionError: assert 10 == 30` (el total pasa a ser el de la página).
2. **Filtro roto**: en `matches`, cambiar `row["agreement"] != "DISAGREE"` por
   `== "MUTACION"`. Resultado: 1 fallo,
   `test_disagreements_and_low_confidence_filters` con
   `AssertionError: assert ['p1','p2','p3'] == ['p1']`.

Ambas mutaciones fueron revertidas; la suite vuelve a 33/33 en verde.

## Limitaciones y datos que el backend NO expone

Se documentan en vez de improvisarse:

- **`segment_id`**: no existe. El exportador solo emite `episode_id`; el contexto
  disponible es el texto del episodio.
- **`assertion_id`**: no existe en el paquete de propuestas. Lo más parecido es
  `claim_id`, que sí se muestra, con su nombre real.
- **Marcas de tiempo**: el paquete no lleva `created_at` ni fecha de extracción.
  Solo hay fecha en la decisión humana ya registrada, si la hay.
- **Versión de contrato**: no hay campo de contrato/esquema; sí `engine_version`,
  `ontology_version`, `prompt_version` y `profile_version`.
- **Título o URL de la fuente**: no viene en el paquete; solo el `source_id`.
- **Umbrales del motor**: no se exportan. El umbral de "baja confianza" de la
  consola (0.6) es un criterio de presentación de esta pantalla y así se dice.
- **Veredicto detallado del proveedor externo**: solo hay `shadow_decision`,
  `shadow_findings`, `ignored_findings`, `provider` y `model`. No hay confianza
  ni justificación del proveedor, así que el "acuerdo/desacuerdo" se calcula
  únicamente cuando existen las dos decisiones; sin sombra se muestra
  "sin comparación posible", nunca "acuerdo".
- **Confianza ausente ≠ confianza baja**: una propuesta sin confianza declarada no
  entra en el filtro de baja confianza y se cuenta aparte
  (`missing_confidence`).

## Dependencias

- `ReviewService.queue(..., include_decided=True, scope=...)` y
  `reason_label` de `app/services/v3_review.py`.
- `get_visibility_scope` (M5b) y `app.routers.v3_review._guard` para el rol.
- El montaje del router depende de `app/routers/v3_review.py`. Si el router de la
  cola cambia de dueño o de prefijo, la consola le sigue.
- **Dependencia documentada y NO implementada**: registrar la consola en la
  navegación de `app/templates/base.html` requeriría tocar una plantilla
  compartida, y darle ruta propia de primer nivel exigiría editar `app/main.py`.
  Ambos quedan fuera por zona prohibida; hoy se llega por URL directa o desde
  `/v3/review`.

## Pendientes

- Enlace en la navegación (ver arriba), a decidir con los dueños de `base.html`.
- Si el exportador llegara a emitir `segment_id`, marcas de tiempo o el detalle
  del proveedor, la ficha tiene su hueco reservado y bastaría con leerlos.
- Acciones de revisión (aprobar/rechazar/corregir/lote): fuera de alcance por
  encargo; siguen en `/v3/review`.
