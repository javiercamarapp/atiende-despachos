# -*- coding: utf-8 -*-
"""seed — Datos de demo para el primer piloto de Likida AI.

Genera y persiste un dataset realista (despacho contable ficticio, CFDIs de
muestra y transacciones bancarias) para que el primer cliente piloto pueda
probar el producto con datos de ejemplo en MXN, sin exponer datos reales.

Módulos:
    demo_data — generación determinista de datos + persistencia opcional en DB.

Uso:
    python -m seed.demo_data [--db /path/to/b2b_ai.db] [--cfdis 50] [--txs 20]
"""
