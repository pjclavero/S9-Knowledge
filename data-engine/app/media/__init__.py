"""Procesado automático de fuentes multimedia (vídeo/audio) para S9 Knowledge.

Flujo: staging → scan → job → extracción de audio → transcripción → Markdown
revisable. NO escribe en Neo4j: solo deja una fuente revisable lista para una
ingesta posterior (fase futura).
"""
