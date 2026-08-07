# Migración M5b de visibilidad — procedimiento

Estampado de los metadatos de autorización (`visibility`, `visibility_source`)
sobre el grafo de producción, **antes** de que el cierre fail-closed de M5b-2
entre en vigor en el visor.

El orden importa y no es negociable: M5b-2 deniega todo nodo o relación sin un
nivel válido. Aplicarlo sobre datos que nunca lo llevaron dejaría el grafo mudo.
Primero se estampa, después se despliega.

## Alcance autorizado

**Puede**: añadir o normalizar `visibility` y `visibility_source`; estampar
nodos; estampar relaciones heredando el extremo más restrictivo; generar
auditoría; ejecutar consultas de comprobación.

**No puede**: borrar nodos o relaciones; cambiar identidad de entidades;
fusionar entidades; cambiar predicados; cambiar temporalidad; modificar
assertions; alterar procedencia; tocar `auth.db` o `jobs.db`; activar M5b en el
visor productivo; desplegar código.

Es migración de **metadatos de autorización, exclusivamente**. El límite está
comprobado sobre el Cypher generado, no solo declarado aquí: las pruebas exigen
que las sentencias no contengan `DELETE`, `REMOVE`, `MERGE` ni `CREATE` y que
no asignen más de los dos campos de visibilidad.

## Criterios de decisión

| Situación | Nivel resultante | Motivo |
|---|---|---|
| Nodo con nivel válido | **se respeta tal cual** | La migración nunca amplía ni recorta lo ya declarado |
| Nodo sin nivel | `secret` | No hay nada de donde deducir. Promover luego es barato; lo contrario no tiene vuelta atrás |
| Relación con nivel válido | **se respeta tal cual** | Ídem |
| Relación sin nivel | el **más restrictivo** de sus extremos | Una arista que toca un secreto revela que ese secreto existe y con quién se relaciona |
| Relación con un extremo ilegible o ausente | `secret` | Un extremo ilegible **no se ignora**: ignorarlo dejaría la arista más visible que el nodo que toca |

### Invariante de monotonía

> Una relación **nunca** puede quedar menos restringida que ninguno de sus
> extremos.

No es una consecuencia accidental del algoritmo: se comprueba sobre las 25
combinaciones del vocabulario, sobre el plan antes de aplicarlo, y sobre el
grafo después. Cualquier extremo `deny` fuerza `deny` en la relación.

Una violación de monotonía **preexistente** (un `player` ya declarado sobre una
arista que toca un secreto) se reporta como **error** y detiene la migración.
No se corrige sola: recortar un nivel ya declarado está fuera del alcance.

## Procedimiento

### 0. Gate previo

- PR de M5b-2/M5b-3 con todos los checks requeridos concluidos y verdes, y
  fusionado. `main` limpio y conocido.
- Copia restaurable: SQLite consistente, exportación lógica de Neo4j y **dump
  físico verificado mediante restauración en aislamiento**. Un cambio masivo de
  propiedades no puede depender solo de una exportación lógica.
  → checkpoint vigente: `docs/52-backup-manual-checkpoint.md`.

### 1. Preflight

Registrar: SHA de `main`, SHA del script, conteos de nodos y relaciones, estado
de Neo4j, `BACKUP_ID`, hora y usuario. Confirmar que **no hay** ingestas,
writers, migraciones ni trabajos en cola que puedan modificar el grafo.

### 2. Dry-run

```
scripts/m5b/migrar_visibilidad.py --dry-run --out plan-m5b.json
```

No escribe nada, y no por confianza: la sesión se abre en `--access-mode read`,
así que ni un error del propio script podría escribir durante la simulación.

Produce el informe por tipo y nivel, y firma el plan (`migration_plan_sha256`).
Comprobar antes de seguir:

```
objetos esperados : 339   (199 nodos + 140 relaciones)
objetos planeados : 339
errores           : 0
desconocidos      : 0
```

**No debe existir ninguna fila `error` ni ningún valor desconocido.** Si la hay,
se analiza; no se aplica.

### 3. Aplicación

```
scripts/m5b/migrar_visibilidad.py --apply --plan plan-m5b.json --confirmar
```

Aplica **exactamente** el plan firmado, sin recalcular. Dos barreras:

1. Si el fichero del plan se ha alterado, el hash no cuadra y aborta.
2. Vuelve a leer el grafo y aborta si cambió desde el dry-run. Un plan obsoleto
   se rehace, no se fuerza: aplicar un plan calculado sobre otro estado sería
   escribir a ciegas.

Sin `--confirmar` enseña las sentencias exactas y no ejecuta.

### 4. Verificación inmediata

```
scripts/m5b/migrar_visibilidad.py --verificar
```

| Comprobación | Esperado |
|---|---|
| Nodos | **199** (idéntico) |
| Relaciones | **140** (idéntico) |
| Nodos sin `visibility` | 0 |
| Relaciones sin `visibility` | 0 |
| Valores desconocidos | 0 |
| Relaciones menos restrictivas que sus extremos | 0 |
| Consulta de pendientes | **0** |

### 5. Pruebas semánticas

Comprobar propiedades no basta. Sobre fixtures reales que cubran los cuatro
niveles encontrados, verificar con el motor contra los datos migrados —todavía
**sin desplegar** el visor nuevo—: `player`, `narrator`, `secret`, `reference`;
relación entre dos visibles; visible→secret; secret→secret; personaje incluido
en `known_by`; personaje no incluido; admin; workspace incorrecto; partida
incorrecta.

## Rollback

Si tras la migración los conteos cambian, quedan pendientes, aparece un valor
desconocido, una relación demasiado permisiva, `known_by` inconsistente o hay
error de escritura parcial:

1. Detener nueva escritura.
2. **Conservar la evidencia.**
3. Restaurar el dump.
4. Comprobar 199 / 140.
5. Analizar en frío.

**No se corrige a mano encima, ni se improvisa una segunda migración para
arreglar la primera.**

> Detalle imprescindible al restaurar: el backup se publica con `chmod -R
> go-rwx` y el usuario del contenedor no puede leer los `.dump`. Hay que
> copiarlos antes a un área legible por ese usuario. El fallo es **silencioso**:
> el contenedor arranca vacío sin error visible, y sin comprobar los conteos una
> restauración vacía parece correcta.

## Estado

Despliegue de M5b en el visor productivo: **no autorizado todavía**. Siguiente
puerta: resultado de la migración + smoke de autorización.
