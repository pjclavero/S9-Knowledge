# Recursos Docker

- Contenedores creados: `s9k-v3-writer-test-<uuid>` (uno por sesión pytest).
- Redes creadas: ninguna explícita.
- Volúmenes creados: ninguno.
- Recursos eliminados: todos los contenedores de prueba, mediante `--rm` y
  teardown `docker rm -f`.
- Recursos ajenos o productivos modificados: ninguno.

La comprobación final con filtros por `s9k-v3-writer-test` devolvió cero
contenedores, cero redes y cero volúmenes.
