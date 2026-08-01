# -*- coding: utf-8 -*-
"""Módulo de Complemento de Pagos: parser, validador y endpoints para complementos
Pagos 1.1 del SAT.

Expone:
  - parse_pagos()   : Extrae datos del complemento Pagos 1.1.
  - validate_pagos(): Valida contra reglas SAT.
  - build_pagos_router(): Router FastAPI con endpoints /pagos/*.
"""
from b2b_ai.features.pagos.parser import parse_pagos, PagosData
from b2b_ai.features.pagos.validators import validate_pagos
from b2b_ai.features.pagos.routes import build_pagos_router

__all__ = ["parse_pagos", "PagosData", "validate_pagos", "build_pagos_router"]
