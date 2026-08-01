# -*- coding: utf-8 -*-
"""Arranca uvicorn contra una DB temporal sembrada para probar SSE en vivo."""
import os, sys, tempfile, bcrypt, uvicorn

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
c.execute("INSERT INTO tenants(name, rfc) VALUES (?,?)", ("SSE Tenant", "RFCSSE001A1"))
tid = c.lastrowid
c.execute("INSERT INTO client_users(tenant_id,email,password_hash,name,role) VALUES (?,?,?,?,?)",
          (tid, "sse@cliente.mx", pw, "SSE User", "cliente"))
c.execute("INSERT INTO notifications(tenant_id,type,channel,recipient,subject,body,status) "
          "VALUES (?,?,?,?,?,?,?)",
          (tid, "test", "email", "sse@cliente.mx", "Alerta SSE",
           "Primer evento", "sent"))
conn.commit()

print("DB=" + DB)
app = create_app(db=db)
uvicorn.run(app, host="127.0.0.1", port=8017, log_level="warning")
