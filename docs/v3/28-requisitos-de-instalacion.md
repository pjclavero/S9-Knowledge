# Requisitos de instalación y despliegue — S9-Knowledge V3

Fecha: 2026-07-29 · **Verificado ejecutando**, no deducido de los imports.

Este documento existe porque las dependencias de V3 ya no son solo paquetes de
Python: hay **binarios del sistema** y **servicios externos** sin los cuales partes
enteras del sistema se saltan en silencio. Quien monte una máquina nueva necesita
esta lista.

---

## 1. Base

| | |
|---|---|
| Python | **3.13** (es la versión de CI; verificado en Debian 13 con 3.13.5) |
| Sistema de referencia | Debian 13 (trixie) |

## 2. Paquetes Python

Los del proyecto están en `data-engine/requirements.lock` y
`viewer/requirements.txt`. Los que hacen falta **específicamente** para que no se
salten capacidades:

| Paquete | Para qué | Si falta |
|---|---|---|
| `jsonschema` | Validación de los contratos congelados | **Todo el subsistema V3 se salta** |
| `pypdf` | Adaptador de PDF nativo | Los tests de PDF y el gold multimodal fallan con `ModuleNotFoundError` |
| `pillow` | Manipulación de imagen para el proveedor OCR | Los tests visuales se saltan |
| `neo4j` | Driver del writer | Las pruebas contra base real se saltan |
| `pytest` | Suite | — |

> **Aviso aprendido por las malas.** Un venv con `pytest jsonschema pillow` parece
> suficiente y no lo es: el test del gold multimodal falla con
> `ModuleNotFoundError` desde `multimodal/adapters/pdf.py` porque le falta `pypdf`.
> Cuesta veinte minutos entender que el fallo es del entorno y no del código.

## 3. Binarios del sistema

### Tesseract — OCR local (opcional, pero necesario para imágenes)

```bash
apt-get install -y tesseract-ocr tesseract-ocr-spa
```

- Verificado en VM105: **Tesseract 5.5.0** con leptonica 1.84.1.
- Idiomas instalados: `eng`, `osd`, `spa`. **Hay que instalar el paquete del idioma
  aparte**: `tesseract-ocr` solo trae inglés y detección de orientación.
- El proveedor lo busca en varias rutas y admite `S9K_TESSERACT_CMD` para indicar
  una ubicación concreta.
- **Sin Tesseract el sistema no se rompe**: los adaptadores visuales vuelven a su
  comportamiento de stub (`UNPROCESSED_PENDING_PROVIDER`, sin texto y sin
  evidencia) y sus tests se saltan con un mensaje explícito. Es una capacidad
  opcional, no un requisito.
- Instalación aditiva: no toca ningún servicio. Verificado que los contenedores de
  VM105 siguieron intactos tras instalarlo.
- **Puerta 4, bloque B1 (carril OCR de la extracción)**: el paquete de idioma
  `tesseract-ocr-spa` no es opcional para este bloque — el corpus de negaciones
  (`ambar-escaneo`) está en español y `eng` solo no reconoce el texto. Fail-closed
  verificado: sin el binario (o sin el paquete de idioma), la fuente `IMAGE` queda
  con episodios pendientes y diagnóstico explícito (`VISION_PROVIDER_NOT_AVAILABLE`
  / `UNPROCESSED_PENDING_PROVIDER`), cero claims, cero evidencia inventada — el
  resto del sistema (el resto de fuentes del split, el resto de la puerta 4) sigue
  funcionando exactamente igual. Ver `docs/v3/39-carril-ocr.md`.
- Estado real verificado para este bloque: Tesseract 5.5.0 con `eng`+`spa` está
  instalado en **VM105** y **no** en VM102. Los tests reales del carril OCR
  (`data-engine/app/tests/test_gate4_b1_ocr_real.py`, gateados con
  `pytest.skip` si falta el binario) se ejecutan y validan en VM105, no en la
  estación de desarrollo `ia02` ni en VM102.

### Docker — solo para las pruebas del writer

Necesario **únicamente** para ejecutar `test_knowledge_v3_writer_neo4j_real.py`,
que levanta un Neo4j efímero. No hace falta para operar el sistema.

- Sin Docker, esos 11 tests se saltan (que es el comportamiento correcto en CI).
- El usuario que ejecute las pruebas debe estar en el grupo `docker`; si no, el
  binario existe pero el socket da `permission denied`.

## 4. Qué se salta si falta cada cosa

| Falta | Qué deja de verificarse |
|---|---|
| `jsonschema` | **Todo `knowledge_v3`** — la suite entera se salta sin avisar de que se salta |
| `pypdf` | PDF nativo y gold multimodal (falla, no se salta) |
| Tesseract | 10 tests de OCR real; el pipeline sigue, marcando pendiente |
| Docker | 11 tests del writer contra Neo4j real |
| Ollama accesible | Tests de humo del extractor semántico |
| Clave NVIDIA | Tests de humo del proveedor externo |

**El patrón peligroso es el primero**: cuando falta `jsonschema`, la suite pasa en
verde con todo el subsistema saltado. Un verde que no significa nada. Al montar una
máquina, comprobad el **número** de tests ejecutados, no el color.

## 5. Servicios externos (opcionales)

| Servicio | Dónde está hoy | Para qué |
|---|---|---|
| Ollama | VM102 `ia-server`, `192.168.1.157:11434`, modelo `qwen2.5:7b` | Extractor semántico local |
| NVIDIA (nube) | `integrate.api.nvidia.com`, clave en `/etc/s9-knowledge/nvidia.env` en VM105 | Extractor semántico remoto y potencia |
| Neo4j | VM105, contenedor `neo4j-knowledge`, `127.0.0.1:7687` | Destino del writer (**producción: no tocar en pruebas**) |

> Pendiente conocido: **ninguna unidad systemd carga `nvidia.env`**, así que la clave
> está inerte en producción. Hay que añadirlo cuando se despliegue el uso de NVIDIA.

## 6. Comprobación rápida de una máquina nueva

```bash
python3 --version                      # 3.13
python3 -c "import jsonschema, pypdf, PIL, neo4j; print('deps ok')"
tesseract --version && tesseract --list-langs   # 5.x, debe incluir spa
docker version >/dev/null && echo "docker ok"   # solo para pruebas del writer

# Y lo que de verdad importa: cuántos tests se ejecutan, no si están en verde
python -m pytest data-engine/app/tests/ -q --ignore=data-engine/app/tests/e2e
# Referencia con todo instalado: ~4.539 pasados
```

## 7. Estado verificado (2026-07-29)

| Máquina | Python | Tesseract | Docker | Notas |
|---|---|---|---|---|
| VM105 `common-services` | 3.13.5 | **5.5.0 + spa** | sí | Aquí viven Neo4j, Grafana e InfluxDB |
| VM102 `ia-server` | — | — | — | Ollama; sin acceso SSH con las credenciales del resto |
| Estación de trabajo `ia02` | 3.13 | no | binario sí, sin permiso de socket | Los tests de OCR y de Neo4j se saltan aquí |

---

## 8. Proveedores externos: qué está realmente disponible (verificado 2026-07-29)

Credenciales en `/etc/s9-knowledge/providers.env` (0600 root:root), cargadas con
`EnvironmentFile=` en systemd o `--env-file` en Docker. **Sin dependencias nuevas:
ni gestor de secretos ni servicio adicional que desplegar.** El panel de gestión,
cuando exista, debe guardar el **nombre de la variable**, nunca su valor.

### Modelos accesibles con la clave actual

Probados contra `https://integrate.api.nvidia.com/v1/chat/completions` con una
imagen renderizada real (texto negro sobre blanco):

| Modelo | Resultado |
|---|---|
| `meta/llama-3.3-70b-instruct` | **200** — texto, ya en uso |
| `meta/llama-3.2-90b-vision-instruct` | **200** — transcripción limpia y exacta |
| `nvidia/nemotron-nano-12b-v2-vl` | **200** — transcripción limpia y exacta |
| `meta/llama-3.2-11b-vision-instruct` | **200** — correcta, con preámbulo conversacional |
| `moonshotai/kimi-k2.6` | **404** — listado en `/models` pero **no habilitado** |
| `microsoft/phi-3-vision-128k-instruct` | **404** — ídem |

> **Cuidado con `/models`: lista modelos que la cuenta no puede usar.** El 404 de
> Kimi lo dice literal: *"Function '23d4f03a-…': Not found for account…"*. Un
> control con `llama-3.3-70b` devolvió 200 con la misma clave y los mismos
> encabezados, así que no era la credencial ni la petición. Si se quiere Kimi, hay
> que solicitar acceso en el portal.

### Los VLM transcriben, pero NO sustituyen al OCR

Los tres modelos de visión leyeron el texto correctamente. Aun así **no pueden
ocupar el carril `OCR_TEXT`**: devuelven texto, no **posiciones**. El contrato de
evidencia exige bounding boxes para `OCR_TEXT`, y sin ellas la evidencia no se
puede anclar y el claim no se sostiene.

Reparto correcto de carriles:

| Carril | Proveedor | Salida |
|---|---|---|
| `OCR_TEXT` | **Tesseract** (local) | Texto **con bbox** por palabra |
| Interpretación visual | **VLM en nube** | Descripción → `VISUAL_INFERRED`, revisión obligatoria por contrato |

Y el sistema **rechaza** a un proveedor que intente devolver ambas cosas a la vez:
es una guarda verificada, no una convención.

### Varios proveedores por capacidad: sí, con matices

- **Se admiten varios** por capacidad; el router ya lo contempla.
- **Dos proveedores de la misma familia no son dos pruebas.** Dos VLM de nube con el
  mismo prompt comparten modos de fallo y cuentan como **una** familia de evidencia.
  Tesseract (algorítmico, local) y un VLM (generativo, nube) sí son independientes.
- **Para OCR, consenso no aplica**: dos OCR dan textos con posiciones distintas, y el
  reconciliador —que fusiona solo con certeza— conservará ambos. Lo que sí aplica es
  **escalado**: Tesseract primero, y a un VLM cuando falle o la confianza sea baja.
- **Donde dos familias sí aportan de verdad es en extracción semántica**, y el
  reconciliador ya registra `proposals`, `providers` e `independent_families` por
  separado, sin votar.

### Pendiente

Ninguna unidad systemd carga todavía `providers.env`. Hasta que se añada
`EnvironmentFile=/etc/s9-knowledge/providers.env`, la clave existe y está inerte en
producción.
