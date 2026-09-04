# 85 — Limitaciones declaradas de `/reviews` por ámbito

Acompaña al PR #204 («Contadores de `/reviews` por ámbito: filtrar y DESPUÉS
contar»). El PR cierra los canales de conteo; este documento registra los tres
bordes que **el operador acepta a sabiendas**, para que la garantía no se lea
más ancha de lo que es.

Una garantía que no declara su borde acaba citada como si no lo tuviera. Estas
tres no son cabos sueltos: son decisiones tomadas.

## 1. `/reviews` sale vacío con una partida activa

Mientras `data-engine/app/review/` no escriba `partida_id`, **ningún paquete real declara partida**. Por la regla 3 de `_fuente_en_ambito` —material no atribuible no se publica— eso significa que, **con una partida activa, el listado sale vacío para todo el corpus v1**. Sin partida activa se sigue viendo como capa juego.

Es **fail-closed** y es la aplicación literal de la regla del operador: «si no podemos calcular el contador con seguridad, prefiero no mostrarlo».

Condiciones de la aceptación:

- **La autorización real no debe depender de esta colección.** Este filtro es de *presentación*: decide qué se enseña en `/reviews`, no qué está autorizado.
- El router y los gates ejecutables **deben seguir cubriendo** el caso; no se relaja la cobertura porque el listado esté vacío en la práctica.
- **No se debe «rellenar»** —ni con un valor por omisión, ni ensanchando el ámbito, ni degradando a capa juego— para que la pantalla parezca más completa.

## 2. Canal temporal: riesgo residual, no garantía resuelta

Se acepta como **riesgo residual**, no como problema cerrado.

> **V3.1 garantiza indistinguibilidad en contenido/estado donde corresponda, *no* resistencia a análisis temporal.**

Dato medido: al añadir **500 fuentes ajenas**, el cuerpo de la respuesta es **idéntico byte a byte**, y la **latencia mediana pasa de 16,0 ms a 284,8 ms** (factor **~17,8x**).

**No se abren mitigaciones de timing ahora.** Sólo se reabriría si se demostrase que el canal permite inferir una propiedad protegida **que forme parte del contrato actual**; la resistencia temporal hoy no lo es.

## 3. `quality_report.json` fuera de `_DOCS_DE_AMBITO`

`_DOCS_DE_AMBITO` no enumera `quality_report.json`. En V3.1 esto se acepta como limitación conocida porque el recurso ha sido demostrado **NO ALCANZABLE** desde el recorrido protegido actual. Esta aceptación **no implica que quede autorizado ni cubierto por el contrato**. Si una futura ruta, montaje o consumidor lo hace alcanzable, la limitación deja de ser aceptable y **debe convertirse en fallo / gate rojo** hasta incorporarlo explícitamente o mantenerlo fuera del alcance por construcción.

Es decir, y sin que haya que deducirlo: **(a)** hoy no bloquea; **(b)** no se está diciendo que esté cubierto; **(c)** no se interpreta como permiso; **(d)** si cambia la alcanzabilidad, la aceptación **caduca automáticamente**.

Evidencia de la no alcanzabilidad, medida sobre `main` ya integrado en esta rama:

- El generador real, `data-engine/app/review/quality_report.py`, deriva el informe **exclusivamente** de `pipeline_state.json`, `approved_payload.json`, `review_queue.json` y `rejected.json` (líneas 127, 144, 154 y 162). **Los cuatro ya los recorre `_DOCS_DE_AMBITO`.**
- `quality_report.py` **no escribe `partida_id` en ninguna parte** (no aparece la subcadena `partida` en el módulo).
- Disparar la fuga exigiría un `quality_report.json` **fabricado a mano**, que no es entrada de usuario.
- Lo mismo aplica a `duplicate_candidates.json`, `bad_relations.json` y `missing_metadata.json`, que el informe absorbe: los produce `data-engine/app/review/audit_graph.py`, que tampoco menciona `partida`, y el visor no los lee (no están ni en `_DOCS_DE_AMBITO` ni en `PIPELINE_FILE_NAMES`).

Si alguna de esas cuatro afirmaciones deja de sostenerse, **la aceptación caduca** y el caso vuelve al operador.
