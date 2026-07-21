| config | n_predictions | existence_f1 | strict_f1 | evidence_correct | offsets_correct | predicate_correct | direction_correct | epistemic_correct | elapsed_ms |
|---|---|---|---|---|---|---|---|---|---|
| base (hybrid=None) | 52 | 0.8113 | 0.2075 | 0.907 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 50.9 |
| hybrid_default ({}) | 52 | 0.8113 | 0.2075 | 0.907 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 56.6 |
| ablate:predicate_direction | 52 | 0.8113 | 0.0 | 0.9302 | 0.9535 | 0.0 | 0.1395 | 0.8605 | 50.5 |
| ablate:temporal_epistemic | 52 | 0.8113 | 0.2075 | 0.907 | 0.9302 | 0.2558 | 0.6279 | 0.814 | 49.8 |
| ablate:evidence(+ver_off) | 52 | 0.8113 | 0.2075 | 0.0233 | 0.814 | 0.2558 | 0.6279 | 0.8605 | 52.4 |
| ablate:verification | 52 | 0.8113 | 0.2075 | 0.907 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 51.6 |
| ablate:consensus | 52 | 0.8113 | 0.2075 | 0.907 | 0.9302 | 0.2558 | 0.6279 | 0.8605 | 43.7 |
| stage:top_k=1 | 16 | 0.4286 | 0.1714 | 0.9333 | 0.9333 | 0.4 | 0.7333 | 0.8667 | 44.0 |
| stage:cross_sentence | 144 | 0.5253 | 0.1212 | 0.6346 | 0.9615 | 0.2308 | 0.6923 | 0.7885 | 141.8 |
