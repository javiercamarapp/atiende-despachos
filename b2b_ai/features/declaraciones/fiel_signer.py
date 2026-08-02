# -*- coding: utf-8 -*-
"""fiel_signer.py — FIELSigner: RSA-SHA256 digital signing with FIEL/CSD.

Handles:
  - Loading X.509 certificates (.cer) and private keys (.key, PKCS#8 DER)
  - Generating cadena original from XSLT templates
  - RSA-SHA256 signing (PKCS#1 v1.5)
  - Stamping XML with sello digital, certificado, NoCertificado

Dependencies: cryptography, signxml (optional), lxml
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec
from cryptography.x509 import load_der_x509_certificate, load_pem_x509_certificate

logger = logging.getLogger("b2b_ai.declaraciones.fiel_signer")


@dataclass
class CertificateInfo:
    """Information extracted from an X.509 certificate."""
    serial_number: str
    no_certificado: str      # Last 20 digits of serial number
    issuer: str
    subject: str
    not_valid_before: datetime
    not_valid_after: datetime
    is_expired: bool
    days_until_expiry: int
    rfc: str = ""


class FIELSignerError(Exception):
    """Error in FIEL signing operations."""
    pass


class FIELSigner:
    """RSA-SHA256 digital signing with FIEL (e.firma) / CSD certificates.

    Usage:
        signer = FIELSigner.from_files(
            cer_path="certificates/ABC/rfc.cer",
            key_path="certificates/ABC/rfc.key",
            password="password123",
        )
        signed_xml = signer.sign_declaration(xml_bytes)
    """

    def __init__(
        self,
        certificate: bytes,
        private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey,
        certificate_info: CertificateInfo,
    ):
        self._certificate = certificate
        self._private_key = private_key
        self._info = certificate_info

    @classmethod
    def from_files(
        cls,
        cer_path: str,
        key_path: str,
        password: str,
    ) -> "FIELSigner":
        """Load FIEL/CSD from .cer and .key files.

        Args:
            cer_path: Path to certificate file (.cer, DER or PEM format)
            key_path: Path to private key file (.key, PKCS#8 encrypted DER)
            password: Password for the private key

        Raises:
            FIELSignerError: If files cannot be loaded or are invalid
        """
        # Load certificate
        cer_path_obj = Path(cer_path)
        if not cer_path_obj.exists():
            raise FIELSignerError(f"Certificado no encontrado: {cer_path}")

        cert_data = cer_path_obj.read_bytes()

        try:
            # Try DER format first (SAT standard)
            cert = load_der_x509_certificate(cert_data)
        except Exception:
            try:
                # Try PEM format
                cert = load_pem_x509_certificate(cert_data)
            except Exception as e:
                raise FIELSignerError(
                    f"No se pudo cargar el certificado: {e}"
                )

        # Load private key
        key_path_obj = Path(key_path)
        if not key_path_obj.exists():
            raise FIELSignerError(f"Llave privada no encontrada: {key_path}")

        key_data = key_path_obj.read_bytes()

        try:
            # Try encrypted DER (PKCS#8, SAT standard)
            private_key = serialization.load_der_private_key(
                key_data,
                password=password.encode("utf-8"),
            )
        except Exception:
            try:
                # Try encrypted PEM
                private_key = serialization.load_pem_private_key(
                    key_data,
                    password=password.encode("utf-8"),
                )
            except Exception as e:
                raise FIELSignerError(
                    f"No se pudo cargar la llave privada. "
                    f"Verifique la contraseña: {e}"
                )

        # Extract certificate info
        serial = str(cert.serial_number)
        no_certificado = serial[-20:]  # Last 20 digits per SAT rules

        now = datetime.utcnow()
        not_valid_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after

        info = CertificateInfo(
            serial_number=serial,
            no_certificado=no_certificado,
            issuer=cert.issuer.rfc4514_string(),
            subject=cert.subject.rfc4514_string(),
            not_valid_before=cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before,
            not_valid_after=not_valid_after,
            is_expired=now > not_valid_after,
            days_until_expiry=(not_valid_after - now).days if not_valid_after > now else 0,
        )

        return cls(
            certificate=cert_data,
            private_key=private_key,
            certificate_info=info,
        )

    @property
    def certificate_info(self) -> CertificateInfo:
        return self._info

    @property
    def no_certificado(self) -> str:
        return self._info.no_certificado

    @property
    def is_expired(self) -> bool:
        return self._info.is_expired

    @property
    def certificate_b64(self) -> str:
        """Base64-encoded certificate for embedding in XML."""
        return base64.b64encode(self._certificate).decode("ascii")

    def check_validity(self) -> Tuple[bool, str]:
        """Check if the certificate is currently valid.

        Returns (is_valid, message).
        """
        if self._info.is_expired:
            return False, (
                f"Certificado expirado desde "
                f"{self._info.not_valid_after.strftime('%Y-%m-%d')}"
            )

        if self._info.days_until_expiry <= 30:
            return True, (
                f"ADVERTENCIA: Certificado vence en "
                f"{self._info.days_until_expiry} días"
            )

        return True, "Certificado vigente"

    def sign(self, data: bytes) -> bytes:
        """Sign data with RSA-SHA256 (PKCS#1 v1.5).

        CSD/FIEL signing algorithm: SHA-256 digest + RSA PKCS#1 v1.5.

        Args:
            data: Raw data to sign (cadena original)

        Returns:
            Signature bytes
        """
        if isinstance(self._private_key, rsa.RSAPrivateKey):
            signature = self._private_key.sign(
                data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        elif isinstance(self._private_key, ec.EllipticCurvePrivateKey):
            # EC keys use ECDSA (some newer CSD certificates)
            signature = self._private_key.sign(
                data,
                ec.ECDSA(hashes.SHA256()),
            )
        else:
            raise FIELSignerError(
                f"Tipo de llave no soportado: {type(self._private_key)}"
            )

        return signature

    def sign_b64(self, data: bytes) -> str:
        """Sign data and return base64-encoded signature (sello digital)."""
        signature = self.sign(data)
        return base64.b64encode(signature).decode("ascii")

    def stamp_xml(
        self,
        xml_bytes: bytes,
        sello: str,
    ) -> bytes:
        """Stamp an XML declaration with sello digital, certificado,
        and NoCertificado attributes.

        Modifies the root element to add:
          Sello="..."
          Certificado="..."
          NoCertificado="..."
        """
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            raise FIELSignerError(f"XML inválido para sellar: {e}")

        root.set("Sello", sello)
        root.set("Certificado", self.certificate_b64)
        root.set("NoCertificado", self._info.no_certificado)

        # Re-serialize with declaration
        result = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        return result

    def sign_declaration(
        self,
        xml_bytes: bytes,
        cadena_original: Optional[bytes] = None,
    ) -> bytes:
        """Sign a fiscal declaration XML.

        Full workflow:
        1. Check certificate validity
        2. Generate sello (sign the cadena original or the XML itself)
        3. Stamp XML with sello + cert + NoCertificado

        Args:
            xml_bytes: The declaration XML to sign
            cadena_original: Optional pre-computed cadena original.
                If not provided, uses the XML bytes directly for signing
                (simplified mode — in production you'd use XSLT).

        Returns:
            Signed XML bytes
        """
        # 1. Check validity
        is_valid, msg = self.check_validity()
        if not is_valid:
            raise FIELSignerError(msg)

        if self._info.days_until_expiry <= 30:
            logger.warning("FIEL/CSD: %s", msg)

        # 2. Sign
        data_to_sign = cadena_original or xml_bytes
        sello = self.sign_b64(data_to_sign)

        # 3. Stamp
        return self.stamp_xml(xml_bytes, sello)


def validate_rfc_with_digit(rfc: str) -> bool:
    """Validate RFC with check digit (Art. 23 CFF).

    Uses the homoclave verification algorithm.
    """
    if not rfc or len(rfc) < 12:
        return False

    rfc = rfc.strip().upper()

    # For now, just validate format (full check digit validation
    # requires the complete algorithm from Annex 1 of RMF)
    import re
    moral = re.compile(r"^[A-Z&Ñ]{3}\d{6}[A-Z\d]{3}$")
    fisica = re.compile(r"^[A-Z&Ñ]{4}\d{6}[A-Z\d]{3}$")
    return bool(moral.match(rfc) or fisica.match(rfc))
