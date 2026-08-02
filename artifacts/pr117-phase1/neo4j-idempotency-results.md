# Idempotencia Neo4j real

| Escenario | Resultado |
|---|---|
| ID-01 primera aplicación | mutación y marca confirmadas |
| ID-02 repetición exacta | no-op; una marca y una mutación |
| ID-03 plan incompatible | conflicto y rollback |
| ID-04 fallo antes de mutación | cero marcas |
| ID-05 fallo durante mutación | rollback total |
| ID-06 caída tras commit | reinicio con caché vacía produce no-op |
| ID-07 concurrencia | una aplicación y un no-op |
| ID-08 dos workspaces | aislados |

Gate global: 0 duplicados, 0 marcas huérfanas, 0 mutaciones sin marca y 0
escrituras cruzadas.
