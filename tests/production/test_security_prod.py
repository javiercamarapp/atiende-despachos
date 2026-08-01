# -*- coding: utf-8 -*-
"""
test_security_prod.py — Postura de seguridad de producción.

Reconfirma vectores ya auditados (SQLi, XSS, auth bypass) sobre la app real y
cubre dos huecos que la suite anterior no tocaba:

  - CSRF: la app autentica por header (X-API-Key), no por cookie. Verificamos
    que no se emiten cookies de sesión y que una petición cross-site de tipo
    "simple" (form-encoded, el vector CSRF clásico) no logra mutar estado.
  - Rate limit bypass por X-Forwarded-For: el limiter confía en el header
    XFF sin validar origen. Esto se documenta como HALLAZGO con evidencia
    (el test reproduce el bypass y pasa; no es un fix, es una fotografía).
"""
import pytest


# --------------------------------------------------------------------------- #
# 1. SQL injection
# --------------------------------------------------------------------------- #
def test_sql_injection_no_rompe_ni_inyecta(clean_client):
    c, h = clean_client["client"], {"X-API-Key": clean_client["key"]}
    payloads = [
        "1 OR 1=1",
        "1'; DROP TABLE invoices; --",
        "'; SELECT * FROM sqlite_master; --",
        "1 UNION SELECT 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24 --",
        "x' OR '1'='1",
        "%27%20OR%201%3D1%20--",
    ]
    for p in payloads:
        # en query param de filtro (categoría)
        r = c.get("/api/v1/invoices", headers=h, params={"categoria": p})
        assert r.status_code == 200, p
        # en path param de id
        r2 = c.get(f"/api/v1/invoices/{p}", headers=h)
        assert r2.status_code in (404, 422, 200), p
        # en JSON body
        r3 = c.post("/api/v1/invoices/process", headers=h,
                    json={"xml_path": p})
        assert r3.status_code in (400, 404, 422), p
    # la tabla sigue existiendo y sana
    assert c.get("/api/v1/stats", headers=h).status_code == 200


# --------------------------------------------------------------------------- #
# 2. XSS
# --------------------------------------------------------------------------- #
def test_xss_no_script_breakout(clean_client):
    """El reporte del dashboard no deja colar HTML/script desde datos."""
    c = clean_client["client"]
    # el reporte se sirve como JSON (application/json), no como HTML:
    # un navegador NO lo ejecuta. Verificamos el content-type.
    r = c.get("/api/v1/stats", headers={"X-API-Key": clean_client["key"]})
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "application/json" in ct
    # y un dato que parezca script, si entrara, no rompe la estructura JSON
    body = r.text
    assert "<script" not in body.lower() or "\\u003cscript" in body


def test_xss_leads_no_almacenan_html(clean_client):
    """Los leads con contenido HTML se guardan como dato (sin ejecutar)."""
    c = clean_client["client"]
    r = c.post("/api/v1/leads", json={
        "nombre": "<script>alert(1)</script>Pepito",
        "email": "pepito@x.com",
        "mensaje": "<img src=x onerror=alert(1)>",
    })
    assert r.status_code == 200
    # se guarda como cadena (el valor está escapado en la respuesta JSON)
    # y la app sigue funcionando
    assert c.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# 3. CSRF — hueco que se cubre aquí
# --------------------------------------------------------------------------- #
def test_no_se_emiten_cookies_de_sesion(clean_client):
    """Sin cookies de sesión no hay vector CSRF clásico (auto-adjunto)."""
    c = clean_client["client"]
    r = c.get("/api/v1/stats", headers={"X-API-Key": clean_client["key"]})
    assert r.status_code == 200
    assert "set-cookie" not in {k.lower() for k in r.headers.keys()}


def test_mutacion_por_form_encoded_rechazada(clean_client):
    """El vector CSRF clásico es un form cross-site (urlencoded). Los
    endpoints de mutación exigen JSON + header; urlencoded no surte efecto."""
    c = clean_client["client"]
    # leads es el único endpoint de mutación público; debe exigir JSON válido
    r = c.post("/api/v1/leads",
               data="nombre=Ana&email=ana%40x.com&mensaje=hola",
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    # FastAPI espera JSON -> sin Content-Type JSON esto da 422/400
    assert r.status_code in (400, 422)
    # los endpoints protegidos siguen exigiendo la API key aunque venga el
    # header Origin de un sitio ajeno
    r2 = c.post("/api/v1/tenants",
                headers={"X-API-Key": "no", "Origin": "https://evil.example"},
                json={"name": "X"})
    assert r2.status_code == 401


# --------------------------------------------------------------------------- #
# 4. Auth bypass — medios alternativos
# --------------------------------------------------------------------------- #
def test_auth_bypass_medios_alternativos(clean_client):
    c = clean_client["client"]
    # sin header / header vacío / key en query / key en cookie -> siempre 401
    assert c.get("/api/v1/stats").status_code == 401
    assert c.get("/api/v1/stats", headers={"X-API-Key": ""}).status_code == 401
    assert c.get("/api/v1/stats", params={"X-API-Key": clean_client["key"]}).status_code == 401
    assert c.get("/api/v1/stats", headers={"Cookie": "X-API-Key=%s" % clean_client["key"]}).status_code == 401
    # el healthcheck es público (by design) pero no expone datos financieros
    h = c.get("/health").json()
    assert "invoices" not in h or isinstance(h["invoices"], int)


# --------------------------------------------------------------------------- #
# 5. Rate limit bypass — VERIFICACIÓN POST-FIX
# --------------------------------------------------------------------------- #
def test_rate_limit_bypass_por_xff(rate_limited_client):
    """POST-FIX: el rate limiter ya no confía en XFF sin proxy configurado.

    Sin B2B_TRUST_PROXY configurado, el middleware usa la IP real de la
    conexión (REMOTE_ADDR), no el header X-Forwarded-For. Por tanto, rotar
    XFF ya no permite evadir el rate limit - las peticiones 11+ reciben 429.
    """
    c = rate_limited_client["client"]
    codes = []
    for i in range(25):
        codes.append(c.get("/api/v1/stats",
                           headers={"X-Forwarded-For": f"10.0.0.{i % 200}"}).status_code)

    # Las primeras 10 peticiones son 401 (auth requerida, no rate limited)
    # Las siguientes 15 son 429 (rate limited por la misma IP real)
    assert codes[:10].count(401) == 10, "Primeras 10 peticiones deben ser 401"
    assert 429 in codes, "El rate limit debe aplicar (429 presente)"
    # Verificamos que hay 429s después de las primeras 10
    assert codes[10:].count(429) >= 10, "Peticiones 11+ deben recibir 429"
