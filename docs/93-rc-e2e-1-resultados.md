# 93 · RC-E2E 1 (diagnóstica): resultados, hallazgos y correcciones

**Programa USABLE-V1 · Fecha de la prueba:** 2026-11-18 y 2026-11-19 · **Documento escrito:** 2026-11-20.
**Naturaleza:** primera ronda del ensayo de release candidate (RC-E2E). Es **diagnóstica**: mide y registra,
no corrige el producto durante la prueba y no promociona ningún estado a VERIFIED de RC. Las correcciones
que se citan abajo se hicieron **después**, en PR propios, y **no han sido verificadas por efecto en un
entorno real**: eso es lo que debe demostrar la RC-E2E final (§8).

> **Numeración.** El número 92 ya está ocupado por `docs/92-alta-de-entidad-desde-el-producto.md`; este
> documento usa el siguiente libre, el 93.

Enlaces: plan canónico en [`PLAN_USABLE_V1.md`](PLAN_USABLE_V1.md) (ficha «RC-E2E 1 (diagnóstica)»);
preparación del ensayo en [`91-ensayo-rc-preparacion.md`](91-ensayo-rc-preparacion.md); guion de despliegue
y filas N1–N17 en [`../deploy/README.md`](../deploy/README.md).

## 0. Cómo leer los estados

Este documento distingue siempre cinco niveles; ninguno implica el siguiente:

| Nivel | Significado |
|---|---|
| **MERGEADO** | el cambio está en `main` con CI required verde y revisión independiente |
| **VERIFIED (arnés local)** | demostrado por tests, calibradores y CI sobre el texto real del código, sin máquina limpia |
| **VERIFIED (laboratorio)** | ejecutado en la máquina de laboratorio sobre el sujeto |
| **RC-E2E** | ejecutado en un ensayo de release candidate con el código **final** que se va a desplegar |
| **Producción** | **sin tocar** en ninguna ronda de este programa; no hay ninguna verificación de producción |

Un escenario **PARCIAL** es PARCIAL; lo no ejecutado es **PENDING** con su motivo. Nada de lo que fue FAIL se
reescribe aquí como mejor de lo que fue.

## 1. Sujeto

- **Sujeto:** `b4e396d1042e3ad8bf7513d2fd3b73d24ad4df8e` (`main` tras #285, que cerró H-06 + H-08, y #286).
  **No se modificó durante la prueba**: cada guion del arnés se negaba a correr si `HEAD` no era el sujeto o el
  árbol tenía cambios.
- Producción: no se tocó. La instalación «legacy» de los escenarios 2 y 3 es **sintética** (una release
  antigua construida en el laboratorio); no se probó con una copia de datos de producción.

## 2. Entorno

- Un laboratorio de **una sola máquina**, restaurada a disco limpio: Debian 13, Python 3.13.5, 4 vCPU,
  4,9 GB de memoria, **sin swap**. TLS y nginx de laboratorio con **CA propia**; resolución del nombre por
  `/etc/hosts`.
- Neo4j 5.26 **Community**, un único contenedor acotado (límite de 1,5 GiB), vivo unos 10 minutos y retirado
  al terminar. El operador **no aceptó la licencia de evaluación de Enterprise**: todo lo que depende de la
  cuenta de sólo lectura del worker (que requiere Enterprise) quedó **PENDING por edición**.
- **Sin Ansible** (la primera instalación y el healthcheck se hicieron a mano; desviación declarada).
- **Sin navegador** (todo lo manual de navegador queda PENDING).
- Sin instantáneas de hipervisor: los «estados conocidos» (máquina limpia, plantillas preparadas, primer
  administrador pendiente, instalación completa, legacy) se restauraron con copias `tar`.
- Reloj de la máquina de laboratorio unos 10 s adelantado respecto al del puesto de control (los sellos de
  evidencia están en hora de laboratorio).

## 3. Método

- Ejecutor con guardas: `HEAD` = sujeto, máquina declarada por identificador, memoria mínima libre (800 MB;
  2500 MB con Neo4j), `/tmp`, disco, un único Neo4j a la vez.
- Antes de cada tanda se consultaba una guarda de presión del hipervisor; sólo se arrancaba tras lecturas
  sostenidas en verde.
- Criterio PASS/FAIL **por efecto observable**, no por texto; un negativo sólo es PASS si el código de salida
  no es 0, la causa nombrada es la esperada **y** el efecto colateral es el del contrato.
- Búsqueda de fugas de secretos sobre **toda** la evidencia: **0 fugas**.
- Los defectos del propio ejecutor (no del producto) se corrigieron y los escenarios afectados se repitieron;
  están listados en el informe interno y no se cuentan como hallazgos.

## 4. Los 14 escenarios

Estado tal cual lo dejó el informe de cierre. «auto» = lo ejecutó y juzgó el arnés sin intervención.

| Esc. | Estado | Motivo |
|---|---|---|
| E1 Instalación limpia | PARCIAL | Primera release en modo producción con HTTPS, nginx y CA reales; GATE A real y N17 PASS. **FAIL** en `preflight.sh`, que bloquea una máquina limpia (RC1-01). Navegador PENDING. Healthcheck instalado a mano, equivalente al rol Ansible (desviación) |
| E2 Upgrade desde legacy | PARCIAL | Legacy **sintética** (release rc5.1, visor como root). STOP en el paso 2b con el servicio vivo (correcto). STOP «sin almacén» en el paso 6 **tras parar y migrar** (RC1-04). Con `--autorizar-creacion-review-db` el upgrade termina bien y la verificación da 13/0 (identidad, filas, sha, el administrador legacy entra, el setup responde 404). Escenario de legacy simulado del repositorio: PASS. Sin copia de producción; navegador PENDING |
| E3 Migración y preservación | PARCIAL | Sin almacén: PASS. N16 con `jobs.db` ausente: PASS. N16 con `jobs.db` de 0 bytes: BLOCK `CORRUPT_STATE` aplicado **después** de parar (RC1-05). Laboratorio del repositorio, escenario C: C1–C3 y C5–C7 PASS; C4 y C8 paran el guion por RC1-06; C9–C11 PENDING (el guion se detiene en el primer FAIL) |
| E4 Identidad, permisos, secretos | PASS (auto) | 30/0 más escenario D del repositorio 32/0, con ACL real |
| E5 Arranque, parada, reinicio | PASS (auto) | 18/0. Pendiente un paso manual con trabajo en curso (F10 del plan) |
| E6 Visor, worker, health, API | PARCIAL | 12/0 (API 401, `Host` hostil 400, healthcheck real; backups UNHEALTHY por «sin conjuntos de backup»; neo4j UNKNOWN sin grafo). Navegador PENDING |
| E7 Auth, sesiones, persistencia | PARCIAL | GATE B real por HTTPS hasta `INSTALLATION_COMPLETE` (12/0), cookies Secure/HttpOnly/SameSite=lax. Navegador e inactividad PENDING |
| E8 Flujos de conocimiento | PARCIAL | Ingesta encolada por la CLI (no por el panel): el worker la recoge en unos 4 s y termina **failed** con `GRAPH_OBSERVATION_UNCONFIGURED` (RC1-G01), 0 nodos creados. Se corta en la observación del grafo: propuestas, revisión, sellado, APPLY, resultado y procedencia quedan **PENDING por el defecto**. La búsqueda autenticada por sesión HTTP quedó PENDING (sonda no creada: el entorno de la sesión denegaba crear ficheros). Navegador PENDING |
| E9 Neo4j efectivo | PARCIAL | 9.03 **FAIL**: el worker no lee su secreto 0640 (RC1-G01). 9.04 FAIL como consecuencia. 9.05 (cuenta del worker de sólo lectura) **PENDING por edición** (Community). 9.07 PASS (el ejecutor no tocó el modo del secreto). Medición aparte por el camino del visor: PASS (lee los 3 nodos sembrados) y healthcheck neo4j=HEALTHY. 9.13 y las pruebas manuales PENDING |
| E10 Bóveda | PARCIAL | Escenario H del repositorio PASS (58 comprobaciones); la parte web PENDING |
| E11 Backup y restauración | PARCIAL | Estado: 21/0 con copia en frío, **sin herramienta del producto** (no existe). Grafo: volcado y carga offline con Neo4j Community, 3 nodos antes y después, el marcador posterior desaparece: PASS 10/0 |
| E12 Negativos y recuperación | PARCIAL | Las filas N automatizables dan rojo por su causa y convergen al restaurar; **los servicios quedan parados tras un STOP de configuración** (RC1-03). N8, N10 y N11 PENDING (manuales); N12 no producible |
| E13 Idempotencia | PARCIAL | 28/0 (dos upgrades del mismo sujeto, ~70–80 s cada uno, estado idéntico). Ansible fuera de la variante |
| E14 Reinicio de la máquina | PASS (auto) | Segundo reinicio, sin ninguna intervención, 14/0. El **primero falló** en HTTPS porque cloud-init regeneró `/etc/hosts` (entorno, RC1-E1). Navegador PENDING |

Resumen honesto: **E4, E5 y E14 son PASS automáticos (ninguno con navegador); todos los demás son PARCIAL**
(dentro de ellos, PASS parciales: el grafo de E11 y el escenario de legacy simulado de E2), y E8 y E9 son
PARCIAL con un FAIL real del producto en medio. **Ningún escenario se cierra como
PASS completo.**

## 5. Hallazgos

Clasificación provisional del informe (la severidad la confirma el organizador al corregir).

| Id | Sev. | Qué es | Estado de la corrección |
|---|---|---|---|
| RC1-G01 (= H-L01) | **P1** | El worker y las CLIs del motor no pueden leer el secreto de Neo4j que deja el despliegue: ninguna ingesta puede terminar | corregido en #288 |
| RC1-06 | **P1** | El paso 3b del despliegue da por parado un servicio en bucle de reinicios y systemd lo relanza durante la migración | corregido en #290 |
| RC1-03 (= H-L04) | P2 | Configuración inválida detectada tras parar y migrar: servicios PARADOS | corregido en #290 (bloque 2c) |
| RC1-04 | P2 | Primer upgrade desde legacy: STOP «sin almacén» con el servicio parado y el estado ya migrado | corregido en #290 |
| RC1-05 | P2 (+P3 doc) | BLOCK de `detect_state` aplicado después de parar; un `jobs.db` de 0 bytes se clasifica CORRUPT | corregido en #290 (decisión antes de parar); la precisión de la documentación sobre «vacía» sigue como P3 |
| RC1-G03 (= H-L02) | P2 | `preflight_ensayo_rc` exige 0600 donde el despliegue deja 0640 | corregido en #288 |
| RC1-G02 | P2 | El mensaje al operador dice «no tiene declarada la conexión» cuando falla la credencial; `error_code` del job vacío | **#291 MERGEADO → `864041d`** |
| RC1-01 | P3 | `preflight.sh` bloquea una máquina limpia (falta el directorio de estado que el despliegue crea) | abierto |
| RC1-02 | P3 doc | Con Python 3.13 una CA propia sin `keyUsage` se rechaza; la guía no lo decía | documentado en #291 (`864041d`) |
| RC1-G04 | P3 | `preflight_ensayo_rc` con el intérprete del sistema no puede cargar el catálogo | documentado en #291 (`864041d`) |
| H-L03, H-L05–H-L17 | P2/P3 | Hallazgos **de lectura** no ejecutados en esta ronda | abiertos, sin medir |
| RC1-E1, RC1-G05, RC1-G06 | entorno | No son defectos del producto (ver §9) | — |

Además, dos deudas de salud no salieron de la RC pero se integraron en la misma tanda (#287): D-1 y D-4
(§7), y tres de #288: D-2, D-6, D-8.

### 5.1 RC1-G01 (P1): el worker no lee su secreto

- **Reproducción:** tras `deploy.sh … --mode upgrade` en producción, el fichero de contraseña del worker queda
  como propiedad de root, grupo del servicio, modo `0640` (paso 5b). Con Neo4j accesible, tres caminos:
  (a) una sonda que construye el driver como el worker; (b) un job `ingest_v3` encolado por la CLI que procesa
  el worker real; (c) la CLI de verificación del esquema del escritor.
- **Observado:** los tres fallan **antes de autenticar**, en la lectura del secreto, que rechaza cualquier bit
  de grupo u otros («hazlo 0600 antes de usarlo»). El job queda `failed`, `reintentable=False`, 0 nodos
  creados; la CLI sale con rc 2.
- **Causa:** la lectura del secreto del motor exige 0600, y la política de H-06 deja 0640 de root; ningún modo
  legible por el usuario del servicio pasaría la comprobación. Antes de H-06 una copia a `/run` lo ocultaba.
- **Divergencia de diagnóstico:** el **visor sí lee** el grafo con su credencial (no comprueba el modo) y el
  healthcheck decía `neo4j=HEALTHY` mientras el worker no podía observar nada.
- **Por qué nadie lo vio:** la CI usa ficheros 0600 del propio usuario de test y el laboratorio nunca había
  tenido Neo4j; `validate_secret_file` acepta 0640.
- **Impacto:** ninguna ingesta termina en una instalación desplegada con `b4e396d`. Bloquea E8 y E9.
- **Corrección:** #288 (`7982f6d`), política única de lectura de secretos.

### 5.2 RC1-06 (P1): la «parada verificada» no lo es con un servicio en bucle

- **Reproducción mínima y determinista:** un visor en bucle de reinicios (unidad con salida inmediata y
  `Restart=always`); se llama a la función real `parar_y_verificar_servicios`.
- **Observado:** imprime «parados y verificados» y devuelve 0; en los 15 s siguientes systemd arranca el
  servicio 4 veces más.
- **Causa (por lectura):** sólo se llama a `systemctl stop` si el servicio está `active`; uno en
  `activating (auto-restart)` no lo está, y la verificación pasa al coincidir con el hueco entre dos
  reinicios.
- **Impacto:** durante la copia, el hash, el renombrado y el `chown`/`chmod` de la migración, systemd puede
  relanzar el proceso antiguo (en una legacy con el visor como root, abriría las bases como root). En esta
  RC el proceso relanzado moría en 1 s sin tocar el estado: **no se observó corrupción** (techo de la
  medida). Visto primero en el escenario C del laboratorio del repositorio (casos C4 y C8).
- **Corrección:** #290 (`31935e6`). El informe dejó la severidad como P1 provisional, rebajable a P2 si se
  exigiera demostrar escritura concurrente.

### 5.3 RC1-03, RC1-04, RC1-05 (P2): validar tarde

Es la misma familia: el despliegue calculaba o validaba después de parar el servicio (3b) y migrar el estado (5b).

- **RC1-03:** sin URL pública declarada, con URL `http://`, con la contraseña de Neo4j en `worker.env`, con el
  secreto del worker vacío, o con `--mode fresh` sobre una instalación con usuarios: STOP correcto y con la
  causa bien nombrada, pero en el paso 6 (el último caso, en el 4), con visor y worker **inactive**. Sólo las
  variables de `CRITICAL_ENV_VARS` paraban en 2b con el servicio vivo. Los datos se preservaron y el
  despliegue convergía al restaurar; el defecto es de **disponibilidad**.
- **RC1-04:** el primer upgrade desde la legacy paraba el visor legacy, migraba (los ficheros originales
  quedaban renombrados con sufijo `.migrado-*`) y sólo entonces pedía `--autorizar-creacion-review-db`. Rearrancar a
  mano la release legacy funcionaba, pero ya no veía sus decisiones, auditoría y propuestas.
- **RC1-05:** `decision=BLOCK` de `detect_state` se calcula en el paso 3 y se aplicaba en el 4, después de
  parar. Un `jobs.db` de **0 bytes** da `CORRUPT_STATE` (deliberado), pero la documentación lo llamaba «vacía»
  y no lo distingue de una cola vacía válida (que sí pasa).
- **Corrección:** #290 (bloque 2c y decisión antes de parar).

### 5.4 RC1-G03 y RC1-G02 (P2)

- **RC1-G03:** `preflight_ensayo_rc --grupo ensayo` tras un despliegue da `ROJO neo4j.credencial modo 0640: se
  exige 0600` (recuento ROJO 1 · PENDIENTE 5 · VERDE 12): dos autoridades contradictorias sobre el mismo
  fichero. Corregido en #288.
- **RC1-G02:** con el mismo job de G01, el `error_message` que ve el operador decía que el despliegue «no
  tiene declarada la conexión al grafo», pero la conexión **sí** estaba declarada; fallaba el modo del secreto,
  cuya causa real sólo aparecía en el journal del worker. Además la columna `error_code` del job quedaba
  vacía aunque el mensaje empezaba por el código. Es la clase «rojo por la causa equivocada»: el operador
  revisaría una configuración que está bien. **#291 MERGEADO → `864041d`**.

### 5.5 P3 abiertos

- **RC1-01:** `preflight.sh --environment production` sale con rc 2 en una máquina limpia por «directorio de
  estado no existe», aunque `deploy.sh --mode fresh` lo crea y termina en verde. Un preflight rojo en el
  camino soportado enseña a ignorarlo.
- **RC1-02:** documentación (CA propia y keyUsage con Python 3.13). El producto falla cerrado y nombra la causa
  (correcto). Documentado en #291 (`864041d`).
- **RC1-G04:** el instrumento depende del entorno virtual de la release y la documentación no lo decía, así
  que dos comprobaciones quedaban sin medir; además `arbol.declarado` sale PENDIENTE porque la plantilla de
  producción no declara el commit del ensayo. Documentado en #291 (`864041d`).
- **Hallazgos de lectura (H-L03, H-L05 a H-L17):** no se ejecutaron en esta ronda; siguen siendo hallazgos de
  lectura, no confirmados por efecto.

## 6. Correspondencia hallazgo → PR → SHA

| Hallazgo | PR | SHA en `main` |
|---|---|---|
| RC1-G01 (H-L01), RC1-G03 (H-L02), D-2, D-6, D-8 | #288 | `7982f6d` |
| RC1-06, RC1-03, RC1-04, RC1-05 | #290 | `31935e6` |
| Deudas de salud D-1 y D-4 (no salieron de la RC) | #287 | `bb7f3c9` |
| CI en `ubuntu-latest` (infraestructura, no hallazgo) | #289 | `e2063bc` |
| RC1-G02, y la documentación de RC1-02 y RC1-G04 | #291 | `864041d` |

Cadena de `main` tras el sujeto: `b4e396d` (sujeto) → #289 `e2063bc` → #287 `bb7f3c9` → #288 `7982f6d` →
#290 `31935e6` → #291 `864041d`.

Qué se hizo en cada uno, resumido (el detalle está en cada PR):

- **#288:** política única de lectura de secretos (`service_state.inspect_secret_for_reading`: fichero propio
  `0600` o `root:s9knowledge` `0640`; la usan el worker y las CLIs del motor); `preflight_ensayo_rc` alineado
  con 0640; D-2 (la declaración «no medible» sólo es legítima en la unidad del healthcheck con sandbox y se
  rechaza en `viewer.env`, `worker.env`, las unidades de visor y worker y el entorno efectivo), D-6 (el gate de
  intérprete, `check_env_reproducibility.py`, compara la tupla completa contra el `Requires-Python` de los
  locks y falla si no encuentra el mínimo) y D-8 (un resto `.migrando-*` de una migración interrumpida se
  retira sólo si se demuestra que es propio y redundante; si no, STOP `RESTO_DE_MIGRACION`). El preflight fija
  `PY_MINIMO="3.12.0"`.
- **#290:** `lib.sh::parar_y_verificar_servicios` (paso 3b) hace `stop` siempre sobre cada unidad existente
  (cancela el reinicio programado de una unidad en `activating (auto-restart)`) y sólo da la parada por buena
  tras 3 lecturas seguidas inactive/failed sin PID; el paso 2c de `deploy.sh` valida configuración y almacén
  de revisión **antes** de parar; y `exigir_decision_de_estado` aplica el BLOCK de `detect_state` también antes
  de parar. Las filas N1, N13 y N16 de `deploy/README.md` ya describen esto.
- **#291:** nuevo código permanente `GRAPH_CREDENTIAL_UNUSABLE` («conexión declarada pero fichero de
  credencial inutilizable»): el mensaje del job nombra la ruta y el motivo (nunca el contenido) y `error_code`
  lleva el mismo código; un error de E/S transitorio al leerlo sale como `GRAPH_OBSERVATION_UNAVAILABLE`
  (reintentable). Documenta RC1-02 en `deploy/README.md` (CA propia bajo la verificación X.509 estricta de
  Python 3.13) y RC1-G04 en `docs/91` (usar el intérprete del entorno virtual de la release). **No** documenta
  la parte `arbol.declarado` de RC1-G04, que sigue abierta.
- **#287:** D-1 (carrera de `state_runtime` con sidecars de SQLite `-wal`/`-shm`) y D-4 (el sondeo de la
  bóveda tiene tiempo máximo).
- **#289:** la CI corre en los runners de GitHub (`ubuntu-latest`); el runner propio queda apagado y
  registrado como respaldo. Ver `docs/ci/MIGRACION_COMMONS_CI.md` §12.

**Verificación de las correcciones (lo que sí se hizo):** cada PR pasó 34/34 check-runs (17 required) en
GitHub y una revisión independiente con dictamen APTO CON OBSERVACIONES; en laboratorio, calibrador H-06/H-08
completo 90/90 e inventario de suites confirmado con la herramienta. La CI de GitHub ejecutó, **después** del
merge de #289 y en verde, los calibradores de inventario de suites (casos SUP-2 a SUP-5), que no se habían
ejecutado en el laboratorio antes de ese merge.

**Lo que NO se ha verificado todavía por efecto:** la parada contra systemd real con el código corregido; la
lectura del secreto `root:s9knowledge 0640` por el worker de extremo a extremo contra Neo4j; y todo lo de
navegador. Ninguna de las correcciones tiene estado de RC-E2E.

## 7. Deuda nueva registrada por las revisiones (P3)

- La **ruta** del fichero de credencial aparece en el `error_message` del job: decidir qué roles pueden verla.
- `set_status` sin mensaje conserva el error previo del job.
- Un `ESTALE` permanente acaba etiquetado como indisponibilidad (reintentable).
- Ningún gate vigila que un calibrador siga cableado en la CI.
- El despliegue tarda unos 8 s más por la verificación de parada.
- `push` y `pull_request` duplican los jobs de CI (cuota).

Deudas de salud ya cerradas en la tanda, no abiertas por la RC: D-1 y D-4 (#287); D-2, D-6, D-8 (#288).

## 8. Regresiones que debe cubrir la RC-E2E final

Lista numerada y verificable. Cada punto debe quedar con evidencia por **efecto** (no por texto) en una
máquina limpia con el código final, y cada uno cierra un hallazgo de esta ronda. Si algún punto falla, la
RC falla y la corrección pasa a la versión siguiente.

1. **Lectura del secreto 0640 por el worker, por su camino real.** Tras un `deploy.sh` en producción, el
   fichero queda `root:s9knowledge 0640`; el worker (no una sonda que lo imite) lee el secreto, autentica y
   observa el grafo. Lo mismo para las CLIs del motor (`writer-schema verify` sale con rc 0). Debe medirse
   con Neo4j real.
2. **Ingesta que llega más allá de la observación del grafo.** Un job `ingest_v3` creado desde el producto
   (panel, no sólo CLI) termina `complete`; hay propuestas visibles, revisión, sellado, APPLY, resultado
   navegable y procedencia; el grafo contiene los nodos esperados. Hoy esto no se ha demostrado nunca de
   extremo a extremo.
3. **Parada de un servicio en bucle de reinicios con systemd real.** Con un servicio en
   `activating (auto-restart)`, el paso de parada lo detiene de verdad: `NRestarts` no sube durante la
   migración y la verificación sólo pasa con la unidad parada y sin PID.
4. **STOP de configuración inválida ANTES de parar, con los servicios en marcha.** URL pública ausente o
   `http://`, contraseña de Neo4j en `worker.env`, secreto del worker vacío: el despliegue termina con la
   causa correcta y visor y worker siguen `active`, con el estado sin migrar.
5. **STOP de upgrade sin almacén de revisión ANTES de parar.** El primer upgrade desde la legacy sin
   `--autorizar-creacion-review-db` se detiene con el servicio legacy vivo y sin ficheros renombrados
   `*.migrado-*`.
6. **BLOCK de estado antes de parar.** `--mode fresh` sobre una instalación con usuarios, `auth.db` truncada
   y `jobs.db` de 0 bytes: el despliegue bloquea con servicios `active` y estado intacto.
7. **Mensaje y `error_code` veraces ante una credencial inutilizable.** Con el fichero del secreto ilegible o
   con modo inválido, el `error_message` del job nombra el fichero de credencial y no dice que «no está
   declarada la conexión»; `error_code` no está vacío. (Corregido en #291; por verificar por efecto.)
8. **Job que termina bien sin `error_code`.** Un job `complete` termina sin `error_code`
   (y no arrastra el de un intento anterior).
9. **`preflight_ensayo_rc` verde con 0640.** Tras el despliegue, `neo4j.credencial` no sale ROJO por el modo
   0640, y las comprobaciones de catálogo y aislamiento se miden (no quedan PENDIENTE por intérprete).
10. **Healthcheck con UNMEASURABLE desde el sandbox.** Con el healthcheck real bajo su unidad systemd, el
    componente de bóveda se declara no medible, nunca UNHEALTHY; `state_runtime` no da UNHEALTHY falso por
    sidecars de SQLite que desaparecen; el sondeo de bóveda respeta su tiempo máximo.
11. **Python.** Un host con Python anterior a 3.12 se rechaza en el preflight con la causa correcta, y el
    despliegue en Python 3.13 construye el entorno del motor con el lock exigido.
12. **Restos `.migrando-*`.** Tras un corte durante la migración no quedan temporales huérfanos que bloqueen
    o confundan el siguiente intento.
13. **Primera instalación.** `preflight.sh` en una máquina limpia no bloquea el camino soportado (RC1-01), o
    queda declarado y documentado el comportamiento elegido.
14. **Reinicio de la máquina** con el código final: servicios, estado, HTTPS y persistencia sin
    intervención, y GATE B tras el reinicio.
15. **Navegador:** login, logout, contraseña errónea, sesión tras reinicio e inactividad, y todo el flujo
    manual de E1, E6, E7, E8, E10 y E14, que no se ejecutó en la RC-1.
16. **Cuenta de sólo lectura del worker (9.05):** requiere Neo4j Enterprise, o una aceptación escrita del
    operador de la exposición residual con Community; la RC-1 quedó PENDING por edición.
17. **Lo no ejecutado de la RC-1:** escenario C del laboratorio del repositorio (C9–C11), con el bucle de
    reinicios ya corregido; N8, N10 y N11 (manuales); búsqueda autenticada por sesión HTTP; copia de
    producción como legacy (si el operador la autoriza).

## 9. Limitaciones y observaciones del entorno

Limitaciones de la RC-1: una sola máquina sin instantáneas de hipervisor; sin Ansible; Neo4j Community, no
Enterprise; sin navegador; legacy sintética; varias esperas por presión del hipervisor.

Observaciones de entorno (**no son defectos del producto**):

- **Presión intermitente del hipervisor:** hubo varios bloqueos breves de CPU en una máquina de producción
  vecina que coincidieron con E/S del laboratorio o de la CI (por ejemplo, durante la descarga de la imagen de
  Neo4j). Es una coincidencia en el tiempo; **la causalidad no está demostrada**. Recomendación: descargar
  imágenes sólo con la guarda de presión sostenida en verde.
- **Telemetría de Neo4j Community:** la imagen envía datos de uso anónimos en su primer arranque si no se
  desactiva; el laboratorio debe fijar `NEO4J_dbms_usage__report_enabled=false` desde el primer arranque.
- **cloud-init:** regeneró `/etc/hosts` en el primer reinicio y el nombre de laboratorio dejó de resolver.
- Memoria con Neo4j vivo: mínimo observado de memoria disponible 3359 MB; el contenedor llegó a unos 832 MiB
  de su límite de 1,5 GiB. Sin aborto.

## 10. Estado del laboratorio y de producción

Tras la RC-1, el laboratorio quedó en el estado «instalación completa del sujeto» con visor, worker y nginx
activos y sin contenedores. **Para la RC final** se ha restaurado a una base limpia preparada (sin producto),
con Neo4j 5.26 **Enterprise** con licencia de evaluación aceptada por el operador; el sujeto de la RC final
es `864041d`. Producción: **sin tocar**.
