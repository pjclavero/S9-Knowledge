# Restricciones

Aplicada únicamente al contenedor efímero mediante
`bootstrap_writer_schema(driver)`:

```cypher
CREATE CONSTRAINT v3_applied_operation_unique IF NOT EXISTS
FOR (op:V3AppliedOperation)
REQUIRE (op.workspace, op.idempotency_key) IS UNIQUE
```

`SHOW CONSTRAINTS` confirmó tipo `UNIQUENESS`, etiqueta
`V3AppliedOperation` y propiedades `[workspace, idempotency_key]`.
