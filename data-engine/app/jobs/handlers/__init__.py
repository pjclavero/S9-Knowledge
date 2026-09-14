"""Handlers REALES de la cola de jobs.

Hasta el Slice 2 `jobs/worker.py` solo registraba `noop` y `echo` —"handlers de
prueba"—, y por eso el panel de operaciones parecia existir sin representar
trabajo real: pintaba fielmente una cola en la que nada de produccion podia
entrar.

Aqui viven los handlers que SI hacen trabajo. Cada uno reutiliza el nucleo que
ya existe; ninguno lanza un proceso ni reimplementa una cadena.
"""
