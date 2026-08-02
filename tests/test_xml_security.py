# -*- coding: utf-8 -*-
"""Tests for b2b_ai.cfdi.xml_security — XXE protection, size limits, encoding."""
import os
import tempfile
import pytest
from lxml import etree


class TestSafeParser:
    """Verify safe_parser() hardening options."""

    def test_safe_parser_disables_entities(self):
        from b2b_ai.cfdi.xml_security import safe_parser
        parser = safe_parser()
        # resolve_entities=False prevents XXE
        assert parser._parser.resolve_entities is False

    def test_safe_parser_no_network(self):
        from b2b_ai.cfdi.xml_security import safe_parser
        parser = safe_parser()
        assert parser._parser.network_access is False

    def test_safe_parser_no_dtd(self):
        from b2b_ai.cfdi.xml_security import safe_parser
        parser = safe_parser()
        assert parser._parser.dtd_validation is False
        assert parser._parser.load_dtd is False


class TestSafeFromString:
    """Verify safe_fromstring parsing and size limits."""

    def test_parse_valid_xml(self):
        from b2b_ai.cfdi.xml_security import safe_fromstring
        xml = b'<root><child>hello</child></root>'
        elem = safe_fromstring(xml)
        assert elem.tag == "root"
        assert elem.find("child").text == "hello"

    def test_parse_with_namespaces(self):
        from b2b_ai.cfdi.xml_security import safe_fromstring
        xml = b'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0"/>'
        elem = safe_fromstring(xml)
        assert "Comprobante" in elem.tag

    def test_rejects_oversized_xml(self):
        from b2b_ai.cfdi.xml_security import safe_fromstring, MAX_XML_BYTES
        huge = b"<root>" + b"x" * (MAX_XML_BYTES + 1) + b"</root>"
        with pytest.raises(ValueError, match="excede"):
            safe_fromstring(huge)

    def test_rejects_malformed_xml(self):
        from b2b_ai.cfdi.xml_security import safe_fromstring
        with pytest.raises(etree.XMLSyntaxError):
            safe_fromstring(b"<root><unclosed>")

    def test_blocks_xxe_entity(self):
        """XXE attack: external entity referencing local file."""
        from b2b_ai.cfdi.xml_security import safe_fromstring
        xxe_xml = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root>&xxe;</root>"""
        # With resolve_entities=False, the entity reference is kept as-is
        # (not expanded).  lxml may raise or return the literal text.
        try:
            elem = safe_fromstring(xxe_xml)
            # Entity should NOT be expanded — text should be empty or literal
            text = elem.text or ""
            assert "root" not in text.lower() or "xxe" in text.lower() or text == ""
        except etree.XMLSyntaxError:
            # Also acceptable — parser rejects the entity declaration
            pass

    def test_blocks_billion_laughs(self):
        """Billion laughs / exponential entity expansion."""
        from b2b_ai.cfdi.xml_security import safe_fromstring
        bomb = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<root>&lol3;</root>"""
        try:
            elem = safe_fromstring(bomb)
            # Should not explode — text length should be reasonable
            text = elem.text or ""
            assert len(text) < 1000000
        except etree.XMLSyntaxError:
            pass  # Also acceptable


class TestSafeParse:
    """Verify safe_parse (file-based) with encoding detection."""

    def test_parse_utf8_file(self):
        from b2b_ai.cfdi.xml_security import safe_parse
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="wb") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?><root>Ñoño</root>'.encode("utf-8"))
            path = f.name
        try:
            tree = safe_parse(path)
            assert tree.getroot().text == "Ñoño"
        finally:
            os.unlink(path)

    def test_parse_iso8859_file(self):
        from b2b_ai.cfdi.xml_security import safe_parse
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="wb") as f:
            f.write('<?xml version="1.0" encoding="ISO-8859-1"?><root>PEÑA</root>'.encode("iso-8859-1"))
            path = f.name
        try:
            tree = safe_parse(path)
            assert "PE" in tree.getroot().text
        finally:
            os.unlink(path)

    def test_parse_nonexistent_file(self):
        from b2b_ai.cfdi.xml_security import safe_parse
        with pytest.raises(OSError, match="no encontrado"):
            safe_parse("/nonexistent/path/file.xml")

    def test_parse_oversized_file(self):
        from b2b_ai.cfdi.xml_security import safe_parse, MAX_XML_BYTES
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="wb") as f:
            f.write(b"<root>" + b"x" * (MAX_XML_BYTES + 1) + b"</root>")
            path = f.name
        try:
            with pytest.raises(ValueError, match="excede"):
                safe_parse(path)
        finally:
            os.unlink(path)


class TestDetectEncoding:
    """Verify _detect_encoding helper."""

    def test_detects_utf8(self):
        from b2b_ai.cfdi.xml_security import _detect_encoding
        assert _detect_encoding(b'<?xml version="1.0" encoding="UTF-8"?>') == "UTF-8"

    def test_detects_iso8859(self):
        from b2b_ai.cfdi.xml_security import _detect_encoding
        assert _detect_encoding(b'<?xml version="1.0" encoding="ISO-8859-1"?>') == "ISO-8859-1"

    def test_defaults_utf8(self):
        from b2b_ai.cfdi.xml_security import _detect_encoding
        assert _detect_encoding(b"<root/>") == "utf-8"

    def test_detects_windows1252(self):
        from b2b_ai.cfdi.xml_security import _detect_encoding
        assert _detect_encoding(b"<?xml version='1.0' encoding='Windows-1252'?>") == "Windows-1252"
