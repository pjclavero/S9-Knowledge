# Doble pase de calidad — notas de revisión

Ground truth revisado en dos pases independientes. **Pase 1**: anotación inicial
(evidencia, offsets, tipos, predicados, negación, temporalidad, estado
epistémico, dirección, decisión). **Pase 2**: revisión independiente de cada
campo y de duplicados. Se registran las divergencias detectadas y su resolución.

## Divergencias detectadas y resolución

1. **`src-01` / `rel-004` (TRUSTS reina Ysolde → Horda de Grael).**
   - Pase 1: `object_type = Character` y `expected_decision = ACCEPT`.
   - Pase 2: la Horda de Grael es una **facción**, no un personaje; y la frase
     contiene negación (`nunca confió`).
   - Resolución: `object_type = Faction`, `negated = True`,
     `temporal_status = PAST`, `expected_decision = REJECT`.

2. **Evidencias con salto de línea aparente.**
   - Pase 1: varias evidencias se anotaron cruzando un supuesto `\n` en los
     límites de párrafo (p. ej. `reina\nYsolde`, `Valle\nRúnico`).
   - Pase 2: las fuentes usan **espacio**, no salto de línea, en esos puntos; los
     offsets no coincidían con el texto real.
   - Resolución: corregidas a espacio; `evidence == source[start:end]` verificado
     de forma programática para las 54 relaciones.

3. **Alias reflexivos (`ALIAS_OF`).**
   - Pase 1: `rel-010` (`el Cuervo`↔`Draven`) y `rel-046`
     (`la Reina de Invierno`↔`Ysolde`) con `subject_id == object_id`.
   - Pase 2: el contrato `RelationCandidate` **prohíbe** `subject == object` salvo
     predicados reflexivos permitidos (lista vacía por defecto).
   - Resolución: se conservan como anotación de **identidad documental** con
     `direction = UNDIRECTED` y `expected_decision = REVIEW`; el test las excluye
     de la materialización como arista de grafo y exige que su predicado sea
     `ALIAS_OF`.

4. **`src-05` — nombres parecidos `Kaelin` / `Kaelan`.**
   - Pase 1: riesgo de fusionar ambas entidades bajo un mismo `id`.
   - Pase 2: son **personas distintas**; solo `Kaelin` cambia de facción.
   - Resolución: `subject_id` distintos (`kaelin` vs `kaelan`); la pertenencia de
     `Kaelin` a la Guardia de Hierro se marca `ENDED` (abandona), la de `Kaelan`
     permanece.

5. **`src-08` — contradicción entre segmentos.**
   - Pase 1: se anotó solo la afirmación del segmento A.
   - Pase 2: el segmento B **niega** la lealtad al Pacto y afirma una alternativa.
   - Resolución: tres relaciones (`rel-030..032`); las dos sobre el Pacto quedan
     `expected_decision = REVIEW` (una con `negated = True`) para reflejar el
     conflicto no resuelto.

6. **`src-16` — tipo de `Ateneo`.**
   - Pase 1: `object_type = Object` en `FOUNDED ... el Ateneo`.
   - Pase 2: el Ateneo es un **lugar/institución**.
   - Resolución: `object_type = Location`, consistente con
     `LIVES_IN ... el Ateneo` de la misma fuente.

7. **Modalidad futura vs. hipótesis.**
   - Pase 1: `competirá` / `se espera que herede` anotados como `HYPOTHETICAL`.
   - Pase 2: expresan **intención/planificación**, no mera posibilidad.
   - Resolución: `epistemic_status = INTENDED` + `temporal_status = FUTURE`;
     `HYPOTHETICAL` se reserva para condicionales/posibilidad
     (`podría`, `Es posible que`, `Si cayera`).

## Resultado

- **Divergencias registradas:** 7 clases, todas resueltas.
- **Duplicados:** ninguno tras el pase 2 (relation IDs únicos).
- **Consistencia final:** las 54 relaciones pasan el test de integridad
  (`test_relation_benchmark_corpus.py`), incluidos offsets exactos, predicados
  normalizados, tipos admitidos y ausencia de Unicode oculto / secretos.
