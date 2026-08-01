# -*- coding: utf-8 -*-
"""Tests de la landing page servida por la API (mismo origen)."""
from fastapi.testclient import TestClient

from b2b_ai.api.app import create_app, LANDING_DIR


def test_landing_servida_en_raiz(tmp_path):
    from b2b_ai.db.db import Database
    app = create_app(Database(str(tmp_path / "landing.db")))
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Elementos de la landing
    assert "B&amp;B AI" in body
    assert "Automatiza tu despacho contable" in body
    assert "id=\"contactForm\"" in body


def test_landing_index_html(tmp_path):
    from b2b_ai.db.db import Database
    app = create_app(Database(str(tmp_path / "landing2.db")))
    c = TestClient(app)
    assert c.get("/index.html").status_code == 200


def test_landing_incluye_seo(tmp_path):
    from b2b_ai.db.db import Database
    app = create_app(Database(str(tmp_path / "landing3.db")))
    c = TestClient(app)
    body = c.get("/").text
    assert "og:title" in body
    assert "twitter:card" in body
    assert "application/ld+json" in body
    assert "viewport" in body


def test_robots_txt(tmp_path):
    from b2b_ai.db.db import Database
    app = create_app(Database(str(tmp_path / "landing4.db")))
    c = TestClient(app)
    r = c.get("/robots.txt")
    assert r.status_code == 200
    assert "User-agent" in r.text
    assert "Sitemap" in r.text


def test_sitemap_xml(tmp_path):
    from b2b_ai.db.db import Database
    app = create_app(Database(str(tmp_path / "landing5.db")))
    c = TestClient(app)
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    assert "<urlset" in r.text
    assert "application/xml" in r.headers["content-type"]


def test_landing_dir_existe():
    """El directorio de la landing debe existir en el árbol del repo."""
    assert LANDING_DIR.is_dir()
    assert (LANDING_DIR / "index.html").is_file()
