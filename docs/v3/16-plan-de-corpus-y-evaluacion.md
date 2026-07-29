# Plan de corpus y evaluación — S9-Knowledge V3

Fecha: 2026-07-28 · Estado: **acordado, no ejecutado**

Por qué existe este documento: con los 20 claims del split `dev` actual, **un solo
acierto mueve el recall cinco puntos**. Es imposible distinguir una mejora real de
una casualidad. Todo lo que sigue existe para poder responder "¿esto mejoró?" con
algo más que ruido, sin repetir el sobreajuste que hundió a V2.

---

## 1. Tres conjuntos, tres reglas de uso

| Conjunto | Tamaño objetivo | Se puede mirar | Para qué |
|---|---|---|---|
| **Desarrollo** (`dev` ampliado) | 150-250 episodios · 300-500 claims · 500-900 menciones | Sí, sin límite | Desarrollar reconciliador, arreglar resolución, ajustar la frontera local |
| **Validación** | 80-150 episodios · 150-300 claims | Ocasionalmente | Detectar sobreajuste **antes** de gastar el held-out |
| **Held-out final** | 100-200 episodios · 200-400 claims | **No**, hasta el final | Decidir si V3 está listo |

Reglas duras del held-out: se ejecuta **una sola vez**, con código, prompt,
ontología, schema, modelos, umbrales, política de revisión y reconciliador
**congelados**. Después no se ajusta nada mirando sus errores. Si el sistema cambia,
hace falta un conjunto final nuevo — el gastado pasa a validación.

El corpus de validación no debe reutilizar frases, personajes ni estructuras del de
desarrollo: juegos distintos, nombres desconocidos, estilos narrativos distintos,
errores de OCR y ASR no vistos, sinónimos, pasivas, pronombres, negaciones y
cambios temporales.

## 2. Ajustes al plan por coste (decididos con el operador)

El corpus `dev` actual —16 episodios, 220 documentos— costó un bloque entero. Estas
tres decisiones evitan que la ampliación se coma el presupuesto:

1. **Gold por capas, no completo en todo.** Para medir el extractor bastan
   menciones y claims gold. Solo un subconjunto (~20 %) necesita la cadena entera
   (resoluciones, assertions, planes) para medir motor y extremo a extremo. Anotar
   500 claims completos cuesta varias veces más que anotar 500 claims.
2. **Subconjunto rápido de iteración.** Con los modelos a 129-224 s por episodio,
   250 episodios × 7 configuraciones son días de inferencia. Se define un
   subconjunto estable de ~50 episodios para iterar, y el corpus completo se ejecuta
   solo en los hitos.
3. **Material real antes que inventado.** El corpus debe parecerse a lo que se va a
   ingerir de verdad (manuales, sesiones, transcripciones propias). Un corpus
   generado por los mismos modelos que luego extraen está contaminado por
   construcción, y el riesgo crece con el tamaño.

## 3. Qué se mide por separado

No basta la cadena completa: cuando el resultado final es malo hay que poder decir
**qué subsistema lo estropeó**.

- **A · Normalización** — fuente → episodios y fragmentos: texto recuperado,
  páginas cubiertas, WER/CER, segmentos perdidos, repeticiones, timestamps,
  evidencia localizable.
- **B · Extractor** — episodios gold → menciones y claims: P/R/F1 de menciones,
  tipos, entidades nuevas, claims, predicado top-1 y top-2, dirección, negación,
  evidencia, abstención, alucinaciones.
- **C · Resolución** — menciones gold → entidades: alias unidos, entidades distintas
  fusionadas por error, duplicados, provisionales, correferencia.
- **D · Motor** — claims gold → decisiones y assertions: predicado, dirección,
  temporalidad, negación, contradicciones, aprobaciones falsas, rechazos falsos,
  cierre correcto de vigencias.
- **E · Cadena completa** — fuente → `GraphMutationPlan`, con atribución del error.

## 4. Configuraciones a comparar

| | Extractor |
|---|---|
| A | Determinista |
| C1 | Semántico · qwen2.5:7b (local) |
| C2 | Semántico · llama-3.3-70b (nube) |
| D1 | Determinista + qwen2.5:7b |
| D2 | Determinista + llama-3.3-70b |
| D3 | Determinista + Ollama + NVIDIA |
| E | La elegida + reconciliador |

En las combinadas **no vale la unión simple**: está medido que el emparejamiento uno
a uno adjudica la mención a un extractor y deja los claims del otro sin argumentos
alineados. Sin reconciliador, sumar extractores no suma.

## 5. Batería específica de negaciones

50-100 casos, independiente del resto, porque las negaciones son fáciles de puntuar
mal y baratas de construir. Debe cubrir: afirmación positiva, negación simple,
`nunca`, `ya no`, `todavía no`, `dejó de`, alcance complejo ("A no cree que B
pertenezca a C"), pregunta negativa, condicional y doble negación.

Métricas: precisión y recall de negación, alcance correcto, `CESSATION`, `NEVER`,
`NOT_YET`, **relaciones positivas creadas por error** y cierres temporales
correctos.

Es la batería con mejor relación señal/coste de todo el plan y **va la primera**
(paso 4 del orden). Se construye cuando el bloque de negaciones en curso haya
entregado, no antes: hoy hay un implementador tocando esa misma área y un corpus
escrito en paralelo se solaparía con sus fixtures.

Anotación importante: los casos deben escribirse **sin mirar** la implementación de
las guardas de no-factividad, o la batería medirá lo que el código ya sabe hacer.

## 6. Multimodal: el mismo contenido en varias modalidades

Mismo gold semántico para: texto original, PDF nativo, PDF escaneado, fotografía,
manuscrito, audio leído y vídeo con audio. Permite localizar la pérdida: si el texto
produce `LEADS` y el audio no, el problema está en el ASR, no en el motor.

## 7. Robustez

Nombres similares, dos entidades con el mismo nombre, alias, errores de una letra,
frases muy largas, tablas rotas, texto repetido, episodios vacíos, JSON incompleto,
proveedor caído, timeout, **inyección de prompt dentro del documento**, predicados
inventados, workspace incorrecto y claims sin evidencia.

## 8. Orden acordado

1. Conectar `SemanticEpisodeExtractor` a la cadena E2E ← *en curso*
2. Corregir negaciones ← *en curso*
3. Ejecutar la suite actual
4. **Batería de negaciones (§5)** — adelantada: 50-100 casos, casi sintética,
   mide exactamente lo que se acaba de implementar. No hace falta esperar a tener
   200 episodios anotados para saber si `ya no lidera` cierra la vigencia y si
   `nunca lideró` se distingue de ella
5. Ampliar el corpus de desarrollo (con gold por capas, §2.1)
6. Repetir A / C1 / C2 / D sobre el subconjunto rápido (§2.2), corpus completo
   solo en el hito
7. Implementar `ProposalReconciler`
8. Repetir las pruebas conjuntas
9. Construir el corpus de validación
10. Congelar el sistema
11. Ejecutar el held-out final, una vez
12. Probar escritura contra un Neo4j aislado
13. Decidir promoción

## 9. Criterio para avanzar

No se exige una cifra perfecta, sí estas condiciones:

- el semántico mejora el recall frente al determinista;
- la precisión no cae de forma descontrolada;
- el top-2 transporta el predicado correcto al motor;
- las menciones están ancladas y no se inventan argumentos;
- **las negaciones no crean relaciones positivas**;
- las finalizaciones cierran historia sin borrarla;
- ningún modelo externo aprueba nada;
- validación se mantiene cerca de desarrollo (si se separan, hay sobreajuste);
- la cadena produce **hechos útiles**, no solo tests estructurales verdes.
