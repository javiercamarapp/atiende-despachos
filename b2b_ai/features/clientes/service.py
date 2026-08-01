# -*- coding: utf-8 -*-
"""
service.py — ClientService: query routing, FAQ search, invoice status, and response generation.

Routes client queries to the appropriate handler based on query type,
searches FAQ entries by keywords, looks up invoice status, and generates
draft responses using templates.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.clientes.models import (
    ClientQuery,
    FAQEntry,
    InvoiceStatus,
    QueryCategory,
    QueryType,
)


# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------

_RESPONSE_TEMPLATES = {
    QueryType.FACTURA: (
        "Estimado/a cliente, respecto a su consulta sobre factura: {contenido}. "
        "Le informamos que su comprobante fiscal ha sido procesado correctamente. "
        "Si necesita más detalles, por favor proporcione el folio fiscal (UUID) de su CFDI."
    ),
    QueryType.DEDUCCION: (
        "Estimado/a cliente, sobre la deducción de {concepto}: "
        "Este gasto es deducible conforme al artículo 105 de la LISR. "
        "Requerimos la factura XML (CFDI) y el comprobante de pago para procesarla."
    ),
    QueryType.ESTATUS: (
        "Estimado/a cliente, el estatus de su CFDI con ID {cfdi_id} es: {estado}. "
        "{observaciones}"
    ),
    QueryType.PREGUNTA: (
        "Estimado/a cliente, respecto a su pregunta: {contenido}. "
        "Le invitamos a revisar nuestra sección de FAQ o contactar a su asesor fiscal."
    ),
    QueryType.RECLAMO: (
        "Estimado/a cliente, hemos recibido su reclamo: {contenido}. "
        "Nuestro equipo lo revisará en un plazo de 48 horas hábiles. "
        "Le asignaremos un número de seguimiento."
    ),
}

# ---------------------------------------------------------------------------
# Default FAQ entries
# ---------------------------------------------------------------------------

_DEFAULT_FAQ: List[FAQEntry] = [
    FAQEntry(
        id="faq-001",
        question="¿Cuánto tiempo tengo para emitir una factura?",
        answer="Tiene hasta el último día del mes siguiente a la fecha de la operación para emitir su CFDI.",
        category=QueryCategory.FACTURACION,
        keywords=["factura", "tiempo", "plazo", "emitir"],
    ),
    FAQEntry(
        id="faq-002",
        question="¿Qué documentos necesito para deducir gastos?",
        answer="Necesita: factura XML (CFDI 4.0), comprobante de pago, y en su caso, contrato o acuerdo.",
        category=QueryCategory.IMPUESTOS,
        keywords=["deducir", "gastos", "documentos", "requisitos"],
    ),
    FAQEntry(
        id="faq-003",
        question="¿Cómo puedo verificar si un CFDI es válido?",
        answer="Ingrese al portal del SAT (consulta.sat.gob.mx) con el UUID, RFC emisor, fecha y monto total.",
        category=QueryCategory.FACTURACION,
        keywords=["verificar", "valido", "cfdi", "sat", "consulta"],
    ),
    FAQEntry(
        id="faq-004",
        question="¿Qué es el régimen fiscal?",
        answer="Es el código que identifica la obligación fiscal del contribuyente ante el SAT (ej. 601 General de Ley Personas Morales).",
        category=QueryCategory.IMPUESTOS,
        keywords=["regimen", "fiscal", "codigo", "sat"],
    ),
    FAQEntry(
        id="faq-005",
        question="¿Puedo pagar con transferencia bancaria?",
        answer="Sí, aceptamos transferencias SPEI. El comprobante bancario sustituye el efectivo para efectos fiscales.",
        category=QueryCategory.PAGOS,
        keywords=["pago", "transferencia", "banco", "spei"],
    ),
    FAQEntry(
        id="faq-006",
        question="¿Cómo cancelo una factura?",
        answer="El emisor puede cancelar el CFDI mediante Portal del SAT o software de facturación, indicando el motivo de cancelación.",
        category=QueryCategory.FACTURACION,
        keywords=["cancelar", "factura", "cancelacion", "cfdi"],
    ),
    FAQEntry(
        id="faq-007",
        question="¿Qué es la deducción de nómina?",
        answer="Los salarios y prestaciones pagados a empleados son deducibles siempre que se cuente con el CFDI de nómina.",
        category=QueryCategory.IMPUESTOS,
        keywords=["nomina", "deduccion", "empleados", "salarios"],
    ),
    FAQEntry(
        id="faq-008",
        question="¿Cuándo se aplica retención de ISR?",
        answer="La retención de ISR se aplica en los casos establecidos en la LISR, como servicios profesionales y arrendamiento.",
        category=QueryCategory.IMPUESTOS,
        keywords=["retencion", "isr", "impuesto", "reten"],
    ),
]


class ClientService:
    """Core service for client query management."""

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        # In-memory stores
        self._queries: Dict[str, ClientQuery] = {}
        self._faqs: List[FAQEntry] = list(_DEFAULT_FAQ)
        self._invoices: Dict[str, InvoiceStatus] = {}

    # -------------------------------------------------------------------
    # Query processing
    # -------------------------------------------------------------------

    def process_client_query(self, query: ClientQuery, tenant_id: Optional[str] = None) -> ClientQuery:
        """Route a client query to the appropriate handler and generate a draft response.

        Parameters
        ----------
        query : ClientQuery
            The incoming client query.
        tenant_id : Optional[str]
            Override tenant ID (uses query.tenant_id if not provided).

        Returns
        -------
        ClientQuery with respuesta populated.
        """
        if tenant_id:
            query.tenant_id = tenant_id

        if not query.id:
            query.id = str(_uuid.uuid4())
        if not query.created_at:
            query.created_at = datetime.now().isoformat()

        # Auto-classify category
        query.categoria = self._classify_query(query)

        # Route to handler
        data: Dict[str, Any] = {}

        if query.tipo == QueryType.FACTURA:
            data["contenido"] = query.contenido
        elif query.tipo == QueryType.DEDUCCION:
            data["concepto"] = query.contenido
        elif query.tipo == QueryType.ESTATUS:
            data["cfdi_id"] = self._extract_cfdi_id(query.contenido)
            invoice = self._invoices.get(data["cfdi_id"])
            if invoice:
                data["estado"] = invoice.estado
                data["observaciones"] = invoice.observaciones or ""
            else:
                data["estado"] = "no encontrado"
                data["observaciones"] = "No se encontró el CFDI con el ID proporcionado."
        elif query.tipo == QueryType.PREGUNTA:
            # Search FAQ
            faq_match = self._search_faq(query.contenido)
            if faq_match:
                data["contenido"] = faq_match.answer
            else:
                data["contenido"] = query.contenido
        elif query.tipo == QueryType.RECLAMO:
            data["contenido"] = query.contenido

        # Generate response
        query.respuesta = self.generate_client_response(query, data)
        return query

    def _classify_query(self, query: ClientQuery) -> QueryCategory:
        """Auto-classify a query into a category based on keywords."""
        content_lower = query.contenido.lower()

        # Keyword-based classification
        if any(kw in content_lower for kw in ["factura", "cfdi", "facturación", "timbrar", "timbre"]):
            return QueryCategory.FACTURACION
        if any(kw in content_lower for kw in ["deduc", "impuesto", "isr", "iva", "retención", "régimen"]):
            return QueryCategory.IMPUESTOS
        if any(kw in content_lower for kw in ["pago", "cobrar", "transferencia", "banco"]):
            return QueryCategory.PAGOS
        if any(kw in content_lower for kw in ["devolución", "devolver", "reembolso"]):
            return QueryCategory.DEVOLUCIONES
        return QueryCategory.GENERAL

    def _extract_cfdi_id(self, text: str) -> str:
        """Extract CFDI UUID from text (looks for UUID pattern)."""
        import re
        uuid_pattern = re.compile(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        )
        match = uuid_pattern.search(text)
        if match:
            return match.group(0)
        return text.strip()

    def _search_faq(self, query_text: str) -> Optional[FAQEntry]:
        """Search FAQ entries by keyword matching against the query text."""
        query_lower = query_text.lower()
        best_match: Optional[FAQEntry] = None
        best_score = 0

        for faq in self._faqs:
            # Check tenant compatibility
            if faq.tenant_id and faq.tenant_id != self.tenant_id:
                continue

            score = 0
            for keyword in faq.keywords:
                if keyword.lower() in query_lower:
                    score += 1
            # Also check question text
            question_words = faq.question.lower().split()
            for word in question_words:
                if len(word) > 3 and word in query_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = faq

        return best_match if best_score > 0 else None

    # -------------------------------------------------------------------
    # Invoice status
    # -------------------------------------------------------------------

    def get_invoice_status(self, cfdi_id: str) -> Optional[InvoiceStatus]:
        """Look up invoice status by CFDI ID (UUID).

        Parameters
        ----------
        cfdi_id : str
            The CFDI UUID or folio fiscal.

        Returns
        -------
        InvoiceStatus or None if not found.
        """
        return self._invoices.get(cfdi_id.strip())

    def register_invoice(self, invoice: InvoiceStatus) -> InvoiceStatus:
        """Register an invoice for status tracking."""
        if not invoice.cfdi_id:
            raise ValueError("cfdi_id es requerido")
        self._invoices[invoice.cfdi_id.strip()] = invoice
        return invoice

    # -------------------------------------------------------------------
    # Deductibility info
    # -------------------------------------------------------------------

    def get_deductibility_info(self, concepto: str) -> Dict[str, Any]:
        """Return deductibility information for a given concept/gasto.

        Parameters
        ----------
        concepto : str
            Description of the expense concept.

        Returns
        -------
        Dict with deductibility info: deductible, percentage, requirements, notes.
        """
        concepto_lower = concepto.lower()

        # Common deductible categories
        categories = [
            {
                "keywords": ["salario", "nómina", "sueldo", "prestacion"],
                "deductible": True,
                "percentage": 100.0,
                "requirements": ["CFDI de nómina", "Timbrado por el SAT"],
                "notes": "Los salarios son deducibles al 100% conforme al art. 28 LISR.",
            },
            {
                "keywords": ["renta", "arrendamiento", "oficina"],
                "deductible": True,
                "percentage": 100.0,
                "requirements": ["CFDI del arrendador", "Contrato de arrendamiento"],
                "notes": "Renta de inmuebles dedicados al activity empresarial es deducible.",
            },
            {
                "keywords": ["luz", "agua", "gas", "telefono", "internet", "servicio"],
                "deductible": True,
                "percentage": 100.0,
                "requirements": ["CFDI a nombre del contribuyente"],
                "notes": "Servicios públicos son deducibles si se destinan a la actividad empresarial.",
            },
            {
                "keywords": ["equipo", "mobiliario", "computadora", "software"],
                "deductible": True,
                "percentage": 100.0,
                "requirements": ["CFDI de compra", "Inventario registrado"],
                "notes": "Bienes muebles: deducibles por depreciación según tabla del art. 219 LISR.",
            },
            {
                "keywords": ["viatico", "viaje", "hotel", "pasaje"],
                "deductible": True,
                "percentage": 100.0,
                "requirements": ["CFDI de cada gasto", "Comprobante de viaje"],
                "notes": "Viáticos son deducibles si se comprueba el viaje de negocios.",
            },
            {
                "keywords": ["comida", "alimentacion", "restaurante", "cena"],
                "deductible": True,
                "percentage": 50.0,
                "requirements": ["CFDI del restaurante"],
                "notes": "Gastos de alimentos: deducibles al 50% conforme al art. 28 fracc. II LISR.",
            },
            {
                "keywords": ["multa", "sancion", "penalizacion"],
                "deductible": False,
                "percentage": 0.0,
                "requirements": [],
                "notes": "Las multas y sanciones no son deducibles (art. 28 fracc. X LISR).",
            },
        ]

        for cat in categories:
            for kw in cat["keywords"]:
                if kw in concepto_lower:
                    return {
                        "concepto": concepto,
                        "deductible": cat["deductible"],
                        "percentage": cat["percentage"],
                        "requirements": cat["requirements"],
                        "notes": cat["notes"],
                    }

        return {
            "concepto": concepto,
            "deductible": None,
            "percentage": None,
            "requirements": [],
            "notes": "No se encontró información específica. Consulte con su contador.",
        }

    # -------------------------------------------------------------------
    # FAQ management
    # -------------------------------------------------------------------

    def get_faqs(self, category: Optional[QueryCategory] = None) -> List[FAQEntry]:
        """Return FAQ entries, optionally filtered by category."""
        if category:
            return [f for f in self._faqs if f.category == category]
        return list(self._faqs)

    def add_faq(self, entry: FAQEntry) -> FAQEntry:
        """Add a new FAQ entry."""
        if not entry.id:
            entry.id = f"faq-{len(self._faqs) + 1:03d}"
        self._faqs.append(entry)
        return entry

    # -------------------------------------------------------------------
    # Response generation
    # -------------------------------------------------------------------

    def generate_client_response(self, query: ClientQuery, data: Dict[str, Any]) -> str:
        """Generate a draft response using templates and context data.

        Parameters
        ----------
        query : ClientQuery
            The original query.
        data : dict
            Context data extracted during routing.

        Returns
        -------
        Draft response string.
        """
        template = _RESPONSE_TEMPLATES.get(query.tipo, _RESPONSE_TEMPLATES[QueryType.PREGUNTA])

        try:
            response = template.format(**data)
        except KeyError:
            # Fallback: fill what we can
            response = template
            for key, value in data.items():
                response = response.replace("{" + key + "}", str(value))
            # Replace any remaining unreplaced placeholders
            import re
            response = re.sub(r"\{[^}]+\}", "", response)

        return response.strip()
