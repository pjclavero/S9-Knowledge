# Slice 2 · Corte 1 — Consola de operador: alta de fuente y ejecución real

> Base: `origin/main` = `3bdfd40ca0ffc7d7ddac5d2e4dcd478b53dec651`.
> Complementa a `docs/69-chasis-de-montaje.md` (contrato del chasis) y a
> `docs/80-panel-b-operations-solo-lectura.md` (cuyo título describe el estado
> ANTERIOR de este panel).

## 1. Qué faltaba

El *Vertical Slice 1* dejó la maquinaria funcionando de punta a punta **desde un
guión**. El reconocimiento del Slice 2 midió la aplicación y encontró que, de
los nueve pasos del recorrido de un operador, **sólo uno era usable**: de 72
rutas montadas, 15 podían escribir, y 13 de ésas eran login, cuenta o
administración. Las escrituras de dominio eran tres, ninguna de ingesta.

El primer paso —*elegir/registrar una fuente*— **existía** como CLI
(`python -m knowledge_v3.pipeline.ingest_cli <fichero>`) y **no era usable**: no
había ninguna ruta `POST` de alta de fuente. Todo lo demás estaba detrás de una
puerta que no se podía abrir.

## 2. El contrato del chasis CAMBIA, y cambia explícitamente

Hasta este corte el contrato era `panel = sólo lectura`. Ahora es
`panel = consola de operador`:

```
GET                  -> observación
POST / mutaciones    -> SÓLO capacidades de producto explícitamente declaradas,
                        autenticadas, autorizadas, CSRF protegidas, AUDITABLES
```

**Lo que NO cambia, y es la mitad importante: lectura por defecto.** Un hueco
sin capacidades declaradas no admite ni un método de escritura en todo su
espacio de URL, igual que antes. El chasis no se abre: se le añade una puerta
con cerradura declarada.

### Dónde vive el mecanismo

| Pieza | Dónde | Qué hace |
|---|---|---|
| `WriteCapability` | `viewer/app/chassis.py` | Declara una mutación como DATO: hueco, ruta, métodos, rol, auditoría |
| `WRITE_CAPABILITIES` | `viewer/app/chassis.py` | La tabla. Hoy tiene **una** entrada: `ingesta_de_fuente` |
| `capabilities_for_slot()` | `viewer/app/chassis.py` | Capacidades de un hueco; vacío = solo lectura |
| `declared_write()` | `viewer/app/chassis.py` | ¿Está declarado este `método path`? |
| `undeclared_writes()` | `viewer/app/chassis.py` | **La puerta**: escrituras montadas que nadie declaró |

El constructor de `WriteCapability` **rechaza**: un rol fuera de `ROLES`, unos
métodos que no sean de escritura, una ruta fuera del espacio de URL de su hueco
y —explícitamente— `audited=False`. La palabra «AUDITABLES» del contrato tiene
mecanismo, no es prosa.

### La comprobación sustituye a la anterior, sin perder fuerza

`test_ninguna_ruta_del_espacio_del_panel_acepta_escritura` pasa a ser
`test_ninguna_escritura_sin_declarar_bajo_el_espacio_del_panel`. La lista blanca
**no está en el test**: está en el chasis, es un dato, y montar un POST nuevo
sigue poniendo la suite en rojo salvo que alguien lo declare — que es justo el
acto que el contrato exige y que una revisión ocular no garantizaba. Los huecos
**C, F y G no declaran nada**, así que siguen siendo de solo lectura por
construcción, con la misma enumeración de siempre.

## 3. Una sola ingesta, dos adaptadores

```
                 run_ingest()          <- EL NÚCLEO. Único.
                  ^        ^
                  |        |
   ingest_cli.main()     jobs/handlers/ingest_v3.py
   (adaptador CLI)       (adaptador cola)
```

`run_ingest` **ya era invocable sin `argparse`** (recibe argumentos por palabra
clave y devuelve el informe), así que no hubo que extraer nada: la CLI queda
como otro adaptador de entrada. El handler **no** lanza `ingest_cli` por shell.

Se comprueba por **AST**, no a ojo (`test_no_hay_dos_ingestas`): el handler
importa `run_ingest` del módulo del núcleo, no contiene ninguna llamada a
`subprocess`/`os.system`/`os.popen`/`runpy`/`main`, llama a `run_ingest`, la
`main()` de la CLI **también** llama a `run_ingest`, y ambos son literalmente el
mismo objeto (`handler.run_ingest is ingest_cli.run_ingest`).

## 4. `ingest_v3` entra en la cola que YA existe

`jobs/worker.py` sólo registraba `noop` y `echo` —«handlers de prueba»—, y por
eso el panel de operaciones parecía existir sin representar trabajo real:
pintaba fielmente una cola en la que nada de producción podía entrar. Ahora
`HANDLERS["ingest_v3"]` es real. **No se ha creado otro sistema de ejecución.**

El import del handler es perezoso y tolerante: en un despliegue sin
`knowledge_v3`, el `job_type` simplemente no tiene handler y `dispatch` lo marca
`skipped` con su mensaje — el comportamiento que ya existía.

### Un error permanente ya no se reintenta

Hallazgo de la ejecución, corregido: `worker.process_one` llamaba siempre a
`mark_failed(retry=True)`, que devuelve el job a `pending` hasta agotar
`max_attempts` (3). Correcto para un fallo transitorio y **absurdo** para uno
que no puede cambiar: una fuente inválida lo seguirá siendo en el segundo
intento. Y no era sólo ruido — mientras el job rebotaba, la consola decía «sigue
en la cola», así que el operador no veía `ERROR` hasta el tercer intento.

El **handler declara** lo que el worker no puede saber: `IngestV3Error.retryable`
(`False` para `SOURCE_PACKAGE_INVALID`). Por defecto se reintenta, que es el
comportamiento anterior.

## 5. Errores: código estable + frase accionable

```
SOURCE_PACKAGE_INVALID
"El paquete de la fuente no es valido."
```

`viewer/app/panel_errors.py` tiene un catálogo **cerrado**. `OperatorError`
**no tiene** campo `detail`, `path`, `exception` ni `traceback`: si no existe el
sitio donde meter la ruta del servidor, nadie la mete «sólo esta vez». El
detalle técnico viaja por `registrar()` hacia el log del servidor, con
`exc_info`.

El código emitido por el handler y el que el panel sabe pintar se cruzan en
`test_los_codigos_del_handler_los_sabe_pintar_el_panel`: un código huérfano
sería un mensaje mudo para el operador.

**Alcance declarado:** esto se aplica al **camino nuevo** de este corte. No es
un bloque de seguridad general ni reescribe los errores del resto del visor.

## 6. Cero conocimiento interno

El operador elige una fuente **por su nombre**, de una lista. El formulario
lleva exactamente dos campos: `fuente` y `csrf_token`.

`viewer/app/sources_catalog.py` traduce entre lo que ve el operador y lo que
resuelve el servidor (fichero, perfil, catálogo y **workspace**, este último
derivado del propio perfil). El identificador que viaja es un **slug**, no una
ruta, y la resolución va siempre en el sentido seguro: se **enumera** el
directorio y se busca el handle entre los que el servidor generó. Nunca se
concatena la entrada del cliente con un directorio, así que no hay nada que
recorrer hacia arriba (`test_el_identificador_de_la_fuente_no_es_una_ruta`
prueba `../../etc/passwd`, rutas absolutas y nombres de fichero).

El directorio sale de `S9K_INGEST_SOURCES_DIR` y, en su ausencia, de
`examples/ingesta-v3`. El operador ni lo escribe ni lo ve.

## 7. El estado sobrevive al refresco y al reinicio

Patrón **PRG** (POST → 303 → GET). La confirmación **no** es un mensaje efímero
en sesión: se reconstruye leyendo el trabajo de `jobs.db`, por el camino de
producción y **con ámbito** (`scoped_job`), de modo que poner el id de otro en la
URL no fabrica un acuse. Por eso recargar no reenvía nada y reiniciar el
servicio no pierde nada.

## 8. Lo que este corte NO toca

`apply`, `review` y `rollback` son cortes posteriores. El handler corre con
`apply=False` y `driver=None` **literales**, y hay una prueba por AST
(`test_este_corte_no_aplica_nada_al_grafo`) que obliga a pasar por ahí a quien
active la escritura.

## 9. Bloqueantes REGISTRADOS, no arreglados

Se anotan aquí para que no se pierdan. **Ninguno se tocó en el Corte 1.** B-1 quedó cerrado después, en el Corte 2 (`docs/87`).

| # | Bloqueante | Por qué importa |
|---|---|---|
| B-1 | ~~`/v3/review/decide` escribe `viewer/output/reviews-v3/decisions.jsonl`, **que no lee nadie**; el motor lee su propio `decisiones.json`. El puente es de **un solo sentido**~~ **CERRADO en el Corte 2** | **Falso éxito de producto**: el operador creía que aprobaba y eso no se aplicaba jamás. Resuelto con **una autoridad única**: la tabla `human_decisions` del SQLite del visor. El motor la lee por un solo camino (`knowledge_v3/review_decisions.py`) y **no** lee `decisions.jsonl`, que es exportación de auditoría. `undo` entra en el mismo contrato. Ver `docs/87` |
| B-2 | `undo` de `/v3/review` **no es un rollback** del grafo | Se llama como si lo fuera |
| B-3 | El rollback exige el `rollback.json` de la corrida | Si no se guardó, **el apply es irreversible por la ruta de operador** |

### Inventario de deuda, corregido formalmente

```
observations mal etiquetado -> CERRADO (arreglado en la tanda 8, verificado en 3bdfd40)
retained incorrecto         -> CONFIRMADO, sigue abierto (es del Corte 3)
```

## 10. Los paneles están apagados por defecto

`S9K_PANEL_B_ENABLED` falla cerrado, y el interruptor apaga **también la
escritura**, no sólo la pantalla: con el hueco apagado el `POST` responde 404
(`test_con_el_panel_apagado_la_capacidad_no_existe`). El orden guarda → interruptor
se conserva, para que un anónimo no pueda enumerar qué paneles están encendidos
comparando 404 contra 302.

**Consecuencia para el despliegue:** esta capacidad no está disponible hasta que
alguien encienda el hueco B explícitamente. Es la postura correcta para
producción y este corte no la cambia.
