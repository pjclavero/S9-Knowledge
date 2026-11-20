# 94 · RC-E2E final (segunda ronda): resultados, hallazgos y veredicto

**Programa USABLE-V1 · Fecha de la prueba:** 2026-11-20 (de las 03:17 a las 07:17 UTC, aproximadamente) ·
**Documento escrito:** 2026-11-20.
**Naturaleza:** segunda ronda del ensayo de release candidate (RC-E2E), la que debía verificar por efecto las
correcciones hechas tras la RC-1 y cubrir las regresiones de
[`93-rc-e2e-1-resultados.md`](93-rc-e2e-1-resultados.md) §8.

> **Veredicto: NO VERIFIED.** La revisión adversarial independiente de la ronda dio **NO APTO** (§8). Varias
> regresiones del documento 93 no se cumplen o no se ejecutaron, y hay cuatro hallazgos del producto: tres
> se corrigieron en `main` **después** de la prueba (§7) y **no están verificados por efecto**; el cuarto
> (RC2-02) sigue abierto. Esta ronda no promociona ningún hito a VERIFIED de RC. Hace falta
> una tercera ronda (§10).
>
> «VERIFIED en laboratorio» no es «VERIFIED en producción», y aquí **ni siquiera hay VERIFIED en
> laboratorio** para la RC en su conjunto: sólo hay puntos concretos demostrados por efecto (§5).

Enlaces: plan canónico en [`PLAN_USABLE_V1.md`](PLAN_USABLE_V1.md) (ficha «RC-E2E final (segunda ronda)»);
ronda anterior en [`93-rc-e2e-1-resultados.md`](93-rc-e2e-1-resultados.md); preparación del ensayo en
[`91-ensayo-rc-preparacion.md`](91-ensayo-rc-preparacion.md); guion de despliegue y filas N1–N17 en
[`../deploy/README.md`](../deploy/README.md).

## 0. Cómo leer los estados

Los cinco niveles son los del documento 93 §0 (MERGEADO, VERIFIED de arnés local, VERIFIED de laboratorio,
RC-E2E, Producción); ninguno implica el siguiente. En las tablas de este documento cada escenario lleva uno
de estos cuatro estados, con su razón:

| Estado | Significado |
|---|---|
| **PASS por efecto** | lo automatizable del escenario se ejecutó y se juzgó por efecto observable, sin fallos. No incluye navegador en ningún caso |
| **PARCIAL** | una parte es PASS por efecto y otra es FAIL o NO EJECUTADO; se dice cuál |
| **FAIL** | se ejecutó y el producto no hizo lo que el contrato pide |
| **NO EJECUTADO** | no se midió; se dice por qué. No es un «pendiente menor»: es ausencia de evidencia |

Nada de lo que fue FAIL o NO EJECUTADO se reescribe aquí como mejor de lo que fue.

## 1. Sujeto

- **Sujeto:** `864041d05302f197f266b6ad9ebdcab83f3bb195` (`main` tras #287, #288, #290 y #291). **No se
  modificó ni se parcheó nada del producto durante la prueba**: clon del repositorio público con `HEAD` =
  sujeto y árbol limpio; cada guion del arnés se negaba a correr si no era así.
- Producción: **no se ha tocado ni actualizado**. La instalación «legacy» de los escenarios 2 y 3 vuelve a
  ser **sintética** (release rc5.1 construida en el laboratorio, con datos sintéticos, sin worker y sin almacén
  de revisión); no se probó con una copia de datos de producción (no autorizada).

## 2. Entorno

- Un laboratorio de **una sola máquina**, exclusiva, restaurada a una base limpia preparada: Debian 13.7,
  kernel 6.12.107, 4 vCPU, 4923 MB de memoria **sin swap**, disco de 99 G; systemd 257, nginx 1.26.3,
  OpenSSL 3.5.7.
- **Python efectivo:** 3.13.5 en el sistema y en los entornos virtuales del visor y del motor de la release
  (numpy 2.5.1, soupsieve 4.0, driver neo4j 5.28.4, igual que el lock).
- **Neo4j efectivo:** imagen `neo4j:5.26-enterprise` (**licencia de evaluación aceptada por el operador**), un
  único contenedor acotado: 1536 MB, heap de 512 MB, pagecache de 256 MB, escuchando sólo en la interfaz
  local, sin reinicio automático y con la telemetría desactivada desde el primer arranque. Cuentas reales: la
  de sólo lectura del worker (rol documentado en `deploy/README.md`: `ACCESS` + `MATCH`) y la del visor.
  **Parado y eliminado al cerrar.**
- TLS y nginx de laboratorio con **CA propia** (con `keyUsage`); resolución del nombre por `/etc/hosts`,
  persistida esta vez también en la plantilla de cloud-init.
- **Sin Ansible** (healthcheck instalado a mano; desviación declarada). **Sin navegador.**
- Sin instantáneas de hipervisor: los estados conocidos se restauraron con copias `tar`.
- Reloj del laboratorio unos 20 s adelantado respecto al del puesto de control (los sellos de evidencia están
  en hora de laboratorio, UTC).

## 3. Método

- El ejecutor de la RC-1, adaptado al sujeto nuevo e instalado con hash. Se rehicieron tres correcciones del
  ejecutor que se habían perdido desde la RC-1 y una cuarta perdida y no listada (la desactivación de la
  telemetría de Neo4j).
- Novedad respecto a la RC-1: una sonda de **sesión HTTP real** (CSRF, cookies, formularios y TLS verificado
  contra la CA del laboratorio). Cubre el intercambio HTTP; **no cubre las pantallas** y no sustituye al
  navegador.
- Guarda de presión del hipervisor consultada aparte antes de cada tanda; para arrancar Neo4j se exigían tres
  lecturas sostenidas en verde de 300 s.
- Criterio PASS/FAIL **por efecto observable**, igual que en la RC-1.
- Búsqueda de fugas de secretos al cerrar cada escenario y antes de cada exportación de evidencia:
  **0 fugas**.
- Defectos del propio ejecutor (no del producto): **11 entradas** (R-01 a R-11, con una R-06b adicional). El
  informe de cierre las da todas por corregidas y con los pasos afectados repetidos; el registro de defectos
  del ejecutor no recoge repetición para una de ellas (R-10, la corrida periódica del healthcheck, §4 E6). Dos de ellas afectan a la
  lectura de E8 y se detallan en §4 y §8: un escape de argumentos que hizo que sólo se ejecutara la primera
  decisión de revisión, y una sonda HTTP que, en los `<select>`, tomaba la primera opción no vacía en lugar
  de la opción por defecto.

## 4. Los 14 escenarios

La numeración es **la del informe de cierre de la RC final**, que no coincide en todo con la del contrato de
la RC-1 (la de la tabla del documento 93 §4). La segunda columna da la equivalencia con el contrato, deducida
de las cifras de los partes por bloque; el informe remite a los partes para esa equivalencia, pero los partes
no traen una tabla explícita.

| Esc. (informe RC final) | Contrato RC-1 | Estado | Motivo |
|---|---|---|---|
| E1 Instalación limpia | E1 | **PARCIAL** | Primera release `--mode fresh` en modo producción con HTTPS, nginx y CA reales, GATE A real y N17: 23 PASS. **FAIL:** `preflight.sh` sigue bloqueando la máquina limpia (RC2-01, reaparición de RC1-01). Navegador NO EJECUTADO. Healthcheck instalado a mano (desviación) |
| E2 Upgrade desde legacy | E2 | **PARCIAL** | Legacy **sintética** rc5.1 (visor como root); no es copia de producción. STOP en 2b con el visor vivo. Sin autorizar: **STOP en 2c con la legacy viva**, mismo PID, 0 ficheros `*.migrado-*`, meta y sha intactos. Con `--autorizar-creacion-review-db`: rc 0 y 13/0 (identidad, filas, sha, el administrador legacy entra, el setup responde 404). Escenario de legacy simulado del repositorio: 18/0. Navegador NO EJECUTADO; copia de producción NO EJECUTADA (no autorizada) |
| E3 Migración y preservación | E3 | **PASS por efecto** (auto) | «Sin almacén» medido en E2. N16 con `jobs.db` ausente 7/0. N16 con `jobs.db` de 0 bytes: BLOCK `CORRUPT_STATE` en el paso 3, **antes de parar**, con el visor vivo (11/0). Escenario C del repositorio C1–C11: 89/0 (C4 y C8 pasan; C9–C11 ejecutados por primera vez). Corte real de la migración: 9/0 |
| E4 Identidad y permisos | E4 | **PASS por efecto** (auto) | 30/0, una segunda corrida del mismo guion 32/0 y el escenario D/E/F del repositorio (33 PASS) (otro usuario no lee ni lista; ACL real; CLIs como root rc 4) |
| E5 Secretos de Neo4j (0640) | E9 (parte) | **PARCIAL** | PASS por efecto: el **worker real** lee el secreto `root:s9knowledge 0640`, autentica y sus jobs terminan `complete`; las CLIs del motor leen el secreto y autentican; ningún paso cambió el modo del fichero y el servicio no puede escribirlo. **FAIL:** `writer-schema verify` por el camino canónico sale con **rc 2** (RC2-02). El informe de cierre lo da como PASS «con matiz»; aquí se registra PARCIAL porque la regresión 1 pedía rc 0 |
| E6 Visor, worker, health, API | E6 | **PARCIAL** | 14/0 en la ejecución única; la **corrida periódica dio 2 PASS / 1 FAIL** (resultado global `UNHEALTHY` con Neo4j parado y sin copias de seguridad; atribuido a un defecto del ejecutor, R-10, y **sin repetir**). Healthcheck real bajo su sandbox y con el timer real: bóveda `UNMEASURABLE` con resultado HEALTHY, `state_runtime` HEALTHY. API 401, `Host` hostil 400. NO EJECUTADO: el tope de 5 s del sondeo de bóveda con un montaje colgado, y todo el navegador |
| E7 Auth, sesiones, persistencia | E7 | **PARCIAL** | GATE B 12/0 hasta `INSTALLATION_COMPLETE`, más sesión HTTP real 5/0 (login con CSRF, contraseña errónea 401 sin cookie, logout, sin sesión 401). Que la sesión sobreviva a un reinicio del visor se observó como **dato, sin contrato escrito**: no es uno de los PASS. NO EJECUTADO: pantallas e inactividad de sesión (60 min) |
| E8 Ingesta y consultas con Neo4j | E8 | **PARCIAL** | Por **sesión HTTP real** desde el panel, no por navegador: alta de ingesta → el worker termina `complete` (5 propuestas) → 2 aprobadas y 1 rechazada → 3 altas → sellado → APLICAR (`PLAN_APPLIED`, 5 marcas) → resultado (3 entidades, 2 hechos) → procedencia y evidencia literal → `/api/entities` autenticada (3 entidades; sin sesión 401). **Salvedades:** «Relaciones añadidas (0)» por `PLAN_SEALED_SIN_PROYECCION`: **no consta que la presión del hipervisor sea la causa** (el sellado respondió en 1 s y sin síntoma de presión); la lectura posterior del código lo atribuye al comportamiento del producto en una primera ingesta, cuyos extremos aún no están en el grafo (RC2-05, §6.5). El ejecutor declaró ese sellado **no aceptable** por coincidir con un episodio de presión, y su repetición falló; el panel de fuentes mostró «ningún workspace visible»; las decisiones de revisión se enviaron con la sonda HTTP que después resultó defectuosa (§8); una segunda corrida lanzada para repetir en calma dio **4 PASS / 3 FAIL**: no pudo sellarse ni aplicarse (las propuestas se deduplican entre corridas) y su búsqueda autenticada, lanzada antes del APPLY de la primera, devolvió 0 elementos (la búsqueda válida es la posterior al APPLY). Otros tres pasos de la sesión quedaron en FAIL sin repetir con el mismo criterio (el acuse, operaciones tras la revisión —404 en la ruta de altas— y el inventario del panel). «2 aprobadas y 1 rechazada» **se infiere** del resultado (2 hechos): la evidencia no guarda el cuerpo enviado de cada decisión. NO EJECUTADO: el negativo de aislamiento (8.M9 del contrato) y todas las pantallas. `preflight_ensayo_rc`: RC2-03 y RC2-04 |
| E9 Credenciales inutilizables (RC1-G02) | E9 (parte) | **PASS por efecto** | Secreto ausente, vacío, 0644 y 0660 → job `failed` con `error_code=GRAPH_CREDENTIAL_UNUSABLE`, mensaje con la ruta y el motivo, sin el secreto, sin la frase «no tiene declarada» y con un solo intento. Fallo reintentable (grafo parado) → `pending` con `GRAPH_OBSERVATION_UNAVAILABLE`; al volver el grafo, **el mismo job** termina `complete` con `error_code` y `error_message` vacíos |
| E10 Bóveda externa | E10 | **PARCIAL** | 8/0 más escenario H del repositorio (≈59 PASS, con el sandbox real del healthcheck). NO EJECUTADO: la parte web (409/éxito, `/admin/health`) |
| E11 Backup y restauración | E11 | **PARCIAL** | Estado: 21/0 con copia en frío, **sin herramienta del producto** (no existe). Grafo (7 PASS / 3 FAIL): 19 nodos antes; volcado offline, marcador posterior y carga offline hechos. **NO EJECUTADO: la verificación tras la carga** (mismos nodos, marcador ausente, el worker sigue leyendo): la guarda impidió volver a arrancar Neo4j y después se decidió no arrancarlo más (RC2-E3). **El grafo restaurado quedó sin verificar** |
| E12 Parada, arranque y RC1-06 | E5 | **PASS por efecto** (auto) | 18/0. RC1-06 con systemd real y control discriminante: con `864041d` el bucle de reinicios se detiene (0 arranques en 30 s); con la función de `b4e396d` no (3 arranques, `NRestarts` 1→4). Es una **medida corta y única**: 30 s sobre la función real de parada, no un despliegue completo con migración. Hubo seis corridas; sólo la última es válida (6/0). En dos anteriores el control con la función de `b4e396d` **no** reprodujo el defecto: sólo lo reproduce si la llamada cae en el hueco de `auto-restart` |
| E13 Recuperación ante fallos | E12 | **PARCIAL** | 70/0: STOP en 2b y 2c y BLOCK en el paso 3 con los servicios vivos y el mismo PID (en N14, sólo el worker), sin llegar al 3b, estado intacto y convergencia al restaurar. **NO EJECUTADO:** N8, N10 y N11 (manuales). N12 no producible sin degradar el producto |
| E14 Idempotencia y reinicio | E13 + E14 | **PASS por efecto** (auto) | Dos upgrades idénticos 28/0. Reinicio real de la máquina, autorizado: **al primer intento y sin intervención**, 14/0 (identificador de arranque nuevo, visor, worker y nginx arriba solos, identidad y privilegios, estado, HTTPS verificado, GATE B de persistencia, setup 404) más sesión HTTP real 5/0 al segundo intento (el primero dio 4/1 por un fallo de la sonda). Ansible y navegador fuera de la variante |

Resumen honesto: **E3, E4, E9, E12 y E14 son PASS por efecto en lo automatizable (ninguno con navegador);
los otros nueve son PARCIAL**, y en E1, E5 y E8 hay dentro un fallo real del producto o de su instrumento
(RC2-01, RC2-02, RC2-03/RC2-04 y RC2-05). **Ningún escenario se cierra como PASS completo**, igual que en la RC-1.

## 5. Regresiones del documento 93 §8

El documento 93 fijó la regla: «si algún punto falla, la RC falla». La columna «Veredicto» es la del informe
de cierre, salvo en las filas 1, 2, 3, 9 y 10, donde este documento es más estricto que el informe.

| # | Regresión | Veredicto | Evidencia o motivo |
|---|---|---|---|
| 1 | Worker y CLIs leen el secreto 0640 | **Demostrada (worker) · NO cumplida (CLI)** | Jobs `complete` por el worker real. `writer-schema verify` lee el secreto y autentica, pero sale con rc 2 porque el rol de sólo lectura documentado no puede listar restricciones (RC2-02). La regresión pedía rc 0 |
| 2 | Ingesta más allá de la observación del grafo | **Parcial** | La cadena panel → `complete` → revisión → sellado → APPLY → resultado → procedencia se recorrió **una vez**, por HTTP y no por navegador, y dejó 3 entidades y 2 hechos; **0 relaciones** (`PLAN_SEALED_SIN_PROYECCION`). No consta que la presión sea la causa: es el comportamiento del producto en una primera ingesta (RC2-05). El ejecutor declaró ese sellado no aceptable y la repetición falló. Decisiones enviadas con una sonda defectuosa (§4, §8) |
| 3 | Parada de un servicio en bucle de reinicios | **Demostrada una vez** (medida corta) | 6/0 con control discriminante en la única corrida válida de seis; ventana de 30 s tras la función de parada, **sin migración** (la regresión pedía que `NRestarts` no subiera durante la migración) |
| 4 | STOP de configuración antes de parar | **Demostrada** | URL pública ausente o `http://`, secreto en variable y secreto vacío → STOP en 2c; mismos PID, meta idéntica |
| 5 | STOP sin almacén antes de parar | **Demostrada** | Legacy viva con el mismo PID, 0 ficheros `*.migrado-*` |
| 6 | BLOCK de estado antes de parar | **Demostrada** | N13, N14 (`auth.db` truncada, worker vivo) y `jobs.db` de 0 bytes (visor vivo) → paso 3 |
| 7 | Mensaje y `error_code` veraces | **Demostrada** | Cuatro variantes de credencial inutilizable (ausente, vacía, 0644 y 0660) → `GRAPH_CREDENTIAL_UNUSABLE`. La variante de permiso denegado no se ejerció |
| 8 | Job que termina bien sin `error_code` | **Demostrada** | También tras un fallo reintentable: el job recuperado no arrastra el `error_code` anterior |
| 9 | `preflight_ensayo_rc` con 0640 | **NO cumplida** (parcial) | `neo4j.credencial` VERDE con 0640 (la mitad de RC1-G03 está cerrada). Catálogo y aislamiento siguen PENDIENTE (RC2-03) y, aun cargando el catálogo, hay un rojo falso en modo bóveda (RC2-04) |
| 10 | Healthcheck `UNMEASURABLE` desde el sandbox | **Parcial** | Ejecución única y timer real. El tope de 5 s del sondeo con un montaje colgado **no se ejercitó** |
| 11 | Python | **Parcial** | El rechazo de 3.11.9 con la causa correcta se midió con un intérprete **simulado**; el despliegue con 3.13 construye el entorno con el lock exacto |
| 12 | Restos `.migrando-*` | **Demostrada** | Corte **real** por SIGKILL al proceso de migración durante la copia (resto de 32 MB); el reintento lo retira, lo dice y converge con el mismo sha |
| 13 | Primera instalación sin bloqueo del preflight | **NO demostrada** | RC2-01: ni cambia el comportamiento ni se documenta como elegido |
| 14 | Reinicio de la máquina | **Demostrada** | 14/0 al primer reinicio, sin intervención, con GATE B después |
| 15 | Navegador | **NO EJECUTADA** | No hay navegador. La sesión HTTP cubre el intercambio, no las pantallas |
| 16 | Cuenta del worker de sólo lectura | **Demostrada** | Un `CREATE` con la cuenta del worker devuelve `Neo.ClientError.Security.Forbidden` (Enterprise) |
| 17 | Lo no ejecutado de la RC-1 | **Parcial** | C9–C11 hechos; búsqueda autenticada por sesión hecha. N8, N10 y N11 **no** (manuales); copia de producción como legacy **no** (no autorizada) |

**Demostrado por efecto en esta ronda** (y sólo en el laboratorio): el worker real lee el secreto 0640 y
autentica; el código `GRAPH_CREDENTIAL_UNUSABLE` con su `error_code`; el job recuperado sin `error_code`
rancio; los STOP y el BLOCK antes de parar, con los mismos PID; el SIGKILL durante la migración converge; la
cuenta del worker recibe `Forbidden` donde debe; el reinicio de la máquina; y RC1-06 con systemd real (una
sola medida discriminante, corta). Los dos P1 de la RC-1 (RC1-G01 y RC1-06) están corregidos por efecto en el laboratorio.

**No cumplido o no ejecutado:** la regresión 1 en su mitad de CLI, la 9, la 13 y la 15; la 2, la 10, la 11 y
la 17 sólo en parte; el grafo restaurado de E11 sin verificar; el aislamiento 8.M9; N8, N10 y
N11.

## 6. Hallazgos

Clasificación provisional del informe. No hay P0 ni P1 del producto en esta ronda. Una revisión independiente de este documento considera defendible **P2** para RC2-02 (incumple una regresión explícita) y para RC2-04 (misma clase que RC1-G03, que el documento 93 clasificó P2); aquí no se reclasifican.

| Id | Sev. | Nuevo o reaparición | Qué es | Estado de la corrección |
|---|---|---|---|---|
| RC2-01 | P3 | reaparición de RC1-01 | `preflight.sh --environment production` bloquea (rc 2) una máquina limpia | corregido en `main` (#293 → `84518ac`), **sin verificar por efecto**: lo tiene que repetir la tercera ronda |
| RC2-02 | P3 (documentación o rol) | nuevo | `writer-schema verify` por el camino canónico no puede dar rc 0 con el rol de sólo lectura documentado | **abierto**; decisión pendiente; sin PR |
| RC2-03 | P3 | reaparición de RC1-G04 | `preflight_ensayo_rc` no carga el catálogo ni con el intérprete del entorno virtual de la release | corregido en `main` (#293 → `84518ac`), **sin verificar por efecto**: lo tiene que repetir la tercera ronda |
| RC2-04 | P3 (rojo por la causa equivocada) | nuevo | `fuentes.pobladas` mide el catálogo plano e ignora la raíz de bóvedas: rojo falso en un despliegue con bóveda | corregido en `main` (#293 → `84518ac`), **sin verificar por efecto**: lo tiene que repetir la tercera ronda |
| RC2-05 | sin clasificar | registrado al revisar este documento | En la **primera ingesta** de una instalación las relaciones no se proyectan (`PROJECTION_NO_ANCHOR`): 0 relaciones en E8 | **abierto**; decisión del operador pendiente (§6.5). #294 sólo corrigió el texto |
| RC2-E1, RC2-E2, RC2-E3 | entorno | — | Presión del hipervisor (§11); no son defectos del producto | — |

### 6.1 RC2-01 (P3): `preflight.sh` bloquea la primera instalación

- **Reproducción:** máquina sin instalación, con las plantillas de configuración preparadas;
  `deploy/scripts/preflight.sh --environment production`.
- **Observado:** `STOP directorio de estado no existe: /var/lib/s9-knowledge`, resumen «3 advertencias, 1
  bloqueos», rc **2**. En la misma pasada, `deploy.sh --mode fresh --confirm-production` termina con rc 0,
  estado `FIRST_ADMIN_PENDING` y GATE A real en verde.
- **Causa:** la rama de producción del preflight sin directorio de estado bloquea; no cambió entre `b4e396d`
  y `864041d`, y `deploy/README.md` no declara ese comportamiento como elegido.
- **Consecuencia:** la regresión 13 queda **no demostrada**.

### 6.2 RC2-02 (P3): `writer-schema verify` y el rol de sólo lectura

- **Reproducción:** Neo4j Enterprise con el rol de sólo lectura tal como lo documenta `deploy/README.md`
  (`GRANT ACCESS` y `GRANT MATCH` sobre nodos y relaciones); despliegue de `864041d`; `s9k-cli.sh
  writer-schema verify`.
- **Observado:** rc **2** con `Neo.ClientError.Security.Forbidden`: «Show constraints» no está permitido para
  la cuenta de sólo lectura. Con la cuenta del writer, `writer-schema ensure` instala 7 de 7 restricciones y
  deja el esquema completo; después, el mismo `verify` vuelve a dar rc 2.
- **Lo que sí demuestra:** la CLI del motor lee el secreto 0640 por su camino real y el servidor la autentica;
  el rechazo es de **autorización**, no de credencial. RC1-G01 está corregido también para las CLIs.
- **Lo que no:** el rc 0 que pedía la regresión 1. El envoltorio de las CLIs superpone siempre la
  configuración del worker, así que el camino canónico usa la cuenta de sólo lectura, y su rol documentado no
  puede listar restricciones.
- **Decisión pendiente:** añadir `SHOW CONSTRAINT` y `SHOW INDEX` al rol documentado, o documentar que
  `verify` se hace con la cuenta del writer. La causa se nombra bien (no es un rojo por la causa equivocada).

### 6.3 RC2-03 (P3): `preflight_ensayo_rc` no carga el catálogo ni con el entorno de la release

- **Reproducción:** tras el despliegue, el guion ejecutado con el intérprete del entorno virtual del visor de
  la release, que es lo que manda `docs/91` desde #291.
- **Observado:** `fuentes.pobladas` y `aislamiento.workspace` quedan PENDIENTE por
  `ModuleNotFoundError: No module named 'app'`; recuento ROJO 0 · PENDIENTE 4 · VERDE 14 · TOTAL 18. Idéntico
  con el `python3` del sistema.
- **Causa medida:** el catálogo importa `app` y el guion sólo añade `deploy/scripts` a la ruta de módulos.
- **Consecuencia:** la corrección de #291 fue **documental y no cierra el defecto** (RC1-G04 reaparece). La
  otra mitad sí está cerrada: `neo4j.credencial` sale VERDE con el 0640 (RC1-G03).

### 6.4 RC2-04 (P3): `fuentes.pobladas` mide el catálogo plano

- **Reproducción (diagnóstico, fuera del camino documentado):** igual que RC2-03, añadiendo el visor de la
  release a la ruta de módulos.
- **Observado:** `ROJO fuentes.pobladas directorio de fuentes VACIO`; recuento ROJO 1 · PENDIENTE 2 ·
  VERDE 15. En el mismo despliegue, el panel de operaciones ofrece la fuente y la ingesta desde el panel
  termina `complete`.
- **Causa por lectura:** la comprobación llama al catálogo sólo con el directorio de fuentes, sin la raíz de
  bóvedas; con esa única variable el catálogo usa el modo plano, no recursivo, y la raíz de la bóveda sólo
  contiene carpetas de juego.
- Es la clase «rojo por la causa equivocada»: el instrumento dice vacío lo que el producto usa.

### 6.5 RC2-05 (sin clasificar): la primera ingesta no proyecta relaciones

- **Observado en E8:** el sellado devolvió `PLAN_SEALED_SIN_PROYECCION` y el resultado mostró «Relaciones añadidas (0)», con 3 entidades y 2 hechos.
- **Causa por lectura (no medida en esta ronda):** las anclas de estado de los extremos salen del snapshot de la corrida; una entidad que no estaba en el grafo al ingerir —toda la primera ingesta de una instalación, o un alta aprobada en la misma revisión— no tiene ancla, y la proyección se omite con `PROJECTION_NO_ANCHOR`. Es un límite que `docs/92` ya declaraba.
- **Lo que no se sostiene:** `docs/92` afirmaba que una segunda ingesta de la misma fuente proyecta la relación. No hay testigo que lo ejerza y la revisión de #294 concluye por lectura que por el camino web no ocurre. Esa afirmación se retiró en #294.
- **No es un artefacto de entorno:** el informe de cierre lo anotó junto al episodio de presión; la evidencia del sellado no muestra síntoma de presión.
- **Decisión pendiente del operador:** anclar las altas del mismo plan, o declararlo como límite con un aviso propio y un camino documentado y probado para proyectar después.

## 7. Correspondencia con PR

**Integrado en `main` desde el sujeto de la RC-1** (`b4e396d`); el detalle de cada PR está en el documento 93
§6:

| PR | SHA en `main` | Qué es |
|---|---|---|
| #289 | `e2063bc` | CI en `ubuntu-latest` (infraestructura) |
| #287 | `bb7f3c9` | Deudas de salud D-1 y D-4 |
| #288 | `7982f6d` | RC1-G01, RC1-G03, D-2, D-6, D-8 |
| #290 | `31935e6` | RC1-03, RC1-04, RC1-05, RC1-06 |
| #291 | `864041d` | RC1-G02 y documentación de RC1-02 y RC1-G04 — **sujeto de esta ronda** |
| #292 | `007790e` | Documentación de la RC-1 (`docs/93`); posterior al sujeto, sin código |

**Correcciones de esta ronda: mergeadas después de la prueba y NO verificadas por efecto.** Están en `main` con tests, calibradores y revisión independiente por lectura (APTO CON OBSERVACIONES en ambos PR), pero ninguna se ha ejercido en una RC:

| Hallazgo | Dónde | Estado |
|---|---|---|
| RC2-01, RC2-03, RC2-04 | #293 → `84518ac` | mergeado; sin verificar por efecto |
| RC2-02 | — | sin PR; decisión pendiente (§6.2) |
| Estabilidad de los testigos del worker (mutantes M1 y MF del calibrador B3) y textos del escenario 8 | #294 → `0ec6fe1` | mergeado; sin verificar por efecto. Los textos dicen la causa y nada más; **no cambia el comportamiento**: en la primera ingesta las relaciones siguen sin proyectarse |

## 8. Revisión independiente y veredicto

- La ronda pasó una **revisión adversarial independiente** cuyo dictamen fue **NO APTO**. El veredicto de la
  RC-E2E final es, por tanto, **NO VERIFIED**.
- El texto de esa revisión no forma parte de las fuentes de este documento (informe de cierre, hallazgos,
  partes por bloque y defectos del ejecutor). **El informe de cierre no la recoge**: se escribió antes y no
  contiene ni el dictamen ni el veredicto. Lo que sigue es lo que el organizador del programa da por
  establecido tras la revisión, contrastado con esas fuentes donde ha sido posible:
  - **Regresiones no cumplidas:** la 1 en su mitad de CLI (RC2-02), la 9 (RC2-03 y RC2-04), la 13 (RC2-01)
    y la 15 (navegador). Coincide con el informe (§5).
  - **Grafo restaurado sin verificar** (E11). Coincide con el informe; la evidencia del ejecutor registra el
    arranque posterior a la carga como rechazado por la guarda de presión, y los dos pasos de verificación
    como no superados.
  - **No ejecutado:** el aislamiento 8.M9, N8, N10, N11 y varios pasos HTTP. El informe recoge N8, N10 y N11,
    la web de la bóveda y la inactividad de sesión; **no menciona 8.M9**, y en la evidencia no hay ningún paso
    que lo ejercite.
  - **Decisiones de E8 enviadas por una sonda defectuosa.** Los defectos del ejecutor lo sustentan en parte:
    un escape de argumentos hizo que sólo se ejecutara la primera decisión (se repitieron), y la sonda HTTP
    tomaba en los `<select>` la primera opción no vacía en lugar de la opción por defecto. Esta segunda
    corrección es posterior al envío de las decisiones, y **no consta que las decisiones se repitieran con la
    sonda corregida** (no se podía: las propuestas se deduplican entre corridas y no se volvió a arrancar
    Neo4j). Lo aprobado, rechazado y aplicado en E8 debe leerse con esa salvedad.
- Ningún hito del plan cambia de estado por esta ronda.

## 9. Lo NO EJECUTADO y por qué

- **Navegador** (no hay): todas las pantallas de E1, E6, E7, E8, E10 y E14, y la regresión 15.
- **Inactividad de sesión** (60 min).
- **N8, N10 y N11** (manuales). **N12** no es producible sin degradar el producto.
- **Aislamiento negativo de E8** (8.M9 del contrato).
- **E11, verificación del grafo tras la carga.**
- **Repetición del sellado y del APPLY de E8** con una sonda correcta: exige reiniciar el almacén de revisión
  y el grafo, y no se hizo por la decisión de no volver a arrancar Neo4j. Repetirlo no haría aparecer
  relaciones mientras RC2-05 siga abierto.
- **Tope de 5 s del sondeo de bóveda** con un montaje colgado (regresión 10).
- **Python anterior a 3.12 real** (regresión 11): sólo simulado.
- **Copia de producción como legacy:** no autorizada.
- **Web de la bóveda** (409/éxito, `/admin/health`).
- **Ansible.**

## 10. Lo que queda para una tercera ronda

Una tercera ronda sólo tiene sentido con las correcciones **mergeadas** y sobre el `main` resultante. Debe
cubrir, por efecto:

1. Las regresiones no cumplidas: 1 (CLI, tras decidir RC2-02), 9 (RC2-03 y RC2-04), 13 (RC2-01) y 15
   (navegador).
2. E8 de extremo a extremo con una sonda correcta o con navegador: decisiones, sellado, APPLY y el
   negativo de aislamiento 8.M9; las relaciones, según lo que se decida en RC2-05.
3. E11: verificación del grafo restaurado.
4. N8, N10 y N11; la inactividad de sesión; la web de la bóveda; el tope de 5 s del sondeo de bóveda; un
   Python anterior a 3.12 real.
5. Lo que sigue condicionado a decisiones del operador: navegador, Ansible, copia de producción como legacy,
   las relaciones en la primera ingesta (RC2-05) y, sobre todo, **dónde y cómo se arranca Neo4j** (§11).

Todo lo demostrado en esta ronda vale para `864041d`; si el sujeto cambia, la tercera ronda lo vuelve a
medir.

## 11. Limitaciones y observaciones del entorno

Limitaciones: una sola máquina sin instantáneas de hipervisor; sin Ansible; sin navegador; legacy sintética;
ventanas de Neo4j cortadas por presión del hipervisor. Un error de procedimiento declarado por el ejecutor:
a las 05:00 UTC se leyó la guarda de presión y se envió el sellado en una misma llamada, cuando la regla pide
leer la guarda aparte y antes.

Observaciones de entorno (**no son defectos del producto**):

- **RC2-E1.** Presión del hipervisor con el laboratorio **en reposo** (03:37–03:41 UTC) y, a continuación, un
  soft lockup en otra máquina del mismo hipervisor. No había nada lanzado en el laboratorio: la causa no está
  en esta RC.
- **RC2-E2.** Dos episodios más con Neo4j vivo (04:37–04:43 y 05:00 UTC). En ambos se paró Neo4j de
  inmediato. Resultados afectados: un `POST /login` sin respuesta en 60 s, repetido en calma (normal,
  descartado); y el sellado del plan de E8, que el ejecutor declaró no aceptable y cuya repetición falló (§4, E8).
- **Incidente RC2-E3.** El sexto arranque del contenedor de Neo4j en el laboratorio, cuarta invocación del guion de arranque (06:46 UTC, tras tres lecturas
  sostenidas en verde de la guarda) fue seguido, a los tres minutos, de paginación en el hipervisor y, a las
  06:50, de **2 soft lockups en otra máquina del mismo hipervisor**. Neo4j se paró a mano antes de que
  llegara a responder. Con este son **4 de 5 episodios de presión que empiezan a los pocos minutos de un
  arranque de Neo4j** en el laboratorio; el único sin Neo4j fue RC2-E1. El quinto episodio (hacia las 05:25 UTC, tras la carga del grafo) sólo consta en los hallazgos del ejecutor y en el rechazo de la guarda al arranque posterior. Visto desde el otro lado: el registro del ejecutor anota **6 arranques, y 2 de ellos no fueron seguidos de ningún episodio**. Es una **correlación, no una
  causalidad demostrada**. El mecanismo propuesto en el informe (la JVM toca de golpe la memoria del
  contenedor y el hipervisor tiene que respaldarla) es plausible y **no está demostrado**.
- **Consecuencia:** **no se vuelve a arrancar Neo4j en el laboratorio sin una decisión del operador.**
  Recomendación del informe: arrancarlo sólo con la memoria de la máquina ya respaldada o en otro nodo, o
  con heap y pagecache más bajos, y con aviso previo.
- Memoria con Neo4j vivo: mínimo observado de memoria disponible **3241 MB** (umbral de aborto de 800 MB,
  nunca alcanzado); el contenedor no pasó de unos 1000 MiB de su límite de 1,5 GiB. Ventanas con Neo4j:
  04:29–04:40, 04:54–05:00, 05:11–05:25 (con volcado y carga) y 06:46–06:50 (sin llegar a responder). Según
  el informe, el factor limitante no fue la memoria del laboratorio sino la del hipervisor; **no está demostrado**, y de la guarda de presión no se conservó registro.

## 12. Estado del laboratorio y de producción

El laboratorio quedó con el sujeto `864041d` instalado y funcionando tras el reinicio: visor, worker y nginx
activos, `INSTALLATION_COMPLETE`, estado conforme y el proveedor de grafo sin configurar. Neo4j: contenedor
**parado y eliminado**, datos de laboratorio borrados; queda la imagen, que venía preinstalada. Ninguna otra
máquina se tocó: la guarda de presión sólo **leyó** el estado del hipervisor y de otra máquina.

**Producción: no se ha tocado ni actualizado.** Este documento no afirma nada más sobre producción.
