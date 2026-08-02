# -*- coding: utf-8 -*-
"""Tests for b2b_ai.features.declaraciones.fiel_signer — FIEL digital signing."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestFIELSigner:
    """Test FIELSigner without real certificates (mocked)."""

    @pytest.fixture
    def mock_signer(self):
        """Create a FIELSigner with mocked crypto components."""
        from b2b_ai.features.declaraciones.fiel_signer import (
            FIELSigner, CertificateInfo
        )

        info = CertificateInfo(
            serial_number="1234567890123456789012345",
            no_certificado="01234567890123456789",
            issuer="CN=SAT",
            subject="CN=Test RFC",
            not_valid_before=datetime.utcnow() - timedelta(days=365),
            not_valid_after=datetime.utcnow() + timedelta(days=365),
            is_expired=False,
            days_until_expiry=365,
            rfc="TESTRFC010101",
        )

        mock_key = MagicMock()
        mock_key.sign.return_value = b"\x00" * 256  # 256-byte RSA signature

        signer = FIELSigner(
            certificate=b"mock_cert_bytes",
            private_key=mock_key,
            certificate_info=info,
        )
        return signer

    def test_no_certificado_length(self, mock_signer):
        """NoCertificado must be exactly 20 digits (SAT requirement)."""
        assert len(mock_signer.no_certificado) == 20
        assert mock_signer.no_certificado.isdigit()

    def test_certificate_b64_encoding(self, mock_signer):
        """Certificate should be base64-encoded for XML embedding."""
        import base64
        b64 = mock_signer.certificate_b64
        decoded = base64.b64decode(b64)
        assert decoded == b"mock_cert_bytes"

    def test_sign_returns_bytes(self, mock_signer):
        """sign() should return bytes (RSA signature)."""
        sig = mock_signer.sign(b"test data to sign")
        assert isinstance(sig, bytes)
        assert len(sig) > 0

    def test_sign_b64_returns_string(self, mock_signer):
        """sign_b64() should return base64 string."""
        import base64
        sig_b64 = mock_signer.sign_b64(b"test data")
        assert isinstance(sig_b64, str)
        # Should be valid base64
        base64.b64decode(sig_b64)

    def test_stamp_xml_adds_attributes(self, mock_signer):
        """stamp_xml() should add Sello, Certificado, NoCertificado to root."""
        xml = b'<?xml version="1.0"?><root/>'
        stamped = mock_signer.stamp_xml(xml, "fake_sello_base64")
        assert b'Sello="fake_sello_base64"' in stamped
        assert b'Certificado=' in stamped
        assert b'NoCertificado="01234567890123456789"' in stamped

    def test_stamp_xml_invalid_xml_raises(self, mock_signer):
        """stamp_xml() with malformed XML should raise FIELSignerError."""
        from b2b_ai.features.declaraciones.fiel_signer import FIELSignerError
        with pytest.raises(FIELSignerError, match="inválido"):
            mock_signer.stamp_xml(b"not xml at all>", "sello")

    def test_check_validity_valid_cert(self, mock_signer):
        """check_validity() for non-expired cert should return True."""
        is_valid, msg = mock_signer.check_validity()
        assert is_valid is True
        assert "vigente" in msg.lower() or "advertencia" in msg.lower()

    def test_check_validity_expired_cert(self):
        """check_validity() for expired cert should return False."""
        from b2b_ai.features.declaraciones.fiel_signer import (
            FIELSigner, CertificateInfo, FIELSignerError
        )
        info = CertificateInfo(
            serial_number="1234567890123456789012345",
            no_certificado="01234567890123456789",
            issuer="CN=SAT",
            subject="CN=Test",
            not_valid_before=datetime.utcnow() - timedelta(days=730),
            not_valid_after=datetime.utcnow() - timedelta(days=1),
            is_expired=True,
            days_until_expiry=0,
        )
        signer = FIELSigner(
            certificate=b"cert", private_key=MagicMock(), certificate_info=info,
        )
        is_valid, msg = signer.check_validity()
        assert is_valid is False
        assert "expirado" in msg.lower()

    def test_sign_declaration_expired_raises(self):
        """sign_declaration() should raise if certificate is expired."""
        from b2b_ai.features.declaraciones.fiel_signer import (
            FIELSigner, CertificateInfo, FIELSignerError
        )
        info = CertificateInfo(
            serial_number="1234567890123456789012345",
            no_certificado="01234567890123456789",
            issuer="CN=SAT", subject="CN=Test",
            not_valid_before=datetime.utcnow() - timedelta(days=730),
            not_valid_after=datetime.utcnow() - timedelta(days=1),
            is_expired=True, days_until_expiry=0,
        )
        signer = FIELSigner(
            certificate=b"cert", private_key=MagicMock(), certificate_info=info,
        )
        with pytest.raises(FIELSignerError):
            signer.sign_declaration(b"<root/>")

    def test_sign_declaration_full_workflow(self, mock_signer):
        """sign_declaration() should return stamped XML."""
        xml = b'<?xml version="1.0" encoding="UTF-8"?><root/>'
        result = mock_signer.sign_declaration(xml)
        assert isinstance(result, bytes)
        assert b"Sello=" in result
        assert b"Certificado=" in result
        assert b"NoCertificado=" in result


class TestValidateRFCWithDigit:
    """Test RFC format validation."""

    def test_valid_moral_rfc(self):
        from b2b_ai.features.declaraciones.fiel_signer import validate_rfc_with_digit
        assert validate_rfc_with_digit("ABC123456T10") is True

    def test_valid_fisica_rfc(self):
        from b2b_ai.features.declaraciones.fiel_signer import validate_rfc_with_digit
        assert validate_rfc_with_digit("XAXX010101000") is True

    def test_invalid_rfc_too_short(self):
        from b2b_ai.features.declaraciones.fiel_signer import validate_rfc_with_digit
        assert validate_rfc_with_digit("AB") is False

    def test_invalid_rfc_empty(self):
        from b2b_ai.features.declaraciones.fiel_signer import validate_rfc_with_digit
        assert validate_rfc_with_digit("") is False

    def test_invalid_rfc_none(self):
        from b2b_ai.features.declaraciones.fiel_signer import validate_rfc_with_digit
        assert validate_rfc_with_digit(None) is False


class TestFromFileErrors:
    """Test error paths in from_files()."""

    def test_missing_cert_file(self):
        from b2b_ai.features.declaraciones.fiel_signer import (
            FIELSigner, FIELSignerError
        )
        with pytest.raises(FIELSignerError, match="no encontrado"):
            FIELSigner.from_files(
                cer_path="/nonexistent/cert.cer",
                key_path="/nonexistent/key.key",
                password="test",
            )
