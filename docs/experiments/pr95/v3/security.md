# V3 · Seguridad

SHA base: `92583f4`.

## Garantías

- **Sin red.** `fragment_protocol.py` es puro y determinista (fragmentación, hashing,
  reconstrucción). El evaluador usa el proveedor inyectado; en tests el transporte
  HTTP es un mock. No se abre ninguna conexión.
- **Sin escritura.** No toca Neo4j, no activa ingesta, no persiste nada. Modo sombra
  estricto preservado (`require_shadow`; nunca `AUTO_APPROVED`).
- **Literalidad estricta.** La evidencia reconstruida es SIEMPRE subcadena literal del
  documento real (`document[start:end] == text`), con offsets coherentes
  (`0 <= start <= end <= len(document)`). Un ID inexistente o una lista vacía se
  rechazan (`fragment_inexistente`).
- **Contrato persistente intacto.** Los `fragment_ids` y `fragment_protocol_version`
  viven solo en la capa experimental (verdicto saneado en memoria); el contrato de 20
  campos de `RelationCandidate` NO cambia. No hay migración de esquema.
- **Prompt injection.** El texto MOSTRADO en el prompt pasa por `sanitize_document`
  (neutraliza los delimitadores sentinela `INPUT_OPEN`/`INPUT_CLOSE`). La
  reconstrucción/validación opera sobre el documento REAL sin sanitizar, por lo que la
  neutralización visual no puede alterar los offsets ni introducir evidencia falsa.
  Test `test_adversarial_text_preserves_literality` cubre texto hostil (delimitadores,
  controles, fences markdown, `AUTO_APPROVED`).
- **Sin secretos.** `assert_no_secrets(messages)` se ejecuta antes de cualquier envío,
  igual que en la base. La API key nunca se serializa.
- **Flag OFF por defecto.** Ningún cambio de comportamiento en producción salvo
  activación explícita de la capa experimental.

## Superficie de ataque añadida

Mínima: un módulo puro sin E/S y dos ramas condicionales en el evaluador, ambas
gobernadas por un flag default OFF. No se introduce parsing nuevo de red ni deserialización insegura (se reutiliza el parser JSON robusto existente).
