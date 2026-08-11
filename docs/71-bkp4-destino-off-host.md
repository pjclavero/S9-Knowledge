# 71 · BKP-4 — Diseño del destino off-host

**Estado: DISEÑO. NADA DE ESTO ESTÁ INSTALADO NI ACTIVO.**
No crea repositorios de copia, no toca producción, no modifica unidades ni
timers, no genera ni usa credenciales. Es un documento de diseño sometido a las
puertas de la sección 8; cada puerta requiere **autorización humana explícita**.

Base canónica: `main` = `e9c66dc`.

---

## 0. El agujero que este carril cierra

| Carril | Estado real | Qué demuestra |
|---|---|---|
| BKP-1 | CONFORME | Restore **real** sobre VM105. RTO-restore medido: **8,2 min**. |
| BKP-2 | Preparado, **sin activar** | Generación automática de copias. |
| BKP-3 | CONFORME | Watchdog de frescura, 26 pruebas. Distingue `SIN_COPIA` de copia rancia; VMID **declarados**, no descubiertos; usa `mtime`, no el sello del nombre; storage inaccesible → `CRITICAL`. |
| BKP-5 | Preparado, **sin activar** | — |
| **BKP-4** | **INEXISTENTE** | **Hoy no hay ninguna copia fuera del chasis.** |

La consecuencia es literal: si el chasis se pierde entero —incendio, fallo de
PSU que se lleva discos por delante (hay antecedente documentado de fallos
correlacionados en el ASM1064 tras cambiar la fuente), robo, borrado
accidental que se replica— **lo que sobrevive hoy es nada**. Todas las copias
existentes viven en los mismos discos, en el mismo armario, alimentados por la
misma fuente.

Dos incidentes previos condicionan todo el diseño y aparecen citados donde
corresponde:

- **El LXC 100 colgado bloqueó la cadena de copias durante SEIS DÍAS** sin que
  nada avisara. Un trabajo colgado no es un trabajo fallido: no emite fallo, no
  dispara `OnFailure=`, simplemente ocupa el turno. → sección 3.
- **Un control positivo que se cuelga puede tumbar el canal de gestión**
  (ocurrió con el agente QEMU de VM109). Toda prueba de fallo inyectado debe
  ser *rápida y acotada*, no solo aislada. → secciones 5 y 7.

---

## 1. Qué se copia, RPO, y los dos RTO

### 1.1 Conjuntos de datos

| # | Conjunto | Origen | Tamaño orden | Método | Por qué |
|---|---|---|---|---|---|
| D1 | `auth.db` | SQLite en VM105 | ~cientos KiB | `sqlite3 .backup` | Nunca `cp` de un fichero abierto: captura escrituras a medias, y arrastrar `-wal`/`-shm` *rejuvenece* artificialmente una copia rancia. |
| D2 | `jobs.db`, `reviews.db`, `glossary.db` | SQLite en VM105 | ~cientos KiB | `sqlite3 .backup` | Ídem. |
| D3 | Grafo Neo4j | `neo4j-knowledge` | ~3 MB datos / ~14 KB export comprimido | **Exportación lógica** en solo lectura vía `cypher-shell` | `neo4j-admin database backup` en caliente es Enterprise; APOC no está instalado; `database dump` exige la base **detenida**. Parar el servicio no está autorizado. |
| D4 | Configuración de servicio | `viewer.env`, compose, nginx | KiB | Copia con **valores redactados** | Se conservan nombres de clave para reconstruir; nunca valores. Los secretos se restauran desde el secret store (sección 4), no desde el backup. |
| D5 | Unidades systemd | `systemctl cat` | KiB | Texto | Sin ellas no hay servicio, solo datos. |
| D6 | Manifiesto + metadatos de release | Generado | KiB | `MANIFEST.sha256`, commit, tag, versiones | Es lo que convierte un directorio en una copia *identificable y verificable*. |
| D7 | Medios de origen (audio/vídeo/manuscritos ya ingeridos) | Almacén de medios | GB | **Fuera de RPO corto**, ver 1.3 | Volumen grande, reproducible desde la fuente original en la mayoría de casos. |

Lo que **no** se copia, y es una decisión, no un olvido: imágenes de
contenedor (se reconstruyen desde GHCR/repo), artefactos derivados
recomputables, y cualquier secreto en claro.

### 1.2 RPO objetivo

| Conjunto | RPO objetivo off-host | Justificación |
|---|---|---|
| D1–D6 | **24 h** | El volumen es de megabytes; el coste de una copia diaria off-host es despreciable. El límite no es técnico sino de ventana de consistencia. |
| D7 | **7 días** | Recuperable desde origen; su pérdida cuesta tiempo de reingesta, no información. |

**Objetivo declarado**: pérdida máxima aceptable de 24 h de escrituras del
grafo y de auth. Esto es un objetivo *de diseño*; no está cumplido hoy y no lo
estará hasta la Fase 3 de la sección 8.

### 1.3 RTO-restore ≠ RTO-hasta-servicio

Esta distinción es la que separa un número bonito de una expectativa honesta.

| Métrica | Definición | Valor |
|---|---|---|
| **RTO-restore** | Desde que existe un host preparado con la copia ya disponible localmente hasta que los datos están restaurados y verificados. | **8,2 min medidos** (BKP-1, sobre VM105). |
| **RTO-recuperación-de-copia** | Desde el desastre hasta tener la copia descifrada y disponible en el host de recuperación. Incluye: obtener la clave, alcanzar el destino remoto, descargar, descifrar, verificar el manifiesto. | **No medido.** Estimación de diseño: 15–60 min según ancho de banda y si la clave está a mano. Se mide en la puerta P5. |
| **RTO-hasta-servicio** | Desde el desastre hasta que el servicio responde a usuarios: aprovisionar host, desplegar release, restaurar datos, reinyectar secretos, reconfigurar red/DNS, validar. | **No medido.** Estimación de diseño: **4–8 h** en el caso «chasis perdido, hardware nuevo». Se mide en la puerta P6. |

Publicar «RTO 8,2 minutos» a secas sería engañoso: es el tramo más corto y más
fácil de los tres. En un escenario de pérdida total del chasis, el término
dominante no son los datos, es el **aprovisionamiento del host y los
secretos**.

---

## 2. El destino: fuera del chasis, de verdad

### 2.1 Criterios de admisibilidad de un destino

Un destino cuenta como off-host solo si cumple **todos**:

| C | Criterio | Motivo |
|---|---|---|
| C1 | Distinto **dominio de fallo eléctrico** (otra PSU, otro circuito, idealmente otro edificio). | El antecedente ASM1064 apunta a la PSU como causa común. |
| C2 | Distinto **chasis físico**. | Incendio, robo, inundación. |
| C3 | **Escritura sin permiso de borrado** desde el origen (append-only / retención inmutable), o al menos credenciales de escritura distintas de las de purga. | Un origen comprometido o un script con un bug no puede destruir el histórico. Un ransomware que llega a producción no debe alcanzar las copias. |
| C4 | **Pull o push, pero nunca con la clave de cifrado en el destino.** | El destino no debe poder leer lo que guarda. |
| C5 | Accesible sin depender de ningún servicio del propio chasis (ni DNS interno, ni proxy, ni Tailscale del propio host caído). | Un destino al que solo se llega a través de lo que se ha perdido no es un destino. |
| C6 | Verificable de forma remota y barata (listado + hash sin descargar todo). | La verificación diaria no puede costar el ancho de banda de una restauración. |

### 2.2 Topología propuesta — regla 3-2-1 explícita

```
                 ORIGEN (VM105, dentro del chasis)
                        │  copia local consistente  (BKP-2, ya diseñado)
                        ▼
              [T0] copia local en el chasis          ← existe hoy (sin activar)
                        │
        ┌───────────────┴────────────────┐
        │ replicación independiente      │  (dos trabajos SEPARADOS, sección 3)
        ▼                                ▼
  [T1] destino off-site primario   [T2] destino frío / offline
   (repo cifrado remoto,            (medio extraíble rotado,
    append-only, otro edificio)      guardado fuera del edificio)
```

- **3 copias**: T0 + T1 + T2.
- **2 medios distintos**: almacenamiento en línea (T1) y medio extraíble (T2).
- **1 fuera del sitio**: T1 obligatoriamente; T2 refuerza con una copia
  *desconectada*, inmune por construcción a cualquier fallo lógico o
  credencial comprometida.

**Respuesta al escenario «se pierde el chasis entero»**: sobreviven T1 y T2.
El objetivo de la Fase 3 es que la respuesta deje de ser «nada» y pase a ser
«T1 con RPO ≤ 24 h, T2 con RPO ≤ 7 días».

### 2.3 Alternativas de destino, y por qué se elige lo que se elige

| Opción | A favor | En contra | Dictamen |
|---|---|---|---|
| **A. Repo Restic sobre SFTP a host remoto con chroot** | Ya hay precedente operativo en el ecosistema (BACKUP-P0 de s9-ai-arena usa exactamente esto); cifrado de cliente por diseño; deduplicación; `check --read-data-subset` barato. | Requiere un host remoto que alguien mantenga; `append-only` exige configuración deliberada del servidor. | **ELEGIDA para T1.** Coherencia con lo ya probado en el ecosistema pesa más que la novedad. |
| B. Object storage S3-compatible con Object Lock | Inmutabilidad real por retención; sin host que mantener. | Dependencia de proveedor y de factura; credenciales en la nube; coste recurrente; salida de datos con coste. | **Descartada de inicio, reevaluable.** Es la mejor opción si aparece presupuesto; se deja como plan B documentado porque el diseño es idéntico salvo el backend. |
| C. Sincronización a Nextcloud propio | Ya existe en el homelab. | **Está en el mismo chasis**: no cumple C1 ni C2. Y ya hubo un acoplamiento que arrastró un servicio a un bucle de reintentos cuando el almacenamiento externo cayó. | **Descartada.** No es off-host. |
| D. Otro disco / otro NAS del mismo armario | Trivial de montar. | Falla C1 y C2 a la vez. Es exactamente lo que ya tenemos. | **Descartada.** |
| E. Solo medio extraíble manual | Barato, offline de verdad. | Depende de que una persona se acuerde. El modo de fallo dominante de este proyecto es precisamente *nadie miró*. | **Descartada como única defensa; aceptada como T2** complementario y con su propia alerta de antigüedad. |
| F. rsync en claro a host remoto | Simple. | Sin cifrado en reposo en destino; sin inmutabilidad; un `rsync --delete` mal invocado propaga el borrado. | **Descartada.** |

> **Requiere decisión del operador**: qué host concreto hace de T1 y qué medio
> concreto hace de T2. El diseño no los nombra ni los presupone; la Fase 1
> (sección 8) es justamente esa elección.

---

## 3. Independencia de trabajos — el fallo de los seis días

**Hecho, no hipótesis**: un LXC (100) se colgó y bloqueó toda la cadena de
copias posteriores durante seis días, en silencio. Cualquier diseño que
encadene trabajos repite ese incidente.

### 3.1 Invariantes de independencia

| I | Invariante | Mecanismo |
|---|---|---|
| I1 | **Ningún objetivo depende del resultado de otro objetivo.** | Un trabajo (unidad systemd) *por objetivo* (por VMID / por conjunto de datos), no una unidad que itera sobre una lista. Instanciadas: `s9k-backup@<objetivo>.service`. |
| I2 | **Ningún trabajo puede exceder su presupuesto de tiempo.** | `RuntimeMaxSec=` en cada unidad + `timeout(1)` interno por *etapa*. El timeout externo es la red de seguridad del interno, no su sustituto. |
| I3 | **Un trabajo colgado se mata, y matarlo emite una señal distinta de «falló».** | `TimeoutStopSec=` + `KillMode=mixed`. Estado terminal `TIMEOUT`, no `FAILED`: son diagnósticos distintos y el operador debe poder distinguirlos. |
| I4 | **La lista de objetivos se declara, no se descubre.** | Igual criterio que BKP-3 con los VMID: un objetivo que desaparece del descubrimiento se vuelve invisible en lugar de alarmar. Un objetivo declarado que no produce copia **alarma**. |
| I5 | **El solapamiento se evita por objetivo, no globalmente.** | `flock` sobre un lock *por objetivo*. Un lock global reintroduce el acoplamiento que I1 elimina. |
| I6 | **La replicación off-host no puede invalidar la copia local.** | T0 se publica atómicamente y se declara válido *antes* de intentar T1/T2. Que el destino remoto esté caído no debe convertir una copia local buena en un fallo. |
| I7 | **El agregador de estado tolera trabajos ausentes.** | Un objetivo sin reporte se computa como `SIN_DATO` → alerta, nunca como «bien». |

### 3.2 Presupuestos de tiempo propuestos

| Etapa | Timeout duro | Racional |
|---|---|---|
| Preflight (espacio, alcanzabilidad, lock) | 60 s | Si no responde rápido, está colgado. |
| Snapshot SQLite (por fichero) | 120 s | Megabytes. |
| Exportación lógica Neo4j | 600 s | Depende del tamaño del grafo; margen ×10 sobre lo observado. |
| Publicación atómica + manifiesto | 120 s | |
| Replicación a T1 | 3600 s | Red doméstica, primer envío completo aparte (ver Fase 3). |
| Verificación remota barata | 300 s | |
| **`RuntimeMaxSec` de la unidad** | **5400 s** | Estrictamente mayor que la suma de las etapas, para que el fallo lo reporte la etapa (diagnóstico fino) y la unidad sea solo la red. |

El diseño de la ventana: **cada objetivo tiene su propia ventana de disparo**;
si un objetivo agota su presupuesto, los demás ya están corriendo o ya han
terminado. Seis días de silencio dejan de ser representables porque ningún
trabajo espera a otro.

---

## 4. Cifrado y gestión de clave

### 4.1 En tránsito y en reposo

| Tramo | Protección |
|---|---|
| Origen → T1 | SSH/SFTP con clave de host verificada (`known_hosts` fijado, sin `StrictHostKeyChecking=no`). |
| En reposo en T1 | **Cifrado del lado del cliente**: el destino recibe bloques ya cifrados y jamás ve la clave. Esto es lo que permite usar un destino que no controlamos del todo. |
| En reposo en T2 | El mismo repositorio cifrado, volcado a medio extraíble. El medio extraíble puede perderse; cifrado, la pérdida es un incidente menor. |
| Copia local T0 | Cifrada también, con la misma clave. Una copia local en claro es una segunda superficie de exposición dentro del chasis ya comprometido. |

### 4.2 Dónde vive la clave

**Perder la clave equivale a no tener copia.** Por tanto la clave necesita su
propio esquema de supervivencia, y ese esquema no puede vivir dentro de lo que
la clave protege.

| Copia de la clave | Ubicación | Forma |
|---|---|---|
| K1 (operativa) | Secret store del host de origen, fichero `0600`, propietario `root` | Usada por los trabajos automáticos. |
| K2 (custodia) | Gestor de contraseñas del operador, fuera del chasis | Recuperación humana. |
| K3 (fría) | Impresa o en medio extraíble, guardada físicamente **fuera del edificio**, separada de T2 | Último recurso. **Nunca junto al medio que cifra.** |

Requisitos adicionales:

- La clave **no se deriva** de nada del sistema (ni hostname, ni MAC, ni
  contraseña reutilizada): material aleatorio dedicado.
- **Rotación**: la rotación de clave de un repositorio cifrado no re-cifra el
  histórico; se planifica como creación de repositorio nuevo + retención del
  antiguo hasta que caduca. Está fuera del alcance de la Fase 3 y se documenta
  como deuda explícita (sección 9).
- Antecedente vigente: hay una **credencial de Neo4j de VM105 expuesta en
  transcripciones locales** pendiente de rotación. La clave de backup no debe
  gestionarse con la misma laxitud; su ciclo de vida arranca limpio.

### 4.3 Secretos: orden obligatorio de entrega

Regla del operador, sin excepciones — **ningún secreto en `argv`, nunca**:

1. **Secret store** (preferente).
2. **Fichero `0600`** propiedad del usuario del servicio, referenciado por
   ruta (p. ej. la variante `*-file` de la opción, o `LoadCredential=` de
   systemd).
3. **stdin** (el proceso lo lee de una tubería).
4. **Variable de entorno efímera**, solo durante la ejecución, nunca exportada
   a hijos innecesarios ni volcada en logs.

Prohibido explícitamente: pasar la clave como argumento (visible en `ps`,
en el journal de systemd y en cualquier traza de error), volcar entornos en
logs de diagnóstico, e incluir la clave en el manifiesto o en la copia de
configuración (D4 va **redactado**).

---

## 5. Verificación de restore: copia-existe ≠ copia-restaura

### 5.1 Los dos sellos, separados

Se mantienen **dos** marcas de estado independientes, y confundirlas es
exactamente el error que este carril existe para evitar:

| Sello | Significado | Quién lo escribe | Umbrales propuestos |
|---|---|---|---|
| `last_backup_success` | Se generó y publicó una copia con manifiesto válido. | Trabajo de copia | `WARN` > 26 h, `CRITICAL` > 48 h |
| `last_offsite_success` | Esa copia está **replicada y verificada** en T1. | Trabajo de replicación | `WARN` > 30 h, `CRITICAL` > 72 h |
| `last_restore_verified` | Una copia se **restauró de verdad** en aislamiento y los datos cuadraron. | Trabajo de verificación de restore | `WARN` > 8 días, `CRITICAL` > 15 días |

Una copia que existe no es una copia que restaura. `last_backup_success`
verde con `last_restore_verified` rojo es un estado perfectamente posible y
debe alarmar por sí solo.

### 5.2 Niveles de verificación

| Nivel | Frecuencia | Qué hace | Coste |
|---|---|---|---|
| V0 — Existencia y frescura | Cada hora | `mtime` real del objeto más reciente en T1 (no el sello del nombre — criterio ya adoptado en BKP-3). Destino inalcanzable → `CRITICAL`, nunca «sin novedad». | Trivial |
| V1 — Integridad estructural | Diaria | Verificación de metadatos/índice del repositorio remoto y del `MANIFEST.sha256`. | Bajo |
| V2 — Integridad de datos por muestreo | Semanal | Lectura y rehash de un subconjunto aleatorio de bloques. Detecta bit rot y truncados que V1 no ve. | Medio |
| V3 — **Restore real en aislamiento** | Semanal | Descarga → descifra → restaura en directorio/instancia efímera → comprueba **invariantes semánticas**, no solo que el fichero abra. | Alto |
| V4 — Ensayo de recuperación completa | Trimestral, **manual y autorizado** | Host limpio, secretos reinyectados, servicio arriba. Mide `RTO-hasta-servicio`. | Muy alto |

**Invariantes de V3** (lo que se comprueba tras restaurar, y sin lo cual «restauró» no significa nada):

- `auth.db`: `PRAGMA integrity_check = ok`; `user_version` esperado; número de
  usuarios ≥ 1 y coincidente con el conteo registrado en el manifiesto.
- `jobs.db` / `reviews.db` / `glossary.db`: `integrity_check = ok` y tablas presentes.
- Grafo: conteos de nodos y relaciones **iguales** a los del manifiesto, no
  «parecidos»; etiquetas e índices declarados presentes; ausencia de
  restricciones si el manifiesto declaraba ninguna.
- El manifiesto verifica **todos** los ficheros, y el conjunto de ficheros
  restaurados es exactamente el declarado: ni uno de más, ni uno de menos.

**Nunca contra rutas productivas.** V3 escribe únicamente en un directorio
efímero propio; V4 exige un host que no sea VM105.

### 5.3 Restricción heredada del incidente de VM109

Los trabajos de verificación —y muy en particular los de fallo inyectado de la
sección 7— **deben ser rápidos y acotados**. Un control positivo que se cuelga
puede tumbar el canal de gestión; ya pasó. Por eso: timeout propio en cada
verificación, ejecución fuera del canal de gestión del hipervisor, y ninguna
prueba que requiera intervención sobre una VM viva sin autorización.

---

## 6. Señales y detección del silencio

**El fallo peligroso es el que no avisa.** Tres semanas sin copia con el
healthcheck en `failed` cada hora, y nadie mirando: ese es el precedente real.

### 6.1 Señales emitidas

| Señal | Emisor | Contenido |
|---|---|---|
| `backup.result` | cada trabajo, por objetivo | `OK` / `FAILED` / `TIMEOUT` / `SKIPPED`, duración, bytes, id de copia |
| `offsite.result` | trabajo de replicación | ídem + destino |
| `restore.verify.result` | verificación V3 | ídem + invariantes comprobadas |
| `heartbeat` | el propio agregador | «sigo vivo», independiente de los resultados |
| Estado agregado | agregador | `OK` / `WARN` / `CRITICAL` / **`SIN_DATO`** |

`SIN_DATO` es una clase de primera categoría, no un caso raro: es el estado del
incidente de los seis días.

### 6.2 Cómo se detecta el silencio

El problema estructural: **nada de lo anterior sirve si nadie mira el estado**,
y un timer desactivado no emite fallo — deja de emitir, sin más.

Tres capas, cada una capaz de detectar el fallo de la anterior:

1. **Antigüedad de sellos** — el watchdog de frescura (BKP-3, ya CONFORME)
   evalúa los tres sellos de 5.1. No depende de los timers de backup, que es
   justo el punto.
2. **Dead man's switch** — el agregador emite un latido *saliente* a un
   observador **fuera del chasis** con un plazo. Si el latido no llega, es el
   observador remoto quien alarma. Invierte la carga: el silencio deja de ser
   la ausencia de una alerta y pasa a ser, él mismo, la alerta. Esta capa es la
   única que sobrevive a «se perdió el chasis entero».
3. **Resumen empujado al operador** — un informe periódico que llega solo,
   con las tres frescuras. Un estado que hay que ir a consultar es un estado
   que no se consulta.

> **Requiere decisión del operador**: qué canal recibe el latido y el resumen.
> El diseño exige que ese canal **no viva en el chasis**; el resto es elección.

### 6.3 Anti-fatiga

Alertar de todo equivale a no alertar. Deduplicación por objetivo+condición,
escalado `WARN` → `CRITICAL` por persistencia, y silenciamiento explícito con
caducidad obligatoria (un silenciamiento sin fecha de fin reproduce el
incidente original).

---

## 7. Calibración: cómo se pone ROJA cada garantía

> «Una afirmación no constituye evidencia porque exista un test verde. La
> evidencia aparece cuando: sabes qué comportamiento afirma; calibras el
> mecanismo que lo mide; introduces una violación; el sistema se pone rojo;
> reviertes; vuelve a verde.»

Sin esta tabla, todo lo anterior son promesas. Cada fila es un ciclo completo
**violación → ROJO → reversión → VERDE**. Todas las pruebas se ejecutan en
entorno de pruebas, **jamás contra producción**, y todas llevan su propio
timeout (sección 5.3).

| # | Garantía afirmada | Violación inyectada | Debe ponerse ROJO en | Reversión |
|---|---|---|---|---|
| G1 | Existe copia off-host más reciente que 24 h | Congelar el reloj de replicación / retirar la copia más reciente de T1 | V0, con `CRITICAL` a >72 h y `WARN` a >30 h | Restituir la copia |
| G2 | El destino inalcanzable no se confunde con «todo bien» | Cortar la ruta al destino (regla de red en el banco de pruebas) | V0 → `CRITICAL`, **nunca** `OK` ni silencio | Restaurar ruta |
| G3 | Un trabajo colgado no bloquea a los demás | Objetivo cebo que hace `sleep` indefinido | Ese objetivo → `TIMEOUT`; **los demás objetivos terminan `OK` en su ventana** | Retirar el cebo |
| G4 | Un trabajo colgado se distingue de uno fallido | Cebo que cuelga vs. cebo que retorna ≠0 | Estados terminales **distintos** (`TIMEOUT` vs `FAILED`), y alertas con texto distinto | Retirar cebos |
| G5 | Un objetivo declarado que desaparece alarma | Eliminar un objetivo de la ejecución dejándolo en la lista declarada | `SIN_DATO` → alerta | Restituir |
| G6 | La copia se publica atómicamente | Matar el proceso a mitad de la construcción | Ningún directorio publicado; `last_backup_success` **no** avanza; nada que parezca válido | Ejecución completa |
| G7 | Corrupción en reposo se detecta | Alterar un byte de un bloque en el repositorio de pruebas | V2 (muestreo con rehash) → `CRITICAL`; **calibrar antes** que V1 sola NO lo detecta (si V1 lo detectase, el muestreo sería redundante y habría que revisar el diseño) | Restaurar el bloque |
| G8 | La restauración se verifica de verdad | Sustituir el export del grafo por uno con **un nodo menos** | V3 falla por conteo ≠ manifiesto | Restaurar export |
| G9 | `last_restore_verified` es independiente de `last_backup_success` | Desactivar solo la verificación V3, dejando la copia corriendo | `backup` verde y `restore_verified` **rojo a los 15 días**, simultáneamente | Reactivar V3 |
| G10 | Ningún secreto aparece en `argv` ni en logs | Prueba que inspecciona `ps`/journal durante una ejecución con clave conocida-cebo, y prueba estática que busca el patrón «clave como argumento» | ROJO si la cadena cebo aparece en `ps`, en el journal o en el manifiesto | — |
| G11 | El destino no puede leer los datos | Intentar listar/abrir el contenido remoto sin la clave | Debe **fallar**; si tiene éxito, el cifrado de cliente no está activo | — |
| G12 | Sin clave no hay restauración (y con clave sí) | Restaurar con clave equivocada | Falla limpio y con mensaje claro; con la clave correcta, V3 verde | — |
| G13 | El origen no puede destruir el histórico | Intentar borrar/purgar en T1 con la credencial del origen | La operación **debe ser rechazada** (append-only). Si tiene éxito, C3 no se cumple. | — |
| G14 | El silencio se detecta | Detener el agregador entero | El observador **externo** alarma por latido ausente dentro del plazo | Reactivar |
| G15 | El fallo de T1 no invalida T0 | Destino remoto caído durante una ejecución completa | `backup.result = OK`, `offsite.result = FAILED`: dos señales distintas, la copia local sigue siendo válida | Levantar destino |
| G16 | La retención nunca deja cero copias | Cuotas a cero | Se conserva siempre la más reciente (lógica ya probada con 9 tests en `deploy/tests/test_backup_retencion_propuesta.py`); extenderla a T1 | — |
| G17 | El manifiesto detecta ficheros de más o de menos | Añadir un fichero no declarado; y borrar uno declarado | V1 falla en **ambos** sentidos | — |

Regla de aceptación de la tabla: una fila solo cuenta como calibrada cuando se
ha observado la secuencia completa **verde → violación → rojo → reversión →
verde**. Una fila que nunca se ha visto roja no es una prueba, es una
decoración.

---

## 8. Puesta en marcha por fases y puertas

Cada puerta es una **autorización humana explícita**. Ningún agente modifica
producción sin aprobación previa; el diagnóstico es siempre de solo lectura.

| Fase | Qué se hace | Toca producción | Puerta de salida |
|---|---|---|---|
| **F0 — Diseño** (este documento) | Documento, tabla de calibración, alternativas descartadas | No | **P0**: operador acepta el diseño. |
| **F1 — Elección de destino** | Decidir host/medio para T1 y T2; verificar C1–C6 sobre los candidatos; estimar ancho de banda y coste | No | **P1**: el operador designa T1 y T2 y **autoriza crear el repositorio** de copia. Sin P1 no existe ningún repositorio real. |
| **F2 — Banco de pruebas** | Réplica del pipeline con datos sintéticos; implementar G1–G17; recorrer los 17 ciclos rojo/verde | No | **P2**: 17/17 calibradas con evidencia de rojo. Especialista APTO + Supervisor CONFORME. |
| **F3 — Primer envío off-host** | Copia inicial completa a T1, en ventana acordada; medir duración real y consumo | **Sí, lectura de producción + escritura solo en T1** | **P3**: autorización explícita, ventana acordada, alcance limitado a lectura + escritura en destino. Nada de reinicios, paradas, migraciones ni escrituras en Neo4j. |
| **F4 — Automatización** | Instalar unidades por objetivo con sus timeouts; sellos y señales; **timers aún desactivados** | Instala, no activa | **P4**: revisión de unidades y presupuestos de tiempo. |
| **F5 — Activación observada** | Activar timers; observar ≥ 7 días; medir `RTO-recuperación-de-copia` | Sí | **P5**: autorización de activación. Criterio de salida: 7 días sin `SIN_DATO` y G1/G2/G3 verdes en producción. |
| **F6 — Ensayo completo** | V4: recuperación de extremo a extremo en host limpio; medir `RTO-hasta-servicio` real | Host aparte | **P6**: autorización del ensayo. Cierra BKP-4 con el número honesto, no con el de 8,2 min. |
| **F7 — T2 frío** | Rotación del medio extraíble + alerta de antigüedad propia | Manual | **P7**: procedimiento de custodia aprobado (medio y clave K3 **separados**). |

### Qué exige autorización del operador, en una lista

1. Designar T1 y T2 (P1).
2. Crear cualquier repositorio de copia real (P1).
3. Generar y custodiar la clave; decidir dónde vive K2 y K3 (P1).
4. Leer producción para el primer envío, y su ventana (P3).
5. Instalar unidades systemd (P4).
6. **Activar cualquier timer** (P5).
7. Ensayo de recuperación completa (P6).
8. Elegir el canal de alertas y el observador externo del dead man's switch (§6.2).

Nada de esto lo decide un agente.

---

## 9. Riesgos abiertos y deuda declarada

| R | Riesgo | Estado |
|---|---|---|
| R1 | **Hoy no existe copia off-host.** Todo lo anterior es diseño; el riesgo sigue abierto en su totalidad hasta P5. | ABIERTO |
| R2 | `RTO-hasta-servicio` no está medido; la estimación 4–8 h no es evidencia. | ABIERTO hasta P6 |
| R3 | La rotación de clave de un repositorio cifrado no re-cifra el histórico; el procedimiento no está diseñado. | DEUDA declarada |
| R4 | La credencial de Neo4j de VM105 expuesta en transcripciones sigue pendiente de rotación; es un vector previo al backup. | ABIERTO, fuera de BKP-4 |
| R5 | El grafo se copia por **exportación lógica** porque Neo4j Community no permite backup en caliente. Si el grafo crece un orden de magnitud, el presupuesto de 600 s y la propia técnica deben revisarse. | VIGILAR |
| R6 | T2 depende de una acción humana periódica; su alerta de antigüedad es imprescindible, no opcional. | Mitigado por diseño, sin probar |
| R7 | Coste y ancho de banda de T1 no estimados hasta F1. | ABIERTO |
| R8 | Un destino append-only mal configurado *parece* funcionar: solo G13 lo distingue. | Cubierto por G13, sin ejecutar |
| R9 | El observador externo del dead man's switch introduce una dependencia nueva; si es él quien calla, nadie lo nota. Necesita su propia comprobación. | ABIERTO, a resolver en F2 |

---

## 10. Resumen ejecutable

- **Hoy sobrevive: nada.** Objetivo de BKP-4: T1 con RPO ≤ 24 h y T2 con RPO ≤ 7 días.
- **8,2 min es RTO-restore, no RTO-hasta-servicio.** Confundirlos es la mentira más fácil de este dominio.
- **Un trabajo por objetivo, con timeout propio.** Seis días de silencio dejan de ser representables.
- **Cifrado de cliente; la clave en tres sitios, uno de ellos fuera del edificio.** Y nunca en `argv`.
- **Tres sellos, no uno**: existe ≠ está fuera ≠ restaura.
- **17 garantías, 17 formas de ponerlas rojas.** Lo que no se puede poner rojo no está probado.
- **Ocho puertas humanas.** Ninguna la cruza un agente por su cuenta.
