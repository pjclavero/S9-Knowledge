# Puerta 5 — Autoridad local

**Tesis bajo prueba:** un proveedor —Ollama, NVIDIA o el que venga— **propone**;
el motor local **decide**; y lo que se escribe sale exclusivamente de la
decisión local.

Se ataca por los dos lados que podrían romperla: los **fallos del proveedor** y
la **evaluación en sombra**.

---

## 1. Los proveedores están vivos (verificación real)

Llamada mínima a través de los puertos reales de
`knowledge_v3/extraction/provider_port.py`. No es un mock: es la red.

| Carril | Puerto | Modelo devuelto | Latencia | JSON válido |
|---|---|---|---|---|
| Ollama local | `OllamaProviderPort` | `qwen2.5:7b` | 87 844 ms en frío / **2 032–2 527 ms en caliente** | sí |
| NVIDIA NIM | `NvidiaProviderPort` | `meta/llama-3.3-70b-instruct` | **6 213 ms** | sí |

Los 88 s de Ollama son **carga del modelo**, no inferencia: una vez residente
(`/api/ps` lo confirma) el mismo prompt baja a ~2,3 s. Se anota la distinción
porque una media que mezcle ambas cifras no describe nada.

Las credenciales se cargan al entorno del proceso desde
`~/.config/s9k/nvidia.env` y **no aparecen en ningún artefacto, log ni commit**.
De los proveedores solo se registran modelo, latencia, códigos de error y
recuentos.

---

## 2. Fallos de proveedor: abstención con diagnóstico, nunca una escritura

`data-engine/app/tests/test_knowledge_v3_gate5_authority.py` — **18 passed,
1 xfailed**. Dobles deterministas: sirven de **regresión**, no de evidencia de
que el proveedor real funcione (esa es la sección 1).

| Modo de fallo | Se traduce a | Diagnóstico | Claims activos | Lote continúa | Escribe |
|---|---|---|---|---|---|
| Timeout | `ProviderUnavailable` | sí | 0 | sí | no |
| 401 / 403 | `ProviderUnavailable` | sí | 0 | sí | no |
| 404 de función | `ProviderUnavailable` | sí | 0 | sí | no |
| JSON inválido | `ProviderBadJSON` | sí | 0 | sí | no |
| **Respuesta vacía (200 con `{}`)** | *no se considera fallo* | **no** | 0 | sí | **no** |

Y además: con el semántico caído el **carril determinista sigue produciendo
claims** — si no lo hiciera, el carril local no sería local.

### HALLAZGO P5-1 — la respuesta vacía no deja rastro

*Observabilidad, **no** brecha de escritura. El gate duro se mantiene: no se
escribe nada.*

Un proveedor que responde `200` con cuerpo `{}` es **indistinguible de "el
modelo no encontró nada"**. `check_semantic_shape` da por buenas las claves
ausentes (`payload.get(key, [])`), el extractor no emite diagnóstico ni
abstención, y marca `run.ok = True`.

Consecuencia: una respuesta truncada, filtrada por seguridad o vaciada por un
límite de cuota queda registrada como **episodio procesado con éxito y cero
hechos**. Es pérdida silenciosa de cobertura sin rastro auditable, y es el único
de los cinco modos que no se declara.

Reproducción mínima (`test_p5_1_una_respuesta_vacia_deberia_dejar_rastro`,
`xfail(strict=True)`):

```python
out = SemanticEpisodeExtractor(EmptyPort()).extract_episode(ctx, episodio)
assert extractor.runs[-1].ok is True   # se cumple: la corrida se declara OK
assert out.diagnostics                  # FALLA: lista vacía
```

No se ha corregido: el ciclo de corrección es de otro agente.

---

## 3. El proveedor no pone ni la evidencia ni la ontología

| Regla | Resultado |
|---|---|
| Todo claim semántico cita un fragmento **de su propio episodio** (abstenciones incluidas) | CONFORME |
| Un predicado inventado fuera del perfil no entra como candidato factual | CONFORME |
| El proveedor no puede firmar una confianza alta: el tope lo pone el sistema | CONFORME |
| El carril **externo** está más capado que el local (`EXTERNAL_CONFIDENCE_CAP`) | CONFORME |

Lo último no es desconfianza decorativa: la salida de un proveedor remoto no se
puede reproducir en local, así que no puede pesar lo mismo que el carril local.

---

## 4. Gates de la puerta

| Gate | Observado | Estado |
|---|---|---|
| 0 claims sin evidencia literal | 0 | **CONFORME** |
| 0 predicados fuera de ontología | 0 | **CONFORME** |
| 0 decisiones efectivas alteradas por la sombra | 0 | **CONFORME** |
| 0 operaciones sombra aplicables | 0 | **CONFORME** |
| 0 escrituras decididas por proveedor | 0 (los 5 modos de fallo) | **CONFORME** |

### Cobertura de la sombra: 0 registros

`evaluate_semantic_shadow` solo compara claims de `extract.semantic`, y ese
carril exige proveedor. En las corridas deterministas de las puertas 4 y 6 la
sombra produce **cero registros**.

Los dos gates de sombra se sostienen sobre una garantía **estructural**, y esa
garantía sí está ejercitada por dos tests:

- `test_el_registro_de_sombra_no_puede_transportar_una_operacion_aplicable`
  comprueba la **forma** del registro, no una corrida concreta: si
  `ShadowDecisionRecord` es `frozen` y sus campos solo admiten `str`, `bool` y
  `tuple[str, ...]`, entonces **no existe corrida** capaz de meter en él un plan
  o una operación ejecutable. `operation_kinds` son etiquetas
  (`"CREATE_ASSERTION"`), y un nombre no se aplica contra un grafo.
- `test_la_sombra_trabaja_sobre_copias_y_no_toca_la_decision_efectiva` pasa la
  misma lista como efectiva y como pre-lote y exige que, tras evaluar, las
  decisiones efectivas sigan idénticas.

Distinción honesta: eso demuestra que la sombra **no puede** alterar ni escribir.
**No** demuestra que la comparación sombra-vs-efectiva sea útil, porque con
cero registros no se ha comparado nada. La utilidad de la sombra sigue sin
medirse y requiere una corrida con proveedor semántico.

---

## 5. Registro por claim de los escenarios C1 / C2 / D-R

Ver `gate5-authority.json` cuando exista, y la sección de carriles de
`gate6-factivity-matrix.md`: los escenarios C1 (semántico+Ollama), C2
(semántico+NVIDIA) y D-R (determinista+semántico+reconciliador) comparten
corpus, ontología y prompt con la puerta 6, así que se miden en la misma
corrida en vez de pagar dos veces el coste de red.
