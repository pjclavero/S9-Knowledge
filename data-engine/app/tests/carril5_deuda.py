# -*- coding: utf-8 -*-
"""DEUDA DECLARADA del carril 5 (V3.1). No es documentacion suelta: este modulo
lo importa `test_carril5_exception_codes.py`, asi que mentir aqui pone rojo.

Cifra total (ejecucion completa del inventario AST sobre
`data-engine/app/tests/**`, no muestra): **259** comprobaciones por subcadena
(`match=` en `pytest.raises`: 130; `"lit" in str(exc)/msg/stderr/...`: 129) en
51 ficheros de prueba.

Convertidas en este carril: **52** — que son EXACTAMENTE todas las que viven
en los 5 ficheros que sostienen garantias RC (medido: 52 de 52, no una muestra),
sobre **6** modulos de producto y **71** puntos de `raise` sellados con codigo.

Criterio de INCLUSION (regla del operador: si una mutacion puede destruir una
propiedad declarada para el RC y todos los instrumentos siguen verdes, es
bloqueante):
  - ledger: unicidad, identidad logica, append-only, cadena de custodia,
    monotonia del tiempo de transaccion, supersesion y transiciones legales;
  - writer seguro: NO-ESCRITURA (guardas de entorno, dry-run, preflight,
    anti-TOCTOU, procedencia, idempotencia);
  - supersesion revisada: fail-closed (checksums, esquema, traversal, symlink,
    Unicode peligroso, segunda supersesion conflictiva).

Criterio de EXCLUSION (las ~207 restantes): NO sostienen una garantia RC. Por
familias, con el motivo:
"""
from __future__ import annotations

#: (familia, ficheros aproximados, comprobaciones, por que NO se convierte)
DEUDA_FUERA_DE_ALCANCE = [
    (
        "benchmarks de relaciones (bloque 7, rondas 1-4)",
        "test_relation_benchmark_block7*.py",
        84,
        "Miden CALIDAD de un benchmark (mensajes de informe, texto de dictamen). "
        "Reescribir un mensaje ahi no destruye ninguna propiedad del RC: destruye "
        "la legibilidad de un informe, que es justo lo que esas pruebas cuidan.",
    ),
    (
        "contratos de candidato de relacion / prompts / parser v2",
        "test_relation_candidate_contract.py, test_relation_v2_b5_parser.py, ...",
        31,
        "Contratos ya validados por JSON Schema y por `V3ContractError`; el "
        "mensaje es superficie de diagnostico, no la garantia. Sellar aqui "
        "duplicaria una defensa que ya existe aguas arriba.",
    ),
    (
        "proveedores externos (NVIDIA, Ollama, hardening, robustez)",
        "test_knowledge_v3_providers_*.py",
        22,
        "Corren en SOMBRA: su fallo no puede escribir en el grafo. Ninguna "
        "garantia RC depende de ellos hoy. Candidatos naturales cuando la "
        "revision externa deje la sombra.",
    ),
    (
        "motor V3, adaptadores, extraccion, glosario, multimodal, jobs, CLI",
        "test_knowledge_v3_engine*.py, test_glossary_*.py, test_media_cli.py, ...",
        70,
        "Errores de uso y de datos de entrada, no invariantes del RC. Convertirlos "
        "a ciegas cambiaria ~80 pruebas sin mover una sola garantia.",
    ),
]

#: Puntos SELLADOS con codigo estable pero SIN prueba de conducta que los ancle:
#: cambiar su codigo no pone roja ninguna prueba (medido, 31 de 71). Tienen
#: codigo para que anclarlos manana sea una linea, pero HOY no estan defendidos.
SIN_ANCLA_MEDIDA = 31
SITIOS_SELLADOS = 71
SITIOS_CON_ANCLA = 40

#: Total del inventario y conversion, medidos por ejecucion completa.
INVENTARIO_TOTAL = 259
INVENTARIO_MATCH = 130
INVENTARIO_IN_STR = 129
CONVERTIDAS = 52

#: Unificacion pendiente con el carril 3: cuando `viewer/tests/exception_codes.py`
#: (PR #198) este en `main`, los dos modulos comparten contrato y pueden fundirse.
#: No se hace ahora porque ese fichero NO existe en `aaf9695`.
DEUDA_UNIFICACION_CARRIL3 = True

__all__ = [
    "CONVERTIDAS", "DEUDA_FUERA_DE_ALCANCE", "DEUDA_UNIFICACION_CARRIL3",
    "INVENTARIO_IN_STR", "INVENTARIO_MATCH", "INVENTARIO_TOTAL",
    "SIN_ANCLA_MEDIDA", "SITIOS_CON_ANCLA", "SITIOS_SELLADOS",
]
