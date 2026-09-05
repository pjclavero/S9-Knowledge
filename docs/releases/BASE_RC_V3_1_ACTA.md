> **ESTE COMMIT NO FORMA PARTE DE `BASE RC V3.1`.**
>
> La base es, exacta e inmutablemente:
>
> ```
> BASE RC V3.1 = f725bd8065f453e702c8d05c6fac3b9ad3a65723
> ```
>
> Este documento la **nombra**; no la recrea ni la desplaza. Se escribe
> DESPUÉS del commit congelado y por eso puede citarlo sin contradicción —
> justo lo que `docs/project-status.yaml` declara que él no puede hacer: un
> fichero versionado no puede contener el hash del commit que lo contiene.
>
> Que `main` avance por encima de `f725bd8`, incluido este mismo commit, **no
> altera la base**.

# ACTA DE CONGELACIÓN — BASE RC V3.1

**Fecha:** 2026-09-05
**Repositorio:** `pjclavero/S9-Knowledge`

---

## SUJETO CONGELADO

```
BASE RC V3.1 = f725bd8065f453e702c8d05c6fac3b9ad3a65723
```

Este acta es el documento que ata la base a ese SHA. `docs/project-status.yaml`
**no** lo hace y declara expresamente que no puede hacerlo: un fichero
versionado no puede contener el hash del commit que lo contiene.

## GENEALOGÍA

```
BASE RC V3   = aaf9695
RC Exercise 1 = FAIL + INCOMPLETE
        |
        |  evolución: V3.1 se produce POR lo aprendido en el Exercise 1
        v
BASE RC V3.1 = f725bd8
RC Exercise 2 = PENDIENTE
```

**V3.1 no borra ni corrige retroactivamente a V3.** `aaf9695` se conserva como
evidencia histórica y su etiqueta no se reutiliza. Ancestría verificada:
`aaf9695` es ancestro de `f725bd8` (`rc=0`).

## SUJETO FUNCIONAL

```
functional_verified_commit = 84f9cc7596381e1e56ff5a2fc059104b3c5aa063
functional_verified_ci     = 17 identidades / 17 ejecuciones / 17 SUCCESS
```

**Delta `84f9cc7..f725bd8`** — 7 ficheros, +286/−47, **exclusivamente estado,
documentación y semántica del gate. Cero código funcional del producto**
(ningún fichero bajo `viewer/`, `data-engine/` ni `authz/`):

| fichero | naturaleza |
|---|---|
| `docs/project-status.yaml` | semántica de estado |
| `scripts/check_docs_consistency.py` + su test | gate de coherencia |
| `.github/suite-inventario.json` | inventario (único decremento: `xfail 3→2`) |
| `.github/xfail-registro.txt` | −1: limitación cerrada, no silenciada |
| `CHANGELOG.md`, `README.md` | documentación |

## VERIFICACIÓN DE LA CONGELACIÓN

| # | condición | resultado |
|---|---|---|
| 1 | CI sobre el SHA congelado | **17 identidades / 17 SUCCESS / 0 fuera** |
| 2 | Segunda lectura estable | mismo conjunto, mismo resultado |
| 3 | Branch protection | **required = 17**, perdidos = ∅, verificado por diferencia de conjuntos |
| 3b | Extras de plataforma | `Dependabot` clasificado como plataforma, **no** job del proyecto |
| 4 | Ancestría `aaf9695 → f725bd8` | `rc=0` |
| 5 | #204 contenido por ancestría | `84f9cc7` ancestro, `rc=0` |
| 6 | Árbol limpio | `git status` vacío, incluidos sin seguimiento |
| 7 | Estado documental | semántica corregida; 17 required correctamente declarados |

## CADENA V3.1 INTEGRADA

| PR | contenido | commit |
|---|---|---|
| #203 | `pip-audit`: `nltk` 3.10.3, `pypdf` 6.16.1, excepción acotada `GHSA-8mgp-746c-j5xp` | `6cad742` |
| #196 | carril 4 — parcialidad por VALOR + contrato Neo4j derivado | `e93c7b5` |
| #198 | carril 3 — CSRF en dos propiedades independientes | `9869d0e` |
| #200 | carril 5 — excepciones críticas por tipo y código | `404cf9a` |
| #199 | carril 1 — anti-desaparición de suites + preflight | `66ad0c1` |
| #197 | carril 2 — métodos de escritura contra especificación independiente | `4fea1f2` |
| #205 | refresco de estado + promoción del job 17 a exigido | `3e66769` |
| #204 | contadores de `/reviews` por ámbito: filtrar y DESPUÉS contar | `84f9cc7` |
| #206 | semántica no-autorreferencial de `main_commit`/`latest_ci` + gate | `f725bd8` |

## LIMITACIONES DECLARADAS (aceptadas por el operador)

**1. `/reviews` vacío con partida activa** — LIMITACIÓN DECLARADA.
Mientras `data-engine/app/review/` no escriba `partida_id`, ningún paquete real
declara partida: con partida activa el listado sale **vacío para todo el corpus
v1**; sin partida activa se ve como capa juego. Es fail-closed y responde a la
regla «si no podemos calcular el contador con seguridad, prefiero no mostrarlo».
Condiciones: la autorización real **no depende** de esa colección, y el router y
los gates ejecutables siguen cubriéndolo. **No se rellena para que parezca más
completo.**

**2. Canal temporal** — RIESGO RESIDUAL, **no** garantía resuelta.
Cuerpo byte a byte idéntico al añadir 500 fuentes ajenas; latencia mediana
**16,0 ms → 284,8 ms (~17,8x)**.

> **V3.1 garantiza indistinguibilidad en contenido/estado donde corresponda,
> NO resistencia a análisis temporal.**

No se abren mitigaciones de timing salvo que se demuestre que permiten inferir
una propiedad protegida que sí forme parte del contrato actual.

**3. `quality_report.json` fuera de `_DOCS_DE_AMBITO`** — LIMITACIÓN DECLARADA
**CONDICIONADA**.
`_DOCS_DE_AMBITO` no lo enumera. Se acepta porque el recurso está **demostrado
no alcanzable** desde el recorrido protegido actual: `quality_report.py` deriva
el informe exclusivamente de `pipeline_state.json`, `approved_payload.json`,
`review_queue.json` y `rejected.json` —los cuatro sí recorridos— y no escribe
`partida_id` en ninguna parte; disparar la fuga exigiría un fichero fabricado a
mano que no es entrada de usuario.

**Esta aceptación NO implica que quede autorizado ni cubierto por el contrato, y
no se interpreta como permiso. Si una futura ruta, montaje o consumidor lo hace
alcanzable, la limitación deja de ser aceptable y debe convertirse en fallo /
gate rojo** hasta incorporarlo explícitamente o mantenerlo fuera de alcance por
construcción.

## OBSERVACIONES REGISTRADAS (no bloqueantes, no mueven la base)

- **`latest_ci` vacío o ausente pasa mudo**: el gate sale `rc=0` con titular
  «COHERENTE» sin avisar. Vía de escape por omisión del campo. Antes de #206 ese
  campo **no lo validaba nadie**, así que el PR sólo mejora.
- **Titular «CI NO VERIFICADA» enmascarado**: es un `elif` posterior al de
  desfase, así que al avanzar `main` prevalece «DESFASADA». **No es un
  silencio**: el `AVISO` se imprime igualmente (comprobado simulando el desfase).
- **Deuda estructural del gate de estado**: compara la terna
  `ci_jobs_running − len(lista) == ci_checks_required` **consigo misma** y no
  consulta `.../protection`. Cruzarlo contra la fuente sigue siendo deuda.

## DEUDAS DECLARADAS QUE VIAJAN CON LA BASE

- `elementId` en las claves de plan de `scripts/m5b/migrar_visibilidad.py`.
- Tres dependencias de API privada de FastAPI.
- Tres ramas de producto que discriminan por **texto del mensaje** de una
  excepción SQLite (`viewer/app/auth/db.py:259,270`, `v3_review_store.py:75`).
- `_DOCS_DE_AMBITO` es una lista enumerada: la unidad de control debería ser la
  estructura, no los sitios donde se ha mirado.
- **Sondas de calibración que reconocen una propiedad por una frase literal.**
  Ya han caducado **dos** al integrar (S4 en #199; «desarme por entorno con
  ascendencia fabricada» en #197). Barrido de `calibra_desarme.py` **autorizado
  DESPUÉS de congelar**, en paralelo al Exercise 2.

## REGLA DE SUJETO DURANTE EL RC EXERCISE 2

El ejercicio se ejecuta **exclusivamente sobre `f725bd8`**, aunque `main` avance
por frontend u otros trabajos. **El sujeto no se mueve en silencio.**

Si el Exercise 2 descubre un defecto que necesita código nuevo:

```
RC Exercise 2 = FAIL   ->   habrá V3.2
```

Nunca se sustituye el sujeto por una versión corregida a mitad del ejercicio.

## CRITERIO DE SALIDA (evita el bucle infinito de hardening)

- Hallazgo de **fragilidad potencial** → se registra y **no mueve** la base.
- **Reproducción real** (`garantía requerida destruida` + `required gate sigue
  verde`) → **el RC Exercise falla** y se pasa a V3.2.

No existe la tercera vía de «esperar un poco más mientras miramos».

## DECISIONES DE PRODUCTO TOMADAS AL CONGELAR (2026-09-05)

**1. Versionado de este acta.** Va al repo en un PR documental posterior, en
`docs/releases/BASE_RC_V3_1_ACTA.md`. **El commit que añade el acta NO forma
parte de la base**: `f725bd8` permanece inmutable. Es coherente con lo que #206
dejó escrito — el acta es externa por definición y por eso sí puede nombrar el
SHA sin contradicción.

**2. Ruta canónica de entidad: `/entities/{entity_id}`.** Coherente con una
colección REST y con el panel Entities. `/entity/{id}` puede quedar
temporalmente como **alias / redirect de compatibilidad**, pero **no puede haber
dos implementaciones que evolucionen por separado**. Va al carril de
frontend/producto, **no a la base RC congelada**.

**3. Divergencia 403 / 404: ACEPTABLE Y DESEADA**, porque responde a dos casos
distintos:

    recurso concreto cuya existencia no puede revelarse
        -> 404  tanto si no existe como si no esta autorizado

    ruta administrativa conocida, usuario autenticado sin permiso
        -> 403

**No se homogeneizan a la fuerza.** Lo que sí se exige: que **ambos tengan una
página HTML coherente** y no JSON crudo cuando el usuario llega desde navegador.

## SEPARACIÓN DE SUJETOS A PARTIR DE AQUÍ

    RC Exercise 2                 -> certifica f725bd8, INMOVIL
    Producto A/C/E/F/G/H          -> ramas nuevas, NO modifican el sujeto

Si los carriles de producto descubren que una ingesta real exige corregir algo
del núcleo, **eso no cambia V3.1 en silencio**: se corrige en rama posterior y
es candidato a **V3.2** cuando corresponda.
