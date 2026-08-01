1|# -*- coding: utf-8 -*-
2|"""
3|models.py — Pydantic schemas for the Fiscal Conciliation module.
4|
5|All models use pydantic v2 (BaseModel) with Field for descriptions.
6|These represent ERP vs SAT comparisons, omissions, discrepancies,
7|and fiscal reports used by contadores in Mexico.
8|"""
9|from __future__ import annotations
10|
11|from enum import Enum
12|from typing import Any, Dict, List, Optional
13|from pydantic import BaseModel, Field, field_validator
14|from b2b_ai.features.compliance import FiscalOutput, AuditTrailEntry
15|
16|
17|# ---------------------------------------------------------------------------
18|# Enums
19|# ---------------------------------------------------------------------------
20|
21|class TipoOmicion(str, Enum):
22|    """Tipo de omisión fiscal detectada."""
23|    FACTURA_SAT = "factura_no_en_erp"      # Factura en SAT pero no en ERP
24|    FACTURA_ERP = "factura_no_en_sat"      # Factura en ERP pero no en SAT
25|    DECLARACION = "declaracion_faltante"    # Declaración no presentada
26|    PAGO = "pago_no_registrado"            # Pago no registrado
27|    AJUSTE = "ajuste_no_reflejado"        # Ajuste no reflejado
28|
29|
30|class TipoDiscrepancia(str, Enum):
31|    """Tipo de discrepancia fiscal."""
32|    MONTO = "monto_diferente"
33|    FECHA = "fecha_diferente"
34|    RFC = "rfc_diferente"
35|    CONCEPTO = "concepto_diferente"
36|    IVA = "iva_diferente"
37|# ---------------------------------------------------------------------------
38|# Backward-compat enums used by tests and legacy service code
39|# ---------------------------------------------------------------------------
40|
41|class DeclaracionTipo(str, Enum):
42|    """Tipo de declaración fiscal (used by ERP/SAT cross-reference)."""
43|    IVA = "iva"
44|    ISR = "isr"
45|    DIOT = "diot"
46|    CONTABILIDAD_ELECTRONICA = "contabilidad_electronica"
47|
48|
49|class DiscrepancySeverity(str, Enum):
50|    """Severity level for fiscal discrepancies."""
51|    LOW = "low"
52|    MEDIUM = "medium"
53|    HIGH = "high"
54|    CRITICAL = "critical"
55|
56|
57|class ERPRecord(BaseModel):
58|    """A record from the ERP system for fiscal cross-reference."""
59|    id: str = Field(default="", description="ERP record identifier")
60|    concepto: str = Field(default="", description="Concept/type of record")
61|    monto: float = Field(default=0.0, ge=0, description="Amount in MXN")
62|    periodo: str = Field(default="", description="Period YYYY-MM")
63|    rfc: Optional[str] = Field(default=None, description="RFC associated")
64|    fecha: Optional[str] = Field(default=None, description="Date YYYY-MM-DD")
65|
66|    model_config = {
67|        "json_schema_extra": {
68|            "examples": [{
69|                "id": "ERP-001",
70|                "concepto": "iva",
71|                "monto": 50000.0,
72|                "periodo": "2026-06",
73|            }]
74|        }
75|    }
76|
77|
78|class SATRecord(BaseModel):
79|    """A record from SAT declarations for fiscal cross-reference."""
80|    id: str = Field(default="", description="SAT record identifier")
81|    tipo: DeclaracionTipo = Field(..., description="Declaration type")
82|    monto: float = Field(default=0.0, ge=0, description="Amount in MXN")
83|    periodo: str = Field(default="", description="Period YYYY-MM")
84|    rfc: Optional[str] = Field(default=None, description="RFC associated")
85|    fecha: Optional[str] = Field(default=None, description="Date YYYY-MM-DD")
86|
87|    model_config = {
88|        "json_schema_extra": {
89|            "examples": [{
90|                "id": "SAT-001",
91|                "tipo": "iva",
92|                "monto": 50000.0,
93|                "periodo": "2026-06",
94|            }]
95|        }
96|    }
97|
98|
99|# ---------------------------------------------------------------------------
100|# Omission schema
101|# ---------------------------------------------------------------------------
102|# Omission schema
103|# ---------------------------------------------------------------------------
104|
105|class Omission(BaseModel):
106|    """Una omisión fiscal detectada entre ERP y SAT."""
107|    id: str = Field(default="", description="Identificador único de la omisión")
108|    tipo: TipoOmicion = Field(
109|        ...,
110|        description="Tipo de omisión",
111|    )
112|    periodo: str = Field(
113|        ...,
114|        description="Período de la omisión (YYYY-MM)",
115|    )
116|    monto: float = Field(
117|        default=0.0,
118|        description="Monto asociado a la omisión",
119|    )
120|    rfc: Optional[str] = Field(
121|        default=None,
122|        description="RFC relacionado (si aplica)",
123|    )
124|    uuid_cfdi: Optional[str] = Field(
125|        default=None,
126|        description="UUID del CFDI relacionado (si aplica)",
127|    )
128|    detalle: str = Field(
129|        default="",
130|        description="Detalle descriptivo de la omisión",
131|    )
132|    resuelta: bool = Field(
133|        default=False,
134|        description="Si la omisión ya fue resuelta",
135|    )
136|
137|
138|# ---------------------------------------------------------------------------
139|# Fiscal Discrepancy schema
140|# ---------------------------------------------------------------------------
141|
142|class FiscalDiscrepancy(BaseModel):
143|    """Una discrepancia entre datos ERP y SAT."""
144|    id: str = Field(default="", description="Identificador único de la discrepancia")
145|    tipo: TipoDiscrepancia = Field(
146|        ...,
147|        description="Tipo de discrepancia",
148|    )
149|    erp_amount: float = Field(
150|        default=0.0,
151|        description="Monto registrado en ERP",
152|    )
153|    sat_amount: float = Field(
154|        default=0.0,
155|        description="Monto registrado en SAT",
156|    )
157|    diff: float = Field(
158|        default=0.0,
159|        description="Diferencia absoluta (ERP - SAT)",
160|    )
161|    explanation: str = Field(
162|        default="",
163|        description="Explicación o causa probable",
164|    )
165|    rfc: Optional[str] = Field(
166|        default=None,
167|        description="RFC relacionado",
168|    )
169|    periodo: Optional[str] = Field(
170|        default=None,
171|        description="Período (YYYY-MM)",
172|    )
173|    resuelta: bool = Field(
174|        default=False,
175|        description="Si la discrepancia ya fue resuelta",
176|    )
177|
178|
179|# ---------------------------------------------------------------------------
180|# Fiscal Comparison schema
181|# ---------------------------------------------------------------------------
182|
223|class ComplianceMixin:
224|    """CFF Art. 89: Adds fiscal compliance fields."""
225|    requires_human_review: bool = Field(default=False, description="Requires human review per CFF Art. 89")
226|    human_review_reason: str = Field(default="", description="Reason for human review")
227|    audit_trail: list = Field(default_factory=list, description="Audit trail entries")
228|    idempotency_key: str = Field(default="", description="Prevents duplicate processing")
229|    referencia_legal: str = Field(default="", description="Legal reference per CFF Art. 89")
230|    supuesto: str = Field(default="", description="Tax scenario per CFF Art. 89")
231|    escalation_path: str = Field(default="review_by_contador", description="Escalation path")
232|
233|
234|class FiscalReport(BaseModel, ComplianceMixin):
235|    """Reporte consolidado de conciliación fiscal."""
236|    id: str = Field(
237|        default="",


183|class FiscalComparison(BaseModel, ComplianceMixin):
184|    """Resultado de la comparación ERP vs SAT."""
185|    erp_total: float = Field(
186|        default=0.0,
187|        description="Total declarado en ERP",
188|    )
189|    sat_total: float = Field(
190|        default=0.0,
191|        description="Total declarado en SAT",
192|    )
193|    diferencia: float = Field(
194|        default=0.0,
195|        description="Diferencia absoluta (ERP - SAT)",
196|    )
197|    omisiones: List[Omission] = Field(
198|        default_factory=list,
199|        description="Omiciones detectadas",
200|    )
201|    discrepancias: List[FiscalDiscrepancy] = Field(
202|        default_factory=list,
203|        description="Discrepancias detectadas",
204|    )
205|    periodo: str = Field(
206|        default="",
207|        description="Período comparado (YYYY-MM)",
208|    )
209|    tenant_id: Optional[str] = Field(
210|        default=None,
211|        description="Tenant ID",
212|    )
213|    created_at: Optional[str] = Field(
214|        default=None,
215|        description="Fecha de creación ISO format",
216|    )
217|
218|
219|# ---------------------------------------------------------------------------
220|# Fiscal Report schema
221|# ---------------------------------------------------------------------------
222|
238|        description="Identificador único del reporte",
239|    )
240|    comparison: FiscalComparison = Field(
241|        default_factory=FiscalComparison,
242|        description="Resultado de comparación ERP vs SAT",
243|    )
244|    total_omisiones: int = Field(
245|        default=0,
246|        description="Número total de omisiones",
247|    )
248|    total_discrepancias: int = Field(
249|        default=0,
250|        description="Número total de discrepancias",
251|    )
252|    monto_total_omisiones: float = Field(
253|        default=0.0,
254|        description="Monto total de omisiones",
255|    )
256|    monto_total_discrepancias: float = Field(
257|        default=0.0,
258|        description="Monto total de discrepancias",
259|    )
260|    recomendaciones: List[str] = Field(
261|        default_factory=list,
262|        description="Recomendaciones para resolver omisiones y discrepancias",
263|    )
264|    created_at: Optional[str] = Field(
265|        default=None,
266|        description="Fecha de creación ISO format",
267|    )
268|