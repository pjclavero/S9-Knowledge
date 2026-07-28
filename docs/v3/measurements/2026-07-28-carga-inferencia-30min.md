# Medición del homelab bajo carga de inferencia — 30 minutos

Fecha: 2026-07-28 · 21:43-22:12 · Muestreo cada 28 s · 62 muestras por máquina

**Qué es esta medición.** Se lanzó como línea base en reposo, pero coincidió con las
tandas C1/D del extractor semántico contra Ollama. En vez de descartarla, se
reetiqueta por lo que realmente es: **el homelab con una inferencia local
concurrente sostenida durante media hora**. La línea base en reposo queda pendiente
para cuando el servidor esté quieto.

## Hardware del host

`yggdrasil` — Intel Xeon E5-2680 v4 @ 2.40 GHz, **28 cores**, 31 GB RAM, 8 GB swap.

| VM encendida | vCPU | RAM asignada |
|---|--:|--:|
| 102 `ia-server` (Ollama) | 8 | 9216 MB |
| 104 `web-hosting` | 4 | 4096 MB |
| 105 `common-services` (pipeline, Neo4j, Grafana, InfluxDB) | 6 | 8096 MB |
| 108 `s9-arena` | 4 | 16384 MB |
| 109 `diana-server` | 4 | 4096 MB |
| **Total** | **26 / 28** | **41.9 GB / 31 GB** |

CPU sin overcommit (26 de 28 cores). **RAM con overcommit de 1.35×.**

## Resultados

### Host `yggdrasil`

| Métrica | Media | Máx | Mín |
|---|--:|--:|--:|
| load1 | 8.40 | 9.40 | 6.13 |
| RAM disponible (MB) | 6168 | 6359 | **5941** |
| Swap usada (MB) | 4377 | 4407 | — |
| Swap-out | 101.9 | **3544** | 0 (58 de 62 muestras) |

### VM105 (pipeline, Neo4j, Grafana)

| Métrica | Media | Máx |
|---|--:|--:|
| load1 | 0.26 | 1.21 |
| RAM disponible (MB) | 5208 | 5227 |
| Swap usada | **0** | 0 |

### VM102 (Ollama)

Sin datos: no acepta SSH con las credenciales del resto del homelab ni con la clave
del host. Se midió indirectamente desde el proceso `kvm`: **VmRSS 9.26-9.30 GB**, es
decir, prácticamente toda su asignación.

## Lecturas

1. **La CPU no es el cuello.** load 8.40 de media sobre **28 cores** es un 30 % de
   ocupación. Sobra músculo de cálculo.
2. **La RAM sí es el cuello, y el margen es estrecho.** 6 GB disponibles de 31, con
   41.9 GB comprometidos entre VMs. Ollama, que es quien consume, ya ocupa su
   asignación entera.
3. **Pero el sistema aguanta:** durante media hora de inferencia continua, la RAM
   disponible **no bajó** (5941-6359 MB, banda estrecha y estable) y la swap usada
   **no creció** (4377→4407 MB). No hay fuga ni presión acumulativa.
4. **Hay swap-out esporádico**: 4 muestras de 62 con actividad, pico de 3544. No es
   thrashing —58 de 62 muestras a cero— pero confirma que el kernel está justo de
   margen y expulsa páginas de vez en cuando.
5. **VM105 no se entera.** Load 0.26, swap cero, RAM plana. La inferencia vive en
   VM102, así que el pipeline, Neo4j y Grafana quedan al margen. Esto es importante
   para la política de desvío: **saturar Ollama no degrada por sí mismo los
   servicios de VM105**; el acoplamiento es por RAM del host, no por CPU ni por la
   VM del pipeline.

## Consecuencias para la prueba de carga

- El escalado de concurrencia debe vigilar **RAM disponible del host y swap-out**,
  no la CPU. El primer síntoma aparecerá ahí.
- Con una inferencia concurrente el sistema es estable. **El experimento real es el
  escalón 2**: si una segunda inferencia concurrente obliga a Ollama a cargar más
  contexto o un segundo modelo, los 6 GB de margen se consumen rápido.
- Antes de subir de escalón conviene decidir sobre **VM108 `s9-arena`**: 16 GB
  asignados, el mayor bloque del host. Es la palanca más directa para ganar margen.
- **VM102 necesita acceso** (SSH o exporter) para medir desde dentro qué hace Ollama
  con la memoria al cargar y descargar el modelo. Hoy solo se ve su huella total
  desde el host.

## Pendiente

- Línea base **en reposo**, con el servidor quieto, para poder restar.
- Acceso a VM102.
- Los datos crudos están en `baseline.csv` del entorno de trabajo; conviene
  moverlos a `docs/v3/measurements/runs/` si se quieren conservar en el repo.
