# -*- coding: utf-8 -*-
"""
contabilidad_electronica.py — Orquestador de contabilidad electrónica del SAT.

Clase principal:
    ContabilidadElectronica — integra catálogo de cuentas + balanza de
    comprobación en un solo flujo que genera los archivos XML listos para
    timbrado, calcula el hash SHA-1 exigido por el SAT y produce el resumen
    mensual.

Ciclo de estados de un paquete:
    borrador -> listo_para_timbrar -> timbrado -> enviado

Responsabilidades:
  - Generar el paquete de contabilidad electrónica (catálogo + balanza) para
    un período mensual.
  - Calcular el hash SHA-1 del archivo XML (requisito SAT).
  - Generar el resumen mensual.
  - Llevar el control de estados del paquete (persistido en DB si se pasa db).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas
from b2b_ai.services.balanza import BalanzaComprobacion

ESTADOS: tuple = ("borrador", "listo_para_timbrar", "timbrado", "enviado")

# Estado por defecto de un paquete recién creado.
ESTADO_INICIAL = "borrador"


class ContabilidadElectronica:
    """Integra catálogo + balanza en el flujo de contabilidad electrónica.

    `db` opcional: si se pasa, los paquetes generados se persisten en la
    tabla `paquetes_contabilidad` y el estado se actualiza en la DB.
    """

    def __init__(self, catalogo: Optional[CatalogoCuentas] = None,
                 db: Optional[Any] = None, tenant_id: Optional[Any] = None,
                 rfc: str = "", razon_social: str = "",
                 ejercicio: Optional[int] = None, mes: Optional[int] = None) -> None:
        self.catalogo = catalogo or CatalogoCuentas()
        self.db = db
        self.tenant_id = tenant_id
        self.rfc = rfc
        self.razon_social = razon_social
        self.ejercicio = ejercicio or datetime.now().year
        self.mes = mes or 1
        # Estado del paquete en curso.
        self.estado = ESTADO_INICIAL
        self._paquete = None
        self._paquete_id = None

    # ---- Utilidades ---------------------------------------------------------
    @staticmethod
    def calcular_hash_sha1(contenido: bytes) -> str:
        """SHA-1 en hexadecimal del contenido (requisito SAT)."""
        # El SAT exige SHA-1 como checksum del archivo de catálogo/balanza.
        # No es un uso criptográfico de seguridad (integridad de firma), es un
        # resumen de archivo obligatorio por la especificación. Se marca
        # usedforsecurity=False para aclararlo ante herramientas de análisis.
        return hashlib.sha1(contenido, usedforsecurity=False).hexdigest()

    def _periodo(self) -> str:
        return "%s-%02d" % (self.ejercicio, int(self.mes))

    # ---- Generación del paquete ----------------------------------------------
    def generar_paquete(self, asientos: List[Dict[str, Any]],
                        saldos_iniciales: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Genera el paquete de contabilidad electrónica del mes.

        asientos: list[dict] con {cuenta, debe, haber, fecha?}.
        saldos_iniciales: opcional {cuenta: monto}.

        Devuelve un dict con catálogo + balanza XML, su hash SHA-1 y el
        resumen. Deja el paquete en estado 'listo_para_timbrar'.
        """
        self.estado = ESTADO_INICIAL

        balanza = BalanzaComprobacion(self.catalogo)
        resumen_balanza = balanza.generar(asientos, periodo=self._periodo(),
                                          saldos_iniciales=saldos_iniciales)

        xml_catalogo = self.catalogo.generar_xml(
            rfc=self.rfc, ejercicio=self.ejercicio, mes=self.mes)
        xml_balanza = balanza.generar_xml(
            rfc=self.rfc, ejercicio=self.ejercicio, mes=self.mes)

        hash_catalogo = self.calcular_hash_sha1(xml_catalogo.encode("utf-8"))
        hash_balanza = self.calcular_hash_sha1(xml_balanza.encode("utf-8"))

        paquete = {
            "periodo": self._periodo(),
            "ejercicio": self.ejercicio,
            "mes": int(self.mes),
            "rfc": self.rfc,
            "razon_social": self.razon_social,
            "catalogo": {"xml": xml_catalogo, "sha1": hash_catalogo,
                         "cuentas": len(self.catalogo)},
            "balanza": {"xml": xml_balanza, "sha1": hash_balanza,
                        "cuadrada": resumen_balanza["cuadrada"],
                        "cuentas": resumen_balanza["cuentas"]},
            "resumen_balanza": resumen_balanza,
            "estado": "listo_para_timbrar",
            "generado_en": datetime.now().isoformat(timespec="seconds"),
        }
        self._paquete = paquete
        self._avanzar_estado("listo_para_timbrar")
        self._persistir_paquete()
        return paquete

    # ---- Resumen mensual ------------------------------------------------------
    def generar_resumen_mensual(self, asientos: Optional[List[Dict[str, Any]]] = None,
                                paquete: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Genera el resumen mensual de contabilidad electrónica."""
        paquete = paquete or self._paquete
        if asientos is None and paquete is None:
            raise ValueError("Se requiere asientos o un paquete generado.")
        if paquete is None:
            bal = BalanzaComprobacion(self.catalogo)
            rb = bal.generar(asientos, periodo=self._periodo())
            resumen = rb
        else:
            resumen = paquete["resumen_balanza"]
        total_debe = resumen.get("total_debe", "0.00")
        total_haber = resumen.get("total_haber", "0.00")
        return {
            "periodo": self._periodo(),
            "rfc": self.rfc,
            "razon_social": self.razon_social,
            "cuentas": resumen.get("cuentas", 0),
            "total_debe": total_debe,
            "total_haber": total_haber,
            "cuadrada": resumen.get("cuadrada", False),
            "saldos_anomalos": resumen.get("saldos_anomalos", []),
            "estado": self.estado,
            "paquete_id": self._paquete_id,
        }

    # ---- Control de estados ----------------------------------------------------
    def _avanzar_estado(self, estado: str) -> None:
        if estado not in ESTADOS:
            raise ValueError("Estado inválido: %r" % estado)
        self.estado = estado
        if self.db and self._paquete_id:
            self.db.update_paquete_estado(self._paquete_id, estado)

    def marcar_listo_para_timbrar(self) -> str:
        """Transición borrador -> listo_para_timbrar."""
        self._avanzar_estado("listo_para_timbrar")
        return self.estado

    def marcar_timbrado(self) -> str:
        """Transición listo_para_timbrar -> timbrado."""
        if self.estado not in ("listo_para_timbrar", "timbrado"):
            raise ValueError("No se puede timbrar desde estado %r" % self.estado)
        self._avanzar_estado("timbrado")
        return self.estado

    def marcar_enviado(self) -> str:
        """Transición timbrado -> enviado."""
        if self.estado not in ("timbrado", "enviado"):
            raise ValueError("No se puede enviar desde estado %r" % self.estado)
        self._avanzar_estado("enviado")
        return self.estado

    # ---- Persistencia (opcional) ------------------------------------------------
    def _persistir_paquete(self) -> Optional[Any]:
        if not self.db or self._paquete is None:
            return None
        paquete_id = self.db.insert_paquete_contabilidad(
            tenant_id=self.tenant_id, periodo=self._periodo(),
            rfc=self.rfc, estado=self.estado,
            payload=self._paquete)
        self._paquete_id = paquete_id
        return paquete_id

    # ---- Vistas ----------------------------------------------------------------
    def obtener_paquete(self) -> Optional[Dict[str, Any]]:
        return self._paquete

    def estado_actual(self) -> str:
        return self.estado
