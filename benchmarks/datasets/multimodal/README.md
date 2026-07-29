# Gold multimodal V3

Split manual y desconectado de los flujos automáticos. Todo el contenido es
inventado para este encargo y no procede de ningún corpus existente.

Las cuatro fuentes describen el mismo hecho semántico:

```text
Liora Vale --ALLY_OF--> Narek Sol
```

Modalidades:

- `sources/bruma.txt`: texto plano.
- `sources/bruma-native.pdf`: PDF con texto nativo.
- `sources/bruma-scan.png`: imagen rasterizada y degradada.
- `sources/bruma-audio-transcript.json`: transcripción ASR simulada con errores.

`semantic_gold.json` es compartido. Los binarios se reconstruyen de forma
determinista con `_authoring/build_assets.py`. Este split no está registrado en
el loader ni en CI.
