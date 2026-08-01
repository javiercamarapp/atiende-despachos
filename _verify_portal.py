# -*- coding: utf-8 -*-
"""Verificación end-to-end del portal server-rendered (t_6baa0aa7)."""
import os, sys, tempfile, bcrypt

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
DB = tmp.name

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

db = Database(path=DB)
pw = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
conn = db.conn
c = conn.cursor()
c.execute("INSERT INTO tenants(name, rfc) VALUES (?,?)", ("Cliente QA", "RFCQA900101A1"))
tid = c.lastrowid
c.execute("INSERT INTO client_users(tenant_id,email,password_hash,name,role) VALUES (?,?,?,?,?)",
          (tid, "qa@cliente.mx", pw, "Cliente QA", "cliente"))
# config de tenant para que settings la muestre
c.execute("INSERT INTO tenant_config(tenant_id, config_key, config_value) VALUES (?,?,?)",
          (tid, "rfc", "RFCQA900101A1"))
for i in range(1, 4):
    c.execute(
        "INSERT INTO invoices(tenant_id,folio_fiscal,archivo,fecha,tipo,serie,folio,"
        "emisor_rfc,emisor_nombre,receptor_rfc,subtotal,iva,total,moneda,categoria,"
        "confianza,valido,requires_human_review,erp_status,status) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, f"FF-{i:04d}-TEST", f"factura{i}.xml", f"2026-07-{i:02d}T10:00:00", "I",
         "A", str(i), "PROV001001A1", f"Proveedor {i}", "RFCQA900101A1",
         "100.00", "16.00", "116.00", "MXN", "gasto_operativo",
         0.99, 1, 1 if i == 2 else 0, "procesado" if i != 2 else "pendiente",
         "procesado"))
c.execute("INSERT INTO notifications(tenant_id,type,channel,recipient,subject,body,status) "
          "VALUES (?,?,?,?,?,?,?)",
          (tid, "portal_test", "email", "qa@cliente.mx", "Bienvenida",
           "Tu portal está listo.", "sent"))
conn.commit()

app = create_app(db=db)
from fastapi.testclient import TestClient
client = TestClient(app)

results = []
def check(name, got, expect):
    if isinstance(expect, set):
        ok = got == expect
    elif isinstance(expect, (list, tuple)):
        ok = got in expect
    else:
        ok = got == expect
    results.append((name, ok, got))
    print(("PASS" if ok else "FAIL"), name, "->", got if not isinstance(got, str) or len(got) < 80 else got[:80])

# 1) Sin sesion -> redirect
r = client.get("/portal/dashboard", follow_redirects=False)
check("dashboard sin sesion -> 302", r.status_code, 302)
check("redirect a /portal/login", r.headers.get("location"), "/portal/login")

# 2) Login malo
r = client.post("/portal/login", data={"email": "qa@cliente.mx", "password": "mala"},
                follow_redirects=False)
check("login malo -> 302", r.status_code, 302)
check("login malo -> /login?error", r.headers.get("location"), "/portal/login?error=1")

# 3) Login bueno -> cookie
r = client.post("/portal/login", data={"email": "qa@cliente.mx", "password": "testpass"},
                follow_redirects=False)
check("login bueno -> 302", r.status_code, 302)
cookie = r.headers.get("set-cookie", "")
check("set-cookie portal_session", "portal_session=" in cookie, True)
token = cookie.split("portal_session=")[1].split(";")[0]
client.cookies.set("portal_session", token)

# 4) Dashboard
r = client.get("/portal/dashboard")
check("dashboard HTML 200", r.status_code, 200)
check("dashboard muestra nav", "/portal/invoices" in r.text, True)

# 5) Facturas + filtros + busqueda
r = client.get("/portal/invoices")
check("invoices HTML 200", r.status_code, 200)
check("invoices 3 filas", r.text.count("FF-000"), 3)
r = client.get("/portal/invoices?q=FF-0002")
check("busqueda filtra no coincidentes", "FF-0003" not in r.text, True)
check("busqueda conserva coincidencia", "FF-0002" in r.text, True)
r = client.get("/portal/invoices?proveedor=PROV001001A1&estado=procesado")
check("filtro proveedor+estado 200", r.status_code, 200)
check("filtro procesado excluye anomalia", "FF-0002" not in r.text, True)

# 6) Detalle
r = client.get("/portal/invoices/2")
check("invoice detail 200", r.status_code, 200)
check("detail muestra folio", "FF-0002" in r.text, True)
r = client.get("/portal/invoices/9999")
check("invoice 404", r.status_code, 404)

# 7) Reportes
r = client.get("/portal/reports")
check("reports HTML 200", r.status_code, 200)
for rid in ("resumen", "proveedores", "flujo_caja", "alertas"):
    rd = client.get(f"/portal/reports/{rid}/download")
    check(f"report {rid} download 200", rd.status_code, 200)
    check(f"report {rid} content-disposition pdf", "reporte_"+rid+".pdf" in rd.headers.get("content-disposition",""), True)
    check(f"report {rid} es html", "text/html" in rd.headers.get("content-type",""), True)
rd = client.get("/portal/reports/noexiste/download")
check("report invalido 404", rd.status_code, 404)

# 8) Settings
r = client.get("/portal/settings")
check("settings HTML 200", r.status_code, 200)
check("settings muestra rfc", "RFCQA900101A1" in r.text, True)
r = client.put("/portal/settings", json={"rfc": "NEWRFC900101A2", "notif_channel": "whatsapp"})
check("settings PUT 200", r.status_code, 200)
check("settings PUT updated keys", set(r.json().get("updated", [])), {"rfc", "notif_channel"})
r = client.get("/portal/settings")
check("settings refleja cambio", "NEWRFC900101A2" in r.text, True)

# 9) Notificaciones JSON
r = client.get("/portal/notifications")
check("notifications JSON 200", r.status_code, 200)
check("notifications cuenta>=1", r.json().get("count", 0) >= 1, True)

# 10) Exportaciones (auth por cookie)
r = client.get("/portal/invoices/export.csv")
check("export.csv 200", r.status_code, 200)
check("export.csv content-type", "text/csv" in r.headers.get("content-type",""), True)
check("export.csv header", "folio_fiscal" in r.text, True)
r = client.get("/portal/invoices/export.xlsx")
check("export.xlsx 200", r.status_code, 200)
check("export.xlsx content-type", "spreadsheetml" in r.headers.get("content-type",""), True)

# 11) SPA JSON sigue vivo (Bearer header, como lo usa portal.html)
hdrs = {"Authorization": "Bearer " + token}
r = client.get("/portal/invoices.json", headers=hdrs)
check("SPA /portal/invoices.json 200", r.status_code, 200)
check("SPA JSON count", r.json().get("count"), 3)
r = client.get("/portal/auth/me", headers=hdrs)
check("SPA auth/me 200", r.status_code, 200)
r = client.get("/portal/dashboard/stats", headers=hdrs)
check("SPA dashboard/stats 200", r.status_code, 200)
# export.csv tambien funciona con Bearer (SPA usa Bearer)
r = client.get("/portal/invoices/export.csv", headers=hdrs)
check("export.csv con Bearer 200", r.status_code, 200)

# 12) PUT settings sin sesion -> 401
c2 = TestClient(app)
r = c2.put("/portal/settings", json={"rfc": "X"})
check("settings PUT sin sesion 401", r.status_code, 401)
# export sin sesion -> 401 (no redirect para recursos)
r = c2.get("/portal/invoices/export.csv")
check("export.csv sin sesion 401", r.status_code, 401)

# 13) Logout
r = client.get("/portal/logout", follow_redirects=False)
check("logout 302", r.status_code, 302)
r = client.get("/portal/dashboard", follow_redirects=False)
check("post-logout dashboard 302", r.status_code, 302)

print("\n==== RESULTADO ====")
fails = [n for n, ok, _ in results if not ok]
print(f"TOTAL {len(results)}  PASS {len(results)-len(fails)}  FAIL {len(fails)}")
for n, ok, got in results:
    if not ok:
        print("  FAIL:", n, "->", got)
os.unlink(DB)
sys.exit(1 if fails else 0)
