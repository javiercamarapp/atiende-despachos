# -*- coding: utf-8 -*-
"""
balanza.py — Balanza de comprobación mensual para contabilidad electrónica
del SAT (XSD balanzaComprobacion, v1.3).

Clase principal:
    BalanzaComprobacion — construye y valida la balanza mensual a partir de
    asientos contables, y genera el XML para envío al SAT.

Campos por cuenta: codigo, descripcion, saldoInicial, debe, haber, saldoFinal.

Responsabilidades:
  - Acumular movimientos por período (mes) y por cuenta.
  - Validar cuadratura: suma(debe) == suma(haber).
  - Detectar cuentas con saldos anómalos (debe/haber de signo contrario a su
    naturaleza o muy desbalanceadas).
  - Generar el XML conforme al schema del SAT.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List, Optional

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas


def _dec(v, default=Decimal("0")):
    try:
        if v is None or v == "":
            return default
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return default


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(d):
    return "{:.2f}".format(_round2(d))


class BalanzaComprobacion:
    """Balanza de comprobación mensual.

    `cuentas` puede ser un CatalogoCuentas (para descripciones/naturaleza) o
    None (se usan heurísticas básicas para las cuentas no catalogadas).

    Uso:
        bal = BalanzaComprobacion(catalogo)
        bal.generar(asientos, periodo="2026-07")
        bal.validar_cuadratura()      # bool
        xml = bal.generar_xml(rfc="...", ejercicio=2026, mes=7)
    """

    def __init__(self, catalogo: Optional[CatalogoCuentas] = None,
                 cuentas_iniciales: Optional[dict] = None):
        self.catalogo = catalogo or CatalogoCuentas([])
        # cuentas_iniciales: {codigo: saldo_inicial_decimal_or_str}
        self.saldos_iniciales = {
            str(k): _dec(v) for k, v in (cuentas_iniciales or {}).items()}
        self.periodo = None
        # lineas: list[dict] con cuenta, descripcion, saldo_inicial, debe,
        # haber, saldo_final
        self.lineas: List[dict] = []
        self._asientos: List[dict] = []

    # ---- Acumulación -------------------------------------------------------
    def _descripcion(self, codigo):
        c = self.catalogo.find(codigo)
        if c:
            return c.descripcion
        # Heurística: tomar el grupo por prefijo si no está en el catálogo.
        return "Cuenta %s" % codigo

    def _naturaleza(self, codigo):
        c = self.catalogo.find(codigo)
        if c:
            return c.naturaleza.upper()
        return "D"

    def acumular(self, asientos: List[dict]) -> dict:
        """Acumula los movimientos {cuenta, debe, haber} por cuenta.

        Devuelve {cuenta: {"debe": Decimal, "haber": Decimal}}."""
        acc = defaultdict(lambda: {"debe": Decimal("0"), "haber": Decimal("0")})
        for a in asientos or []:
            cta = a.get("cuenta")
            if not cta:
                continue
            acc[str(cta)]["debe"] += _dec(a.get("debe"))
            acc[str(cta)]["haber"] += _dec(a.get("haber"))
        return acc

    def generar(self, asientos: List[dict], periodo: Optional[str] = None,
                saldos_iniciales: Optional[dict] = None) -> dict:
        """Construye la balanza del período desde los asientos contables.

        asientos: list[dict] con {cuenta, debe, haber, fecha?}.
        periodo: 'YYYY-MM'. Si los asientos traen fecha, se filtra por mes.
        saldos_iniciales: opcional {cuenta: monto}.

        Devuelve el resumen de la balanza (dict) y llena `self.lineas`.
        """
        self.periodo = periodo
        if saldos_iniciales is not None:
            self.saldos_iniciales = {str(k): _dec(v)
                                     for k, v in saldos_iniciales.items()}

        # Filtrar por período cuando hay fecha en los asientos.
        rows = list(asientos or [])
        if periodo:
            p = str(periodo)
            filt = []
            for a in rows:
                fecha = a.get("fecha")
                if fecha is None or str(fecha)[:7] == p:
                    filt.append(a)
            rows = filt
        self._asientos = rows

        acc = self.acumular(rows)
        self.lineas = []
        for cta in sorted(acc):
            debe = acc[cta]["debe"]
            haber = acc[cta]["haber"]
            saldo_ini = self.saldos_iniciales.get(str(cta), Decimal("0"))
            nat = self._naturaleza(cta)
            if nat == "D":
                saldo_fin = saldo_ini + debe - haber
            else:
                saldo_fin = saldo_ini + haber - debe
            self.lineas.append({
                "cuenta": str(cta),
                "descripcion": self._descripcion(cta),
                "nivel": self._nivel(cta),
                "naturaleza": nat,
                "saldo_inicial": _fmt(saldo_ini),
                "debe": _fmt(debe),
                "haber": _fmt(haber),
                "saldo_final": _fmt(saldo_fin),
            })
        return self.resumen()

    def _nivel(self, codigo):
        c = self.catalogo.find(codigo)
        return c.nivel if c else 3

    # ---- Resumen -----------------------------------------------------------
    def resumen(self) -> dict:
        total_debe = sum(_dec(l["debe"]) for l in self.lineas)
        total_haber = sum(_dec(l["haber"]) for l in self.lineas)
        return {
            "periodo": self.periodo,
            "cuentas": len(self.lineas),
            "total_debe": _fmt(total_debe),
            "total_haber": _fmt(total_haber),
            "cuadrada": total_debe == total_haber,
            "saldos_anomalos": [l["cuenta"] for l in self.detectar_saldos_anomalos()],
            "lineas": self.lineas,
        }

    def validar_cuadratura(self) -> bool:
        """True si suma(debe) == suma(haber)."""
        return (sum(_dec(l["debe"]) for l in self.lineas)
                == sum(_dec(l["haber"]) for l in self.lineas))

    def detectar_saldos_anomalos(self, umbral=0.01) -> List[dict]:
        """Devuelve las cuentas con saldo anómalo.

        Una cuenta es anómala si su saldo final contradice su naturaleza:
        - Deudora ('D') con saldo final negativo (debe < haber por encima del
          umbral).
        - Acreedora ('A') con saldo final negativo (haber < debe por encima
          del umbral).
        Es decir, si el saldo calculado para su naturaleza es negativo.
        """
        anomalos = []
        for l in self.lineas:
            saldo_fin = _dec(l["saldo_final"])
            nat = l["naturaleza"]
            if nat == "D" and saldo_fin < -umbral:
                anomalos.append({**l, "razon": "saldo deudor negativo"})
            elif nat == "A" and saldo_fin < -umbral:
                anomalos.append({**l, "razon": "saldo acreedor negativo"})
        return anomalos

    # ---- Generación XML -----------------------------------------------------
    def generar_xml(self, rfc="", ejercicio=None, mes=None,
                    tipo_envio="B") -> str:
        """Genera el XML de balanza de comprobación (XSD balanzaComprobacion
        1.3 del SAT). Devuelve el XML como string."""
        import xml.sax.saxutils as sx

        ejercicio = ejercicio or datetime.now().year
        mes = int(mes or 1)
        mes_s = str(mes).zfill(2)
        hoy = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        def esc(v):
            return sx.escape(str(v or ""))

        ctas = "\n".join(
            '      <BCE:Cta NumCta="%s" SaldoIni="%s" Debe="%s" Haber="%s" '
            'SaldoFin="%s"/>'
            % (esc(l["cuenta"]), esc(l["saldo_inicial"]), esc(l["debe"]),
               esc(l["haber"]), esc(l["saldo_final"]))
            for l in self.lineas)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<BCE:Balanza '
            'xmlns:BCE="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/BalanzaComprobacion" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/BalanzaComprobacion '
            'http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/BalanzaComprobacion/BalanzaComprobacion_1_3.xsd" '
            'Version="1.3" TipoEnvio="%s" RFC="%s" Mes="%s" Anio="%s" '
            'FechaModificacion="%s" Sello="" noCertificado="" Certificado="">\n'
            '  <BCE:Ctas>\n%s\n  </BCE:Ctas>\n'
            '</BCE:Balanza>\n' % (esc(tipo_envio), esc(rfc), mes_s,
                                  ejercicio, hoy, ctas))
