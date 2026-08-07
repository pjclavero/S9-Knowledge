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

```
rol/                                  raíz de bóvedas, propiedad de Mimir
├── _plantilla/                       árbol vacío que se copia al «añadir juego»
└── <juego>/                          ← workspace
    ├── 00-entrada/                   material sin clasificar
    ├── 10-lore/                      capa compartida del juego (partida_id = None)
    │   ├── ambientacion/
    │   ├── reglas/
    │   ├── personajes/               PNJ y figuras del mundo
    │   ├── lugares/
    │   └── cronologia/
    ├── 20-partidas/
    │   └── <partida>/                ← partida_id
    │       ├── sesiones/             actas y transcripciones, una por sesión
    │       ├── material-jugadores/
    │       ├── notas-narrador/
    │       ├── secretos/
    │       └── personajes/           fichas de PJ
    ├── 90-referencia/                material externo citable
    └── 99-archivo/                   retirado — no se ingiere nunca
```

Los prefijos numéricos no son decoración: ordenan la carpeta en cualquier
cliente y hacen que el nombre visible no cambie al renombrar el contenido.

## 3. Correspondencia carpeta → ámbito

Es la parte que de verdad importa, porque de aquí sale la visibilidad de cada
hecho. Se aplica sobre la ruta **relativa a la raíz de bóvedas**.

| Ruta | `workspace` | `partida_id` | `visibility` inicial |
|---|---|---|---|
| `<juego>/10-lore/**` | `<juego>` | `None` (compartido) | `player` |
| `<juego>/20-partidas/<p>/material-jugadores/**` | `<juego>` | `<p>` | `player` |
| `<juego>/20-partidas/<p>/sesiones/**` | `<juego>` | `<p>` | `player` |
| `<juego>/20-partidas/<p>/notas-narrador/**` | `<juego>` | `<p>` | `narrator` |
| `<juego>/20-partidas/<p>/secretos/**` | `<juego>` | `<p>` | `secret` |
| `<juego>/20-partidas/<p>/personajes/**` | `<juego>` | `<p>` | `narrator` |
| `<juego>/90-referencia/**` | `<juego>` | `None` | `reference` |
| `<juego>/00-entrada/**` | `<juego>` | `None` | `secret` (lo más restrictivo) |
| `<juego>/99-archivo/**` | — | — | **no se ingiere** |
| cualquier otra ruta | — | — | **no se ingiere** |

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

- **Contraseña de aplicación nueva para `Mimir`.** La actual devuelve `401
  Unauthorized` contra el Nextcloud reconstruido; era también la causa del bucle
  de reintentos del montaje.
- Revisar este árbol frente a la carpeta `rol/` y la plantilla ya creadas.
- Confirmar los nombres definitivos de juego y partida (`<juego>` y `<p>` pasan
  a ser identificadores de ámbito; renombrarlos después es una migración).
