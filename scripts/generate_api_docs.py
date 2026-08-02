#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_api_docs.py — Genera documentación API completa desde el OpenAPI spec
de la app real de Likida AI Enterprise.

Importa `b2b_ai.api.app:app`, obtiene el contrato OpenAPI con `app.openapi()`
y lo convierte a documentación Markdown (o HTML) con:
    - Todos los endpoints (método, ruta, parámetros, request body, responses)
    - Sección de autenticación (flujo API key + JWT)
    - Sección de RBAC (permisos y roles disponibles)

Nunca genera la documentación a mano: siempre desde el spec real.

Uso:
    B2B_ENV=development \\
    B2B_JWT_SECRET=$(openssl rand -hex 32) \\
    B2B_ENCRYPTION_KEY=$(openssl rand -hex 24) \\
    python scripts/generate_api_docs.py [--format markdown|html] [--output PATH]

Flags:
    --format markdown|html   Formato de salida (default: markdown).
    --output <path>          Ruta de salida (default: docs/api-reference.md para
                             markdown, docs/api-reference.html para html).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Raíz del repo en sys.path para importar b2b_ai sin instalación editable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_METHODS = ("get", "post", "put", "patch", "delete")


# ---------------------------------------------------------------------------
# Helpers sobre el spec
# ---------------------------------------------------------------------------
def _title(s: str) -> str:
    return s.upper()


def _demote_headings(text: str) -> str:
    """Demote every markdown heading in `text` by one level, so the app's own
    description (which contains # / ## headings) does not clash with the doc's
    structure."""
    out = []
    for line in str(text).split("\n"):
        stripped = line.lstrip()
        # ATX heading: 1+ '#' then whitespace.
        if stripped.startswith("#") and stripped.lstrip("#")[:1] in ("", " "):
            out.append("#" + line)
        else:
            out.append(line)
    return "\n".join(out)


def _normalize_and_balance_md(text: str) -> str:
    """Sanea el markdown de la description de la app antes de insertarlo.

    1. Convierte escapes literales `\\n` en saltos de línea reales.
    2. Si el recuento de fences de código (```) es impar, elimina el último
       para que los bloques queden balanceados (el markdown de la description
       de la app está malformado)."""
    text = str(text).replace("\\n", "\n")
    lines = text.split("\n")
    fences = [i for i, l in enumerate(lines) if l.strip().startswith("```")]
    if len(fences) % 2 == 1:
        lines.pop(fences[-1])
    return "\n".join(lines)


def _resolve_schema(spec: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """Resuelve un $ref a su schema dentro de components.schemas."""
    parts = ref.split("/")
    node: Any = spec
    for p in parts:
        if p in ("#", ""):
            continue
        node = node.get(p, {})
    return node if isinstance(node, dict) else {}


def _type_of(schema: Dict[str, Any], spec: Dict[str, Any]) -> str:
    """Describe el tipo de un schema de forma legible."""
    if not schema:
        return "any"
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "allOf" in schema:
        parts = [_type_of(s, spec) for s in schema.get("allOf", [])]
        return " + ".join(parts)
    t = schema.get("type", "any")
    if t == "array":
        return f"array[{_type_of(schema.get('items', {}), spec)}]"
    if t == "object":
        props = schema.get("properties")
        if props:
            return "object{" + ", ".join(list(props)[:6]) + "}"
        return "object"
    if "enum" in schema:
        return f"{t}({'|'.join(str(e) for e in schema['enum'])})"
    return t


def _param_table(spec: Dict[str, Any], params: List[Dict[str, Any]]) -> str:
    """Tabla Markdown de parámetros."""
    if not params:
        return "_Sin parámetros._"
    rows = ["| Parámetro | En | Tipo | Requerido | Descripción |",
            "|---|---|---|---|---|"]
    for p in params:
        req = "sí" if p.get("required") else "no"
        sch = p.get("schema", {})
        rows.append(
            f"| `{p.get('name','')}` | {p.get('in','')} | "
            f"`{_type_of(sch, spec)}` | {req} | {_clean(p.get('description',''))} |")
    return "\n".join(rows)


def _request_body(spec: Dict[str, Any], rb: Any) -> str:
    if not rb:
        return ""
    content = rb.get("content", {})
    lines: List[str] = []
    for ctype, cmeta in content.items():
        sch = cmeta.get("schema", {})
        lines.append(f"**Content-Type:** `{ctype}`  ")
        lines.append(f"**Schema:** `{_type_of(sch, spec)}`  ")
        ex = cmeta.get("example") or sch.get("example")
        if ex:
            lines.append("**Ejemplo:**  ")
            lines.append("```json")
            lines.append(json.dumps(ex, indent=2, ensure_ascii=False))
            lines.append("```")
        props = sch.get("properties")
        if props:
            lines.append("")
            lines.append("| Campo | Tipo | Descripción |")
            lines.append("|---|---|---|")
            for name, prop in props.items():
                req = " *" if name in (sch.get("required") or []) else ""
                lines.append(
                    f"| `{name}`{req} | `{_type_of(prop, spec)}` | "
                    f"{_clean(prop.get('description',''))} |")
    return "\n".join(lines) if lines else "_Sin cuerpo._"


def _responses(spec: Dict[str, Any], responses: Dict[str, Any]) -> str:
    if not responses:
        return "_Sin responses documentadas._"
    rows = ["| Código | Descripción | Contenido |",
            "|---|---|---|"]
    for code, meta in sorted(responses.items()):
        desc = _clean(meta.get("description", ""))
        content = ""
        for ctype, cmeta in (meta.get("content") or {}).items():
            sch = cmeta.get("schema", {})
            content = f"`{ctype}` · `{_type_of(sch, spec)}`"
            ex = cmeta.get("example") or sch.get("example")
            if ex:
                content += " · ver ejemplo abajo"
        rows.append(f"| `{code}` | {desc} | {content or '—'} |")
    out = "\n".join(rows)
    # Incluye ejemplos concretos cuando están en el spec.
    for code, meta in sorted(responses.items()):
        for ctype, cmeta in (meta.get("content") or {}).items():
            sch = cmeta.get("schema", {})
            ex = cmeta.get("example") or sch.get("example")
            if ex:
                out += f"\n\n**Ejemplo respuesta `{code}`:**\n```json\n"
                out += json.dumps(ex, indent=2, ensure_ascii=False)
                out += "\n```"
    return out


def _clean(s: str) -> str:
    """Achata texto multilinea para celdas de tabla."""
    if not s:
        return ""
    return " ".join(str(s).split()).replace("|", "/")


def _auth_section(spec: Dict[str, Any]) -> str:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    lines = [
        "## Autenticación",
        "",
        "La API se asegura con **API key** y, en los módulos de auth/portal, con "
        "**JWT Bearer**. Ambas viven en el contrato OpenAPI:",
        "",
    ]
    if not schemes:
        lines.append("_No se definieron esquemas de seguridad en el spec._")
        return "\n".join(lines)
    lines.append("| Esquema | Tipo | Header |")
    lines.append("|---|---|---|")
    for name, sch in schemes.items():
        header = sch.get("name", "")
        where = "query" if sch.get("in") == "query" else "header"
        lines.append(f"| `{name}` | {sch.get('type','')} | "
                     f"`{header}` (en {where}) |")
    lines.append("")
    lines.append("### Flujo API key")
    lines.append("")
    lines.append("1. Emite una API key al crear un tenant o mediante la env `B2B_API_KEY`.")
    lines.append("2. Envía la key en el header de cada petición:")
    lines.append("")
    lines.append("```http")
    lines.append("X-API-Key: demo-<key>")
    lines.append("```")
    lines.append("")
    lines.append("Cada key resuelve un `tenant_id` (aislamiento multi-tenant). Si la key "
                 "coincide con `B2B_API_KEY` se trata como key de servicio.")
    lines.append("")
    lines.append("### Flujo JWT (módulos de auth)")
    lines.append("")
    lines.append("```http")
    lines.append("Authorization: Bearer <jwt>")
    lines.append("```")
    lines.append("")
    lines.append("### Respuestas de error estándar")
    lines.append("")
    lines.append("| Código | Significado |")
    lines.append("|---|---|")
    lines.append("| `400` | Petición mal formada / error de negocio |")
    lines.append("| `401` | Falta o es inválida la credencial |")
    lines.append("| `403` | Credencial válida pero sin permiso |")
    lines.append("| `404` | Recurso no encontrado |")
    lines.append("| `413` | Payload excede el límite |")
    lines.append("| `422` | Validación de schemas/reglas falló |")
    lines.append("| `429` | Rate limit superado |")
    lines.append("| `500` | Error interno |")
    return "\n".join(lines)


def _rbac_section() -> str:
    """Documenta permisos y roles disponibles desde el módulo RBAC real."""
    lines = [
        "## RBAC — Permisos y roles",
        "",
        "La plataforma implementa control de acceso por **permiso** "
        "(convención `<recurso>:<acción>`). Cada rol agrupa una lista de permisos.",
        "",
    ]
    try:
        from b2b_ai.features.roles.models import Permission
        perms = list(Permission.ALL)
        lines.append("### Permisos disponibles")
        lines.append("")
        for p in perms:
            lines.append(f"- `{p}`")
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"> No se pudo leer el catálogo de permisos: {exc}")
        lines.append("")

    try:
        from b2b_ai.features.roles.seed import DEFAULT_ROLE_DEFS
        lines.append("### Roles por defecto")
        lines.append("")
        lines.append("| Rol | Permisos |")
        lines.append("|---|---|")
        for role, (plist, _desc) in DEFAULT_ROLE_DEFS.items():
            lines.append(f"| `{role}` | {', '.join(f'`{p}`' for p in plist)} |")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"> Roles no disponibles: {exc}")
    lines.append("")
    lines.append("> Los permisos se aplican sobre los módulos de pipeline "
                 "(`pipeline:run`), bank feeds (`bank_feeds:*`) y gestión "
                 "documental (`documents:delete`), entre otros.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversor Markdown → HTML (mínimo, sin dependencias externas)
# ---------------------------------------------------------------------------
def _md_to_html(md: str) -> str:
    import html as _html
    lines = md.split("\n")
    out: List[str] = []
    i = 0
    in_code = False
    code_buf: List[str] = []
    in_table = False
    table_buf: List[str] = []

    def flush_table() -> None:
        nonlocal in_table, table_buf
        if not in_table:
            return
        rows = []
        for r in table_buf:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            rows.append(cells)
        if len(rows) >= 2:
            html = "<table>\n<thead><tr>" + "".join(
                f"<th>{_html.escape(c)}</th>" for c in rows[0]) + "</tr></thead>\n<tbody>"
            for row in rows[2:]:
                html += "<tr>" + "".join(
                    f"<td>{_html.escape(c)}</td>" for c in row) + "</tr>"
            html += "</tbody></table>"
            out.append(html)
        in_table = False
        table_buf = []

    while i < len(lines):
        line = lines[i]

        # Bloques de código con backticks
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_buf = []
            else:
                out.append("<pre><code>" + _html.escape("\n".join(code_buf)) +
                           "</code></pre>")
                in_code = False
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Tablas
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if not in_table:
                in_table = True
                table_buf = []
            table_buf.append(line)
            i += 1
            continue
        if in_table:
            flush_table()

        s = line.strip()
        if not s:
            out.append("")
            i += 1
            continue
        if s.startswith("####"):
            out.append(f"<h4>{_html.escape(s[5:].strip())}</h4>")
        elif s.startswith("###"):
            out.append(f"<h3>{_html.escape(s[4:].strip())}</h3>")
        elif s.startswith("##"):
            out.append(f"<h2>{_html.escape(s[3:].strip())}</h2>")
        elif s.startswith("#"):
            out.append(f"<h1>{_html.escape(s[2:].strip())}</h1>")
        elif s.startswith("- ") or s.startswith("* "):
            out.append(f"<li>{_html.escape(s[2:].strip())}</li>")
        elif s.startswith("> "):
            out.append(f"<blockquote>{_html.escape(s[2:].strip())}</blockquote>")
        elif s.startswith("---"):
            out.append("<hr>")
        else:
            out.append(f"<p>{_html.escape(s)}</p>")
        i += 1
    if in_table:
        flush_table()
    if in_code:
        out.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>API Reference — Likida AI Enterprise</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
max-width:980px;margin:24px auto;padding:0 18px;line-height:1.55;color:#1a1a1a}}
h1,h2,h3,h4{{margin:1.2em 0 .4em}} h1{{border-bottom:3px solid #0b5394;padding-bottom:6px}}
h2{{border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:2em}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:.92em}}
th,td{{border:1px solid #ccc;padding:6px 9px;text-align:left;vertical-align:top}}
th{{background:#f0f4f8}} code{{background:#f5f5f5;padding:1px 4px;border-radius:3px;font-size:.9em}}
pre{{background:#0d1117;color:#e6edf3;padding:12px;border-radius:6px;overflow:auto}}
pre code{{background:none;color:inherit}} blockquote{{border-left:4px solid #999;margin:8px 0;padding:2px 12px;color:#555}}
li{{margin:2px 0}}</style></head><body>
{body}
</body></html>"""


# ---------------------------------------------------------------------------
# Generación del documento
# ---------------------------------------------------------------------------
def _build_markdown(app: Any) -> str:
    spec: Dict[str, Any] = app.openapi()
    paths: Dict[str, Any] = spec.get("paths", {})
    schemas = spec.get("components", {}).get("schemas", {})

    meta = spec.get("info", {})
    desc = _demote_headings(_normalize_and_balance_md(meta.get("description", "")))
    lines = [
        f"# API Reference — {spec.get('info',{}).get('title','Likida AI Enterprise')}",
        "",
        desc,
        "",
        f"- **Versión:** {meta.get('version','')}",
        f"- **Rutas:** {len(paths)} · **Schemas:** {len(schemas)}",
        "- **Base URL (local):** `http://localhost:8000`",
        "- **Base URL (producción):** `https://api.likida.ai`",
        "- **Interactiva:** `GET /docs` (Swagger), `GET /redoc`",
        "- **Contrato:** `GET /openapi.json`",
        "",
        "> Documento **auto-generado** por `scripts/generate_api_docs.py` desde el "
        "spec OpenAPI real (`app.openapi()`). No editar a mano.",
        "",
        "---",
        "",
    ]

    # Autenticación
    lines.append(_auth_section(spec))
    lines.append("")
    lines.append("---")
    lines.append("")

    # RBAC
    lines.append(_rbac_section())
    lines.append("")
    lines.append("---")
    lines.append("")

    # Agrupar endpoints por prefijo de ruta (primer segmento).
    groups: "OrderedDict[str, List[tuple]]" = OrderedDict()
    for path, item in sorted(paths.items()):
        parts = [p for p in path.split("/") if p]
        group = parts[0] if parts else "(raíz)"
        groups.setdefault(group, []).append((path, item))

    lines.append("## Endpoints")
    lines.append("")
    lines.append("| Método | Ruta | Resumen |")
    lines.append("|---|---|---|")
    for path, item in sorted(paths.items()):
        first_op = None
        for m in _METHODS:
            if m in item:
                first_op = item[m]
                break
        summary = _clean((first_op or {}).get("summary", ""))
        methods = ",".join(m.upper() for m in _METHODS if m in item)
        lines.append(f"| `{methods}` | `{path}` | {summary} |")
    lines.append("")

    for group, entries in groups.items():
        lines.append(f"## Grupo: `/{group}`")
        lines.append("")
        for path, item in entries:
            lines.append(f"### `{path}`")
            lines.append("")
            for m in _METHODS:
                op = item.get(m)
                if not op:
                    continue
                lines.append(f"#### **{m.upper()}** `{path}`")
                lines.append("")
                if op.get("summary"):
                    lines.append(f"_{_clean(op['summary'])}_")
                    lines.append("")
                if op.get("description"):
                    lines.append(_clean(op["description"]))
                    lines.append("")
                tags = op.get("tags")
                if tags:
                    lines.append(f"**Tags:** {', '.join(f'`{t}`' for t in tags)}")
                    lines.append("")
                lines.append("**Parámetros**")
                lines.append("")
                lines.append(_param_table(spec, op.get("parameters", [])))
                lines.append("")
                body = op.get("requestBody")
                if body:
                    lines.append("**Request body**")
                    lines.append("")
                    lines.append(_request_body(spec, body))
                    lines.append("")
                lines.append("**Responses**")
                lines.append("")
                lines.append(_responses(spec, op.get("responses", {})))
                lines.append("")
    return "\n".join(lines)


def _resolve_out(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output).resolve()
    if args.format == "html":
        return _REPO_ROOT / "docs" / "api-reference.html"
    return _REPO_ROOT / "docs" / "api-reference.md"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["markdown", "html"], default="markdown")
    parser.add_argument("--output", default="",
                        help="Ruta de salida (default: docs/api-reference.md|.html)")
    args = parser.parse_args(argv)

    from b2b_ai.api.app import app

    md = _build_markdown(app)
    out_path = _resolve_out(args)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "html":
        out_path.write_text(_md_to_html(md), encoding="utf-8")
    else:
        out_path.write_text(md, encoding="utf-8")

    n_paths = len(app.openapi().get("paths", {}))
    print(f"OK  {out_path}  ({out_path.stat().st_size} bytes)")
    print(f"Documentado: {n_paths} rutas · formato={args.format}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
