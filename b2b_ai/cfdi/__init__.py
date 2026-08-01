# -*- coding: utf-8 -*-
"""Sub-paquete de facturación CFDI: parser completo, catálogos SAT,
validación fiscal avanzada y cancelación."""
from b2b_ai.cfdi.parser import parse_cfdi, CFDIError
from b2b_ai.cfdi.validator import validate_cfdi
from b2b_ai.cfdi.cancellation import evaluate_cancellation

__all__ = ["parse_cfdi", "CFDIError", "validate_cfdi", "evaluate_cancellation"]
