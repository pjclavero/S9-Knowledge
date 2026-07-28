# Plan de medición de capacidad y observabilidad — S9-Knowledge V3

Fecha: 2026-07-28 · Estado: **acordado, no ejecutado**

Objetivo: aprovechar las pruebas E2E para medir **a la vez** calidad semántica y
coste de infraestructura, y determinar no el máximo técnico del servidor sino el
**límite operativo seguro** con el que S9-Knowledge puede procesar durante horas sin
comprometer el resto del homelab.

> **Precondición dura:** ninguna prueba de capacidad se ejecuta antes de que la
> cadena E2E use el `SemanticEpisodeExtractor`. Medir el extractor legacy sería
> medir algo que ya vamos a sustituir.

---

## 1. Auditoría de la observabilidad existente (hecha)

Fuente: `pjclavero/s9-server` → `servicios/grafana.md`.

**El anexo asumía Prometheus. La realidad es InfluxDB.** Esto cambia el diseño de
la instrumentación y evita montar una pila duplicada.

| Pieza | Realidad |
|---|---|
| Grafana | OSS, en **VM105** (`192.168.1.205`), puerto LAN 3001 → 3000, `https://grafana.seccionnueve.duckdns.org` |
| Base de métricas | **InfluxDB v2** en VM105:8086, org `s9` |
| Métricas del host | **Telegraf** en el host Proxmox `yggdrasil` → bucket `homelab`, retención **infinita** |
| Métricas por VM/LXC | **pvestatd** (nativo de Proxmox) → bucket `proxmox`, retención **90 días** |
| Dashboard actual | "Yggdrasil — Homelab Monitor", 6 paneles, refresco 30 s (solo host) |

Los buckets están separados **a propósito**: compartirlos provoca `HTTP 422` por
choque de tipos en measurements homónimos (`system`).

### Lo que YA está cubierto y no hay que construir

- **Host completo**: `cpu`, `system` (carga), `mem`, `disk`, `diskio`, `net`,
  `processes`, `kernel`, temperaturas de CPU/placa/**13 discos**, SMART de todos los
  discos, ARC de ZFS y `zpool_status` (salud, capacidad, errores por pool).
- **Por VM/LXC, sin instalar nada en los guests**: `cpustat`, `memory`, `nics`,
  `blockstat`, `ballooninfo`, etiquetados por `vmid`. Cubre buena parte de las capas
  5.1 y 5.2 del anexo.

### Lo que falta de verdad

1. **Métricas internas del guest**: presión PSI (CPU/memoria/IO), swap in/out,
   page faults, OOM kills, descriptores, RSS por proceso. `pvestatd` ve la VM desde
   fuera; no ve qué proceso dentro consume.
2. **Métricas por contenedor/servicio** (Ollama, workers, motor, Neo4j).
3. **Métricas de aplicación** (etapas del pipeline, proveedores, colas).
4. **Dashboards por VM**: el `grafana.md` ya lo declara pendiente — el dashboard
   actual solo cubre el host, aunque el bucket `proxmox` tenga los datos.

### Decisión de instrumentación

La aplicación expone un endpoint `/metrics` en **formato Prometheus** y **Telegraf
lo recoge** (`inputs.prometheus`) escribiendo a InfluxDB. Así:

- la aplicación queda con instrumentación estándar y portable;
- no se monta un Prometheus paralelo (el anexo prohíbe duplicar exporters);
- Grafana lo consume por el datasource que ya existe.

Los nombres de métrica y las etiquetas son los del anexo (`s9_stage_duration_seconds`,
`s9_claims_*`, `s9_provider_*`, etiquetas `stage`/`provider`/`model`/`pipeline_mode`/
`result`/`modality`/`negation_kind`). **Prohibidas** las etiquetas de alta
cardinalidad: nada de `run_id`, ids de episodio, rutas, textos ni hashes completos —
esos van a logs e informes.

### Ojo: Ollama no corre donde se cree

`qwen2.5:7b` corre en **VM102 `ia-server` (192.168.1.157)**, no en VM105. Medir "el
coste de Ollama" exige mirar VM102 (que `pvestatd` ya cubre desde fuera), mientras
que el pipeline, Neo4j y Grafana viven en VM105. Cualquier conclusión sobre "carga
local" debe decir **de qué máquina** habla.

---

## 2. Correlación de ejecuciones

Cada ejecución lleva identidad estable: `run_id`, `commit`, `corpus_hash`,
`scenario`, `provider`, `model`, `prompt_version`, `ontology_version`.

Al empezar y terminar se crea una **anotación en Grafana** vía su API (funciona con
cualquier datasource, también InfluxDB). Sin secretos en el texto de la anotación.
Si la API no estuviera disponible, log estructurado que Grafana pueda representar.

---

## 3. Línea base antes de medir nada

20-30 minutos de observación con el servidor en su estado habitual, registrando
medias, **percentiles y picos** (no solo medias: una media esconde justo el pico que
tumba un servicio). Se guarda en
`docs/v3/measurements/<fecha>-server-baseline.md` y es la referencia de todo lo
demás.

---

## 4. Escenarios

| | Extractor | Qué mide |
|---|---|---|
| A | Determinista | Coste mínimo, baseline sin modelos |
| C1 | Semántico · Ollama (VM102) | Carga del modelo, RAM pico, tiempo/episodio, sostenido |
| C2 | Semántico · NVIDIA (nube) | CPU/RAM local, latencia de red y proveedor, errores, **carga que se evita** |
| D1 | Determinista + Ollama | |
| D2 | Determinista + NVIDIA | |
| D3 | Determinista + ambos | Solo si no mezcla autoridad; **no** para decidir por mayoría |
| N | Corpus de negaciones | simple, NEVER, CESSATION, NOT_YET, pregunta, condicional, alcance ambiguo, cierre temporal |

Mismo corpus `dev` en todos mientras se comparen. Entrada **siempre** por
`KnowledgePipeline`, nunca llamando al extractor suelto. Writer en dry-run.

## 5. Escalado de concurrencia

Nivel 1 (1 trabajo, 1 worker, 1 inferencia local) → Nivel 2 (2 trabajos, Ollama
concurrencia máxima 1) → Nivel 3 (3 trabajos). **Solo se sube de nivel si el
anterior no produjo** swap continuo, iowait elevado, timeouts, degradación de otros
servicios, cola creciente, reinicios ni errores. NVIDIA admite más concurrencia
externa, pero normalización, resolución, motor, ledger y logs siguen siendo locales:
el cuello no desaparece, se desplaza.

## 6. Prueba prolongada

Varias horas con la configuración estable, buscando: fugas de memoria, descarga del
modelo en Ollama, crecimiento de cachés, vaciado de cola, degradación progresiva,
reintentos, checkpoints y que una caída no obligue a repetirlo todo.

## 7. Criterios de parada (abortar de forma controlada)

OOM kill · pérdida de un servicio crítico · errores continuos en Nextcloud · Neo4j
sin responder · MQTT sin responder · iowait sostenido excesivo · swap in/out
continuo · memoria disponible crítica · temperatura fuera de rango · cola creciendo
sin límite · errores repetidos del proveedor · pérdida de datos · aislamiento de
workspace roto.

**No se espera a que el servidor se bloquee.**

Umbrales iniciales de advertencia (señales, no leyes): CPU host sostenida > 85 %,
iowait > 10-15 %, RAM disponible del host < 10 %, swap in/out continuo, cualquier
OOM kill, latencia de almacenamiento degradada, servicios productivos lentos.

El informe debe distinguir **umbral observado**, **umbral de advertencia**, **límite
operativo recomendado** y **límite técnico máximo**. No son lo mismo y confundirlos
es como se rompe un homelab.

## 8. Impacto en el resto del homelab

Durante cada escenario, comprobaciones **ligeras** (healthchecks, latencia de una
consulta segura, códigos de respuesta, logs de error) sobre Nextcloud, Neo4j, MQTT,
servicios web y alertas de Proxmox. Nada de pruebas agresivas contra producción.

## 9. Entregables

- Por ejecución: `docs/v3/measurements/<fecha>-<scenario>-<run_id>.md` (+ JSON) con
  identidad, configuración, calidad, rendimiento, impacto y resultado.
- Comparativa final: `docs/v3/18-capacidad-resultados.md` con la tabla escenario ×
  (calidad, tiempo, RAM VM, CPU host, iowait, swap, impacto) y las recomendaciones:
  configuración más rápida, de mayor calidad, de menor consumo, más estable, límite
  operativo seguro, límite técnico observado, proveedor y concurrencia
  recomendados, modelo local recomendado, fallback, riesgos y **datos que faltan**.

## 10. Hipótesis a evaluar (no a presuponer)

Producción normal con 1 worker pesado, Ollama con 1 inferencia concurrente máxima,
NVIDIA con 1-2 trabajos según cuota, y procesamiento por cola reanudable con
checkpoints. Los datos pueden recomendar más o menos.

## 11. Riesgo propio de esta medición

La instrumentación tiene coste. Si el endpoint de métricas y el muestreo añaden
sobrecarga apreciable, **las latencias medidas dejan de ser las de producción**. Hay
que medir el overhead de la propia observabilidad (una ejecución con y otra sin) y
declararlo en el informe. El anexo ya avisa: no introducir una observabilidad que
invalide el benchmark.
