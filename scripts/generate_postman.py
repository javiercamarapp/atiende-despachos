#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera docs/likida-api.postman_collection.json a partir de docs/openapi.json.

Todas las requests, environment variables y tests se derivan del contrato
OpenAPI real, de modo que la colección nunca se desincroniza del código.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
with open(os.path.join(PROJ, "docs", "openapi.json"), encoding="utf-8") as f:
    spec = json.load(f)

# ---- Environments ------------------------------------------------
environments = [
    {
        "name": "likida-local",
        "values": [
            {"key": "base_url", "value": "http://localhost:8000",
             "enabled": True, "description": "Instancia local (uvicorn)"},
            {"key": "api_key", "value": "tu-api-key",
             "enabled": True, "description": "Header X-API-Key"},
            {"key": "tenant_id", "value": "1", "enabled": True},
            {"key": "portal_token", "value": "", "enabled": True},
            {"key": "jwt_token", "value": "", "enabled": True},
            {"key": "invoice_id", "value": "1", "enabled": True},
            {"key": "periodo", "value": "2026-07", "enabled": True},
            {"key": "job_id", "value": "", "enabled": True},
        ],
    },
    {
        "name": "likida-prod",
        "values": [
            {"key": "base_url", "value": "https://api.b2b-ai.local",
             "enabled": True, "description": "Producción"},
            {"key": "api_key", "value": "sk_live_xxx", "enabled": True},
            {"key": "tenant_id", "value": "1", "enabled": True},
            {"key": "portal_token", "value": "", "enabled": True},
            {"key": "jwt_token", "value": "", "enabled": True},
            {"key": "invoice_id", "value": "1", "enabled": True},
            {"key": "periodo", "value": "2026-07", "enabled": True},
            {"key": "job_id", "value": "", "enabled": True},
        ],
    },
]

# ---- Param/example resolution -------------------------------------
def _sample(schema, depth=0):
    """Construye un ejemplo JSON a partir de un schema OpenAPI."""
    if depth > 4:
        return None
    if not schema:
        return ""
    if "example" in schema:
        return schema["example"]
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if "allOf" in schema:
        out = {}
        for s in schema["allOf"]:
            if "$ref" in s:
                out.update(_sample_ref(s["$ref"], depth + 1))
            else:
                v = _sample(s, depth + 1)
                if isinstance(v, dict):
                    out.update(v)
        return out
    if "$ref" in schema:
        return _sample_ref(schema["$ref"], depth + 1)
    if schema.get("type") == "object" or "properties" in schema:
        out = {}
        for k, v in (schema.get("properties") or {}).items():
            val = _sample(v, depth + 1)
            if val is not None:
                out[k] = val
        return out
    if schema.get("type") == "array":
        item = _sample(schema.get("items"), depth + 1)
        return [item] if item is not None else []
    t = schema.get("type")
    if t == "integer":
        return 1
    if t == "number":
        return 100.0
    if t == "boolean":
        return False
    if t == "string":
        return schema.get("enum", ["ejemplo"])[0] if schema.get("enum") else "ejemplo"
    return ""


def _sample_ref(ref, depth):
    name = ref.split("/")[-1]
    return _sample(spec["components"]["schemas"].get(name), depth)


def _body_from_schema(schema):
    s = _sample(schema)
    if not s:
        s = {}
    return json.dumps(s, ensure_ascii=False, indent=2)


def _path_params(parameters):
    params = []
    for p in parameters or []:
        if p.get("in") == "path":
            params.append({"key": p["name"],
                           "value": "{{%s}}" % _var_for(p["name"]),
                           "type": "text"})
        elif p.get("in") == "query":
            default = p.get("schema", {}).get("default", "")
            params.append({"key": p["name"], "value": default if default != "" else "",
                           "type": "text"})
    return params


def _var_for(name):
    mapping = {"periodo": "periodo", "invoice_id": "invoice_id",
               "job_id": "job_id", "job_or_id": "invoice_id",
               "tenant_id": "tenant_id", "tid": "tenant_id",
               "subscription_id": "1", "user_id": "1", "step": "1"}
    return mapping.get(name, name)


# ---- Folders por tag ----------------------------------------------
TAGS_ORDER = ["invoices", "stats", "dashboard", "accounting", "payroll",
              "reconcile", "reconciliation", "collections", "contabilidad",
              "sat", "webhooks", "notifications", "billing", "tenants",
              "onboarding", "auth", "enterprise", "portal", "system", "crm"]

def _folder_for(op):
    tags = op.get("tags") or []
    for t in TAGS_ORDER:
        if t in tags:
            return t
    return "general"


folders = {}
items = []

for path, path_item in spec["paths"].items():
    for method, op in path_item.items():
        if not isinstance(op, dict):
            continue
        m = method.upper()
        body = None
        rb = op.get("requestBody") or {}
        content = rb.get("content") or {}
        # Preferir los ejemplos curados del openapi.json si existen
        for ctype, media in content.items():
            if "examples" in media and media["examples"]:
                ex = list(media["examples"].values())[0]
                if "value" in ex:
                    body = json.dumps(ex["value"], ensure_ascii=False, indent=2)
                break
        if body is None:
            for ctype, media in content.items():
                if "schema" in media:
                    body = _body_from_schema(media["schema"])
                    break
        if body and body == "{}":
            body = None

        header = [{"key": "Content-Type", "value": "application/json"}]
        sec = op.get("security") or [{}]
        scheme = list(sec[0].keys())[0] if sec and sec[0] else None
        if scheme == "ApiKeyAuth":
            header.append({"key": "X-API-Key", "value": "{{api_key}}", "type": "text"})
        elif scheme in ("BearerAuth", "JWTAuth"):
            header.append({"key": "Authorization",
                           "value": "Bearer {{%s}}" % ("jwt_token" if scheme == "JWTAuth" else "portal_token"),
                           "type": "text"})

        query = _path_params(op.get("parameters"))

        # Tests automatizados por status esperado
        expected = 200
        if op.get("responses", {}).get("201"):
            expected = 201
        # Las operaciones de escritura pueden devolver 200; validar body ok
        pmtest = (
            "// Status esperado (default 200, ajustar por endpoint)\n"
            f"pm.test('Status es {expected} o 2xx', function () {{\n"
            f"    pm.expect(pm.response.code).to.be.oneOf([{expected}, 200, 201, 202, 204]);\n"
            "});\n"
            "pm.test('Respuesta es JSON válido', function () {\n"
            "    pm.expect(pm.response.headers.get('content-type')).to.include('json');\n"
            "});\n"
        )
        if m == "POST":
            pmtest += (
                "pm.test('POST devuelve ok', function () {\n"
                "    var j = pm.response.json();\n"
                "    pm.expect(j).to.be.an('object');\n"
                "});\n"
            )

        item = {
            "name": "%s %s" % (m, path),
            "request": {
                "method": m,
                "header": header,
                "url": {
                    "raw": "{{base_url}}%s" % path,
                    "host": ["{{base_url}}"],
                    "path": path.lstrip("/").split("/"),
                    "query": [{"key": q["key"], "value": q.get("value", ""), "disabled": not q.get("value")}
                              for q in query],
                    "variable": [{"key": v["key"], "value": v["value"]}
                                 for v in query if False],
                },
                "description": op.get("summary") or op.get("description") or "",
            },
            "event": [{"listen": "test", "script": {"exec": pmtest.splitlines(), "type": "text/javascript"}}],
        }
        if body:
            item["request"]["body"] = {
                "mode": "raw",
                "raw": body,
                "options": {"raw": {"language": "json"}},
            }
        # path variables -> url
        url = item["request"]["url"]
        # reconstruct path with vars
        segs = path.lstrip("/").split("/")
        url["path"] = [("{{%s}}" % _var_for(s[1:-1])) if s.startswith("{") and s.endswith("}") else s for s in segs]
        url["raw"] = "{{base_url}}/" + "/".join(
            ("{{%s}}" % _var_for(s[1:-1])) if s.startswith("{") and s.endswith("}") else s for s in segs)

        items.append((_folder_for(op), item))

# ---- Build collection ---------------------------------------------
collection = {
    "info": {
        "name": "Likida Likida AI Enterprise API",
        "description": "Colección oficial de la API REST de Likida AI Enterprise (Likida) Enterprise. "
                       "Generada desde docs/openapi.json. Usa el environment "
                       "`likida-local` o `likida-prod`.",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [],
}
for folder_name in TAGS_ORDER:
    folder_items = [i for f, i in items if f == folder_name]
    if folder_items:
        collection["item"].append({"name": folder_name.capitalize(), "item": folder_items})
    # also general leftovers
gen_items = [i for f, i in items if f == "general"]
if gen_items:
    collection["item"].append({"name": "General", "item": gen_items})

out = os.path.join(HERE, "likida-api.postman_collection.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(collection, f, indent=2, ensure_ascii=False)
json.load(open(out, encoding="utf-8"))

env_names = []
for env in environments:
    obj = {"name": env["name"],
           "values": env["values"],
           "_postman_variable_scope": "environment"}
    env_out = os.path.join(HERE, "likida-api.postman_environment_%s.json" % env["name"].split("-")[-1])
    with open(env_out, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    env_names.append(os.path.basename(env_out))

nreq = sum(len(f["item"]) for f in collection["item"])
print(f"OK. {nreq} requests in {len(collection['item'])} folders -> "
      f"{os.path.basename(out)} y {env_names}")
