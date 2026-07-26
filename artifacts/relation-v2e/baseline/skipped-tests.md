# Tests que se saltan en el baseline — Bloque 0

**Commit:** `8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb` · **Medido en:** entorno local
(ver `environment.json`), **no en CI**.

Suite completa del repo (`pytest.ini`): **3198 passed, 5 skipped, 0 failed** (exit 0).
Los 5 skips son estos, todos con motivo explícito y ninguno silencioso.

| # | Test | Motivo declarado | ¿Por qué se salta aquí? | ¿Se salta también en CI? |
|---|---|---|---|---|
| 1 | `data-engine/app/tests/test_relation_v2_b5_parser.py:286` | `spaCy no instalado: comparacion diferida` | spaCy no está instalado y el proyecto **no descarga nada** (`syntax.py:1187-1195`, `SyntaxProviderUnavailable`) | **Sí.** `requirements.lock` no incluye spaCy |
| 2 | `data-engine/app/tests/test_relation_v2_b5_parser.py:298` | `Stanza no instalado: comparacion diferida` | Igual que el anterior | **Sí.** `requirements.lock` no incluye Stanza |
| 3 | `viewer/tests/browser/test_login_browser.py:22` | `Playwright no instalado: SKIP, no PASS` | Playwright no está instalado en local | **No.** El job `test-login-browser` de `.github/workflows/ci.yml` instala Chromium y **falla explícitamente si algún test se salta** con el navegador disponible |
| 4 | `tests/wave2b/test_external_nvidia_live.py:35` | `Test live NVIDIA: requiere S9K_NVIDIA_LIVE=1, S9K_NVIDIA_ENABLED=true y API key` | Prohibición absoluta del bloque: **sin red, sin proveedores reales** | **Sí** (no hay API key en CI) |
| 5 | `tests/wave2b/test_local_llm_ollama_live.py:51` | `Test live de Ollama: requiere S9K_OLLAMA_LIVE=1 y S9K_OLLAMA_BASE_URL alcanzable` | Igual: sin red ni proveedor local | **Sí** |

## Lectura

- **Ninguno de los 5 skips oculta un fallo.** Los 5 son gates de dependencia externa
  (spaCy, Stanza, Playwright, NVIDIA, Ollama) y todos declaran el motivo.
- Los skips 1 y 2 son exactamente la limitación §8.8 del informe de resultados
  (*"La comparación con spaCy/Stanza está sin medir"*): **sigue sin medirse en `8fc7c8d`**.
- El skip 3 es una diferencia **entre este entorno y CI**, no un skip del proyecto: en CI
  ese contrato **sí** se ejerce en un navegador real.
- Los skips 4 y 5 confirman §8.7: **nunca se han ejecutado proveedores reales**. Este bloque
  tampoco los ejecuta.

## Aviso operativo (no es un skip, es una trampa del arnés)

`deploy/tests/test_release_checksum.py::test_import_real_de_python_no_altera_checksum`
**falla** —no se salta— si se ejecuta con `PYTHONDONTWRITEBYTECODE=1`:

```
AssertionError: el import no generó bytecode; el test no estaría probando nada
```

El test es correcto: su premisa es que el import genere `.pyc`. La instrucción de purgar
`__pycache__` de este proyecto es compatible con él (purgar después ≠ prohibir escribir),
pero **la variable de entorno no lo es**. En este baseline la suite `deploy` y la suite
combinada se ejecutaron **sin** `PYTHONDONTWRITEBYTECODE`, purgando `__pycache__` a
continuación (verificado: `find . -name '*.pyc' | wc -l` → `0`).
