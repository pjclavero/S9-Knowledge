# -*- coding: utf-8 -*-
"""S9-Knowledge V3 — dataset gold comun y arnes de medicion.

Este paquete NO implementa ningun subsistema del pipeline: solo (a) custodia el
dataset gold de DESARROLLO y (b) mide salidas de subsistemas contra ese gold.

Piezas
------
- ``datasets/``  : el dataset gold, en JSON, dividido por *split*. Hoy solo
  existe ``dev``. El arnes NUNCA cablea el nombre del split: cualquier
  directorio hermano (``heldout``, ``real``...) se carga con el mismo codigo.
- ``authoring/`` : el codigo que GENERA ``datasets/dev`` de forma determinista.
  Los ficheros del dataset estan versionados; un test comprueba que regenerar
  produce exactamente los mismos bytes.
- ``loader.py``  : carga y valida el dataset contra los contratos congelados.
- ``matching.py``: emparejamiento prediccion-vs-gold. Aqui es donde se hacen
  trampas sin querer, asi que vive aparte, documentado y con tests de mutacion.
- ``metrics.py`` : aritmetica de P/R/F1 y demas. Calcula; no estima.
- ``ablations.py``: configuraciones etiquetadas (dosier 8, "Ablaciones").
- ``harness.py`` : orquestador por subsistema (dosier 13, "Metricas").
- ``report.py``  : salida JSON estable y tabla markdown.
- ``cli.py``     : interfaz de linea de comandos.

Reglas duras de este paquete
----------------------------
1. No escribe en Neo4j, no llama a proveedores, no toca produccion.
2. El gold es de DESARROLLO. Todo fichero lleva ``split: "dev"`` y todo
   documento lleva ``metadata.benchmark.split``. El held-out lo prepara un
   equipo independiente y se anade como split hermano SIN tocar el arnes.
3. Las metricas se calculan sobre datos reales de entrada. No hay ningun
   numero cableado ni estimado en la salida del arnes.
"""
from __future__ import annotations

#: Version del formato del dataset y del arnes. Sube cuando cambia la forma de
#: los ficheros del dataset o el significado de una metrica.
BENCHMARK_FORMAT_VERSION = "1.0.0"

#: Split de desarrollo. El arnes lo trata como un valor mas, nunca como el unico.
DEV_SPLIT = "dev"

__all__ = ["BENCHMARK_FORMAT_VERSION", "DEV_SPLIT"]
