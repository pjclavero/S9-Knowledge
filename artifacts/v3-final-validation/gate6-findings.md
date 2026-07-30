# Puerta 6 — Hallazgos

Fichero **aparte** de `gate6-factivity-matrix.md` a propósito: aquél lo genera
`gate6_report.py` y se sobrescribe en cada análisis; éste se escribe a mano y
sobrevive a las regeneraciones.

---

## F6-1 — El carril determinista no extrae **nada** de este corpus

`det` y `combined` producen **0 hechos en las 100 frases**, incluidos los 20
controles positivos (`HECHO_AFIRMADO`, `NEGACION_FACTUAL`).

No es un defecto del extractor: `RELATION_RULES` es una lista **curada y muy
literal** por decisión explícita del diseño («cada frase que se añade aquí es
una apuesta de precisión que el benchmark tendrá que pagar»). El corpus de
factividad se escribió con prosa variada y anti-plantilla, así que cae fuera de
su distribución.

**La consecuencia sí importa:** cualquier gate de seguridad calculado sobre este
carril («0 hechos del mundo en preguntas») pasa **por inanición**, no por
acierto. Por eso `gate6_report.py` mide la vacuidad *antes* que nada y marca los
aprobados de un carril vacuo como **no acreditables**.

Es el mismo fenómeno que encontraron de forma independiente los otros dos
carriles de trabajo de esta campaña: el split `dev` completo en `local_only`
produce **0 claims en sus 6 fuentes**. Tres medidas independientes, la misma
causa.

---

## F6-2 — El carril NVIDIA se equivoca **en las dos direcciones**

24 frases (muestra estratificada, una por familia antes de repetir),
`meta/llama-3.3-70b-instruct`, 0 errores de transporte, latencia mediana 50 s
por frase (dos llamadas: extracción + segunda pasada temporal).

Lo que **no** extrae (falsos negativos):

| Caso | Familia | Esperado | Observado |
|---|---|---|---|
| `fact:hecho-afirmado:01` | HECHO_AFIRMADO | WRITE_POSITIVE | **NO_FACT** |
| `fact:hecho-afirmado:02` | HECHO_AFIRMADO | WRITE_POSITIVE | **NO_FACT** |
| `fact:negacion-factual:01` | NEGACION_FACTUAL | WRITE_NEGATIVE | **NO_FACT** |
| `fact:negacion-factual:02` | NEGACION_FACTUAL | WRITE_NEGATIVE | **NO_FACT** |

Lo que **sí** materializa y no debería (falsos positivos — 4 violaciones):

| Caso | Familia | Observado | Texto |
|---|---|---|---|
| `fact:hipotesis:01` | HIPOTESIS | **CREATE_POSITIVE** | «**Cabe suponer que** Sira Delantre sirva en secreto a la Casa Verrant, aunque nada lo prueba.» |
| `fact:hipotesis:02` | HIPOTESIS | **CREATE_POSITIVE** | «Los vigías **barajan la posibilidad de que** el Sello de Lava se encuentre todavía en el Foso Humeante.» |
| `fact:orden:01` | ORDEN | **CREATE_NEGATIVE** | «**Custodia** el Sello de Lava…, y **no se lo entregues** a nadie de la Casa Verrant.» |
| `fact:rumor:02` | RUMOR | **CREATE_NEGATIVE** | «**Dicen los arrieros, aunque nadie lo firma,** que Runa Belisa dejó de servir al gremio hace tres inviernos.» |

Los cuatro tienen la **misma causa raíz**: el marco no-factivo del español no
está en el léxico de `cues.py`. «Cabe suponer que», «barajan la posibilidad de
que» y «dicen los arrieros, aunque nadie lo firma» no se reconocen, así que la
política de factualidad clasifica la frase como aserción y deja pasar la
relación que el proveedor propuso.

### Esto confirma empíricamente el hallazgo D-G1

El trabajo de E2E encontró por lectura que `"corre el rumor de que"` falta en
`cues.py`, y anticipó: *«hoy lo enmascara que el extractor determinista no
reconoce el verbo; en cuanto el carril semántico proponga esa relación, el rumor
entra al grafo como hecho»*.

**Es exactamente lo que se acaba de medir con un proveedor real.** `fact:rumor:02`
lleva un marco de rumor explícito y sale como hecho negativo del mundo. La
predicción y la medida coinciden; deja de ser una hipótesis de revisión de
código.

Lectura conjunta: la política de factualidad (`factivity.py`) es correcta en su
lógica de precedencia —el carril `policy` clasifica las 100 frases bien—, pero
**depende por completo de que `cues.py` detecte la marca**. Con el determinista
la laguna no se nota porque no propone nada; con un semántico real, sí.

---

## F6-4 — Ollama: 2 de 4 episodios agotan el tiempo, y el sistema reacciona bien

4 frases, `qwen2.5:7b` sobre CPU. Latencia mediana **600 199 ms** — es decir, el
**timeout del cliente de Ollama (600 s)**, no un tiempo de respuesta.

| Caso | Familia | Resultado | Diagnóstico |
|---|---|---|---|
| `fact:alcance-complejo:01` | ALCANCE_COMPLEJO | abstención | `PROVIDER_UNAVAILABLE` |
| `fact:contrafactual:01` | CONTRAFACTUAL | abstención | `PROVIDER_UNAVAILABLE` |
| `fact:condicional:01` | CONDICIONAL | sin claim | `CONDITIONAL_CONTEXT` |
| `fact:deseo:01` | DESEO | sin claim | `DESIRE_CONTEXT` |

Dos lecturas, y la segunda es la buena noticia de esta puerta:

1. **Operativa:** `qwen2.5:7b` sobre esta CPU **no puede** completar el prompt
   real de extracción dentro de su propio timeout de cliente para la mitad de
   los episodios. El carril Ollama, tal y como está configurado, no es utilizable
   para ingesta en esta máquina.
2. **De seguridad — y ésta vale mucho:** cuando el proveedor real se cayó de
   verdad, el sistema hizo **exactamente** lo que la puerta 5 exige: diagnóstico
   `PROVIDER_UNAVAILABLE`, abstención con evidencia anclada, **cero** hechos del
   mundo, y el lote siguió con los episodios restantes.

Esto no es un mock: es un fallo de proveedor **real**, no provocado, observado en
vivo. Los tests de la puerta 5 cubren los cinco modos de fallo con dobles; aquí
se ve el comportamiento confirmado contra un proveedor que se cayó solo.

---

## F6-3 — El gate de acuerdo entre carriles no es medible

Los tres carriles medidos (`det`, `combined`, `nvidia`) son **vacuos** según el
criterio de controles positivos. Dos carriles que no extraen nada coinciden
siempre, así que un «100 % de acuerdo» calculado sobre ellos sería un número sin
contenido. Se reporta **NO CONFORME por no medible**, no CONFORME.

---

## Nota de alcance

El corpus es `dev-synthetic`. Mide **cobertura de familias de no-factividad**,
no generalización. Que NVIDIA falle 4 de 24 aquí no predice su tasa en
producción; lo que sí establece es que **existen construcciones no-factivas
reales del español que el sistema materializa como hechos**, y da los cuatro
ejemplos concretos.
