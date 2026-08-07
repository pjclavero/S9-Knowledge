# Bóvedas — esquema de carpetas y automatización desde el panel

Propuesta para revisión del operador. **No implementa nada**: fija el árbol y
las reglas antes de que entren datos, porque reorganizar carpetas con material
dentro es mucho más caro que decidirlo ahora.

Contexto: el almacenamiento anterior (`nextcloud-data`) dejó de funcionar y se
está montando `nextcloud-data-temp`, que arranca vacío. Es el mejor momento
posible para fijar la estructura.

## 1. Cuenta e identidad

Una sola cuenta de Nextcloud: **`Mimir`**, miembro del grupo `mimir`, creada
para el proyecto. **Nunca la cuenta de administración de Nextcloud.**

La distinción que importa no es cuántas cuentas hay, sino qué puede destruir la
credencial que el servidor guarda. Con `Mimir` como dueña de la raíz de bóvedas
y nada más, el peor caso posible afecta a material que sabemos regenerar, jamás
al resto de los documentos del operador.

«Administración» en el panel del proyecto es otra capa distinta: decide **quién
puede pulsar el botón**, no con qué credencial habla el servidor con Nextcloud.
Ambas cosas conviven: el botón, reservado a administración del proyecto; la
credencial almacenada, la de un usuario corriente.

| Uso | Credencial | Permiso |
|---|---|---|
| Ingesta (montaje continuo, desatendido) | contraseña de aplicación de `Mimir` | **solo lectura** |
| Creación de estructura y enlaces (acción puntual desde el panel) | la misma cuenta | escritura limitada a la raíz de bóvedas |
| Borrado y reorganización | ninguna credencial del proyecto | solo el operador, a mano, desde Nextcloud |

El borrado no se resuelve con cuentas sino con permisos del enlace compartido:
Nextcloud permite compartir concediendo lectura y creación **sin** borrado ni
edición. El panel debe crear el enlace ya con esos permisos, para que no dependa
de que alguien se acuerde.

## 2. Árbol propuesto

El operador ya había creado `rol/` con una plantilla organizada por **formato**
(`manuales`, `sesiones`, `transcripciones`, `videos`). Esa propuesta y esta se
organizan por ejes distintos, y hacen falta los dos:

- Por **formato** se navega cómodamente a mano.
- Por **ámbito** se decide la visibilidad, que es lo que el formato no puede
  decir: una transcripción puede ser material de jugadores o una conversación
  privada del narrador, y ser transcripción no distingue una de otra.

No compiten. **El ámbito manda arriba; el formato vive dentro.** Para el sistema
las carpetas de formato son transparentes —el tipo de fichero se deduce de su
extensión— así que existen solo para comodidad del operador y el ingestor las
atraviesa sin que alteren el ámbito.

```
rol/                                  raíz de bóvedas, propiedad de Mimir
├── _plantilla/                       se copia al «añadir juego» — NO se ingiere
└── <juego>/                          ← workspace
    ├── entrada/                      material sin clasificar
    ├── manuales/                     reglas del sistema        ┐ capa compartida
    ├── lore/                         ambientación, PNJ, lugares┘ (partida_id = None)
    ├── partidas/
    │   └── <partida>/                ← partida_id
    │       ├── sesiones/
    │       │   └── sesion-01/        una carpeta por sesión
    │       │       ├── videos/       ┐ carpetas de formato:
    │       │       ├── transcripciones/ │ transparentes para el ámbito
    │       │       └── acta.md       ┘
    │       ├── aportaciones/
    │       │   └── <jugador>/     una por jugador, compartida solo con él (ver 4 bis)
    │       ├── material-jugadores/
    │       ├── notas-narrador/
    │       ├── secretos/
    │       └── personajes/           fichas de PJ
    ├── referencia/                   material externo citable
    └── archivo/                      retirado — no se ingiere nunca
```

Convenciones de nombre, por razones prácticas:

- `sesion-01`, no `sesion 1`. El espacio complica rutas y órdenes de consola, y
  sin cero de relleno la sesión 10 se ordena antes que la 2.
- `_plantilla` con guion bajo: la ancla arriba al ordenar y la deja fuera de la
  ingesta por convención visible, no por una regla escondida.

## 3. Correspondencia carpeta → ámbito

Es la parte que de verdad importa, porque de aquí sale la visibilidad de cada
hecho. Se aplica sobre la ruta **relativa a la raíz de bóvedas**.

| Ruta | `workspace` | `partida_id` | `visibility` inicial |
|---|---|---|---|
| `<juego>/manuales/**` | `<juego>` | `None` (compartido) | `player` |
| `<juego>/lore/**` | `<juego>` | `None` (compartido) | `player` |
| `<juego>/partidas/<p>/aportaciones/<jugador>/**` | `<juego>` | `<p>` | `secret` (lo más restrictivo, hasta revisión) |
| `<juego>/partidas/<p>/material-jugadores/**` | `<juego>` | `<p>` | `player` |
| `<juego>/partidas/<p>/sesiones/**` | `<juego>` | `<p>` | `player` |
| `<juego>/partidas/<p>/notas-narrador/**` | `<juego>` | `<p>` | `narrator` |
| `<juego>/partidas/<p>/secretos/**` | `<juego>` | `<p>` | `secret` |
| `<juego>/partidas/<p>/personajes/**` | `<juego>` | `<p>` | `narrator` |
| `<juego>/referencia/**` | `<juego>` | `None` | `reference` |
| `<juego>/entrada/**` | `<juego>` | `None` | `secret` (lo más restrictivo) |
| `<juego>/archivo/**` | — | — | **no se ingiere** |
| `_plantilla/**` | — | — | **no se ingiere** |
| cualquier otra ruta | — | — | **no se ingiere** |

Las carpetas de formato bajo `sesiones/<sesion>/` (`videos/`,
`transcripciones/`, y las que el operador añada) **no aparecen en esta tabla a
propósito**: heredan el ámbito de la sesión que las contiene y no pueden
modificarlo. Añadir una carpeta de formato nueva nunca cambia la visibilidad de
nada.

Dos reglas de cierre, ambas a prueba de fallos:

1. **Ruta desconocida → no se ingiere.** Nunca «se asume lo razonable». Un
   fichero fuera del esquema es un error de colocación que debe verse, no un
   hecho que entra con visibilidad adivinada.
2. **La carpeta propone, no decide.** La correspondencia fija el valor
   **inicial**; a partir de ahí manda `KnowledgeVisibilityV1` y el motor. Mover
   un fichero de carpeta **nunca amplía** la visibilidad de un hecho ya
   registrado — eso exige un `EXPLICIT_VISIBILITY_OVERRIDE` auditado, igual que
   `local_override_of`.

La carpeta no otorga conocimiento a nadie: `known_by` solo se puebla por las
fuentes válidas ya decididas (concesión manual, revelación explícita,
participación explícita en escena, comunicación directa, importación aprobada).

## 4. «Añadir este juego» desde el panel

Flujo propuesto, con las restricciones que impone el diseño actual:

1. El administrador del proyecto introduce el nombre del juego.
2. El panel **valida el nombre** antes de tocar nada: sin `/`, sin `..`, sin
   rutas absolutas, longitud acotada, y comprueba que la carpeta no existe ya.
3. Crea `rol/<juego>/` copiando `_plantilla/`, mediante la **API de Nextcloud**
   con la credencial de `Mimir`. El montaje de ingesta sigue siendo de solo
   lectura y no participa: así un fallo nuestro en la ingesta no puede escribir
   jamás.
4. Crea el enlace de compartición con permiso de **lectura y creación, sin
   borrado ni edición**.
5. Registra el `workspace` correspondiente y deja constancia en auditoría de
   quién lo creó y cuándo.

Restricciones que no se negocian:

- El creador de estructura solo puede escribir **bajo la raíz de bóvedas**, y
  solo crear carpetas. Nunca borrar, nunca sobrescribir.
- La operación es **idempotente**: repetirla no duplica ni pisa nada.
- Si falla a mitad, deja el estado a la vista; no intenta «arreglarlo» borrando.

## 4 bis. Aportaciones de los jugadores y procedencia

Nextcloud desplegado: **33.0.0**.

**Comprobado contra la instancia real, y desmiente lo que se suponía**: el buzón
de archivos («file drop», solo creación sin lectura) **no está disponible en
compartidos internos**, solo en enlaces públicos. Al crear un compartido interno
con `permissions=4`, Nextcloud lo eleva por su cuenta a `5` —lectura más
creación— y rechaza con `400 Failed to update share` cualquier intento de
bajarlo. Un compartido interno **siempre** concede lectura.

Decisión resultante: **una subcarpeta por jugador**, compartida individualmente.

```
partidas/<partida>/aportaciones/
├── <jugador-1>/     compartido solo con <jugador-1>
└── <jugador-2>/     compartido solo con <jugador-2>
```

Cada jugador lee y escribe en la suya, y no ve las de los demás porque no están
compartidas con él. El aislamiento lo da la estructura, no el permiso, que era
lo que Nextcloud no nos podía garantizar.

| Opción | Atribución | Riesgo |
|---|---|---|
| Enlace público | **Ninguna fiable.** La subida se registra a nombre del dueño de la carpeta; el apodo que se pide al subir lo escribe el propio usuario | URL reenviable |
| Compartido interno de `aportaciones/` entera | Fiable | Cada jugador leería lo aportado por los demás |
| **Subcarpeta por jugador, compartido interno** | **Fiable** (usuario autenticado) | Ninguno de los anteriores |

Permisos efectivos concedidos: `5` = **lectura + creación**. No incluye edición
(`2`), borrado (`8`) ni recompartir (`16`), así que un jugador puede depositar
material y consultar lo suyo, pero **no puede modificarlo ni borrarlo** una vez
subido, ni dar acceso a terceros. El borrado sigue siendo exclusivo del
operador.

Sigue en pie la regla de no compartir nunca por encima de este nivel: ni la
carpeta de la partida ni la del juego, porque `notas-narrador/` y `secretos/`
cuelgan de ahí y el compartido de Nextcloud no pasa por el motor de visibilidad.

Consecuencia operativa: ante nombres repetidos Nextcloud renombra el segundo
fichero en lugar de sobrescribirlo, que es el comportamiento deseado.

**Regla de fondo: la procedencia no concede conocimiento.** Ni siquiera con
usuarios autenticados. Que un jugador aporte la transcripción de una sesión no
significa que su personaje sepa lo que contiene, ni deja de saberlo si la aportó
otro. Es el mismo razonamiento que ya se aplicó a la presencia en episodio: la
subida produce como mucho un `KNOWLEDGE_GRANT_CANDIDATE`, nunca una concesión
efectiva. `known_by` se puebla solo por las fuentes válidas ya fijadas.

La atribución se conserva porque sirve para trazabilidad —saber a quién
preguntar si algo está mal— no para decidir visibilidad. Compartir en Nextcloud
y visibilidad en el motor son capas independientes, y añadir o quitar gente del
grupo no altera ningún hecho ya registrado.

## 5. Requisito de reingesta — bloqueante para M1

Reprocesar material ya revisado es **deseable**: con más contexto alrededor
aparecen relaciones que antes no eran deducibles. Pero hay que separar dos cosas
que suenan parecidas:

- **Re-extraer** — bien. Volver a mirar el material con más datos alrededor.
- **Volver a preguntar lo ya decidido** — inaceptable. Si un hecho ya se aprobó
  o rechazó, esa decisión debe sobrevivir a la reingesta. Si no, cada lote nuevo
  devuelve a la cola lo ya despachado y la revisión humana se vuelve
  insostenible.

Condición técnica: identificar el **contenido por su hash** y los **hechos por
su identidad semántica**. Nunca por `fileid`, `etag`, ruta ni fecha de
Nextcloud, que cambian al mover un fichero o al migrar de almacenamiento — y
acabamos de migrar de almacenamiento, así que esto no es hipotético.

**Puerta de M1**: existe una prueba que ingiere el mismo material dos veces y
exige que **cero** decisiones ya tomadas regresen a la cola de revisión, que las
relaciones nuevas aparezcan, y que no se dupliquen las viejas. Sin esa prueba en
verde no hay primera ingesta.

Nota de coste: si el carril externo está activo, la reingesta paga tokens otra
vez. Debe medirse antes de habilitar reprocesado automático.

## 6. Pendiente del operador

- ~~Contraseña de aplicación nueva para `Mimir`.~~ **Resuelto (2026-08-07)**: la
  anterior no sobrevivió a la reconstrucción de Nextcloud y devolvía `401
  Unauthorized` — esa era además la causa real del bucle de reintentos del
  montaje, no el almacenamiento caído. Renovada por el operador; el remoto
  vuelve a listar. `rclone.conf` queda en `600` (su ofuscación es reversible, no
  es cifrado).
- Revisar el árbol de la sección 2 frente a la plantilla ya creada, y ajustar
  esta última si se acepta: añadir el nivel `partidas/<partida>/`, renombrar
  `sesion 1` → `sesion-01` y `plantilla` → `_plantilla`.
- Confirmar los nombres definitivos de juego y partida (`<juego>` y `<p>` pasan
  a ser identificadores de ámbito; renombrarlos después es una migración).
- Decidir cuándo se reactiva el montaje (`systemctl enable --now`). Sigue parado
  y deshabilitado a propósito.
