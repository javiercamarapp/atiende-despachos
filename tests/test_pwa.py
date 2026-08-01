# -*- coding: utf-8 -*-
"""Tests de la FASE 5: PWA + dashboard (mobile-responsive)."""
import json

from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app, LANDING_DIR


def _client(tmp_path):
    return TestClient(create_app(Database(str(tmp_path / "pwa.db"))))


def test_manifest_served(tmp_path):
    c = _client(tmp_path)
    r = c.get("/manifest.json")
    assert r.status_code == 200
    man = r.json()
    assert man["name"]
    assert man["short_name"]
    assert man["start_url"] == "/dashboard"
    assert man["display"] == "standalone"
    assert man["theme_color"]
    sizes = {i["sizes"] for i in man["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    # instalable: al menos un icono "any" y 192px
    any_icons = [i for i in man["icons"] if i.get("purpose", "any") == "any"]
    assert any("192x192" in i["sizes"] for i in any_icons)
    assert "shortcuts" in man


def test_service_worker_served(tmp_path):
    c = _client(tmp_path)
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers["content-type"]
    body = r.text
    assert "serviceWorker" not in body  # es el propio SW
    assert "b2b-shell-" in body         # cache shell
    assert "b2b-api-" in body           # cache API (offline de facturas)


def test_dashboard_served(tmp_path):
    c = _client(tmp_path)
    for path in ("/dashboard", "/dashboard.html"):
        r = c.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "Panel de control" in body
        assert "X-API-Key" in body or "apiKey" in body
        assert "beforeinstallprompt" in body


def test_dashboard_category_filter_only_valid_categories(tmp_path):
    """El filtro de categorías del dashboard debe contener SOLO las categorías
    reales del clasificador. 'honorarios' no es una categoría del clasificador
    (gasto_operativo, inversion, activo_fijo, nomina, desconocido); si apareciera
    sería un filtro muerto que jamás matchea ninguna factura."""
    c = _client(tmp_path)
    body = c.get("/dashboard").text
    valid = {"gasto_operativo", "inversion", "activo_fijo", "nomina", "desconocido"}
    # Extraer las <option> del select#catFilter
    import re
    m = re.search(r'<select id="catFilter".*?</select>', body, re.S)
    assert m, "select#catFilter no encontrado en el dashboard"
    opts = set(re.findall(r'<option[^>]*>([^<]+)</option>', m.group(0)))
    opts.discard("Todas")
    assert opts, "debe haber opciones de categoría"
    assert opts <= valid, f"categorías inválidas en el filtro: {opts - valid}"


def test_dashboard_mobile_responsive(tmp_path):
    """El dashboard debe ser mobile-first: viewport + media queries + 16px inputs."""
    c = _client(tmp_path)
    body = c.get("/dashboard").text
    assert 'name="viewport"' in body
    assert "@media(min-width:" in body      # breakpoint desktop
    assert "grid-template-columns:1fr" in body  # mobile-first columna única
    assert "font-size:16px" in body         # evita zoom automático iOS
    assert "safe-area-inset" in body        # notch/pantallas con muesca


def test_landing_pwa_meta(tmp_path):
    c = _client(tmp_path)
    body = c.get("/").text
    assert 'rel="manifest"' in body
    assert "sw.js" in body
    assert 'rel="apple-touch-icon"' in body
    assert 'name="theme-color"' in body


def test_icons_served(tmp_path):
    c = _client(tmp_path)
    for name in ("icon-192.png", "icon-512.png", "maskable-512.png"):
        r = c.get(f"/icons/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 0
        assert r.content[:4] == b"\x89PNG"


def test_icons_path_traversal_blocked(tmp_path):
    c = _client(tmp_path)
    r = c.get("/icons/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


def test_icons_non_png_rejected(tmp_path):
    c = _client(tmp_path)
    assert c.get("/icons/sw.js").status_code == 404


def test_landing_sw_registration_script(tmp_path):
    """La landing debe registrar el SW (script de carga)."""
    c = _client(tmp_path)
    body = c.get("/").text
    assert "navigator.serviceWorker.register" in body


def test_pwa_files_exist_on_disk():
    """Los artefactos PWA deben existir en el árbol de la landing."""
    for rel in ("manifest.json", "sw.js", "dashboard.html",
                "icons/icon-192.png", "icons/icon-512.png",
                "icons/maskable-512.png"):
        assert (LANDING_DIR / rel).is_file(), f"falta {rel}"


def test_dashboard_offline_cache_logic():
    """El dashboard debe persistir las facturas en localStorage (offline)."""
    body = (LANDING_DIR / "dashboard.html").read_text()
    assert "b2b_cached_invoices" in body       # clave de caché de facturas
    assert "localStorage.setItem" in body
    assert "navigator.onLine" in body          # banner online/offline
    assert "Mostrando datos de caché" in body  # mensaje offline
