# 00 · Visión

S9 Knowledge convierte material heterogéneo de campañas de rol (PDFs, textos,
audios de sesión, vídeos de YouTube, páginas web y notas manuales) en un **grafo de
conocimiento** consultable y navegable, alojado en el homelab Sección 9 (self-hosted,
sin servicios cloud).

## Para qué

- Tener una **memoria viva** de cada campaña: personajes, criaturas, lugares,
  facciones, objetos, eventos, combates y sesiones, con sus relaciones.
- Registrar la **evolución temporal**: qué se sabía en cada sesión y cómo cambia.
- Modelar el **conocimiento por personaje**: cada jugador ve solo lo que su
  personaje conoce, no todo lo que existe en el mundo.
- Permitir edición manual (SilverBullet) y, en el futuro, un **visor web** y un
  **panel de gestión**.

## Principios

- **Neo4j es la fuente de verdad**; el visor solo presenta.
- **Trazabilidad total**: cada nodo/relación sabe de qué documento, tipo de fuente,
  hash, versión de extractor y prompt proviene.
- **Multi-bóveda**: cada campaña es un `workspace` aislado.
- **Self-hosted y privado**: nada de APIs externas; Neo4j/Ollama no expuestos.
- **No romper producción**: cambios con backup y prueba mínima.
