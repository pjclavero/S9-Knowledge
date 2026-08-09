# deploy/release — gate de despliegue

Responde por escrito a **¿qué exactamente desplegaríamos?**. Nada de aquí toca
producción: todo se ejecuta en local, en CI o contra un host destino al que ya
se tiene acceso legítimo.

Documentación completa: [`docs/61-release-manifest-y-rollback.md`](../../docs/61-release-manifest-y-rollback.md).

## Uso

```bash
# 1. Manifiesto: qué desplegaríamos
python3 deploy/release/generate_manifest.py -o deploy/release/RELEASE_MANIFEST.json
python3 deploy/release/generate_manifest.py --format md

# 2. Comprobador de configuración (en el HOST destino para su alcance completo)
python3 deploy/release/config_check.py --env-file /etc/s9-knowledge/viewer.env \
        --production --check-filesystem --check-units --check-neo4j
#   0 OK · 1 WARNING · 2 ERROR · 3 fallo interno del comprobador

# 3. Smoke suite de laboratorio (in-process, sin red)
python3 deploy/release/smoke_lab.py

# 4. Calibración: demuestra que el comprobador enrojece de verdad
python3 deploy/release/calibrate_config_check.py

# Todo lo anterior, fijado por tests:
python3 -m pytest deploy/tests/test_release_readiness.py -q
```

## Reglas que el kit no negocia

- Una **ausencia crítica** nunca produce OK.
- Un **fallo interno** del comprobador nunca produce código 0.
- Los **secretos** se referencian por **ruta**: nunca se leen, imprimen ni
  hashean. De su valor solo se comprueba, sin revelarlo, que no sea un marcador
  de posición y que tenga longitud suficiente.
- Lo **no comprobable** sin acceso al destino se declara como WARNING explícito,
  jamás como OK.
- El **grafo legacy está en NO APPLY**: ninguna migración de Neo4j puede
  declararse necesaria, y hay un test que lo impide.

## `spec.py` es la fuente única de verdad

Variables, ficheros, secretos, directorios, versiones, componentes, migraciones
y métricas de recuperación viven en un solo sitio, que el manifiesto y el
comprobador comparten. Añadir un requisito nuevo es editar `spec.py`; el
manifiesto y las comprobaciones lo recogen solos, y la calibración pasa a
exigirlo.
