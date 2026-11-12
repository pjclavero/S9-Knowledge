# -*- coding: utf-8 -*-
"""Sonda del escenario H (se ejecuta COMO el usuario de servicio con `runuser -u s9knowledge --`).

Usa el escritor REAL de la boveda (`vault_writer.escribir_label_workspace`) sobre la carpeta de
juego dada y escribe en stdout una linea JSON: {"resultado": "OK"|"CONTROLADO"|"EXCEPCION", ...}.
CONTROLADO = el escritor rechazo con un error de dominio (DestinoNoSeguroError, etc.) SIN cambios;
EXCEPCION = una excepcion no controlada (p.ej. PermissionError sin contexto): eso es un defecto.

uso: h_vault_probe.py <raiz-del-repo> <carpeta-de-juego> <label>
"""
from __future__ import annotations

import json
import sys

raiz, carpeta, label = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, raiz + "/viewer")
sys.path.append(raiz + "/data-engine/app")   # knowledge_v3, jobs... (puente visor -> motor)
from pathlib import Path  # noqa: E402

from app import sources_catalog, vault_writer  # noqa: E402

carpeta = Path(carpeta)
perfil = carpeta / sources_catalog.NOMBRE_PERFIL
try:
    lectura = vault_writer.leer_estado_perfil(perfil)
    vault_writer.escribir_label_workspace(carpeta, label, lectura.huella)
    print(json.dumps({"resultado": "OK"}))
except (vault_writer.DestinoNoSeguroError, vault_writer.RutaNoSeguraError,
        vault_writer.EscrituraRechazadaError, vault_writer.ConflictoEscrituraError,
        vault_writer.EntradaInvalidaError) as exc:
    print(json.dumps({"resultado": "CONTROLADO", "tipo": type(exc).__name__, "causa": str(exc)}))
except Exception as exc:  # noqa: BLE001 - lo que no es de dominio es el defecto que se busca
    print(json.dumps({"resultado": "EXCEPCION", "tipo": type(exc).__name__, "causa": str(exc)}))
