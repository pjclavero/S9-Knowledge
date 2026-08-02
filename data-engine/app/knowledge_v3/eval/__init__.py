# -*- coding: utf-8 -*-
"""Arnes de medicion de la puerta 4 (programa de cobertura del extractor).

Este paquete es SOLO MEDICION: no toca `extraction/`, `engine/`, `writer/`,
`pipeline/` ni `reconcile/`. Contiene:

* `integrity` — verificacion de que un corpus gold no se ha editado sin
  declararlo (hash contra su manifiesto).
* `dev_corpus` — envoltorio del corpus de DESARROLLO congelado (split
  `negation` de `benchmarks/datasets/`), con la integridad verificada antes
  de cargarlo.
* `generalization_corpus` — corpus de GENERALIZACION (B0): frases nuevas,
  con entidades que no comparten literales con el corpus de desarrollo.
* `harness` — la medicion unificada que corre sobre ambos corpus con la
  misma configuracion y publica las metricas lado a lado.

La leccion que gobierna este paquete es la del motor de relaciones v2:
predicado 0.81 en dev==test cayo a 0.24 en datos reales. Ninguna mejora futura
de `extraction/` se acepta aqui si solo mejora el numero de desarrollo.
"""
from __future__ import annotations
