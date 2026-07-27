# 51 - Regresión de despliegue "forward-ref" y contrato de resolución de refs

Estado: **CORREGIDO** (rama `fix/deploy-forward-ref-regression`)
Fecha: 2026-07-18
Afecta a: `deploy/scripts/deploy.sh`, `deploy/scripts/lib.sh`

## Síntoma

Un despliegue hacia un tag o commit que **todavía no estaba materializado** en
el object store de la release activa (`/opt/s9-knowledge/current/.git`) fallaba
al resolver la referencia. Este es el caso **normal** de un deploy hacia
delante: el commit objetivo (p. ej. `deploy-v0.3.0-rc5`) es posterior a la
release en producción y aún no vive en su object store; se trae por `fetch`
dentro de la copia nueva en el paso 2.

## Causa raíz

El patrón histórico de resolución era equivalente a:

```sh
RESOLVED_COMMIT="$(git rev-parse "$ref" || printf '%s' "$ref")"
```

`git rev-parse <ref>` **imprime su propio argumento en stdout aunque falle** y
sale con código distinto de cero cuando el objeto no está presente. El fallback
`|| printf '%s' "$ref"` vuelve a imprimir la misma referencia, de modo que
`RESOLVED_COMMIT` acababa conteniendo el ref **dos veces**
(`"deploy-v0.3.0-rc5\ndeploy-v0.3.0-rc5"`). Ese valor multilínea corrupto
rompía después el `checkout`/`build` con `invalid refspec` /
`ambiguous argument`.

PR #33 corrigió el síntoma inmediato en línea dentro de `deploy.sh`
(`git rev-parse --verify -q "<ref>^{commit}"`, silencioso), pero:

- la lógica seguía dispersa y duplicada entre el paso de naming y el paso 2;
- no existía una **prueba automatizada** que reprodujera el escenario del ref
  ausente con repositorios git reales;
- no había un contrato único que rechazara inyección de opciones, refs
  ambiguas, salida multilínea o argumentos que empiezan por `-`.

## Corrección

Se centraliza toda la resolución en una única función en `lib.sh`:

```
resolve_release_commit <ref> [--repo-url URL] [--work-dir DIR] [--allow-branch]
```

### Contrato

| Requisito | Garantía |
|-----------|----------|
| Entrada | tag `deploy-*`, SHA completo, SHA corto inequívoco; branch solo con `--allow-branch` (dev) |
| stdout | **exclusivamente** el SHA del commit (40/64 hex) + `\n`; nunca el ref, mensajes ni "ok" |
| stderr | todos los diagnósticos |
| Salida | `0` si resuelve a un commit; `!= 0` en cualquier otro caso |
| Seguridad | rechaza refs que empiezan por `-` (inyección de opciones), con espacios, saltos de línea o caracteres fuera de `[A-Za-z0-9._/-]` |
| Ambigüedad | `rev-parse --verify -q` rechaza prefijos que resuelven a más de un objeto |
| Tipo | valida que el objeto es un **commit** (`^{commit}`) |
| Materialización | resuelve primero en local silenciosamente; si falta y hay `--repo-url`, hace un `fetch` específico y seguro (con `--` para que ni ref ni url se interpreten como opciones) y reintenta |

Nunca se hace `fetch` sobre `current`: rompería su checksum (que cubre `.git`).
El work-dir de resolución es siempre la copia nueva de la release o un
laboratorio.

## Prueba de regresión (E2E git real)

`deploy/tests/test_resolve_release_commit.py` monta repositorios git **reales**
(origin bare + clones), no mocks de comandos:

- un clon "operativo" que solo conoce el commit A;
- un tag anotado `deploy-test-rc` sobre B publicado en origin pero **no
  materializado** en el operativo (estado exacto del deploy hacia delante).

`test_regression_old_pattern_duplicates_new_pattern_clean` demuestra, en el
mismo escenario, que el patrón antiguo **duplica** el ref (falla) y que
`resolve_release_commit` devuelve **un único SHA limpio** (pasa). Casos
adicionales: tag anotado/ligero ausente, SHA completo ausente pero alcanzable,
SHA inexistente, tag inexistente, origin inaccesible, shallow clone, ref con
guion inicial (inyección), ref con salto de línea/espacio, objeto que no es
commit, branch rechazada en modo release y permitida con el flag, rollback a un
commit ya presente, e idempotencia.
