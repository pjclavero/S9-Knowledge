# -*- coding: utf-8 -*-
"""Adaptadores de fuente del normalizador multimodal.

Reales (producen contenido de verdad):
    `text`       texto plano y notas
    `markdown`   Markdown con secciones y tablas
    `pdf`        PDF con texto nativo (pypdf), pagina a pagina
    `table`      CSV y tablas Markdown -> episodio TABLE estructurado
    `transcript` audio, video y YouTube ENVOLVIENDO la salida ya producida por
                 `media/`, `audio/` y `youtube/` (aqui no se transcribe nada)

Declarados con interfaz definida e implementacion stub honesta:
    `visual`     OCR, HTR, imagen y dibujo. La ejecucion real corresponde al
                 subsistema de proveedores; aqui esta el puerto y el punto de
                 enganche, y sin proveedor se emiten episodios pendientes.
"""
