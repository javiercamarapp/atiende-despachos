# -*- coding: utf-8 -*-
"""Re-verificación fresca de los fixes del document_management en el repo real.

Importa los módulos directamente del repo y ejerce el comportamiento corregido.
No usa pytest (riesgo de mmap documentado en el repo).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
from b2b_ai.features.document_management.routes import (
    build_document_router,
    _require_tenant,
    _sanitize_download_name,
)
from b2b_ai.features.document_management.storage import (
    LocalStorage,
    StorageBackendError,
)
from b2b_ai.features.document_management.service import (
    DocumentService,
    _reset_state,
)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

ok = 0
fail = 0


def chk(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [PASS] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name}")


tmp = tempfile.mkdtemp(prefix="dm_reverify_")

# 1. Auth dep: dict shape + header via Depends
class FA:
    def validate(self, k):
        return bool(k)

    def get_tenant_id(self, k):
        return "T1"

    def get_user_id(self, k):
        return "u1"


dep = make_require_api_key(FA())
app = FastAPI()


@app.get("/p")
def p(info: dict = Depends(dep)):
    return info


c = TestClient(app)
chk("auth: no header -> 401", c.get("/p").status_code == 401)
r = c.get("/p", headers={"X-API-Key": "k"})
chk("auth: header -> dict 200",
    r.status_code == 200 and r.json() == {"tenant_id": "T1", "user_id": "u1", "key": "k"})


class FB:
    def validate(self, k):
        return k == "good"

    def get_tenant_id(self, k):
        return "T1"

    def get_user_id(self, k):
        return None


dep2 = make_require_api_key(FB())
app2 = FastAPI()


@app2.get("/p2")
def p2(info: dict = Depends(dep2)):
    return info


c2 = TestClient(app2)
chk("auth: invalid key -> 401",
    c2.get("/p2", headers={"X-API-Key": "bad"}).status_code == 401)

# 2. tenant strict 400 / no fallback
try:
    _require_tenant({})
    chk("tenant {} -> 400", False)
except HTTPException as e:
    chk("tenant {} -> 400", e.status_code == 400)
try:
    _require_tenant({"tenant_id": None})
    chk("tenant None -> 400", False)
except HTTPException as e:
    chk("tenant None -> 400", e.status_code == 400)
chk("tenant present -> value", _require_tenant({"tenant_id": "X"}) == "X")

# 3. traversal + prefix-sibling + legit
st = LocalStorage(root=str(Path(tmp) / "storage"))


def expect_err(rel):
    try:
        st.save(rel, b"x")
        return False
    except StorageBackendError:
        return True


chk("traversal ../ evil blocked", expect_err("../evil"))
chk("traversal ../../etc blocked", expect_err("../../etc/passwd"))
chk("prefix-sibling blocked", expect_err("../storage_evil/x.bin"))
p3 = st.save("T1/ab/abc.bin", b"data")
chk("legit nested saved", st.exists(p3) and st.read(p3) == b"data")

# 4. Content-Disposition sanitize
out = _sanitize_download_name('a"\r\nb;c')
chk("sanitize strips \" CR LF ;", all(ch not in out for ch in '"\r\n;'))
chk("sanitize basename only", _sanitize_download_name("../../x/y.pdf") == "y.pdf")

# 5. router: tenant isolation + missing tenant 400
def authA():
    return {"tenant_id": "TENANT_A", "user_id": "ua"}


app3 = FastAPI()
app3.include_router(build_document_router(db=None, require_api_key=lambda: authA()))
c3 = TestClient(app3)
_reset_state()
up = c3.post("/api/v1/documents/upload",
             files={"file": ("f.txt", b"secret-A", "text/plain")})
chk("router upload 200", up.status_code == 200)
did = up.json()["document"]["id"]


def authB():
    return {"tenant_id": "TENANT_B", "user_id": "ub"}


app4 = FastAPI()
app4.include_router(build_document_router(db=None, require_api_key=lambda: authB()))
c4 = TestClient(app4)
chk("router: tenant B cannot read A (404)",
    c4.get(f"/api/v1/documents/{did}").status_code == 404)


def noTenant():
    return {"user_id": "u"}


app5 = FastAPI()
app5.include_router(build_document_router(db=None, require_api_key=lambda: noTenant()))
c5 = TestClient(app5)
chk("router: missing tenant -> 400",
    c5.post("/api/v1/documents/upload",
            files={"file": ("x", b"d", "application/octet-stream")}).status_code == 400)

# 6. persistence (real DB — survives service recreation)
from b2b_ai.db.db import Database
root = Path(tmp) / "docs"
_db = Database(str(Path(tmp) / "dm.db"))
s1 = DocumentService(db=_db, kind="local", root=str(root))
doc = s1.upload_document("T1", "persist.pdf", b"bytes", tags=["fiscal"])
# Nueva instancia contra la MISMA base: el dato sobrevive la recreación.
s2 = DocumentService(db=_db, kind="local", root=str(root))
re = s2.get_document("T1", doc.id)
chk("persistence survives recreation",
    re.name == "persist.pdf" and re.tags == ["fiscal"]
    and s2.read_document_bytes("T1", doc.id) == b"bytes")

print("=" * 50)
print(f"RESULT: {ok}/{ok + fail} checks passed")
sys.exit(1 if fail else 0)
