# -*- coding: utf-8 -*-
"""Suite Q — OLA 2B Lote 2 (tests/wave2b).

Matriz de QA transversal que IMPORTA los modulos REALES ya integrados en main
(`relations.syntax`, `relations.local_llm_shadow`, `relations.external_ai_shadow`,
`relations.consensus_adapter`, `relations.observability`) y comprueba sus
invariantes de seguridad, incluidos 12 MUTATION checks. Q no reimplementa nada:
solo ejercita el producto real y bloquea si detecta un defecto.
"""
