# -*- coding: utf-8 -*-
"""Sanity funcional de versioning + request_id (NO es pytest)."""
import uuid
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from b2b_ai.api.versioning import install_versioning, get_api_version
from b2b_ai.api.request_id import install_request_id, get_request_id, REQUEST_ID_HEADER
from b2b_ai.api.errors import install_error_handlers


def make_app():
    app = FastAPI()
    install_request_id(app)
    install_versioning(app)
    install_error_handlers(app)

    @app.get("/health")
    def health(request: Request):
        return {"request_id": request.state.request_id,
                "api_version": request.state.api_version}

    @app.get("/api/v1/ping")
    def v1(request: Request):
        return {"version": request.state.api_version,
                "request_id": request.state.request_id}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


client = TestClient(make_app(), raise_server_exceptions=False)

ok = 0

# 1. health: X-Request-ID generado + X-API-Version default v1
r = client.get("/health")
assert r.status_code == 200, r.text
assert REQUEST_ID_HEADER in r.headers
uuid.UUID(r.headers[REQUEST_ID_HEADER])
assert r.headers["X-API-Version"] == "v1", r.headers
assert r.json()["request_id"] == r.headers[REQUEST_ID_HEADER]
assert r.json()["api_version"] == "v1"
ok += 1
print("[1] health: request_id=%s version=%s" % (
    r.headers[REQUEST_ID_HEADER], r.headers["X-API-Version"]))

# 2. /api/v1/ping: version v1 del path + header X-API-Version
r = client.get("/api/v1/ping")
assert r.status_code == 200
assert r.headers["X-API-Version"] == "v1"
assert "Deprecation" in r.headers
assert r.json()["version"] == "v1"
ok += 1
print("[2] v1 ping: version=%s deprecation=%s" % (
    r.headers["X-API-Version"], "Deprecation" in r.headers))

# 3. Reutiliza X-Request-ID entrante
sent = str(uuid.uuid4())
r = client.get("/api/v1/ping", headers={REQUEST_ID_HEADER: sent})
assert r.headers[REQUEST_ID_HEADER] == sent
ok += 1
print("[3] reutiliza header entrante: ok")

# 4. Accept-Version v2 en health
r = client.get("/health", headers={"Accept-Version": "v2"})
assert r.headers["X-API-Version"] == "v2"
ok += 1
print("[4] accept-version v2: version=%s" % r.headers["X-API-Version"])

# 5. Conflicto accept-version vs path -> 400
r = client.get("/api/v1/ping", headers={"Accept-Version": "v2"})
assert r.status_code == 400
assert r.json()["error"]["type"] == "version_conflict"
ok += 1
print("[5] conflicto version -> 400: ok")

# 6. Error 500 incluye request_id en body y header
r = client.get("/boom")
assert r.status_code == 500
assert REQUEST_ID_HEADER in r.headers
assert r.json()["error"]["request_id"] == r.headers[REQUEST_ID_HEADER]
ok += 1
print("[6] error incluye request_id: body=%s header=%s" % (
    r.json()["error"]["request_id"], r.headers[REQUEST_ID_HEADER]))

# 7. contextvar aislado tras request
assert get_request_id() == ""
assert get_api_version() is None
ok += 1
print("[7] contextvar aislado: ok")

print("ALL_OK (%d checks)" % ok)
